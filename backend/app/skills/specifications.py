"""Step 14 deterministic technical specifications skill & optional Gemini prose drafting (default 0 tokens)."""

from dataclasses import dataclass, field
import json
import re
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.providers.base import LLMRequest, ProviderResponseError, ProviderUsageLimitError, TaskComplexity, TokenUsage, sanitize_secret_text
from app.providers.secrets import SecretStore
from app.schemas.reports import ReportLanguage
from app.schemas.specifications import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NO_VERIFIED_STANDARD_LABEL,
    SPEC_SECTION_PARTS,
    VERIFY_CODE_LABEL,
    SpecClause,
    SpecPartKey,
    SpecSection,
    SpecStandardCitation,
    SpecTraceRef,
)
from app.services.provider_settings import _load_provider_config, _summarize_usage, execute_provider_request
from app.services.research import estimate_prompt_tokens

_URL_RE = re.compile(r"(?:https?://|project-file://)[^\s,;\"')>\]]+", re.IGNORECASE)
_UNGROUNDED_STD_RE = re.compile(
    r"\b(?:ASTM|ACI|BS|EN|IEC|IEEE|ISO|ASHRAE|NFPA|ASME|ANSI|SBC|LBC)\s*[A-Z]?\s*\d[\w./-]*\b",
    re.IGNORECASE,
)


class SpecificationInputError(ValueError):
    """Raised when specification generation inputs violate source traceability or project bounds."""


@dataclass(frozen=True)
class _TradeSpecTemplate:
    key: str
    section_code: str
    discipline: str
    title_en: str
    title_ar: str
    keywords: tuple[str, ...]


_TRADE_TEMPLATES: tuple[_TradeSpecTemplate, ...] = (
    _TradeSpecTemplate(
        key="architectural_doors",
        section_code="SPEC-01",
        discipline="architecture",
        title_en="Doors, Frames & Architectural Hardware",
        title_ar="الأبواب والحلوق والخردوات المعمارية",
        keywords=("door", "doors", "frame", "hardware", "closer", "hpl", "timber door", "باب", "أبواب", "حلق"),
    ),
    _TradeSpecTemplate(
        key="architectural_windows",
        section_code="SPEC-02",
        discipline="architecture",
        title_en="Windows, Glazing & Aluminum Curtain/Fenestration",
        title_ar="النوافذ والزجاج وأعمال الألومنيوم",
        keywords=("window", "windows", "glazing", "aluminum", "aluminium", "curtain wall", "sill", "نافذة", "نوافذ", "شباك", "شبابيك", "زجاج", "ألومنيوم"),
    ),
    _TradeSpecTemplate(
        key="architectural_finishes",
        section_code="SPEC-03",
        discipline="architecture",
        title_en="Interior Finishes, Tiling, Ceilings & Painting",
        title_ar="التشطيبات الداخلية والبلاط والأسقف والدهانات",
        keywords=("floor", "tile", "porcelain", "vinyl", "paint", "plaster", "gypsum", "ceiling", "skirting", "finish", "waterproof", "screed", "بلاط", "بورسلان", "دهان", "لياسة", "جبس", "سقف", "أرضيات", "وزرة", "تشطيب"),
    ),
    _TradeSpecTemplate(
        key="civil_structural",
        section_code="SPEC-04",
        discipline="structural",
        title_en="Concrete, Reinforcement & Masonry Works",
        title_ar="أعمال الخرسانة وحديد التسليح والمباني",
        keywords=("concrete", "rebar", "reinforcement", "steel", "masonry", "block", "brick", "excavation", "foundation", "slab", "beam", "column", "structural", "خرسانة", "حديد", "تسليح", "بناء", "طوب", "بلوك", "حفر", "أساسات"),
    ),
    _TradeSpecTemplate(
        key="electrical",
        section_code="SPEC-05",
        discipline="electrical",
        title_en="Electrical Power Distribution, Cabling & Lighting",
        title_ar="التمديدات الكهربائية ولوحات التوزيع والإنارة",
        keywords=("electrical", "panel", "mdb", "db", "breaker", "mccb", "mcb", "cable", "wire", "conduit", "lighting", "luminaire", "socket", "receptacle", "earthing", "grounding", "voltage", "amp", "كهرباء", "كهربائي", "لوحة", "كابل", "قاطع", "إنارة", "مأخذ"),
    ),
    _TradeSpecTemplate(
        key="plumbing_hvac",
        section_code="SPEC-06",
        discipline="plumbing",
        title_en="Plumbing Piping, Sanitary Fixtures, Water Supply & HVAC",
        title_ar="أعمال السباكة والمواسير والأجهزة الصحية والتكييف",
        keywords=("plumbing", "pipe", "piping", "ppr", "upvc", "copper pipe", "galvanized", "valve", "pump", "tank", "sanitary", "wc", "lavatory", "sink", "water", "drainage", "hvac", "chiller", "split", "duct", "diffuser", "سباكة", "مواسير", "أنابيب", "محبس", "مضخة", "خزان", "صحي", "مياه", "صرف", "تكييف"),
    ),
)


@dataclass
class _SectionBucket:
    key: str
    section_code: str
    discipline: str
    title: str
    boq_items: list[dict[str, Any]] = field(default_factory=list)
    drawing_entries: list[dict[str, Any]] = field(default_factory=list)
    drawing_refs_set: set[str] = field(default_factory=set)
    boq_item_ids: list[str] = field(default_factory=list)
    drawing_ids: list[str] = field(default_factory=list)
    keywords_bag: set[str] = field(default_factory=set)


def _classify_boq_item_trade(item: dict[str, Any]) -> str:
    text = " ".join(
        str(item.get(k) or "")
        for k in ("discipline", "layer_or_category", "description", "technical_reference", "remarks")
    ).lower()
    for tmpl in _TRADE_TEMPLATES:
        if any(kw in text for kw in tmpl.keywords):
            return tmpl.key
    disc = str(item.get("discipline") or "").strip().lower()
    if disc in ("electrical",):
        return "electrical"
    if disc in ("plumbing", "mechanical", "hvac", "fire"):
        return "plumbing_hvac"
    if disc in ("structural", "civil"):
        return "civil_structural"
    if disc in ("architecture", "architectural", "finishes"):
        return "architectural_finishes"
    return "general_works"


def _match_sources_for_bucket(
    bucket: _SectionBucket,
    reviewed_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not reviewed_sources:
        return []
    tmpl_kw = next((t.keywords for t in _TRADE_TEMPLATES if t.key == bucket.key), ())
    bucket_text = " ".join(
        [bucket.title, bucket.discipline, *tmpl_kw, *bucket.keywords_bag]
        + [
            " ".join(str(it.get(k) or "") for k in ("description", "technical_reference", "remarks"))
            for it in bucket.boq_items
        ]
    ).lower()

    matched: list[dict[str, Any]] = []
    for rs in reviewed_sources:
        rs_text = " ".join(
            str(rs.get(k) or "")
            for k in ("source_name", "url", "relevant_info", "query_text", "source_priority_tier")
        ).lower()
        explicit_url_hit = any(
            str(rs.get("url") or "").lower() in str(it.get("technical_reference") or "").lower()
            or str(rs.get("source_name") or "").lower() in str(it.get("technical_reference") or "").lower()
            for it in bucket.boq_items
            if it.get("technical_reference")
        )
        disc_hit = bucket.discipline.lower() in rs_text or (
            bucket.discipline == "architecture" and any(w in rs_text for w in ("door", "window", "finish", "building", "architectural", "interior", "بناء", "معماري"))
        ) or (
            bucket.discipline == "plumbing" and any(w in rs_text for w in ("plumbing", "pipe", "water", "sanitary", "hvac", "سباكة", "مياه"))
        ) or (
            bucket.discipline == "electrical" and any(w in rs_text for w in ("electrical", "cable", "voltage", "power", "lighting", "كهرب"))
        ) or (
            bucket.discipline == "structural" and any(w in rs_text for w in ("concrete", "structural", "masonry", "steel", "خرسانة"))
        )
        kw_hit = any(kw in rs_text and kw in bucket_text for kw in tmpl_kw)
        if explicit_url_hit or disc_hit or kw_hit:
            matched.append(rs)
    return matched


def _part_labels(language: ReportLanguage) -> dict[SpecPartKey, str]:
    if language == "ar":
        return {
            "scope": "1. نطاق الأعمال (Scope)",
            "standards": "2. المعايير والمرجعيات المعتمدة (Standards)",
            "materials": "3. المواد والمنتجات (Materials)",
            "execution": "4. التنفيذ والمصنعية (Execution)",
            "testing": "5. الفحص والاختبارات الحقلية (Testing)",
            "acceptance": "6. معايير القبول والاستلام (Acceptance)",
            "submittals": "7. التقديمات والمخططات التنفيذية (Submittals)",
            "warranty": "8. الضمان ووثائق التسليم (Warranty)",
        }
    return {
        "scope": "1. Scope of Work",
        "standards": "2. Applicable Standards",
        "materials": "3. Materials & Products",
        "execution": "4. Execution & Installation",
        "testing": "5. Inspection & Testing",
        "acceptance": "6. Acceptance Criteria",
        "submittals": "7. Submittals",
        "warranty": "8. Warranty & Closeout",
    }


def build_deterministic_specification_sections(
    *,
    boq_sheets: list[dict[str, Any]],
    drawings: list[dict[str, Any]],
    reviewed_sources: list[dict[str, Any]],
    language: ReportLanguage,
) -> tuple[list[SpecSection], list[str], dict[str, Any]]:
    """Deterministically compile all Step 14 spec sections strictly from real BOQ items, drawing schedules, and reviewed sources."""
    all_boq_items: list[dict[str, Any]] = []
    for sheet in boq_sheets:
        for it in sheet.get("items") or []:
            row_copy = dict(it)
            row_copy["_boq_sheet_id"] = sheet["id"]
            row_copy["_boq_sheet_title"] = sheet["title"]
            all_boq_items.append(row_copy)

    if not all_boq_items and not drawings:
        raise SpecificationInputError(
            "Cannot generate technical specifications: project has neither BOQ items nor parametric drawing schedules."
        )

    is_ar = language == "ar"
    buckets: dict[str, _SectionBucket] = {}

    def _get_bucket(key: str) -> _SectionBucket:
        if key in buckets:
            return buckets[key]
        tmpl = next((t for t in _TRADE_TEMPLATES if t.key == key), None)
        if tmpl is not None:
            b = _SectionBucket(
                key=tmpl.key,
                section_code=tmpl.section_code,
                discipline=tmpl.discipline,
                title=tmpl.title_ar if is_ar else tmpl.title_en,
            )
        else:
            b = _SectionBucket(
                key="general_works",
                section_code="SPEC-07",
                discipline="multidisciplinary",
                title="الأعمال الهندسية العامة والتجهيزات المرتبطة بجدول الكميات" if is_ar else "General Works & Miscellaneous BOQ Items",
            )
        buckets[key] = b
        return b

    drawings_by_no = {str(d.get("drawing_no") or "").strip().upper(): d for d in drawings if d.get("drawing_no")}

    # 1. Map EVERY real BOQ item deterministically to its trade bucket + cross-linked drawings
    for it in all_boq_items:
        trade_key = _classify_boq_item_trade(it)
        bucket = _get_bucket(trade_key)
        bucket.boq_items.append(it)
        if it["id"] not in bucket.boq_item_ids:
            bucket.boq_item_ids.append(it["id"])
        dwg_ref_raw = str(it.get("drawing_reference") or "").strip()
        if dwg_ref_raw:
            for d_no, d_obj in drawings_by_no.items():
                if d_no and d_no in dwg_ref_raw.upper():
                    if d_obj["id"] not in bucket.drawing_ids:
                        bucket.drawing_ids.append(d_obj["id"])
                    bucket.drawing_refs_set.add(f"{d_obj['drawing_no']} ({d_obj['title']})")

    # 2. Attach EVERY real ParametricDrawing schedule (doors, windows, finishes/rooms)
    for dr in drawings:
        metrics = dr.get("computed_metrics_json") or {}
        door_sched = list(metrics.get("door_schedule") or [])
        win_sched = list(metrics.get("window_schedule") or [])
        rooms = list(metrics.get("rooms") or [])
        dwg_no = str(dr.get("drawing_no") or dr["id"][:8])

        if door_sched:
            b_doors = _get_bucket("architectural_doors")
            if dr["id"] not in b_doors.drawing_ids:
                b_doors.drawing_ids.append(dr["id"])
            ref_tag = f"{dwg_no}:door_schedule"
            b_doors.drawing_refs_set.add(ref_tag)
            b_doors.drawing_entries.append(
                {"drawing": dr, "schedule_kind": "door_schedule", "ref_tag": ref_tag, "rows": door_sched}
            )

        if win_sched:
            b_wins = _get_bucket("architectural_windows")
            if dr["id"] not in b_wins.drawing_ids:
                b_wins.drawing_ids.append(dr["id"])
            ref_tag = f"{dwg_no}:window_schedule"
            b_wins.drawing_refs_set.add(ref_tag)
            b_wins.drawing_entries.append(
                {"drawing": dr, "schedule_kind": "window_schedule", "ref_tag": ref_tag, "rows": win_sched}
            )

        if rooms:
            b_fin = _get_bucket("architectural_finishes")
            if dr["id"] not in b_fin.drawing_ids:
                b_fin.drawing_ids.append(dr["id"])
            ref_tag = f"{dwg_no}:finish_schedule"
            b_fin.drawing_refs_set.add(ref_tag)
            b_fin.drawing_entries.append(
                {"drawing": dr, "schedule_kind": "finish_schedule", "ref_tag": ref_tag, "rows": rooms}
            )

    order_map = {t.key: idx for idx, t in enumerate(_TRADE_TEMPLATES)}
    sorted_buckets = sorted(buckets.values(), key=lambda b: (order_map.get(b.key, 99), b.section_code))

    sections_out: list[SpecSection] = []
    missing_standards_notices: list[str] = []
    used_source_ids: set[str] = set()

    for seq_idx, bucket in enumerate(sorted_buckets, start=1):
        sec_code = f"SPEC-{seq_idx:02d}"
        sec_traces: list[SpecTraceRef] = []

        for idx, it in enumerate(bucket.boq_items, start=1):
            sec_traces.append(
                SpecTraceRef(
                    trace_id=f"BOQ-{it.get('item_no') or idx}",
                    trace_kind="boq_item",
                    boq_sheet_id=it["_boq_sheet_id"],
                    boq_item_id=it["id"],
                    boq_item_no=str(it.get("item_no") or f"Row {it.get('row_order', idx)}"),
                    label=f"BOQ {it.get('item_no') or idx}: {str(it.get('description') or '')[:80]} ({it.get('quantity')} {it.get('unit')})",
                )
            )

        for entry in bucket.drawing_entries:
            dr = entry["drawing"]
            dwg_no = str(dr.get("drawing_no") or dr["id"][:8])
            skind = entry["schedule_kind"]
            sec_traces.append(
                SpecTraceRef(
                    trace_id=f"DWG-{dwg_no}-{skind}",
                    trace_kind="drawing_schedule",
                    drawing_id=dr["id"],
                    drawing_no=dwg_no,
                    schedule_kind=skind,
                    label=f"Drawing {dwg_no} ({skind}, {len(entry['rows'])} row(s))",
                )
            )

        # Also ensure drawing_ids linked via BOQ drawing_reference without a matching schedule get a trace ref
        entry_dwg_ids = {e["drawing"]["id"] for e in bucket.drawing_entries}
        for dr in drawings:
            if dr["id"] in bucket.drawing_ids and dr["id"] not in entry_dwg_ids:
                dwg_no = str(dr.get("drawing_no") or dr["id"][:8])
                sec_traces.append(
                    SpecTraceRef(
                        trace_id=f"DWG-{dwg_no}",
                        trace_kind="drawing",
                        drawing_id=dr["id"],
                        drawing_no=dwg_no,
                        label=f"Drawing {dwg_no}: {dr.get('title')}",
                    )
                )

        matched_sources = _match_sources_for_bucket(bucket, reviewed_sources)
        std_citations: list[SpecStandardCitation] = []
        src_traces: list[SpecTraceRef] = []
        for s_idx, rs in enumerate(matched_sources, start=1):
            used_source_ids.add(rs["id"])
            pub_part = f" ({rs['publication_date']})" if rs.get("publication_date") else ""
            excerpt = str(rs.get("relevant_info") or "").strip()[:180]
            excerpt_part = f" — {excerpt}" if excerpt else ""
            cite_txt = (
                f"{rs['source_name']}{pub_part} [{rs['url']}]{excerpt_part} — {VERIFY_CODE_LABEL}"
            )
            std_citations.append(
                SpecStandardCitation(
                    research_source_id=rs["id"],
                    source_name=rs["source_name"],
                    url=rs["url"],
                    publication_date=rs.get("publication_date"),
                    status="verified_source_log",
                    citation_text=cite_txt,
                    verification_label=VERIFY_CODE_LABEL,
                )
            )
            src_traces.append(
                SpecTraceRef(
                    trace_id=f"SRC-{seq_idx:02d}-{s_idx:02d}",
                    trace_kind="research_source",
                    research_source_id=rs["id"],
                    source_url=rs["url"],
                    label=f"Source {rs['source_name']} ({rs['url']})",
                )
            )

        if not std_citations:
            std_citations.append(
                SpecStandardCitation(
                    research_source_id=None,
                    source_name=NO_VERIFIED_STANDARD_LABEL,
                    url="",
                    publication_date=None,
                    status="no_verified_standard_on_file",
                    citation_text=(
                        f"{NO_VERIFIED_STANDARD_LABEL} (لا يوجد معيار موثق في سجل البحث لهذا القسم)"
                        if is_ar
                        else NO_VERIFIED_STANDARD_LABEL
                    ),
                    verification_label=NO_VERIFIED_STANDARD_LABEL,
                )
            )
            missing_standards_notices.append(f"{sec_code} ({bucket.title}): {NO_VERIFIED_STANDARD_LABEL}")

        # Build concise grounded descriptions from exact BOQ & Drawing data
        boq_summary_bits = [
            f"[{it.get('item_no') or '?'}] {it.get('description')} (Qty: {it.get('quantity')} {it.get('unit')}; Status: {it.get('verification_status')})"
            for it in bucket.boq_items
        ]
        sched_summary_bits: list[str] = []
        mat_schedule_bits: list[str] = []
        dwg_refs_display: list[str] = []
        for entry in bucket.drawing_entries:
            dwg_no = str(entry["drawing"].get("drawing_no") or "")
            dwg_refs_display.append(f"{dwg_no} ({entry['schedule_kind']})")
            skind = entry["schedule_kind"]
            if skind == "door_schedule":
                for row in entry["rows"]:
                    sched_summary_bits.append(
                        f"Dwg {dwg_no} Door {row.get('mark')}: {row.get('count')} nos, {row.get('width_mm')}x{row.get('height_mm')}mm"
                    )
                    mat_schedule_bits.append(
                        f"Door {row.get('mark')}: material={row.get('material')}, fire_rating={row.get('fire_rating')}, hardware={row.get('hardware')}"
                    )
            elif skind == "window_schedule":
                for row in entry["rows"]:
                    sched_summary_bits.append(
                        f"Dwg {dwg_no} Window {row.get('mark')}: {row.get('count')} nos, {row.get('width_mm')}x{row.get('height_mm')}mm (sill {row.get('sill_mm')}mm)"
                    )
                    mat_schedule_bits.append(
                        f"Window {row.get('mark')}: glazing={row.get('glazing')}"
                    )
            elif skind == "finish_schedule":
                for row in entry["rows"]:
                    rm_label = row.get("name_ar") if is_ar else row.get("name_en")
                    sched_summary_bits.append(
                        f"Dwg {dwg_no} Room {row.get('room_id')} ({rm_label}): area={row.get('area_m2')} m2"
                    )
                    mat_schedule_bits.append(
                        f"Room {row.get('room_id')}: floor={row.get('floor_finish')}, wall={row.get('wall_finish')}, ceiling={row.get('ceiling_finish')}, skirting={row.get('skirting')}"
                    )

        boq_mat_bits = [
            f"{it.get('item_no') or '?'}: {it.get('description')}"
            + (f" [Ref: {it.get('technical_reference')}]" if it.get("technical_reference") else "")
            for it in bucket.boq_items
        ]
        all_scope_items = "; ".join(boq_summary_bits + sched_summary_bits) or bucket.title
        all_materials_items = "; ".join(boq_mat_bits + mat_schedule_bits) or bucket.title
        std_text_joined = " | ".join(c.citation_text for c in std_citations)
        dwg_refs_txt = ", ".join(sorted(bucket.drawing_refs_set)) or ("مخططات المشروع المعتمدة" if is_ar else "approved project drawings")

        base_traces = list(sec_traces[:12]) or list(src_traces[:4])
        std_clause_traces = list(src_traces) if src_traces else list(base_traces[:4])

        if is_ar:
            part_texts: dict[SpecPartKey, str] = {
                "scope": f"يشمل هذا القسم توريد وتنفيذ وفحص الأعمال المربوطة مباشرة ببنود جدول الكميات وجداول المخططات: {all_scope_items}.",
                "standards": (
                    f"المرجعيات المعتمدة من سجل المصادر المراجَع: {std_text_joined}. "
                    "(لا يُسمح بإدراج أي بنود مواصفات أو سنوات إصدار غير موثقة في السجل)."
                ),
                "materials": (
                    f"تُورَّد المواد والمكونات المطابقة لأوصاف المشروع المسجلة: {all_materials_items}. "
                    "يجب مطابقة درجات التصنيع والنشرات الفنية للمصنّع مع المالك والمهندس قبل التوريد."
                ),
                "execution": (
                    f"يُنفَّذ التركيب وفق المخططات التنفيذية المعتمدة ({dwg_refs_txt}) وتعليمات الشركة المصنّعة، "
                    "مع التحقق من المناسيب والأبعاد والربط مع التخصصات الأخرى وفق الكود المحلي المعتمد."
                ),
                "testing": (
                    f"تخضع بنود القسم ({bucket.title}) للفحص البصري والأبعادي والتشغيلي وفق خطة الفحص والاختبار (ITP) المعتمدة، "
                    f"مع التحقق من طرق الاختبار وحدود القبول وفق المرجعيات الموثقة أو الكود المحلي المعتمد ({VERIFY_CODE_LABEL})."
                ),
                "acceptance": (
                    "لا يُقبل الاستلام إلا بعد مطابقة الكميات والأعداد مع جدول الكميات وجداول المخططات، "
                    "وإغلاق كافة ملاحظات الجودة (QA)، وتأكيد أي بنود موسومة بـ Extracted-Needs-Check."
                ),
                "submittals": (
                    f"يقدّم المقاول قبل البدء: النشرات الفنية للمنتجات، العينات المعتمدة، المخططات التنفيذية المربوطة بالمرجع ({dwg_refs_txt})، "
                    "وشهادات الاختبار والجودة للاعتماد."
                ),
                "warranty": (
                    "يسلّم المقاول أدلة التشغيل والصيانة (O&M)، ومخططات الوضع الراهن (As-Built)، وقائمة قطع الغيار، "
                    "ووثائق الضمان التعاقدية وفق شروط العقد المحددة من المالك (دون افتراض مدد ضمان غير منصوص عليها)."
                ),
            }
        else:
            part_texts = {
                "scope": f"Work covered under this section comprises supply, installation, and verification directly mapped to project BOQ and drawing schedules: {all_scope_items}.",
                "standards": (
                    f"Applicable standards traceability from reviewed project source log: {std_text_joined}. "
                    "No unverified clause numbers, edition years, or external requirements are assumed."
                ),
                "materials": (
                    f"Provide materials conforming strictly to documented project descriptions and schedule attributes: {all_materials_items}. "
                    "Exact manufacturer grades and datasheets shall be verified by the Engineer prior to procurement."
                ),
                "execution": (
                    f"Install and coordinate all items strictly with project drawings ({dwg_refs_txt}) and manufacturer instructions, "
                    "verifying field dimensions, tolerances, and MEP/architectural interfaces against the locally adopted code."
                ),
                "testing": (
                    f"All works under '{bucket.title}' shall undergo visual, dimensional, and functional inspection per the approved "
                    f"Inspection & Test Plan (ITP), with test methods and pass criteria confirmed ({VERIFY_CODE_LABEL})."
                ),
                "acceptance": (
                    "Final acceptance requires reconciled quantities matching BOQ and Parametric Drawing schedules, signed submittal approvals, "
                    "and zero open QA findings or unconfirmed 'Extracted-Needs-Check' discrepancies."
                ),
                "submittals": (
                    f"Submit manufacturer product datasheets, physical samples, shop drawings coordinated with ({dwg_refs_txt}), "
                    "and factory/field test certificates for Engineer review prior to fabrication or installation."
                ),
                "warranty": (
                    "Provide O&M manuals, as-built markups, spare parts schedule, and executed contractor/manufacturer warranty documentation "
                    "per project Contract Conditions (no assumed warranty durations fabricated)."
                ),
            }

        clauses: list[SpecClause] = []
        for p_idx, part_key in enumerate(SPEC_SECTION_PARTS, start=1):
            refs_for_clause = std_clause_traces if part_key == "standards" else base_traces
            clauses.append(
                SpecClause(
                    clause_id=f"{sec_code}-{part_key.upper()}-01",
                    part=part_key,
                    text=part_texts[part_key],
                    draft_origin="deterministic_template",
                    trace_refs=refs_for_clause,
                )
            )

        sections_out.append(
            SpecSection(
                section_code=sec_code,
                title=bucket.title,
                discipline=bucket.discipline,
                mapped_boq_item_ids=bucket.boq_item_ids,
                mapped_drawing_ids=bucket.drawing_ids,
                mapped_drawing_refs=sorted(bucket.drawing_refs_set),
                standards=std_citations,
                clauses=clauses,
                missing_parts=[],
            )
        )

    metadata = {
        "source_boq_sheet_ids": [s["id"] for s in boq_sheets],
        "source_drawing_ids": [d["id"] for d in drawings],
        "source_research_ids": sorted(used_source_ids),
        "reviewed_sources_available": [
            {"id": rs["id"], "source_name": rs["source_name"], "url": rs["url"]}
            for rs in reviewed_sources
        ],
    }
    return sections_out, missing_standards_notices, metadata


class _AiClauseRewrite(BaseModel):
    section_code: str = Field(..., min_length=1, max_length=32)
    clause_id: str = Field(..., min_length=1, max_length=64)
    drafted_text: str = Field(..., min_length=10, max_length=4000)


class _AiSpecDraftPayload(BaseModel):
    executive_summary: str = Field(..., min_length=10, max_length=2500)
    clause_rewrites: list[_AiClauseRewrite] = Field(default_factory=list, max_length=80)


def _contains_ungrounded_standard(
    text: str,
    *,
    allowed_source_text: str,
) -> bool:
    for url_hit in _URL_RE.findall(text):
        if url_hit.lower() not in allowed_source_text:
            return True
    for std_hit in _UNGROUNDED_STD_RE.findall(text):
        if std_hit.lower() not in allowed_source_text:
            return True
    return False


def draft_specification_prose_with_ai(
    db: Session,
    secret_store: SecretStore,
    *,
    project_id: str,
    project_code: str,
    project_name: str,
    language: ReportLanguage,
    sections: list[SpecSection],
    reviewed_sources: list[dict[str, Any]],
    complexity: TaskComplexity = "fast",
    client_factory: Callable[[str], Any] | None = None,
    task_id: str | None = None,
) -> tuple[str, list[SpecSection], TokenUsage, int, int]:
    """Optional Gemini prose drafting: NEVER touches standards citations/numbers/mappings, tags every clause as UNVERIFIED AI DRAFT."""
    editable_items = [
        {
            "section_code": sec.section_code,
            "section_title": sec.title,
            "clause_id": cl.clause_id,
            "part": cl.part,
            "template_text": cl.text,
            "trace_labels": [tr.label for tr in cl.trace_refs[:6]],
        }
        for sec in sections
        for cl in sec.clauses
        if cl.part != "standards"
    ]
    prompt_payload = {
        "project": f"[{project_code}] {project_name}",
        "language": language,
        "rules": [
            "Rephrase prose clarity ONLY for the listed clauses.",
            "NEVER perform arithmetic or change quantities/units/dimensions.",
            "NEVER invent standard numbers, edition years, URLs, or unverified test thresholds.",
            "Keep exact section_code and clause_id keys unchanged.",
        ],
        "clauses": editable_items,
    }
    prompt_text = json.dumps(prompt_payload, ensure_ascii=False)
    prompt_chars = len(prompt_text)
    est_tokens = estimate_prompt_tokens(prompt_text)

    cfg = _load_provider_config(db)
    daily_usage, monthly_usage = _summarize_usage(db)
    if daily_usage.total_tokens + est_tokens > cfg.usage_limits.daily_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated specification AI draft prompt ({est_tokens} tokens) plus daily usage "
            f"({daily_usage.total_tokens}) would exceed Step 04 daily limit ({cfg.usage_limits.daily_token_limit})."
        )
    if monthly_usage.total_tokens + est_tokens > cfg.usage_limits.monthly_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated specification AI draft prompt ({est_tokens} tokens) plus monthly usage "
            f"({monthly_usage.total_tokens}) would exceed Step 04 monthly limit ({cfg.usage_limits.monthly_token_limit})."
        )

    sys_instr = (
        "You are an engineering consultancy specifications editor. Draft concise clear prose ONLY from the provided "
        "BOQ/drawing clause inputs in the requested language ('ar' or 'en'). Do not invent standards, clause numbers, "
        "edition years, URLs, brand grades, or numeric calculations."
    )
    llm_req = LLMRequest(
        prompt=prompt_text,
        system_instruction=sys_instr,
        complexity=complexity,
        temperature=0.1,
        response_schema=_AiSpecDraftPayload,
    )
    llm_resp = execute_provider_request(
        db,
        secret_store,
        llm_req,
        client_factory=client_factory,
        project_id=project_id,
        task_id=task_id,
    )
    try:
        parsed = _AiSpecDraftPayload.model_validate(llm_resp.parsed_json)
    except ValidationError as exc:
        raise ProviderResponseError(
            f"Specification AI draft JSON validation failed: {exc.errors()[0].get('msg', 'invalid schema')}"
        ) from exc

    allowed_text = " ".join(
        [
            " ".join(str(rs.get(k) or "") for k in ("source_name", "url", "relevant_info"))
            for rs in reviewed_sources
        ]
        + [item["template_text"] for item in editable_items]
    ).lower()

    rewrites_by_key = {
        (rw.section_code.strip(), rw.clause_id.strip()): sanitize_secret_text(rw.drafted_text.strip())
        for rw in parsed.clause_rewrites
        if rw.drafted_text.strip()
        and not _contains_ungrounded_standard(rw.drafted_text, allowed_source_text=allowed_text)
    }

    unverified_prefix = (
        f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] "
        if language == "ar"
        else f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] "
    )

    updated_sections: list[SpecSection] = []
    for sec in sections:
        new_clauses: list[SpecClause] = []
        for cl in sec.clauses:
            if cl.part != "standards":
                ai_txt = rewrites_by_key.get((sec.section_code, cl.clause_id))
                if ai_txt:
                    cleaned_ai = ai_txt if unverified_prefix.strip(" []") in ai_txt else f"{unverified_prefix}{ai_txt}"
                    new_clauses.append(
                        SpecClause(
                            clause_id=cl.clause_id,
                            part=cl.part,
                            text=cleaned_ai,
                            draft_origin="ai_unverified_draft",
                            trace_refs=cl.trace_refs,
                        )
                    )
                    continue
            new_clauses.append(cl)
        updated_sections.append(
            SpecSection(
                section_code=sec.section_code,
                title=sec.title,
                discipline=sec.discipline,
                mapped_boq_item_ids=sec.mapped_boq_item_ids,
                mapped_drawing_ids=sec.mapped_drawing_ids,
                mapped_drawing_refs=sec.mapped_drawing_refs,
                standards=sec.standards,
                clauses=new_clauses,
                missing_parts=sec.missing_parts,
            )
        )

    exec_sum = sanitize_secret_text(parsed.executive_summary.strip())
    if _contains_ungrounded_standard(exec_sum, allowed_source_text=allowed_text):
        exec_sum = ""
    if exec_sum:
        exec_sum = f"{unverified_prefix}{exec_sum}"
    return exec_sum, updated_sections, llm_resp.usage, est_tokens, prompt_chars
