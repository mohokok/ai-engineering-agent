"""Tests for Step 17 owner-supplied standards library, upload SHA-256 + unconfirmed suggestion gate, supersession tracking, bilingual registers, and QA flags."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import ValidationError
import pymupdf
import pytest

from app.core.config import Settings
from app.db.models import TechnicalComparison
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.standards import (
    AI_UNVERIFIED_SUGGESTION_LABEL_AR,
    AI_UNVERIFIED_SUGGESTION_LABEL_EN,
    MAX_EXCERPT_CHARS,
    OwnerExcerptIn,
    UPLOADED_UNCONFIRMED_LABEL_AR,
    UPLOADED_UNCONFIRMED_LABEL_EN,
)
from app.services.workspace import resolve_project_file_path
from app.skills.standards import (
    StandardInputError,
    get_synthetic_standards_presets,
    resolve_supersession_chain,
    suggest_metadata_deterministically,
    validate_no_supersession_cycle,
)


class _InMemorySecretStore(SecretStore):
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._keys: dict[str, str] = dict(initial or {})

    @property
    def backend_name(self) -> str:
        return "InMemoryTestKeyring"

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        self._keys[provider_name] = api_key

    def get_api_key(self, provider_name: str) -> str | None:
        return self._keys.get(provider_name)

    def delete_api_key(self, provider_name: str) -> None:
        self._keys.pop(provider_name, None)


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(workspaces_dir=tmp_path / "workspaces", database_url="")


def _fake_standards_ai_factory(captured_prompts: list[str]):
    class _Models:
        def list(self) -> list[Any]:
            return []

        def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
            captured_prompts.append(str(contents))
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "suggested_number": "SYN-555-2025",
                        "suggested_title": "Synthetic Uploaded Panel Guide (AI Header Hint)",
                        "suggested_issuing_body": "Synthetic Test Institute",
                        "suggested_edition_year": "2025",
                    }
                ),
                usage_metadata=SimpleNamespace(
                    prompt_token_count=120,
                    candidates_token_count=45,
                    total_token_count=165,
                ),
            )

    return lambda _api_key: SimpleNamespace(models=_Models())


def test_step17_unit_supersession_cycles_excerpt_cap_and_synthetic_presets() -> None:
    """Verify deterministic cycle rejection, chain resolution, 300-char excerpt cap, 0-token suggestion, and fake-only presets."""
    # 1. Excerpt character cap (strict <= 300 chars)
    ok_excerpt = OwnerExcerptIn(page_ref="p. 12", text="A" * MAX_EXCERPT_CHARS)
    assert len(ok_excerpt.text) == MAX_EXCERPT_CHARS
    with pytest.raises(ValidationError):
        OwnerExcerptIn(page_ref="p. 12", text="A" * (MAX_EXCERPT_CHARS + 1))

    # 2. Supersession cycle rejection & chain resolution
    links = {
        "s1": "s2",
        "s2": "s3",
        "s3": None,
    }
    with pytest.raises(StandardInputError):
        validate_no_supersession_cycle(target_id="s1", candidate_superseded_by_id="s1", links_by_id=links)
    with pytest.raises(StandardInputError):
        validate_no_supersession_cycle(target_id="s3", candidate_superseded_by_id="s1", links_by_id=links)
    validate_no_supersession_cycle(target_id="s4", candidate_superseded_by_id="s2", links_by_id=links)

    docs_by_id = {
        "s1": {"standard_number": "SYN-1000-2012", "title": "Ed 2012", "edition_year": "2012", "status": "superseded", "superseded_by_id": "s2"},
        "s2": {"standard_number": "SYN-1000-2018", "title": "Ed 2018", "edition_year": "2018", "status": "superseded", "superseded_by_id": "s3"},
        "s3": {"standard_number": "SYN-1000-2024", "title": "Ed 2024", "edition_year": "2024", "status": "current", "superseded_by_id": None},
    }
    imm_num, imm_title, chain = resolve_supersession_chain(std_id="s1", docs_by_id=docs_by_id)
    assert imm_num == "SYN-1000-2018"
    assert imm_title == "Ed 2018"
    assert chain is not None
    assert "SYN-1000-2012 (2012) -> SYN-1000-2018 (2018) [superseded] -> SYN-1000-2024 (2024) [current]" == chain

    # 3. Deterministic 0-token metadata suggestion from header text
    sug = suggest_metadata_deterministically(
        "SYN-777-2023\nSynthetic Plumbing Slope Rules\nIssued by: Synthetic National Board\nEdition: 2023",
        original_filename="syn_777.txt",
    )
    assert sug["suggested_number"] == "SYN-777-2023"
    assert sug["suggested_edition_year"] == "2023"
    assert "Synthetic Plumbing Slope Rules" in sug["suggested_title"]
    assert sug["requires_owner_confirmation"] is True

    # 4. Presets strictly synthetic (SYN-* only, no shipped real copyrighted standard text)
    presets = get_synthetic_standards_presets()
    assert len(presets) == 3
    for p in presets:
        assert p.standard.standard_number.startswith("SYN-")
        assert p.standard.owner_excerpts == []


def test_step17_api_upload_sha256_zero_tokens_ai_confirm_supersede_search_and_exports(tmp_path: Path) -> None:
    """Verify full Step 17 lifecycle: owner create, upload SHA-256 (0 tokens + optional AI tag), confirm, supersede, search, & EN/AR DOCX/PDF/XLSX exports without copyright leak."""
    captured_prompts: list[str] = []
    app = create_app(
        settings=_test_settings(tmp_path),
        secret_store=_InMemorySecretStore({"gemini": "AIzaSyntheticTestKey987654321"}),
        provider_client_factory=_fake_standards_ai_factory(captured_prompts),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Synthetic Standards Clinic", "code": "STD-17", "classification": "Preliminary"},
        ).json()
        pid = project["id"]
        slug = project["workspace_slug"]

        # 1. Presets endpoint
        presets_res = client.get("/api/standards/presets")
        assert presets_res.status_code == 200
        assert len(presets_res.json()["presets"]) == 3

        # 2. Excerpt > 300 chars rejected (422)
        bad_ex_res = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-BAD-1",
                "title": "Rejected Overlong Excerpt",
                "status": "current",
                "owner_excerpts": [{"page_ref": "p. 1", "text": "X" * (MAX_EXCERPT_CHARS + 5)}],
            },
        )
        assert bad_ex_res.status_code == 422

        # 3. Register owner-entered current & withdrawn & old standards (0 tokens)
        cur_res = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-1000-2024",
                "title": "Synthetic Electrical Distribution Panel Practice",
                "issuing_body": "Synthetic Committee",
                "edition_year": "2024",
                "status": "current",
                "jurisdiction": "Libya Local Scope",
                "adopted_locally": True,
                "owner_notes": "Adopted current baseline.",
                "owner_excerpts": [
                    {
                        "page_ref": "p. 7",
                        "text": "Owner-noted limit: feeder breaker thermal rating check on distribution schedule.",
                    }
                ],
            },
        )
        assert cur_res.status_code == 201, cur_res.text
        std_cur = cur_res.json()
        assert std_cur["tokens_used"] == 0
        assert std_cur["metadata_status"] == "owner_entered"
        assert std_cur["version"] == 1

        old_res = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-1000-2018",
                "title": "Synthetic Electrical Distribution Panel Practice (Legacy)",
                "issuing_body": "Synthetic Committee",
                "edition_year": "2018",
                "status": "current",
                "adopted_locally": False,
            },
        )
        assert old_res.status_code == 201
        std_old = old_res.json()

        withdrawn_res = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-900-2010",
                "title": "Synthetic Obsolete Lead Pipe Standard",
                "issuing_body": "Synthetic Plumbing Institute",
                "edition_year": "2010",
                "status": "withdrawn",
                "adopted_locally": False,
            },
        )
        assert withdrawn_res.status_code == 201

        # 4. Register supersession (SYN-1000-2018 -> SYN-1000-2024) + cycle block
        sup_res = client.post(
            f"/api/standards/{std_old['id']}/supersede",
            json={
                "superseded_by_id": std_cur["id"],
                "supersession_note": "Replaced by 2024 edition per owner decree.",
            },
        )
        assert sup_res.status_code == 200, sup_res.text
        sup_data = sup_res.json()
        assert sup_data["status"] == "superseded"
        assert sup_data["superseded_by_number"] == "SYN-1000-2024"
        assert "SYN-1000-2018 (2018) -> SYN-1000-2024 (2024) [current]" == sup_data["replacement_chain_summary"]
        assert sup_data["version"] == 2

        cycle_res = client.post(
            f"/api/standards/{std_cur['id']}/supersede",
            json={"superseded_by_id": std_old["id"], "supersession_note": "Bad cycle"},
        )
        assert cycle_res.status_code == 422

        # 5. Upload TXT standard with long copyrighted filler prose:
        #    (a) Default use_ai=False -> 0 tokens, unverified suggestion, exact SHA-256
        copyright_marker = "FULL_COPYRIGHT_PROSE_DO_NOT_EXPORT_TOKEN_998877"
        raw_doc = (
            "SYN-222-2021\nSynthetic Owner Licensed Fire Valve Document\nIssued by: Synthetic Fire Board\n"
            "Edition: 2021\n\n"
            + (f"Section text containing {copyright_marker} proprietary sentences. " * 25)
        ).encode("utf-8")
        expected_sha = hashlib.sha256(raw_doc).hexdigest()

        up_det_res = client.post(
            "/api/standards/upload",
            data={"project_id": pid, "jurisdiction": "National", "adopted_locally": "false", "use_ai": "false"},
            files={"file": ("syn_222_2021.txt", raw_doc, "text/plain")},
        )
        assert up_det_res.status_code == 201, up_det_res.text
        up_det = up_det_res.json()
        assert up_det["tokens_used"] == 0
        assert up_det["file_sha256"] == expected_sha
        assert up_det["metadata_status"] == "unverified_suggestion"
        assert UPLOADED_UNCONFIRMED_LABEL_EN in up_det["metadata_label"]
        assert UPLOADED_UNCONFIRMED_LABEL_AR in up_det["metadata_label"]
        assert len(captured_prompts) == 0

        # Confirm metadata -> version increments & status cleared
        conf_det_res = client.post(
            f"/api/standards/{up_det['id']}/confirm",
            json={"confirmed_by": "Eng. Owner", "status": "current", "edition_year": "2021"},
        )
        assert conf_det_res.status_code == 200
        assert conf_det_res.json()["metadata_status"] == "owner_confirmed"
        assert conf_det_res.json()["version"] == 2

        # (b) Optional use_ai=True upload -> tagged UNVERIFIED AI SUGGESTION until confirmed
        up_ai_res = client.post(
            "/api/standards/upload",
            data={"project_id": pid, "use_ai": "true", "complexity": "fast", "adopted_locally": "true"},
            files={"file": ("syn_ai_555.txt", b"SYN-555-2025 Synthetic Document\nEdition: 2025\n", "text/plain")},
        )
        assert up_ai_res.status_code == 201, up_ai_res.text
        up_ai = up_ai_res.json()
        assert up_ai["tokens_used"] == 165
        assert len(captured_prompts) == 1
        assert up_ai["metadata_status"] == "unverified_ai_suggestion"
        assert up_ai["ai_suggestion_status"] == "unverified_ai_suggestion"
        assert AI_UNVERIFIED_SUGGESTION_LABEL_EN in up_ai["metadata_label"]

        # Confirm AI suggestion
        conf_ai_res = client.post(
            f"/api/standards/{up_ai['id']}/confirm",
            json={"confirmed_by": "Eng. Owner", "status": "current", "edition_year": "2025"},
        )
        assert conf_ai_res.status_code == 200
        assert conf_ai_res.json()["ai_suggestion_status"] == "owner_confirmed"

        # (c) pymupdf-generated synthetic PDF upload (default 0 tokens -> unconfirmed suggestion -> SHA-256 -> confirm, no copyright body leak)
        pdf_copyright_marker = "PDF_FULL_COPYRIGHT_PROSE_DO_NOT_EXPORT_654321"
        syn_pdf = pymupdf.open()
        syn_page = syn_pdf.new_page()
        syn_page.insert_text(
            (72, 72),
            "SYN-333-2022\nSynthetic PDF Fire Pump Practice\nIssued by: Synthetic National Authority\nEdition: 2022\n",
            fontsize=11,
        )
        syn_page.insert_text(
            (72, 180),
            (f"Proprietary PDF clause prose containing {pdf_copyright_marker}. " * 12)[:1200],
            fontsize=9,
        )
        pdf_bytes = syn_pdf.tobytes()
        syn_pdf.close()
        expected_pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()

        up_pdf_res = client.post(
            "/api/standards/upload",
            data={"project_id": pid, "jurisdiction": "Libya Local Scope", "adopted_locally": "true", "use_ai": "false"},
            files={"file": ("syn_333_2022.pdf", pdf_bytes, "application/pdf")},
        )
        assert up_pdf_res.status_code == 201, up_pdf_res.text
        up_pdf = up_pdf_res.json()
        assert up_pdf["tokens_used"] == 0
        assert up_pdf["file_sha256"] == expected_pdf_sha
        assert up_pdf["metadata_status"] == "unverified_suggestion"
        suggested_pdf = up_pdf["suggested_metadata"] or {}
        norm_pdf_num = " ".join(str(suggested_pdf.get("suggested_number") or up_pdf["standard_number"]).replace("\xa0", " ").replace("\xad", "-").split())
        assert "SYN-333-2022" in norm_pdf_num
        assert suggested_pdf.get("suggested_edition_year") == "2022"

        conf_pdf_res = client.post(
            f"/api/standards/{up_pdf['id']}/confirm",
            json={
                "confirmed_by": "Eng. Owner",
                "standard_number": "SYN-333-2022",
                "title": "Synthetic PDF Fire Pump Practice",
                "edition_year": "2022",
                "status": "current",
            },
        )
        assert conf_pdf_res.status_code == 200
        assert conf_pdf_res.json()["metadata_status"] == "owner_confirmed"

        # 6. Search over owner-supplied data only (by keyword, number, status, adopted_locally)
        srch_sup = client.get(f"/api/standards?project_id={pid}&status=superseded")
        assert srch_sup.status_code == 200
        assert srch_sup.json()["total"] == 1
        assert srch_sup.json()["standards"][0]["standard_number"] == "SYN-1000-2018"

        srch_kw = client.get(f"/api/standards?project_id={pid}&q=Lead+Pipe")
        assert srch_kw.status_code == 200
        assert srch_kw.json()["total"] == 1
        assert srch_kw.json()["standards"][0]["standard_number"] == "SYN-900-2010"

        # 7. Cite SYN-1000-2018 (superseded) in a real Calculation & verify where_cited + DOCX/PDF/XLSX exports (no full text leak!)
        presets_calc = client.get("/api/calculations/presets").json()["presets"]
        calc_res = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "title": "Feeder Panel Basis (Citing Old Edition)",
                "calculation_type": "electrical_load_schedule",
                "language": "en",
                "classification": "Preliminary",
                "inputs": presets_calc[0]["inputs"],
                "references": [
                    {
                        "source_kind": "owner_supplied",
                        "source_name": "Legacy Panel Spec Basis",
                        "source_ref": "SYN-1000-2018 Clause 3.1",
                    }
                ],
            },
        )
        assert calc_res.status_code == 201, calc_res.text

        old_detail = client.get(f"/api/standards/{std_old['id']}").json()
        assert len(old_detail["where_cited"]) == 1
        assert old_detail["where_cited"][0]["module"] == "calculation"
        assert old_detail["where_cited"][0]["flagged_status"] == "superseded"
        assert len(old_detail["citation_warnings"]) == 1

        # Export English & Arabic registers
        for reg_lang in ("en", "ar"):
            exp_res = client.post(
                "/api/standards/export-register",
                json={"project_id": pid, "language": reg_lang, "classification": "For Review"},
            )
            assert exp_res.status_code == 201, exp_res.text
            exp_data = exp_res.json()
            assert exp_data["standards_count"] == 6
            assert exp_data["cited_warnings_count"] >= 1
            assert len(exp_data["files"]) == 3

            files_by_fmt = {f["format"]: f for f in exp_data["files"]}
            for fmt, fmeta in files_by_fmt.items():
                dl = client.get(fmeta["download_url"])
                assert dl.status_code == 200
                disk_path = resolve_project_file_path(
                    _test_settings(tmp_path).workspaces_dir,
                    workspace_slug=slug,
                    relative_path=fmeta["relative_path"],
                )
                assert hashlib.sha256(disk_path.read_bytes()).hexdigest() == fmeta["sha256"]

            # Inspect XLSX live formulas and confirm full copyrighted text NEVER leaks!
            xlsx_path = resolve_project_file_path(
                _test_settings(tmp_path).workspaces_dir,
                workspace_slug=slug,
                relative_path=files_by_fmt["xlsx"]["relative_path"],
            )
            wb = load_workbook(xlsx_path, data_only=False)
            expected_sheet_title = "سجل المعايير" if reg_lang == "ar" else "Standards Register"
            ws_reg = wb[expected_sheet_title]
            assert ws_reg.views.sheetView[0].rightToLeft is (reg_lang == "ar")
            assert ws_reg["E14"].value == '=COUNTIF(E7:E12,"current")'
            assert ws_reg["L14"].value == "=SUM(L7:L12)"
            all_xlsx_text = " ".join(
                str(cell.value or "")
                for sheet in wb.worksheets
                for row in sheet.iter_rows()
                for cell in row
            )
            assert "SYN-1000-2018" in all_xlsx_text
            assert "SYN-333-2022" in all_xlsx_text
            assert "Feeder Panel Basis" in all_xlsx_text
            assert copyright_marker not in all_xlsx_text
            assert pdf_copyright_marker not in all_xlsx_text

            # Inspect PDF text cleanly
            pdf_path = resolve_project_file_path(
                _test_settings(tmp_path).workspaces_dir,
                workspace_slug=slug,
                relative_path=files_by_fmt["pdf"]["relative_path"],
            )
            with pymupdf.open(str(pdf_path)) as pdoc:
                raw_pdf_text = "\n".join(page.get_text("text") for page in pdoc)
            pdf_text = " ".join(raw_pdf_text.replace("\xa0", " ").replace("\xad", "-").split())
            assert "SYN-1000-2024" in pdf_text
            assert "SYN-333-2022" in pdf_text
            assert copyright_marker not in pdf_text
            assert copyright_marker not in raw_pdf_text
            assert pdf_copyright_marker not in pdf_text
            assert pdf_copyright_marker not in raw_pdf_text

            # Inspect DOCX text cleanly
            docx_path = resolve_project_file_path(
                _test_settings(tmp_path).workspaces_dir,
                workspace_slug=slug,
                relative_path=files_by_fmt["docx"]["relative_path"],
            )
            ddoc = DocxDocument(str(docx_path))
            docx_text = "\n".join(
                [p.text for p in ddoc.paragraphs]
                + [c.text for tbl in ddoc.tables for row in tbl.rows for c in row.cells]
            )
            assert "SYN-1000-2018" in docx_text
            assert "SYN-333-2022" in docx_text
            assert copyright_marker not in docx_text
            assert pdf_copyright_marker not in docx_text


def test_step17_qa_agent_catches_cited_superseded_withdrawn_unknown_unconfirmed_and_uncited_standards(
    tmp_path: Path,
) -> None:
    """Verify QA passes when citing confirmed current library standard, and catches cited superseded/withdrawn/unknown/unconfirmed or unregistered standards."""
    app = create_app(
        settings=_test_settings(tmp_path),
        secret_store=_InMemorySecretStore(),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "QA Standards Guard Project", "code": "QASTD-17", "classification": "For Review"},
        ).json()
        pid = project["id"]

        # 1. Register valid current library standard SYN-1000-2024 + produce compliant Calculation
        std_cur = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-1000-2024",
                "title": "Current Valid Synthetic Panel Standard",
                "issuing_body": "Synthetic Board",
                "edition_year": "2024",
                "status": "current",
                "adopted_locally": True,
            },
        ).json()

        calc_presets = client.get("/api/calculations/presets").json()["presets"]
        ok_calc = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "title": "Compliant Feeder Calculation",
                "calculation_type": "electrical_load_schedule",
                "language": "en",
                "classification": "For Review",
                "inputs": calc_presets[0]["inputs"],
                "references": [
                    {
                        "source_kind": "owner_supplied",
                        "source_name": "Approved Panel Reference (SYN-1000-2024)",
                        "source_ref": "SYN-1000-2024",
                    }
                ],
            },
        )
        assert ok_calc.status_code == 201
        ok_calc_id = ok_calc.json()["id"]
        assert client.post(f"/api/calculations/{ok_calc_id}/export", json={"language": "en"}).status_code == 201

        qa_pass_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_pass_res.status_code == 201, qa_pass_res.text
        qa_pass = qa_pass_res.json()
        assert qa_pass["status"] == "passed", qa_pass
        assert std_cur["id"] in qa_pass["qa_context_summary"]["inspected_standard_ids"]

        # 2. Seed all prohibited standard citation scenarios:
        #    (a) Superseded standard SYN-1000-2018 -> cited in new Calculation
        std_old = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-1000-2018",
                "title": "Old Synthetic Panel Standard",
                "edition_year": "2018",
                "status": "superseded",
                "superseded_by_id": std_cur["id"],
                "supersession_note": "Replaced by SYN-1000-2024",
            },
        ).json()
        bad_calc_sup = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "title": "Bad Calculation Citing Superseded Standard",
                "calculation_type": "electrical_load_schedule",
                "language": "en",
                "classification": "For Review",
                "inputs": calc_presets[0]["inputs"],
                "references": [
                    {
                        "source_kind": "owner_supplied",
                        "source_name": "Legacy Edition Basis",
                        "source_ref": "SYN-1000-2018 Sec 4",
                    }
                ],
            },
        )
        assert bad_calc_sup.status_code == 201
        assert client.post(f"/api/calculations/{bad_calc_sup.json()['id']}/export", json={"language": "en"}).status_code == 201

        #    (b) Withdrawn standard SYN-900-2010 -> cited in TechnicalComparison row directly
        client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-900-2010",
                "title": "Withdrawn Synthetic Material Rule",
                "edition_year": "2010",
                "status": "withdrawn",
            },
        )
        with app.state.session_factory() as db:
            db.add(
                TechnicalComparison(
                    project_id=pid,
                    title="Panel Comparison Citing Withdrawn Code",
                    comparison_scope="material",
                    discipline="electrical",
                    language="en",
                    classification="For Review",
                    revision="R0",
                    use_ai=False,
                    ai_draft_status="not_used",
                    owner_decision_status="pending_owner_decision",
                    criteria_json=[
                        {
                            "criterion_id": "C1",
                            "label": "Safety Grade",
                            "category": "qualitative",
                            "weight": "100",
                            "unit": "",
                            "direction": "higher_better",
                            "mandatory": False,
                            "source_kind": "owner_entered",
                            "source_ref": "SYN-900-2010 Clause 2",
                        }
                    ],
                    options_json=[],
                    matrix_result_json={"options": []},
                )
            )
            db.commit()

        #    (c) Unknown-edition standard SYN-700-UNK -> cited in Calculation
        client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-700-UNK",
                "title": "Unknown Edition Synthetic Guide",
                "edition_year": "unknown",
                "status": "unknown",
            },
        )

        #    (d) Uploaded unconfirmed standard SYN-555-2025 -> not confirmed by owner
        up_unconf = client.post(
            "/api/standards/upload",
            data={"project_id": pid, "use_ai": "false"},
            files={"file": ("syn_555_2025.txt", b"SYN-555-2025 Unconfirmed Standard\nEdition: 2025\n", "text/plain")},
        )
        assert up_unconf.status_code == 201

        #    (e) Calculation citing unknown-edition SYN-700-UNK, unconfirmed SYN-555-2025, AND unregistered SYN-888-2022
        bad_calc_multi = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "title": "Bad Calculation Citing Unknown Unconfirmed And Unregistered Codes",
                "calculation_type": "electrical_load_schedule",
                "language": "en",
                "classification": "For Review",
                "inputs": calc_presets[0]["inputs"],
                "references": [
                    {
                        "source_kind": "owner_supplied",
                        "source_name": "Mixed Unverified Codes",
                        "source_ref": "SYN-700-UNK and SYN-555-2025 and SYN-888-2022",
                    }
                ],
            },
        )
        assert bad_calc_multi.status_code == 201
        assert client.post(f"/api/calculations/{bad_calc_multi.json()['id']}/export", json={"language": "en"}).status_code == 201

        # Confirm get detail for SYN-1000-2018 reports exact superseded citation hit
        sup_detail = client.get(f"/api/standards/{std_old['id']}").json()
        assert any(h["module"] == "calculation" and h["flagged_status"] == "superseded" for h in sup_detail["where_cited"])

        # 3. Run QA Agent -> MUST fail with 'reference' findings for EVERY prohibited case!
        qa_fail_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_fail_res.status_code == 201, qa_fail_res.text
        qa_fail = qa_fail_res.json()
        assert qa_fail["status"] == "issues_found"

        ref_issues = [iss for iss in qa_fail["issues"] if iss["check_category"] == "reference"]
        joined_ref_blob = " | ".join(f"{i['title']} :: {i['description']} :: {i['reference']}" for i in ref_issues)

        assert "SYN-1000-2018" in joined_ref_blob and "superseded" in joined_ref_blob.lower()
        assert "SYN-900-2010" in joined_ref_blob and "withdrawn" in joined_ref_blob.lower()
        assert "SYN-700-UNK" in joined_ref_blob
        assert "SYN-555-2025" in joined_ref_blob
        assert "SYN-888-2022" in joined_ref_blob
