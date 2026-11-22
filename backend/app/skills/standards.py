"""Step 17 deterministic standards metadata suggestion, supersession chain resolver, citation scanner, & synthetic fixtures."""

import json
import re
from pathlib import Path
from typing import Any, Callable

from docx import Document as DocxDocument
from pydantic import BaseModel, Field, ValidationError
import pymupdf
from sqlalchemy.orm import Session

from app.providers.base import (
    LLMRequest,
    ProviderResponseError,
    ProviderUsageLimitError,
    TaskComplexity,
    TokenUsage,
    sanitize_secret_text,
)
from app.providers.secrets import SecretStore
from app.schemas.standards import (
    AI_UNVERIFIED_SUGGESTION_LABEL_EN,
    StandardCitationHitOut,
    StandardCreateRequest,
    StandardPresetOut,
)
from app.services.provider_settings import _load_provider_config, _summarize_usage, execute_provider_request
from app.services.research import estimate_prompt_tokens

# Case-sensitive standard code syntax detector (uppercase issuer prefixes only so lowercase English text like "en" never matches).
STANDARD_CODE_DETECT_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?:SYN|ISO|IEC|ASTM|ACI|BS|EN|IEEE|ASHRAE|NFPA|ASME|ANSI|SBC|LBC)(?:\s+[A-Z]|\s*-?\s*\d)[\w./-]*\b"
)

_DOC_NUMBER_RE = re.compile(r"\b[A-Z]{2,10}(?:\s+[A-Z])?\s*-?\s*\d{2,6}[\w./-]*\b")
_YEAR_RE = re.compile(r"\b(?:19\d{2}|20[0-3]\d)\b")
_ISSUER_HINT_RE = re.compile(
    r"(?:issued\s+by|published\s+by|issuer|authority|organization)\s*[:\-]\s*([^\n\r;]{2,120})",
    re.IGNORECASE,
)


class StandardInputError(ValueError):
    """Raised when standard metadata, excerpt length, or supersession links violate Step 17 rules."""


def extract_bounded_header_text(file_path: Path, extension: str) -> str:
    """Deterministically extract bounded header text (<= 4000 chars) from uploaded PDF/DOCX/TXT ONLY — never stored permanently as full text."""
    ext = extension.lower()
    text_chunks: list[str] = []
    if ext == ".pdf":
        with pymupdf.open(str(file_path)) as pdoc:
            for page in pdoc[:3]:
                txt = page.get_text("text") or ""
                if txt.strip():
                    text_chunks.append(txt.strip())
    elif ext == ".docx":
        ddoc = DocxDocument(str(file_path))
        for p in ddoc.paragraphs[:40]:
            if p.text.strip():
                text_chunks.append(p.text.strip())
        for tbl in ddoc.tables[:3]:
            for row in tbl.rows[:15]:
                row_txt = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if row_txt:
                    text_chunks.append(row_txt)
    else:
        raw = file_path.read_text(encoding="utf-8", errors="ignore")
        if raw.strip():
            text_chunks.append(raw[:4000].strip())

    joined = "\n".join(text_chunks).strip()
    return joined[:4000]


def suggest_metadata_deterministically(header_text: str, *, original_filename: str) -> dict[str, Any]:
    """Suggest metadata strictly from literal lines physically inside the uploaded document (0 AI tokens, never from memory)."""
    stem = Path(original_filename).stem.replace("_", " ").strip()
    lines = [ln.strip() for ln in header_text.splitlines() if ln.strip()]
    head_block = "\n".join(lines[:15])

    num_match = _DOC_NUMBER_RE.search(head_block)
    suggested_number = num_match.group(0).strip() if num_match else (stem[:64] or "DOC-UNCONFIRMED")

    year_match = _YEAR_RE.search(head_block)
    suggested_year = year_match.group(0) if year_match else "unknown"

    issuer_match = _ISSUER_HINT_RE.search(head_block)
    suggested_issuer = issuer_match.group(1).strip() if issuer_match else ""

    suggested_title = ""
    for ln in lines[:10]:
        if len(ln) >= 6 and ln != suggested_number:
            suggested_title = ln[:240]
            break
    if not suggested_title:
        suggested_title = stem or original_filename

    return {
        "suggested_number": suggested_number,
        "suggested_title": suggested_title,
        "suggested_issuing_body": suggested_issuer,
        "suggested_edition_year": suggested_year,
        "suggestion_origin": "deterministic_file_header",
        "requires_owner_confirmation": True,
    }


class _AiMetadataSuggestionPayload(BaseModel):
    suggested_number: str | None = Field(default=None, max_length=128)
    suggested_title: str | None = Field(default=None, max_length=300)
    suggested_issuing_body: str | None = Field(default=None, max_length=200)
    suggested_edition_year: str | None = Field(default=None, max_length=32)


def suggest_metadata_with_ai(
    db: Session,
    secret_store: SecretStore,
    *,
    header_text: str,
    original_filename: str,
    project_id: str | None = None,
    complexity: TaskComplexity = "fast",
    client_factory: Callable[[str], Any] | None = None,
) -> tuple[dict[str, Any], TokenUsage]:
    """Optional Gemini help ONLY to read header metadata printed inside an uploaded document; tagged UNVERIFIED AI SUGGESTION."""
    prompt_payload = {
        "filename": original_filename,
        "rules": [
            "Read ONLY metadata visibly printed in the attached uploaded document excerpt.",
            "NEVER recall or guess missing edition years, issuing bodies, or clause numbers from memory.",
            "Return null/unknown for any field not literally printed in the excerpt.",
        ],
        "document_header_excerpt": header_text[:3500],
    }
    prompt_text = json.dumps(prompt_payload, ensure_ascii=False)
    est_tokens = estimate_prompt_tokens(prompt_text)

    cfg = _load_provider_config(db)
    daily_usage, monthly_usage = _summarize_usage(db)
    if daily_usage.total_tokens + est_tokens > cfg.usage_limits.daily_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated standards metadata prompt ({est_tokens} tokens) plus daily usage "
            f"({daily_usage.total_tokens}) would exceed Step 04 daily limit ({cfg.usage_limits.daily_token_limit})."
        )
    if monthly_usage.total_tokens + est_tokens > cfg.usage_limits.monthly_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated standards metadata prompt ({est_tokens} tokens) plus monthly usage "
            f"({monthly_usage.total_tokens}) would exceed Step 04 monthly limit ({cfg.usage_limits.monthly_token_limit})."
        )

    sys_instr = (
        "Extract ONLY bibliographic header metadata explicitly printed in the uploaded document excerpt "
        "(standard number, document title, issuing body, edition year). NEVER use outside knowledge or memory; "
        "return null if missing."
    )
    llm_req = LLMRequest(
        prompt=prompt_text,
        system_instruction=sys_instr,
        complexity=complexity,
        temperature=0.0,
        response_schema=_AiMetadataSuggestionPayload,
    )
    llm_resp = execute_provider_request(
        db,
        secret_store,
        llm_req,
        client_factory=client_factory,
        project_id=project_id,
    )
    try:
        parsed = _AiMetadataSuggestionPayload.model_validate(llm_resp.parsed_json)
    except ValidationError as exc:
        raise ProviderResponseError(
            f"Standard metadata AI suggestion validation failed: {exc.errors()[0].get('msg', 'invalid schema')}"
        ) from exc

    det_fallback = suggest_metadata_deterministically(header_text, original_filename=original_filename)
    suggestion = {
        "suggested_number": sanitize_secret_text((parsed.suggested_number or det_fallback["suggested_number"]).strip()),
        "suggested_title": sanitize_secret_text((parsed.suggested_title or det_fallback["suggested_title"]).strip()),
        "suggested_issuing_body": sanitize_secret_text((parsed.suggested_issuing_body or det_fallback["suggested_issuing_body"]).strip()),
        "suggested_edition_year": sanitize_secret_text((parsed.suggested_edition_year or det_fallback["suggested_edition_year"]).strip() or "unknown"),
        "suggestion_origin": AI_UNVERIFIED_SUGGESTION_LABEL_EN,
        "requires_owner_confirmation": True,
    }
    return suggestion, llm_resp.usage


def validate_no_supersession_cycle(
    *,
    target_id: str,
    candidate_superseded_by_id: str | None,
    links_by_id: dict[str, str | None],
) -> None:
    """Reject self-supersession or circular supersession chains (A -> B -> A)."""
    if not candidate_superseded_by_id:
        return
    if candidate_superseded_by_id == target_id:
        raise StandardInputError("A standard cannot supersede itself.")
    seen: set[str] = {target_id}
    cur: str | None = candidate_superseded_by_id
    guard = 0
    while cur and guard < 100:
        if cur in seen:
            raise StandardInputError("Circular supersession chain detected across standards_library.")
        seen.add(cur)
        cur = links_by_id.get(cur)
        guard += 1


def resolve_supersession_chain(
    *,
    std_id: str,
    docs_by_id: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None, str | None]:
    """Return (immediate_superseded_by_number, immediate_superseded_by_title, formatted_chain_summary)."""
    doc = docs_by_id.get(std_id)
    if not doc:
        return None, None, None
    next_id = doc.get("superseded_by_id")
    if not next_id or next_id not in docs_by_id:
        return None, None, None

    imm = docs_by_id[next_id]
    chain_parts: list[str] = [f"{doc['standard_number']} ({doc.get('edition_year', 'unknown')})"]
    seen = {std_id}
    cur_id: str | None = next_id
    guard = 0
    while cur_id and cur_id in docs_by_id and cur_id not in seen and guard < 25:
        seen.add(cur_id)
        node = docs_by_id[cur_id]
        chain_parts.append(f"{node['standard_number']} ({node.get('edition_year', 'unknown')}) [{node['status']}]")
        cur_id = node.get("superseded_by_id")
        guard += 1

    return imm["standard_number"], imm["title"], " -> ".join(chain_parts)


def find_citations_for_standard(
    *,
    std_doc: dict[str, Any],
    specifications: list[dict[str, Any]],
    calculations: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    review_reports: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
) -> tuple[list[StandardCitationHitOut], list[str]]:
    """Scan real project deliverables where this standard number is cited and flag superseded/withdrawn/unknown/unconfirmed hits."""
    std_num = str(std_doc.get("standard_number") or "").strip()
    if not std_num:
        return [], []
    # Match exact token boundaries around standard_number so e.g. SYN-100 doesn't match SYN-1000 cleanly!
    pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(std_num)}(?![A-Za-z0-9])", re.IGNORECASE)

    status = str(std_doc.get("status") or "unknown")
    edition = str(std_doc.get("edition_year") or "unknown").strip().lower()
    meta_status = str(std_doc.get("metadata_status") or "")
    flag = "ok"
    if status == "withdrawn":
        flag = "withdrawn"
    elif status == "superseded":
        flag = "superseded"
    elif status == "unknown" or not edition or edition == "unknown":
        flag = "unknown_edition_or_status"
    elif meta_status in {"unverified_ai_suggestion", "unverified_suggestion"}:
        flag = "unconfirmed_metadata"

    hits: list[StandardCitationHitOut] = []

    for sp in specifications:
        sp_title = str(sp.get("title") or sp.get("id", "")[:8])
        for sec in sp.get("sections") or []:
            sec_code = str(sec.get("section_code") or "")
            texts_to_check = [
                ("standards_table", " ".join(
                    f"{st.get('source_name', '')} {st.get('citation_text', '')}"
                    for st in (sec.get("standards") or [])
                    if isinstance(st, dict)
                ))
            ] + [
                (f"clause:{cl.get('clause_id', '')}", str(cl.get("text") or ""))
                for cl in (sec.get("clauses") or [])
                if isinstance(cl, dict)
            ]
            for loc_lbl, txt in texts_to_check:
                if pat.search(txt):
                    hits.append(
                        StandardCitationHitOut(
                            module="specification",
                            artifact_id=str(sp["id"]),
                            artifact_title=sp_title,
                            location=f"{sec_code} / {loc_lbl}",
                            flagged_status=flag,
                        )
                    )

    for calc in calculations:
        c_title = str(calc.get("title") or calc.get("id", "")[:8])
        c_blob = " ".join(
            [str(calc.get("references_text") or "")]
            + [
                f"{r.get('source_name', '')} {r.get('source_ref', '')} {r.get('notes', '')}"
                for r in (calc.get("references_json") or [])
                if isinstance(r, dict)
            ]
        )
        if pat.search(c_blob):
            hits.append(
                StandardCitationHitOut(
                    module="calculation",
                    artifact_id=str(calc["id"]),
                    artifact_title=c_title,
                    location="references",
                    flagged_status=flag,
                )
            )

    for cmp_row in comparisons:
        cmp_title = str(cmp_row.get("title") or cmp_row.get("id", "")[:8])
        for crit in cmp_row.get("criteria_json") or []:
            if isinstance(crit, dict) and pat.search(str(crit.get("source_ref") or "")):
                hits.append(
                    StandardCitationHitOut(
                        module="comparison",
                        artifact_id=str(cmp_row["id"]),
                        artifact_title=cmp_title,
                        location=f"criterion:{crit.get('criterion_id', '')}",
                        flagged_status=flag,
                    )
                )
        for opt in cmp_row.get("options_json") or []:
            if not isinstance(opt, dict):
                continue
            for cell in opt.get("cells") or []:
                if isinstance(cell, dict) and pat.search(str(cell.get("source_ref") or "")):
                    hits.append(
                        StandardCitationHitOut(
                            module="comparison",
                            artifact_id=str(cmp_row["id"]),
                            artifact_title=cmp_title,
                            location=f"{opt.get('option_id', '')}.{cell.get('criterion_id', '')}",
                            flagged_status=flag,
                        )
                    )

    for rep in review_reports:
        r_title = str(rep.get("title") or rep.get("id", "")[:8])
        r_blob = json.dumps(
            {
                "findings": rep.get("findings") or [],
                "verified_facts": rep.get("verified_facts") or [],
                "source_registry": rep.get("source_registry") or [],
            },
            ensure_ascii=False,
        )
        if pat.search(r_blob):
            hits.append(
                StandardCitationHitOut(
                    module="review_report",
                    artifact_id=str(rep["id"]),
                    artifact_title=r_title,
                    location="report_body",
                    flagged_status=flag,
                )
            )

    for sched in schedules:
        s_title = str(sched.get("title") or sched.get("id", "")[:8])
        for act in sched.get("activities_json") or []:
            if isinstance(act, dict) and pat.search(str(act.get("source_ref") or "")):
                hits.append(
                    StandardCitationHitOut(
                        module="schedule",
                        artifact_id=str(sched["id"]),
                        artifact_title=s_title,
                        location=f"activity:{act.get('activity_id', '')}",
                        flagged_status=flag,
                    )
                )

    warnings: list[str] = []
    if hits and flag != "ok":
        warnings.append(
            f"Standard '{std_num}' has status/metadata flag '{flag}' while cited in {len(hits)} deliverable location(s)."
        )
    return hits, warnings


def get_synthetic_standards_presets() -> list[StandardPresetOut]:
    """Return strictly synthetic placeholder standards ONLY (fake SYN-* numbers; zero real copyrighted standard texts)."""
    return [
        StandardPresetOut(
            key="syn_1",
            label_en="Synthetic Current Standard Fixture (SYN-1000-2024)",
            label_ar="نموذج معيار تمثيلي ساري (SYN-1000-2024)",
            standard=StandardCreateRequest(
                standard_number="SYN-1000-2024",
                title="Synthetic Electrical Distribution Panel Practice Baseline (Fake Fixture)",
                issuing_body="Synthetic Standards Committee (Example Only)",
                edition_year="2024",
                status="current",
                jurisdiction="Synthetic Municipal Scope",
                adopted_locally=True,
                owner_notes="Strictly synthetic fixture for testing library indexing & citation verification.",
                owner_excerpts=[],
            ),
        ),
        StandardPresetOut(
            key="syn_2",
            label_en="Synthetic Old Edition Fixture (SYN-1000-2018 — Superseded)",
            label_ar="نموذج طبعة قديمة ملغاة باستبدال (SYN-1000-2018)",
            standard=StandardCreateRequest(
                standard_number="SYN-1000-2018",
                title="Synthetic Electrical Distribution Panel Practice Baseline (2018 Edition)",
                issuing_body="Synthetic Standards Committee (Example Only)",
                edition_year="2018",
                status="superseded",
                supersession_note="Owner-registered synthetic supersession example replaced by SYN-1000-2024.",
                jurisdiction="Synthetic Municipal Scope",
                adopted_locally=False,
                owner_notes="Do not cite on new work once SYN-1000-2024 is adopted.",
                owner_excerpts=[],
            ),
        ),
        StandardPresetOut(
            key="syn_3",
            label_en="Synthetic Withdrawn Document Fixture (SYN-900-2010 — Withdrawn)",
            label_ar="نموذج معيار مسحوب (SYN-900-2010)",
            standard=StandardCreateRequest(
                standard_number="SYN-900-2010",
                title="Synthetic Legacy Piping Coating Bulletin (Withdrawn Fixture)",
                issuing_body="Synthetic Materials Board (Example Only)",
                edition_year="2010",
                status="withdrawn",
                jurisdiction="Synthetic Municipal Scope",
                adopted_locally=False,
                owner_notes="Withdrawn synthetic standard fixture for QA withdrawal trapping.",
                owner_excerpts=[],
            ),
        ),
    ]
