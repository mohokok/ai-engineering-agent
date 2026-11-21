"""Bilingual Arabic RTL / English LTR DOCX & PDF technical specification exporter (reuses Step 9 bidi/Tahoma font helpers)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Inches, Pt, RGBColor
import pymupdf

from app.schemas.reports import ReportLanguage
from app.schemas.specifications import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NO_VERIFIED_STANDARD_LABEL,
    SPEC_SECTION_PARTS,
    SpecPartKey,
    SpecSection,
)
from app.services.report_generator import (
    _WINDOWS_FONTS_DIR,
    _configure_rtl_table,
    _esc,
    _esc_ltr,
    _esc_rtl_cell,
    _set_element_tag,
    _shade_cell,
    _style_paragraph,
)


@dataclass(frozen=True)
class SpecificationRenderData:
    """Normalized immutable technical specification payload rendered cleanly to DOCX and PDF."""

    project_code: str
    project_name: str
    title: str
    discipline: str
    language: ReportLanguage
    classification: str
    revision: str
    version: int
    export_version: int
    issued_at_iso: str
    use_ai: bool
    ai_draft_status: str
    owner_approved_by: str | None
    owner_approved_at_iso: str | None
    summary: str
    source_boq_sheet_ids: list[str] = field(default_factory=list)
    source_drawing_ids: list[str] = field(default_factory=list)
    source_research_ids: list[str] = field(default_factory=list)
    missing_standards_notices: list[str] = field(default_factory=list)
    sections: list[SpecSection] = field(default_factory=list)


_SPEC_LABELS: dict[ReportLanguage, dict[str, Any]] = {
    "ar": {
        "classification_prefix": "التصنيف",
        "disclaimer": "إشعار مهني: وثيقة المواصفات الفنية هذه أولية ومُشتقّة من بنود جدول الكميات والمخططات وسجل المصادر المراجَع — لا تُعتمد للتنفيذ إلا بعد التحقق وفق الكود المحلي المعتمد (verify against the locally adopted code) وتوقيع مهندس مرخص.",
        "project": "المشروع",
        "discipline": "التخصص",
        "rev_ver": "الإصدار / المراجعة",
        "date": "تاريخ التصدير (UTC)",
        "draft_det": "المسار الحتمي: مولَّد برمجياً من جداول الكميات والمخططات ومصادر البحث (0 توكن ذكاء اصطناعي).",
        "draft_approved": "صياغة مدعومة بالذكاء الاصطناعي — مُعتمَدة من المالك",
        "summary_heading": "الملخص والمرجعية التتبعية (Traceability Overview)",
        "trace_heading": "ملخص الربط بالمستندات الفعلية",
        "boq_count": "جداول الكميات المرتبطة",
        "dwg_count": "المخططات البارامترية المرتبطة",
        "src_count": "مصادر البحث الموثقة المستشهد بها",
        "missing_std_heading": "تنبيهات نقص المعايير الموثقة (يجب التحقق وفق الكود المحلي)",
        "sec_boq_map": "بنود جدول الكميات المرتبطة (BOQ IDs)",
        "sec_dwg_map": "المخططات والجداول المرتبطة",
        "std_table_title": "جدول المعايير المعتمدة للقسم",
        "col_std_status": "الحالة",
        "col_std_name": "المرجع / المعيار",
        "col_std_url": "الرابط / التاريخ",
        "col_std_label": "وسم التحقق",
        "trace_prefix": "التتبع",
        "parts": {
            "scope": "1. نطاق الأعمال (Scope)",
            "standards": "2. المعايير المعتمدة (Standards)",
            "materials": "3. المواد والمنتجات (Materials)",
            "execution": "4. التنفيذ والمصنعية (Execution)",
            "testing": "5. الفحص والاختبارات (Testing)",
            "acceptance": "6. معايير القبول (Acceptance)",
            "submittals": "7. التقديمات المطلوبة (Submittals)",
            "warranty": "8. الضمان والتسليم (Warranty)",
        },
    },
    "en": {
        "classification_prefix": "Classification",
        "disclaimer": "Engineering Notice: Technical specifications generated from actual project BOQs, parametric drawing schedules, and reviewed research sources — not construction-ready without verification against the locally adopted code and licensed engineer sign-off.",
        "project": "Project",
        "discipline": "Discipline",
        "rev_ver": "Version / Revision",
        "date": "Export Date (UTC)",
        "draft_det": "Deterministic Template Path: Derived directly from project BOQs, drawings & reviewed source log (0 AI tokens).",
        "draft_approved": "AI-Drafted Prose — Owner Approved",
        "summary_heading": "Executive Summary & Traceability Overview",
        "trace_heading": "Project Source Mapping Summary",
        "boq_count": "Linked BOQ Sheets",
        "dwg_count": "Linked Parametric Drawings",
        "src_count": "Verified Research Sources Cited",
        "missing_std_heading": "Sections Without Verified Standards on File",
        "sec_boq_map": "Mapped BOQ Item IDs",
        "sec_dwg_map": "Mapped Drawings & Schedules",
        "std_table_title": "Section Applicable Standards",
        "col_std_status": "Status",
        "col_std_name": "Standard / Source Name",
        "col_std_url": "URL & Date",
        "col_std_label": "Verification Label",
        "trace_prefix": "Trace",
        "parts": {
            "scope": "1. Scope of Work",
            "standards": "2. Applicable Standards",
            "materials": "3. Materials & Products",
            "execution": "4. Execution & Installation",
            "testing": "5. Inspection & Testing",
            "acceptance": "6. Acceptance Criteria",
            "submittals": "7. Submittals",
            "warranty": "8. Warranty & Closeout",
        },
    },
}


def _draft_banner_text(data: SpecificationRenderData, lbl: dict[str, Any]) -> tuple[str, bool]:
    if data.ai_draft_status == "unverified_ai_draft":
        if data.language == "ar":
            return f"{AI_UNVERIFIED_DRAFT_LABEL_AR} — ({AI_UNVERIFIED_DRAFT_LABEL_EN})", True
        return AI_UNVERIFIED_DRAFT_LABEL_EN, True
    if data.ai_draft_status == "owner_approved":
        who = data.owner_approved_by or "Owner"
        when = data.owner_approved_at_iso or ""
        return f"{lbl['draft_approved']}: {who} ({when})".strip(), False
    return str(lbl["draft_det"]), False


def generate_specification_docx(out_path: Path, data: SpecificationRenderData) -> None:
    """Write an immutable bilingual (Arabic RTL / English LTR) technical specification DOCX document."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing specification DOCX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _SPEC_LABELS[data.language]
    doc = Document()

    section = doc.sections[0]
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.6)
    section.right_margin = Inches(0.6)
    if is_ar:
        _set_element_tag(section._sectPr, "w:bidi")

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Tahoma" if is_ar else "Calibri"
    normal_style.font.size = Pt(10)

    h = doc.add_heading(f"{data.title} — [{lbl['classification_prefix']}: {data.classification}]", level=1)
    _style_paragraph(h, is_ar=is_ar, bold=True, font_size=15, color=RGBColor(0x1E, 0x3A, 0x5F))

    meta = (
        f"{lbl['project']}: [{data.project_code}] {data.project_name} | "
        f"{lbl['discipline']}: {data.discipline} | "
        f"{lbl['rev_ver']}: v{data.version} ({data.revision}, Export #{data.export_version}) | "
        f"{lbl['date']}: {data.issued_at_iso}"
    )
    p_meta = doc.add_paragraph(meta)
    _style_paragraph(p_meta, is_ar=is_ar, font_size=9, color=RGBColor(0x33, 0x41, 0x55))

    banner_txt, is_unverified = _draft_banner_text(data, lbl)
    p_draft = doc.add_paragraph(banner_txt)
    _style_paragraph(
        p_draft,
        is_ar=is_ar,
        bold=True,
        font_size=9,
        color=RGBColor(0xB9, 0x1C, 0x1C) if is_unverified else RGBColor(0x1E, 0x3A, 0x5F),
    )

    p_disc = doc.add_paragraph(lbl["disclaimer"])
    _style_paragraph(p_disc, is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0x9A, 0x34, 0x12))

    # Summary & mapping overview
    p_sum_h = doc.add_heading(lbl["summary_heading"], level=2)
    _style_paragraph(p_sum_h, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    p_sum = doc.add_paragraph(data.summary)
    _style_paragraph(p_sum, is_ar=is_ar, font_size=10)

    p_map = doc.add_paragraph(
        f"{lbl['boq_count']}: {len(data.source_boq_sheet_ids)} | "
        f"{lbl['dwg_count']}: {len(data.source_drawing_ids)} | "
        f"{lbl['src_count']}: {len(data.source_research_ids)}"
    )
    _style_paragraph(p_map, is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0x03, 0x69, 0xA1))

    if data.missing_standards_notices:
        p_m_h = doc.add_heading(lbl["missing_std_heading"], level=3)
        _style_paragraph(p_m_h, is_ar=is_ar, bold=True, font_size=10, color=RGBColor(0x9A, 0x34, 0x12))
        for msg in data.missing_standards_notices:
            pm = doc.add_paragraph(f"• {msg}")
            _style_paragraph(pm, is_ar=is_ar, font_size=9, color=RGBColor(0x9A, 0x34, 0x12))

    parts_labels: dict[SpecPartKey, str] = lbl["parts"]
    for sec in data.sections:
        p_sh = doc.add_heading(f"{sec.section_code} — {sec.title} ({sec.discipline})", level=2)
        _style_paragraph(p_sh, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))

        map_line = (
            f"{lbl['sec_boq_map']}: {', '.join(b[:8] for b in sec.mapped_boq_item_ids) or '—'} | "
            f"{lbl['sec_dwg_map']}: {', '.join(sec.mapped_drawing_refs) or '—'}"
        )
        pmap = doc.add_paragraph(map_line)
        _style_paragraph(pmap, is_ar=is_ar, font_size=8, color=RGBColor(0x47, 0x55, 0x69))

        # Standards table
        p_st_h = doc.add_heading(lbl["std_table_title"], level=3)
        _style_paragraph(p_st_h, is_ar=is_ar, bold=True, font_size=10, color=RGBColor(0x1E, 0x3A, 0x5F))
        stbl = doc.add_table(rows=1, cols=4)
        _configure_rtl_table(stbl, is_ar=is_ar)
        hdrs = (lbl["col_std_status"], lbl["col_std_name"], lbl["col_std_url"], lbl["col_std_label"])
        for i, htxt in enumerate(hdrs):
            stbl.rows[0].cells[i].text = htxt
            _shade_cell(stbl.rows[0].cells[i], "1E3A5F")
            _style_paragraph(stbl.rows[0].cells[i].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
        for std in sec.standards:
            rc = stbl.add_row().cells
            rc[0].text = std.status
            rc[1].text = std.source_name
            rc[2].text = f"{std.url or '—'} ({std.publication_date or '—'})"
            rc[3].text = std.verification_label or NO_VERIFIED_STANDARD_LABEL
            if std.status == "no_verified_standard_on_file":
                _shade_cell(rc[0], "FEF3C7")
            for c_obj in rc:
                _style_paragraph(c_obj.paragraphs[0], is_ar=is_ar, font_size=8)

        # Clauses organized cleanly across the 8 required sub-sections
        clauses_by_part: dict[SpecPartKey, list[Any]] = {k: [] for k in SPEC_SECTION_PARTS}
        for cl in sec.clauses:
            clauses_by_part.setdefault(cl.part, []).append(cl)
        for pkey in SPEC_SECTION_PARTS:
            p_ph = doc.add_heading(parts_labels[pkey], level=3)
            _style_paragraph(p_ph, is_ar=is_ar, bold=True, font_size=10, color=RGBColor(0x1E, 0x3A, 0x5F))
            for cl in clauses_by_part.get(pkey, []):
                trace_str = " | ".join(f"{tr.trace_id}: {tr.label}" for tr in cl.trace_refs[:6])
                p_cl = doc.add_paragraph(
                    f"[{cl.clause_id}] {cl.text}\n[{lbl['trace_prefix']}: {trace_str}]"
                )
                _style_paragraph(p_cl, is_ar=is_ar, font_size=9)

    doc.save(str(out_path))


def generate_specification_pdf(out_path: Path, data: SpecificationRenderData) -> None:
    """Render crisp bilingual (Arabic RTL / English LTR) multi-page vector PDF via PyMuPDF Story + Tahoma."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing specification PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _SPEC_LABELS[data.language]

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    font_face_css = ""
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'SpecFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'SpecFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'SpecFont', Tahoma, sans-serif"
    else:
        font_stack = "sans-serif"

    banner_txt, is_unverified = _draft_banner_text(data, lbl)
    banner_cls = "warn-banner" if is_unverified else "ok-banner"
    parts_labels: dict[SpecPartKey, str] = lbl["parts"]

    missing_html = ""
    if data.missing_standards_notices:
        lis = "".join(f"<li>{_esc_rtl_cell(m, is_ar=is_ar)}</li>" for m in data.missing_standards_notices)
        missing_html = (
            f"<div class='warn-banner'><strong>{_esc(lbl['missing_std_heading'])}</strong>"
            f"<ul>{lis}</ul></div>"
        )

    sections_html_parts: list[str] = []
    for sec in data.sections:
        boq_map_txt = ", ".join(b[:8] for b in sec.mapped_boq_item_ids) or "—"
        dwg_map_txt = ", ".join(sec.mapped_drawing_refs) or "—"
        std_rows = "".join(
            f"<tr class=\"{'warn-row' if s.status == 'no_verified_standard_on_file' else ''}\">"
            f"<td>{_esc_ltr(s.status)}</td>"
            f"<td>{_esc_rtl_cell(s.source_name, is_ar=is_ar)}</td>"
            f"<td>{_esc_ltr((s.url or '—') + (' | ' + s.publication_date if s.publication_date else ''))}</td>"
            f"<td><strong>{_esc_rtl_cell(s.verification_label, is_ar=is_ar)}</strong></td>"
            f"</tr>"
            for s in sec.standards
        )
        std_tbl_html = (
            f"<h4>{_esc(lbl['std_table_title'])}</h4>"
            f"<table><thead><tr>"
            f"<th>{_esc(lbl['col_std_status'])}</th>"
            f"<th>{_esc(lbl['col_std_name'])}</th>"
            f"<th>{_esc(lbl['col_std_url'])}</th>"
            f"<th>{_esc(lbl['col_std_label'])}</th>"
            f"</tr></thead><tbody>{std_rows}</tbody></table>"
        )

        clauses_by_part: dict[SpecPartKey, list[Any]] = {k: [] for k in SPEC_SECTION_PARTS}
        for cl in sec.clauses:
            clauses_by_part.setdefault(cl.part, []).append(cl)
        part_blocks: list[str] = []
        for pkey in SPEC_SECTION_PARTS:
            cl_lis = []
            for cl in clauses_by_part.get(pkey, []):
                trace_badges = " | ".join(_esc_rtl_cell(f"{tr.trace_id}: {tr.label}", is_ar=is_ar) for tr in cl.trace_refs[:6])
                origin_badge = (
                    f" <span class='ai-tag'>{_esc(AI_UNVERIFIED_DRAFT_LABEL_AR if is_ar else AI_UNVERIFIED_DRAFT_LABEL_EN)}</span>"
                    if cl.draft_origin == "ai_unverified_draft"
                    else ""
                )
                cl_lis.append(
                    f"<li><strong>{_esc_ltr('[' + cl.clause_id + ']')}</strong>{origin_badge} "
                    f"{_esc_rtl_cell(cl.text, is_ar=is_ar)}"
                    f"<div class='trace'>{_esc(lbl['trace_prefix'])}: {trace_badges}</div></li>"
                )
            part_blocks.append(f"<h4>{_esc(parts_labels[pkey])}</h4><ul>{''.join(cl_lis)}</ul>")

        sections_html_parts.append(
            f"<div class='sec-block'>"
            f"<h2>{_esc_ltr(sec.section_code)} — {_esc(sec.title)} ({_esc_ltr(sec.discipline)})</h2>"
            f"<div class='meta'>{_esc(lbl['sec_boq_map'])}: {_esc_ltr(boq_map_txt)} | {_esc(lbl['sec_dwg_map'])}: {_esc_rtl_cell(dwg_map_txt, is_ar=is_ar)}</div>"
            f"{std_tbl_html}"
            f"{''.join(part_blocks)}"
            f"</div>"
        )

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{_esc(data.language)}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 9.2pt; color: #0f172a; line-height: 1.45; hyphens: none; }}
.banner {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 6pt; margin-bottom: 8pt; }}
h1 {{ font-size: 13.5pt; color: #1e3a5f; margin: 0 0 4pt 0; }}
h2 {{ font-size: 11pt; color: #1e3a5f; margin: 10pt 0 4pt 0; border-bottom: 1px solid #cbd5e1; padding-bottom: 2pt; page-break-after: avoid; }}
h4 {{ font-size: 9.5pt; color: #1e3a5f; margin: 6pt 0 2pt 0; page-break-after: avoid; }}
.badge {{ display: inline-block; background-color: #dbeafe; color: #1e3a5f; font-weight: bold; padding: 2pt 6pt; border: 1px solid #93c5fd; font-size: 8.5pt; }}
.warn-banner {{ background-color: #fef3c7; border: 0.8pt solid #d97706; color: #92400e; padding: 5pt 7pt; font-weight: bold; font-size: 8.6pt; margin: 4pt 0; }}
.ok-banner {{ background-color: #ecfdf5; border: 0.8pt solid #16a34a; color: #166534; padding: 5pt 7pt; font-weight: bold; font-size: 8.6pt; margin: 4pt 0; }}
.disclaimer {{ color: #9a3412; font-weight: bold; font-size: 8.4pt; margin-top: 4pt; }}
.meta {{ font-size: 8.3pt; color: #334155; margin: 2pt 0 4pt 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 4pt 0 6pt 0; direction: {dir_attr}; font-size: 8pt; }}
th, td {{ border: 0.6pt solid #94a3b8; padding: 3.5pt 4pt; text-align: {align}; vertical-align: top; }}
th {{ background-color: #1e3a5f; color: #ffffff; font-weight: bold; }}
.warn-row td {{ background-color: #fef3c7; }}
.trace {{ color: #0369a1; font-size: 7.7pt; margin-top: 1.5pt; }}
.ai-tag {{ background-color: #fee2e2; color: #991b1b; padding: 1pt 4pt; font-size: 7.5pt; font-weight: bold; }}
ul {{ margin: 2pt 0 5pt 0; padding-left: 14pt; padding-right: 14pt; }}
li {{ margin-bottom: 3pt; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(data.title)} &nbsp; <span class="badge">{_esc(lbl['classification_prefix'])}: {_esc_ltr(data.classification)}</span></h1>
    <div class="meta">{_esc(lbl['project'])}: {_esc_ltr('[' + data.project_code + ']')} {_esc(data.project_name)} | {_esc(lbl['discipline'])}: {_esc_ltr(data.discipline)} | {_esc(lbl['rev_ver'])}: {_esc_ltr(f'v{data.version} ({data.revision}, Export #{data.export_version})')} | {_esc(lbl['date'])}: {_esc_ltr(data.issued_at_iso)}</div>
    <div class="{banner_cls}">{_esc(banner_txt)}</div>
    <div class="disclaimer">{_esc(lbl['disclaimer'])}</div>
  </div>
  <h2>{_esc(lbl['summary_heading'])}</h2>
  <p>{_esc_rtl_cell(data.summary, is_ar=is_ar)}</p>
  <div class="meta">{_esc(lbl['boq_count'])}: {_esc_ltr(len(data.source_boq_sheet_ids))} | {_esc(lbl['dwg_count'])}: {_esc_ltr(len(data.source_drawing_ids))} | {_esc(lbl['src_count'])}: {_esc_ltr(len(data.source_research_ids))}</div>
  {missing_html}
  {''.join(sections_html_parts)}
</body>
</html>"""

    archive = pymupdf.Archive(str(_WINDOWS_FONTS_DIR)) if has_win_tahoma else None
    story = pymupdf.Story(html=html_doc, archive=archive)
    writer = pymupdf.DocumentWriter(str(out_path))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    try:
        more = True
        page_guard = 0
        while more and page_guard < 120:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            page_guard += 1
    finally:
        writer.close()
