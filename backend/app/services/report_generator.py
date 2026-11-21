"""Deterministic Arabic RTL / English LTR DOCX and PDF report generator for Step 09."""

from dataclasses import dataclass, field
import html
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
import pymupdf

from app.schemas.reports import (
    CategorizedStatement,
    DocumentRegisterEntry,
    OcrExtractedTextItem,
    ReportLanguage,
    ReviewFinding,
    RevisionBlockOut,
    SourceLocationRef,
)

_WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")


@dataclass(frozen=True)
class ReviewReportRenderData:
    """Normalized immutable report payload rendered symmetrically to DOCX and PDF."""

    project_code: str
    project_name: str
    client_name: str | None
    location: str | None
    title: str
    discipline: str
    language: ReportLanguage
    classification: str
    summary: str
    revision_block: RevisionBlockOut
    findings: list[ReviewFinding]
    verified_facts: list[CategorizedStatement]
    calculated_items: list[CategorizedStatement]
    assumptions: list[CategorizedStatement]
    recommendations: list[CategorizedStatement]
    gaps_or_unextracted: list[str]
    source_registry: list[SourceLocationRef]
    is_inventory_only: bool = True
    document_register: list[DocumentRegisterEntry] = field(default_factory=list)
    verified_facts_total: int = 0
    verified_facts_shown: int = 0
    appendix_verified_facts: list[CategorizedStatement] = field(default_factory=list)
    ocr_text_items: list[OcrExtractedTextItem] = field(default_factory=list)


_LABELS: dict[ReportLanguage, dict[str, str]] = {
    "ar": {
        "classification_prefix": "التصنيف",
        "disclaimer": "ملاحظة: هذا التقرير استشاري أولي لا يُعد صالحاً للتنفيذ دون مراجعة واعتماد مهندس مرخص.",
        "inventory_notice": "إشعار النطاق: هذا التقرير في الوضع الحتمي عبارة عن جرد ملفات وفحص تقني آلي فقط (0 توكن) — وليس مراجعة هندسية فنية.",
        "project": "المشروع",
        "client": "الجهة المالكة",
        "location": "الموقع",
        "discipline": "التخصص",
        "revision_heading": "جدول ضبط الوثيقة والمراجعة (Revision Block)",
        "ver_label": "الإصدار / المراجعة",
        "date_label": "تاريخ الإصدار",
        "prepared_label": "أعده",
        "sources_label": "المصادر المراجَعة",
        "change_label": "ملاحظة التعديل",
        "summary_heading": "الملخص التنفيذي",
        "register_heading": "0. سجل المستندات والملفات (Document Register)",
        "reg_file": "الملف",
        "reg_type": "النوع",
        "reg_scope": "الصفحات / العناصر",
        "reg_status": "حالة الاستخراج والوحدات",
        "reg_conf": "مستوى الثقة",
        "findings_heading": "1. الملاحظات والعيوب المرصودة فعلياً (مربوطة بالمصادر)",
        "col_id": "المعرف",
        "col_disc": "التخصص",
        "col_sev": "الخطورة",
        "col_loc": "المرجع / الموقع",
        "col_ev": "الأدلة ورابط المصدر",
        "col_rec": "الإجراء المطلوب",
        "col_stat": "الحالة",
        "source_link_prefix": "المصدر",
        "facts_heading": "2.1 الحقائق الحتمية والبيانات الأصلية (Verified Facts)",
        "calc_heading": "2.2 القيم المحسوبة برمجياً (مجاميع هندسية وليست صافي مساحة مبنى)",
        "ocr_heading": "2.3 نصوص مستخرجة بالتعرف الضوئي (OCR — غير مُتحقَّق منها)",
        "assump_heading": "2.4 الافتراضات الأولية (تحتاج تأكيد المالك)",
        "recs_heading": "2.5 التوصيات المرتبطة بالعيوب المرصودة",
        "appendix_heading": "الملحق أ: القائمة الكاملة للحقائق الحتمية (كل البنود)",
        "sources_heading": "3. سجل المصادر المرجعية (الاستخراج وسجل البحث)",
        "gaps_heading": "4. فجوات البيانات والمستندات غير المستخرجة / غير المراجَعة",
        "empty_section": "لا توجد بنود مسجلة في هذا القسم ضمن النطاق الحالي.",
        "empty_findings": "لا توجد عيوب أو تعارضات مرصودة ضمن نطاق الفحص الحتمي.",
        "method_prefix": "طريقة الحساب",
    },
    "en": {
        "classification_prefix": "Classification",
        "disclaimer": "Notice: Advisory engineering output — not construction-ready without a licensed engineer's sign-off.",
        "inventory_notice": "SCOPE NOTICE: Deterministic mode produces a file inventory & automated technical check (0 tokens) — it is NOT an engineering review.",
        "project": "Project",
        "client": "Client / Owner",
        "location": "Location",
        "discipline": "Discipline",
        "revision_heading": "Document Control & Revision Block",
        "ver_label": "Version / Revision",
        "date_label": "Issue Date (UTC)",
        "prepared_label": "Prepared By",
        "sources_label": "Sources Included",
        "change_label": "Revision Note",
        "summary_heading": "Executive Summary",
        "register_heading": "0. Document Register",
        "reg_file": "File",
        "reg_type": "Type",
        "reg_scope": "Pages / Entities",
        "reg_status": "Extraction Status & Units",
        "reg_conf": "Confidence / Verification",
        "findings_heading": "1. Concrete Observed Issues & Discrepancies (Source-Linked)",
        "col_id": "ID",
        "col_disc": "Discipline",
        "col_sev": "Severity",
        "col_loc": "Location / Drawing Ref",
        "col_ev": "Observed Evidence & Source Link",
        "col_rec": "Required Verification Action",
        "col_stat": "Status",
        "source_link_prefix": "Source",
        "facts_heading": "2.1 Verified Facts (Deterministic Metadata & Native Extractions Only)",
        "calc_heading": "2.2 Deterministic Calculated Quantities & Checks",
        "ocr_heading": "2.3 Extracted Text (OCR — Per-Page Confidence, Not Verified)",
        "assump_heading": "2.4 Preliminary Assumptions (Pending Owner Confirmation)",
        "recs_heading": "2.5 Action Recommendations (Linked to Observed Findings)",
        "appendix_heading": "Appendix A: Complete Verified Facts Inventory",
        "sources_heading": "3. Source Location & Provenance Register",
        "gaps_heading": "4. Data Gaps & Unextracted / Unreviewed Sources",
        "empty_section": "No items recorded in this category for the current review scope.",
        "empty_findings": "No concrete unit, reconciliation, OCR, or missing-data issues observed.",
        "method_prefix": "Method / Formula",
    },
}


def _facts_scope_banner(data: ReviewReportRenderData) -> str | None:
    total = data.verified_facts_total if data.verified_facts_total else len(data.verified_facts)
    shown = data.verified_facts_shown if data.verified_facts_total else len(data.verified_facts)
    if total == 0:
        return None
    if data.language == "ar":
        if total > shown:
            return f"عرض {shown} من أصل {total} حقيقة — القائمة الكاملة ({total} بنداً) متاحة في الملحق أ وملف JSON المرفق في 08_Reports."
        return f"عرض {shown} من أصل {total} حقيقة (كامل البنود)."
    if total > shown:
        return f"Showing {shown} of {total} verified facts — complete list of {total} items is included in Appendix A and the 08_Reports JSON log."
    return f"Showing {shown} of {total} verified facts (complete)."


def _collect_cited_sources(data: ReviewReportRenderData) -> list[SourceLocationRef]:
    """Return only sources actually cited across findings, facts, calculations, OCR, assumptions, or recommendations."""
    cited_ids: set[str] = set()
    cited_map: dict[str, SourceLocationRef] = {}

    def _scan_links(links: Iterable[SourceLocationRef] | None) -> None:
        if not links:
            return
        for ref in links:
            if ref.ref_id not in cited_ids:
                cited_ids.add(ref.ref_id)
                cited_map[ref.ref_id] = ref

    for finding in data.findings:
        _scan_links(finding.source_links)
    for stmt in data.verified_facts:
        _scan_links(stmt.source_links)
    for stmt in data.appendix_verified_facts:
        _scan_links(stmt.source_links)
    for stmt in data.calculated_items:
        _scan_links(stmt.source_links)
    for ocr_item in data.ocr_text_items:
        _scan_links(ocr_item.source_links)
    for stmt in data.assumptions:
        _scan_links(stmt.source_links)
    for stmt in data.recommendations:
        _scan_links(stmt.source_links)

    ordered = [ref for ref in data.source_registry if ref.ref_id in cited_ids]
    seen_ids = {ref.ref_id for ref in ordered}
    for ref_id, ref in cited_map.items():
        if ref_id not in seen_ids:
            ordered.append(ref)
    return ordered


def _sources_scope_banner(
    data: ReviewReportRenderData,
    *,
    cited_count: int,
    total_count: int,
) -> str | None:
    if cited_count == 0 and total_count == 0:
        return None
    if data.language == "ar":
        return (
            f"عرض المصادر المستشهد بها فقط: {cited_count} من أصل {total_count} مستخرج "
            f"({cited_count} cited of {total_count} extracted) — السجل الكامل ({total_count}) محفوظ في ملف JSON المرفق في 08_Reports."
        )
    return (
        f"{cited_count} cited of {total_count} extracted — complete {total_count}-source provenance registry "
        "is preserved in the companion 08_Reports JSON file."
    )


def _format_source_links_text(links: Iterable[SourceLocationRef]) -> str:
    parts: list[str] = []
    for ref in links:
        loc_bits = [ref.ref_id, ref.source_name, ref.page_or_sheet, ref.location]
        if ref.url:
            loc_bits.append(ref.url)
        parts.append(" | ".join(b for b in loc_bits if b))
    return " ; ".join(parts) if parts else "Unlinked"


def _set_element_tag(parent_el: OxmlElement, tag_name: str, attrs: dict[str, str] | None = None) -> None:
    existing = parent_el.find(qn(tag_name))
    if existing is None:
        existing = OxmlElement(tag_name)
        parent_el.append(existing)
    if attrs:
        for k, v in attrs.items():
            existing.set(qn(k), v)


def _style_paragraph(paragraph: Any, *, is_ar: bool, bold: bool = False, font_size: int = 10, color: RGBColor | None = None) -> None:
    if is_ar:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_pr = paragraph._p.get_or_add_pPr()
        _set_element_tag(p_pr, "w:bidi")
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for run in paragraph.runs:
        run.bold = bold or run.bold
        run.font.size = Pt(font_size)
        run.font.name = "Tahoma" if is_ar else "Calibri"
        if color is not None:
            run.font.color.rgb = color
        r_pr = run._r.get_or_add_rPr()
        _set_element_tag(
            r_pr,
            "w:rFonts",
            {
                "w:ascii": "Tahoma" if is_ar else "Calibri",
                "w:hAnsi": "Tahoma" if is_ar else "Calibri",
                "w:cs": "Tahoma",
            },
        )
        if is_ar:
            _set_element_tag(r_pr, "w:rtl")


def _shade_cell(cell: Any, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    _set_element_tag(tc_pr, "w:shd", {"w:val": "clear", "w:color": "auto", "w:fill": fill_hex})


def _configure_rtl_table(table: Any, *, is_ar: bool) -> None:
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.RIGHT if is_ar else WD_TABLE_ALIGNMENT.LEFT
    if is_ar:
        tbl_pr = table._tbl.tblPr
        if tbl_pr is not None:
            _set_element_tag(tbl_pr, "w:bidiVisual")


def generate_review_report_docx(out_path: Path, data: ReviewReportRenderData) -> None:
    """Write a complete bilingual (Arabic RTL / English LTR) DOCX review report cleanly."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing deliverable DOCX: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _LABELS[data.language]
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

    # 1. Title & Classification Banner
    h = doc.add_heading(f"{data.title} — [{lbl['classification_prefix']}: {data.classification}]", level=1)
    _style_paragraph(h, is_ar=is_ar, bold=True, font_size=15, color=RGBColor(0x1E, 0x3A, 0x5F))

    meta_line = (
        f"{lbl['project']}: [{data.project_code}] {data.project_name} | "
        f"{lbl['discipline']}: {data.discipline} | "
        f"{lbl['classification_prefix']}: {data.classification}"
    )
    if data.client_name:
        meta_line += f" | {lbl['client']}: {data.client_name}"
    if data.location:
        meta_line += f" | {lbl['location']}: {data.location}"
    p_meta = doc.add_paragraph(meta_line)
    _style_paragraph(p_meta, is_ar=is_ar, font_size=9, color=RGBColor(0x33, 0x41, 0x55))

    p_disc = doc.add_paragraph(lbl["disclaimer"])
    _style_paragraph(p_disc, is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0x9A, 0x34, 0x12))

    # 2. Revision Block Table
    p_rev_h = doc.add_heading(lbl["revision_heading"], level=2)
    _style_paragraph(p_rev_h, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))

    rev_rows = [
        (lbl["ver_label"], f"v{data.revision_block.version} ({data.revision_block.revision})"),
        (lbl["classification_prefix"], str(data.revision_block.classification)),
        (lbl["date_label"], data.revision_block.issued_at_iso),
        (lbl["prepared_label"], f"{data.revision_block.prepared_by} — {data.revision_block.review_notice}"),
        (
            lbl["sources_label"],
            f"Files={data.revision_block.source_files_count}, Reviewed Research={data.revision_block.reviewed_research_count}",
        ),
        (lbl["change_label"], data.revision_block.change_note),
    ]
    rev_tbl = doc.add_table(rows=len(rev_rows), cols=2)
    _configure_rtl_table(rev_tbl, is_ar=is_ar)
    for row_idx, (k, v) in enumerate(rev_rows):
        c0 = rev_tbl.rows[row_idx].cells[0]
        c1 = rev_tbl.rows[row_idx].cells[1]
        c0.text = k
        c1.text = v
        _shade_cell(c0, "E2E8F0")
        for p in c0.paragraphs:
            _style_paragraph(p, is_ar=is_ar, bold=True, font_size=9)
        for p in c1.paragraphs:
            _style_paragraph(p, is_ar=is_ar, font_size=9)

    # 3. Executive Summary & Deterministic Inventory Notice
    if data.is_inventory_only:
        p_inv = doc.add_paragraph(lbl["inventory_notice"])
        _style_paragraph(p_inv, is_ar=is_ar, bold=True, font_size=9.5, color=RGBColor(0x92, 0x40, 0x0E))
    p_sum_h = doc.add_heading(lbl["summary_heading"], level=2)
    _style_paragraph(p_sum_h, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    p_sum = doc.add_paragraph(data.summary)
    _style_paragraph(p_sum, is_ar=is_ar, font_size=10)

    # 3b. Plain Document Register Table
    p_reg_h = doc.add_heading(lbl["register_heading"], level=2)
    _style_paragraph(p_reg_h, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    if not data.document_register:
        p_empty = doc.add_paragraph(lbl["empty_section"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        reg_headers = [
            lbl["reg_file"],
            lbl["reg_type"],
            lbl["reg_scope"],
            lbl["reg_status"],
            lbl["reg_conf"],
        ]
        reg_tbl = doc.add_table(rows=1 + len(data.document_register), cols=len(reg_headers))
        _configure_rtl_table(reg_tbl, is_ar=is_ar)
        for idx, htxt in enumerate(reg_headers):
            cell = reg_tbl.rows[0].cells[idx]
            cell.text = htxt
            _shade_cell(cell, "1E3A5F")
            for p in cell.paragraphs:
                _style_paragraph(p, is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
        for r_idx, row_reg in enumerate(data.document_register, start=1):
            reg_vals = [
                row_reg.file_name,
                row_reg.file_type,
                row_reg.pages_or_entities,
                row_reg.extraction_status,
                row_reg.confidence,
            ]
            for c_idx, val in enumerate(reg_vals):
                cell = reg_tbl.rows[r_idx].cells[c_idx]
                cell.text = val
                if r_idx % 2 == 0:
                    _shade_cell(cell, "F8FAFC")
                for p in cell.paragraphs:
                    _style_paragraph(p, is_ar=is_ar, font_size=8)

    # 4. Findings Table (ID, Discipline, Severity, Location/Drawing Ref, Evidence & Source Link, Recommendation, Status)
    p_f_h = doc.add_heading(lbl["findings_heading"], level=2)
    _style_paragraph(p_f_h, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    if not data.findings:
        p_empty = doc.add_paragraph(lbl["empty_findings"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        headers = [
            lbl["col_id"],
            lbl["col_disc"],
            lbl["col_sev"],
            lbl["col_loc"],
            lbl["col_ev"],
            lbl["col_rec"],
            lbl["col_stat"],
        ]
        f_tbl = doc.add_table(rows=1 + len(data.findings), cols=len(headers))
        _configure_rtl_table(f_tbl, is_ar=is_ar)
        for idx, htxt in enumerate(headers):
            cell = f_tbl.rows[0].cells[idx]
            cell.text = htxt
            _shade_cell(cell, "1E3A5F")
            for p in cell.paragraphs:
                _style_paragraph(p, is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
        for r_idx, f in enumerate(data.findings, start=1):
            src_str = _format_source_links_text(f.source_links)
            vals = [
                f.finding_id,
                f.discipline,
                f.severity,
                f.location_or_drawing_ref,
                f"{f.evidence}\n[{lbl['source_link_prefix']}: {src_str}]",
                f.recommendation,
                f.status,
            ]
            for c_idx, val in enumerate(vals):
                cell = f_tbl.rows[r_idx].cells[c_idx]
                cell.text = val
                if r_idx % 2 == 0:
                    _shade_cell(cell, "F8FAFC")
                for p in cell.paragraphs:
                    _style_paragraph(p, is_ar=is_ar, font_size=8)

    # 5. Strictly Separated Categories (Verified Facts N of M / Calculated / Unverified OCR Text / Assumptions / Recommendations)
    facts_banner = _facts_scope_banner(data)
    ch_facts = doc.add_heading(lbl["facts_heading"], level=2)
    _style_paragraph(ch_facts, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    if facts_banner:
        p_ban = doc.add_paragraph(facts_banner)
        _style_paragraph(p_ban, is_ar=is_ar, bold=True, font_size=8.5, color=RGBColor(0x03, 0x69, 0xA1))
    if not data.verified_facts:
        p_empty = doc.add_paragraph(lbl["empty_section"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        for item in data.verified_facts:
            line = f"• {item.text}"
            if item.source_links:
                line += f" — [{lbl['source_link_prefix']}: {_format_source_links_text(item.source_links)}]"
            p_item = doc.add_paragraph(line)
            _style_paragraph(p_item, is_ar=is_ar, font_size=9)

    ch_calc = doc.add_heading(lbl["calc_heading"], level=2)
    _style_paragraph(ch_calc, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    if not data.calculated_items:
        p_empty = doc.add_paragraph(lbl["empty_section"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        for item in data.calculated_items:
            line = f"• {item.text}"
            if item.formula_or_method:
                line += f" — [{lbl['method_prefix']}: {item.formula_or_method}]"
            if item.source_links:
                line += f" — [{lbl['source_link_prefix']}: {_format_source_links_text(item.source_links)}]"
            p_item = doc.add_paragraph(line)
            _style_paragraph(p_item, is_ar=is_ar, font_size=9)

    ch_ocr = doc.add_heading(lbl["ocr_heading"], level=2)
    _style_paragraph(ch_ocr, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x9A, 0x34, 0x12))
    if not data.ocr_text_items:
        p_empty = doc.add_paragraph(lbl["empty_section"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        for ocr_item in data.ocr_text_items:
            src_str = _format_source_links_text(ocr_item.source_links)
            p_ocr = doc.add_paragraph(
                f"• [{ocr_item.source_file} — {ocr_item.page_or_sheet}] {ocr_item.status_label}: "
                f"{ocr_item.text} — [{lbl['source_link_prefix']}: {src_str}]"
            )
            _style_paragraph(p_ocr, is_ar=is_ar, font_size=9)

    for heading_text, items in (
        (lbl["assump_heading"], data.assumptions),
        (lbl["recs_heading"], data.recommendations),
    ):
        ch = doc.add_heading(heading_text, level=2)
        _style_paragraph(ch, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
        if not items:
            p_empty = doc.add_paragraph(lbl["empty_section"])
            _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
            continue
        for item in items:
            line = f"• {item.text}"
            if item.formula_or_method:
                line += f" — [{lbl['method_prefix']}: {item.formula_or_method}]"
            if item.source_links:
                line += f" — [{lbl['source_link_prefix']}: {_format_source_links_text(item.source_links)}]"
            p_item = doc.add_paragraph(line)
            _style_paragraph(p_item, is_ar=is_ar, font_size=9)

    if data.appendix_verified_facts and len(data.appendix_verified_facts) > len(data.verified_facts):
        p_app_h = doc.add_heading(lbl["appendix_heading"], level=2)
        _style_paragraph(p_app_h, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
        for idx_a, item in enumerate(data.appendix_verified_facts, start=1):
            src_str = _format_source_links_text(item.source_links) if item.source_links else ""
            suffix = f" — [{lbl['source_link_prefix']}: {src_str}]" if src_str else ""
            p_app = doc.add_paragraph(f"{idx_a}. {item.text}{suffix}")
            _style_paragraph(p_app, is_ar=is_ar, font_size=8.5)

    # 6. Source Register & Gaps (list ONLY cited sources in DOCX/PDF; full M-entry registry remains in JSON)
    cited_sources = _collect_cited_sources(data)
    src_banner = _sources_scope_banner(
        data,
        cited_count=len(cited_sources),
        total_count=len(data.source_registry),
    )
    p_src_h = doc.add_heading(lbl["sources_heading"], level=2)
    _style_paragraph(p_src_h, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    if src_banner:
        p_src_note = doc.add_paragraph(src_banner)
        _style_paragraph(p_src_note, is_ar=is_ar, bold=True, font_size=8.5, color=RGBColor(0x33, 0x41, 0x55))
    if not cited_sources:
        p_empty = doc.add_paragraph(lbl["empty_section"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        for ref in cited_sources:
            url_part = f" | URL: {ref.url}" if ref.url else ""
            p_ref = doc.add_paragraph(
                f"[{ref.ref_id}] {ref.source_name} ({ref.page_or_sheet} / {ref.location}){url_part}"
            )
            _style_paragraph(p_ref, is_ar=is_ar, font_size=8)

    p_gap_h = doc.add_heading(lbl["gaps_heading"], level=2)
    _style_paragraph(p_gap_h, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    if not data.gaps_or_unextracted:
        p_empty = doc.add_paragraph(lbl["empty_section"])
        _style_paragraph(p_empty, is_ar=is_ar, font_size=9)
    else:
        for gap in data.gaps_or_unextracted:
            p_gap = doc.add_paragraph(f"• {gap}")
            _style_paragraph(p_gap, is_ar=is_ar, font_size=9)

    doc.save(str(out_path))


def _esc(val: object) -> str:
    return html.escape(str(val if val is not None else ""), quote=True)


def _esc_ltr(val: object) -> str:
    escaped = html.escape(str(val if val is not None else ""), quote=True)
    # Use Unicode LRI/PDI isolates + HTML <bdi> because PyMuPDF Story ignores HTML5 <bdi> alone.
    return f"<span dir='ltr'>\u2066{escaped}\u2069</span>"


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def _esc_rtl_cell(val: object, *, is_ar: bool) -> str:
    raw = str(val if val is not None else "")
    if is_ar and raw and not _has_arabic(raw) and any(ch.isascii() and ch.isalnum() for ch in raw):
        return _esc_ltr(raw)
    return _esc(raw)


def _format_source_links_html(links: Iterable[SourceLocationRef], *, is_ar: bool = False) -> str:
    parts: list[str] = []
    for ref in links:
        ref_tag = _esc_ltr(f"[{ref.ref_id}]")
        rest = " | ".join(
            _esc_rtl_cell(b, is_ar=is_ar) for b in (ref.source_name, ref.page_or_sheet, ref.location) if b
        )
        url_part = f" | {_esc_ltr(ref.url)}" if ref.url else ""
        parts.append(f"{ref_tag} {rest}{url_part}".strip())
    return " ; ".join(parts) if parts else "Unlinked"


def generate_review_report_pdf(out_path: Path, data: ReviewReportRenderData) -> None:
    """Render crisp multi-page Arabic RTL / English LTR PDF with embedded Arabic font via PyMuPDF Story."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing deliverable PDF: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _LABELS[data.language]

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    font_face_css = ""
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'DocFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'DocFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'DocFont', Tahoma, sans-serif"
    else:
        font_stack = "sans-serif"

    rev_rows_html = "".join(
        f"<tr><td class='revlbl'><strong>{_esc(k)}</strong></td><td class='revval'>{_esc_rtl_cell(v, is_ar=is_ar)}</td></tr>"
        for k, v in (
            (lbl["ver_label"], f"v{data.revision_block.version} ({data.revision_block.revision})"),
            (lbl["classification_prefix"], data.revision_block.classification),
            (lbl["date_label"], data.revision_block.issued_at_iso),
            (lbl["prepared_label"], f"{data.revision_block.prepared_by} — {data.revision_block.review_notice}"),
            (
                lbl["sources_label"],
                f"Files={data.revision_block.source_files_count}, Reviewed Research={data.revision_block.reviewed_research_count}",
            ),
            (lbl["change_label"], data.revision_block.change_note),
        )
    )

    if data.document_register:
        reg_rows_html = "".join(
            f"<tr>"
            f"<td>{_esc_rtl_cell(r.file_name, is_ar=is_ar)}</td>"
            f"<td>{_esc_rtl_cell(r.file_type, is_ar=is_ar)}</td>"
            f"<td>{_esc_rtl_cell(r.pages_or_entities, is_ar=is_ar)}</td>"
            f"<td>{_esc_rtl_cell(r.extraction_status, is_ar=is_ar)}</td>"
            f"<td>{_esc_rtl_cell(r.confidence, is_ar=is_ar)}</td>"
            f"</tr>"
            for r in data.document_register
        )
        register_html = (
            f"<table>"
            f"<colgroup><col style='width:24%'/><col style='width:10%'/><col style='width:20%'/><col style='width:25%'/><col style='width:21%'/></colgroup>"
            f"<tbody><tr>"
            f"<th>{_esc(lbl['reg_file'])}</th><th>{_esc(lbl['reg_type'])}</th>"
            f"<th>{_esc(lbl['reg_scope'])}</th><th>{_esc(lbl['reg_status'])}</th>"
            f"<th>{_esc(lbl['reg_conf'])}</th>"
            f"</tr>{reg_rows_html}</tbody></table>"
        )
    else:
        register_html = f"<p class='muted'>{_esc(lbl['empty_section'])}</p>"

    if data.findings:
        findings_cards = []
        for f in data.findings:
            src_html = _format_source_links_html(f.source_links, is_ar=is_ar)
            findings_cards.append(
                f"<div class='fcard'>"
                f"<div class='fhead'>"
                f"<strong>{_esc_ltr(f.finding_id)}</strong>"
                f" &nbsp;|&nbsp; {_esc(lbl['col_disc'])}: {_esc_rtl_cell(f.discipline, is_ar=is_ar)}"
                f" &nbsp;|&nbsp; {_esc(lbl['col_sev'])}: {_esc_rtl_cell(f.severity, is_ar=is_ar)}"
                f" &nbsp;|&nbsp; {_esc(lbl['col_stat'])}: {_esc_rtl_cell(f.status, is_ar=is_ar)}"
                f"</div>"
                f"<div class='fbody'>"
                f"<div class='frow'><strong>{_esc(lbl['col_loc'])}:</strong> {_esc_rtl_cell(f.location_or_drawing_ref, is_ar=is_ar)}</div>"
                f"<div class='frow'><strong>{_esc(lbl['col_ev'])}:</strong> {_esc_rtl_cell(f.evidence, is_ar=is_ar)}</div>"
                f"<div class='frow src'><strong>{_esc(lbl['source_link_prefix'])}:</strong> {src_html}</div>"
                f"<div class='frow'><strong>{_esc(lbl['col_rec'])}:</strong> {_esc_rtl_cell(f.recommendation, is_ar=is_ar)}</div>"
                f"</div>"
                f"</div>"
            )
        findings_html = "".join(findings_cards)
    else:
        findings_html = f"<p class='muted'>{_esc(lbl['empty_findings'])}</p>"

    def render_category(title_txt: str, items: list[CategorizedStatement], *, banner_note: str | None = None) -> str:
        banner_p = f"<p class='scope-note'>{_esc(banner_note)}</p>" if banner_note else ""
        if not items:
            body_html = f"<p class='muted'>{_esc(lbl['empty_section'])}</p>"
        else:
            lis = []
            for item in items:
                extra = ""
                if item.formula_or_method:
                    extra += f" <span class='src'>[{_esc(lbl['method_prefix'])}: {_esc_rtl_cell(item.formula_or_method, is_ar=is_ar)}]</span>"
                if item.source_links:
                    extra += f" <span class='src'><strong>{_esc(lbl['source_link_prefix'])}:</strong> {_format_source_links_html(item.source_links, is_ar=is_ar)}</span>"
                lis.append(f"<li>{_esc(item.text)}{extra}</li>")
            body_html = f"<ul>{''.join(lis)}</ul>"
        return f"<h3>{_esc(title_txt)}</h3>{banner_p}{body_html}"

    if data.ocr_text_items:
        ocr_lis = []
        for o in data.ocr_text_items:
            src_o = _format_source_links_html(o.source_links, is_ar=is_ar) if o.source_links else ""
            src_part = f" <span class='src'><strong>{_esc(lbl['source_link_prefix'])}:</strong> {src_o}</span>" if src_o else ""
            ocr_lis.append(
                f"<li><strong>[{_esc_rtl_cell(o.source_file, is_ar=is_ar)} — {_esc_rtl_cell(o.page_or_sheet, is_ar=is_ar)}]</strong> "
                f"<span class='ocrtag'>{_esc(o.status_label)}</span>: {_esc_rtl_cell(o.text, is_ar=is_ar)}{src_part}</li>"
            )
        ocr_html = f"<h3>{_esc(lbl['ocr_heading'])}</h3><ul>{''.join(ocr_lis)}</ul>"
    else:
        ocr_html = f"<h3>{_esc(lbl['ocr_heading'])}</h3><p class='muted'>{_esc(lbl['empty_section'])}</p>"

    facts_banner = _facts_scope_banner(data)
    categories_html = "".join(
        [
            render_category(lbl["facts_heading"], data.verified_facts, banner_note=facts_banner),
            render_category(lbl["calc_heading"], data.calculated_items),
            ocr_html,
            render_category(lbl["assump_heading"], data.assumptions),
            render_category(lbl["recs_heading"], data.recommendations),
        ]
    )

    if data.appendix_verified_facts and len(data.appendix_verified_facts) > len(data.verified_facts):
        app_lis = []
        for item in data.appendix_verified_facts:
            src_a = (
                f" <span class='src'><strong>{_esc(lbl['source_link_prefix'])}:</strong> {_format_source_links_html(item.source_links, is_ar=is_ar)}</span>"
                if item.source_links
                else ""
            )
            app_lis.append(f"<li>{_esc(item.text)}{src_a}</li>")
        appendix_html = f"<h2>{_esc(lbl['appendix_heading'])}</h2><ol>{''.join(app_lis)}</ol>"
    else:
        appendix_html = ""

    cited_sources = _collect_cited_sources(data)
    src_banner = _sources_scope_banner(
        data,
        cited_count=len(cited_sources),
        total_count=len(data.source_registry),
    )
    src_banner_html = f"<p class='scope-note'>{_esc(src_banner)}</p>" if src_banner else ""
    if cited_sources:
        src_items = "".join(
            f"<li><strong>{_esc_ltr('[' + ref.ref_id + ']')}</strong> {_esc(ref.source_name)} — {_esc(ref.page_or_sheet)} / {_esc(ref.location)}"
            f"{' | ' + _esc_ltr(ref.url) if ref.url else ''}</li>"
            for ref in cited_sources
        )
        sources_html = f"{src_banner_html}<ul>{src_items}</ul>"
    else:
        sources_html = f"{src_banner_html}<p class='muted'>{_esc(lbl['empty_section'])}</p>"

    if data.gaps_or_unextracted:
        gaps_html = f"<ul>{''.join(f'<li>{_esc(g)}</li>' for g in data.gaps_or_unextracted)}</ul>"
    else:
        gaps_html = f"<p class='muted'>{_esc(lbl['empty_section'])}</p>"

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{_esc(data.language)}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 9.5pt; color: #0f172a; line-height: 1.45; hyphens: none; }}
.banner {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 6pt; margin-bottom: 10pt; }}
h1 {{ font-size: 14pt; color: #1e3a5f; margin: 0 0 4pt 0; }}
h2 {{ font-size: 11.5pt; color: #1e3a5f; margin: 12pt 0 5pt 0; border-bottom: 1px solid #cbd5e1; padding-bottom: 2pt; page-break-after: avoid; break-after: avoid; }}
h3 {{ font-size: 10.2pt; color: #1e3a5f; margin: 9pt 0 4pt 0; page-break-after: avoid; break-after: avoid; }}
.badge {{ display: inline-block; background-color: #dbeafe; color: #1e3a5f; font-weight: bold; padding: 2pt 6pt; border: 1px solid #93c5fd; font-size: 9pt; }}
.disclaimer {{ color: #9a3412; font-weight: bold; font-size: 8.5pt; margin: 4pt 0 0 0; }}
.meta {{ font-size: 8.8pt; color: #334155; margin: 3pt 0; }}
table {{ border-collapse: separate; border-spacing: 0; width: 100%; table-layout: fixed; margin: 6pt 0 10pt 0; direction: {dir_attr}; font-size: 8.2pt; }}
tr {{ page-break-inside: avoid; break-inside: avoid; }}
th, td {{ border: 0.6pt solid #94a3b8; padding: 4pt 5pt; text-align: {align}; vertical-align: top; word-wrap: break-word; }}
th {{ background-color: #1e3a5f; color: #ffffff; font-weight: bold; }}
.revlbl {{ background-color: #e2e8f0; color: #0f172a; width: 28%; }}
.revval {{ width: 72%; }}
.fcard {{ border: 0.8pt solid #94a3b8; margin: 0 0 7pt 0; page-break-inside: avoid; break-inside: avoid; background-color: #ffffff; }}
.fhead {{ background-color: #1e3a5f; color: #ffffff; padding: 4pt 6pt; font-size: 8.5pt; font-weight: bold; }}
.fbody {{ padding: 4pt 6pt; font-size: 8.5pt; }}
.frow {{ margin-bottom: 2.5pt; }}
.src {{ color: #0369a1; font-size: 7.8pt; }}
.muted {{ color: #64748b; font-size: 8.5pt; }}
.inv-notice {{ background-color: #fef3c7; border: 0.8pt solid #f59e0b; color: #78350f; padding: 5pt 7pt; font-weight: bold; font-size: 8.8pt; margin: 6pt 0; }}
.scope-note {{ color: #0369a1; font-weight: bold; font-size: 8.4pt; margin: 2pt 0 4pt 0; }}
.ocrtag {{ color: #9a3412; font-weight: bold; font-size: 8pt; }}
ul, ol {{ margin: 3pt 0 6pt 0; padding-left: 14pt; padding-right: 14pt; }}
li {{ margin-bottom: 3pt; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(data.title)} &nbsp; <span class="badge">{_esc(lbl['classification_prefix'])}: {_esc_ltr(data.classification)}</span></h1>
    <div class="meta">{_esc(lbl['project'])}: {_esc_ltr('[' + data.project_code + ']')} {_esc(data.project_name)} | {_esc(lbl['discipline'])}: {_esc(data.discipline)}
      {(' | ' + _esc(lbl['client']) + ': ' + _esc(data.client_name)) if data.client_name else ''}
      {(' | ' + _esc(lbl['location']) + ': ' + _esc(data.location)) if data.location else ''}
    </div>
    <div class="disclaimer">{_esc(lbl['disclaimer'])}</div>
    {(f"<div class='inv-notice'>{_esc(lbl['inventory_notice'])}</div>") if data.is_inventory_only else ''}
  </div>

  <h2>{_esc(lbl['revision_heading'])}</h2>
  <table class="revtable"><tbody>{rev_rows_html}</tbody></table>

  <h2>{_esc(lbl['summary_heading'])}</h2>
  <p>{_esc(data.summary)}</p>

  <h2>{_esc(lbl['register_heading'])}</h2>
  {register_html}

  <h2>{_esc(lbl['findings_heading'])}</h2>
  {findings_html}

  {categories_html}

  {appendix_html}

  <h2>{_esc(lbl['sources_heading'])}</h2>
  {sources_html}

  <h2>{_esc(lbl['gaps_heading'])}</h2>
  {gaps_html}
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
        while more and page_guard < 100:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            page_guard += 1
    finally:
        writer.close()
