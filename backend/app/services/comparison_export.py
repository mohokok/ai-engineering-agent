"""Step 15 bilingual Arabic RTL / English LTR DOCX, PDF & live-formula XLSX technical comparison exporter."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
import pymupdf

from app.schemas.comparisons import (
    ADVISORY_NOTICE_AR,
    ADVISORY_NOTICE_EN,
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    ComparisonCriterionIn,
    ComparisonMatrixOut,
    NOT_PROVIDED_LABEL,
)
from app.schemas.reports import ReportLanguage
from app.services.branding_exports import (
    apply_docx_branding,
    apply_xlsx_branding,
    write_branded_story_pdf,
)
from app.services.calc_export import _safe_xlsx_text
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
class ComparisonRenderData:
    """Normalized immutable Step 15 technical comparison payload for DOCX, PDF, and XLSX export."""

    project_code: str
    project_name: str
    title: str
    comparison_scope: str
    discipline: str
    language: ReportLanguage
    classification: str
    revision: str
    version: int
    export_version: int
    issued_at_iso: str
    use_ai: bool
    ai_draft_status: str
    owner_decision_status: str
    owner_selected_option_id: str | None
    owner_decision_note: str | None
    owner_decided_by: str | None
    owner_decided_at_iso: str | None
    summary: str | None
    criteria: list[ComparisonCriterionIn] = field(default_factory=list)
    matrix: ComparisonMatrixOut = field(default_factory=lambda: ComparisonMatrixOut(
        total_weight=0.0,
        weights_sum_valid=False,
        advisory_notice=ADVISORY_NOTICE_EN,
    ))


_CMP_LABELS: dict[ReportLanguage, dict[str, str]] = {
    "ar": {
        "classification_prefix": "التصنيف",
        "project": "المشروع",
        "scope": "نطاق المقارنة",
        "discipline": "التخصص",
        "rev_ver": "الإصدار / المراجعة",
        "date": "تاريخ التصدير (UTC)",
        "advisory_heading": "تنويه هام — مصفوفة مقارنة استشارية فقط",
        "ai_det": "المسار الحتمي: تقييم عددي بـ Decimal ومصادر المشروع الفعلية (0 توكن ذكاء اصطناعي).",
        "ai_unverified": AI_UNVERIFIED_DRAFT_LABEL_AR,
        "ai_approved": "صياغة الملخص بالذكاء الاصطناعي — مُعتمَدة من المالك",
        "decision_pending": "حالة القرار: بانتظار قرار المالك / المهندس المرخص (لم يتم اعتماد خيار نهائي بعد).",
        "decision_done": "قرار المالك المعتمد",
        "summary_heading": "الملخص التنفيذي / المفاضلة الفنية",
        "ranking_heading": "1. ملخص ترتيب الخيارات الاستشاري وتجاوز المتطلبات الإلزامية",
        "matrix_heading": "2. مصفوفة التقييم الموزونة والقيم الخام والموحدة (مع حفظ المصادر)",
        "flags_heading": "3. تنبيهات الوحدات المتعارضة والقيم الإلزامية المفقودة",
        "risks_heading": "4. المخاطر المسجلة لكل خيار",
        "col_rank": "الترتيب الاستشاري",
        "col_option": "الخيار / العرض",
        "col_vendor": "المورد / المصدر",
        "col_score": "الدرجة الموزونة (/100)",
        "col_mandatory": "الاجتياز الإلزامي",
        "col_missing": "قيم مفقودة",
        "col_mismatch": "تعارض وحدات",
        "col_criterion": "المعيار والفئة",
        "col_weight": "الوزن (%)",
        "col_unit": "وحدة القياس",
        "col_value": "القيمة",
        "col_norm": "توحيد (0-100)",
        "col_weighted": "الموزون",
        "col_source": "المرجع والمصدر",
        "pass": "ناجح (PASS)",
        "fail": "راسب (FAIL)",
        "none_flags": "لا توجد تعارضات وحدات أو قيم إلزامية مفقودة.",
    },
    "en": {
        "classification_prefix": "Classification",
        "project": "Project",
        "scope": "Scope",
        "discipline": "Discipline",
        "rev_ver": "Version / Revision",
        "date": "Export Date (UTC)",
        "advisory_heading": "Professional Notice — Advisory Comparison Only",
        "ai_det": "Deterministic Path: Decimal scoring grounded in project BOQ/Specs/Calculations/Sources (0 AI tokens).",
        "ai_unverified": AI_UNVERIFIED_DRAFT_LABEL_EN,
        "ai_approved": "AI Narrative Summary — Owner Approved",
        "decision_pending": "Decision Status: Pending Owner / Licensed Engineer Decision (no option finalized).",
        "decision_done": "Recorded Owner Decision",
        "summary_heading": "Executive Trade-off Narrative",
        "ranking_heading": "1. Advisory Ranking & Mandatory Gating Summary",
        "matrix_heading": "2. Weighted Criteria Matrix, Converted Values & Source Provenance",
        "flags_heading": "3. Unit Mismatch & Missing Mandatory Value Flags",
        "risks_heading": "4. Option-Level Risks Register",
        "col_rank": "Advisory Rank",
        "col_option": "Option / Offer",
        "col_vendor": "Vendor / Source",
        "col_score": "Weighted Score (/100)",
        "col_mandatory": "Mandatory Gate",
        "col_missing": "Missing Values",
        "col_mismatch": "Unit Mismatches",
        "col_criterion": "Criterion (Category)",
        "col_weight": "Weight (%)",
        "col_unit": "Target Unit",
        "col_value": "Value",
        "col_norm": "Norm (0-100)",
        "col_weighted": "Weighted",
        "col_source": "Source Reference",
        "pass": "PASS",
        "fail": "FAIL",
        "none_flags": "No unit mismatches or missing mandatory values detected.",
    },
}


def _ai_banner_text(data: ComparisonRenderData, lbl: dict[str, str]) -> str:
    if data.ai_draft_status == "unverified_ai_draft":
        return f"[{lbl['ai_unverified']}] — Narrative requires Owner review/approval."
    if data.ai_draft_status == "owner_approved":
        who = data.owner_decided_by or "Owner"
        return f"{lbl['ai_approved']} ({who})"
    return lbl["ai_det"]


def _decision_banner_text(data: ComparisonRenderData, lbl: dict[str, str]) -> str:
    if data.owner_decision_status == "owner_selected" and data.owner_selected_option_id:
        opt_name = next(
            (o.name for o in data.matrix.options if o.option_id == data.owner_selected_option_id),
            data.owner_selected_option_id,
        )
        return (
            f"{lbl['decision_done']}: [{data.owner_selected_option_id}] {opt_name} "
            f"| By: {data.owner_decided_by or 'Owner'} ({data.owner_decided_at_iso or data.issued_at_iso}) "
            f"| Note: {data.owner_decision_note or '—'}"
        )
    return lbl["decision_pending"]


def generate_comparison_docx(out_path: Path, data: ComparisonRenderData) -> None:
    """Render immutable bilingual Arabic RTL / English LTR Step 15 comparison DOCX."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing comparison DOCX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _CMP_LABELS[data.language]
    doc = Document()

    for section in doc.sections:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Inches(11.69)
        section.page_height = Inches(8.27)
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)
        if is_ar:
            sect_pr = section._sectPr
            _set_element_tag(sect_pr, "w:bidi")

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Tahoma"
    normal_style.font.size = Pt(9.5)

    apply_docx_branding(
        doc,
        language=data.language,
        classification=data.classification,
        document_title=data.title,
    )

    p_title = doc.add_heading(f"{data.title} [{lbl['classification_prefix']}: {data.classification}]", level=1)
    _style_paragraph(p_title, is_ar=is_ar, bold=True, font_size=14, color=RGBColor(0x1E, 0x3A, 0x5F))

    meta_lines = [
        f"{lbl['project']}: [{data.project_code}] {data.project_name} | {lbl['scope']}: {data.comparison_scope} | {lbl['discipline']}: {data.discipline}",
        f"{lbl['rev_ver']}: v{data.version} (Export v{data.export_version}, {data.revision}) | {lbl['date']}: {data.issued_at_iso}",
        f"{lbl['advisory_heading']}: {ADVISORY_NOTICE_AR if is_ar else ADVISORY_NOTICE_EN}",
        _ai_banner_text(data, lbl),
        _decision_banner_text(data, lbl),
    ]
    for idx, line_txt in enumerate(meta_lines):
        p = doc.add_paragraph(line_txt)
        color = RGBColor(0x9A, 0x34, 0x12) if idx == 2 else (RGBColor(0xB9, 0x1C, 0x1C) if (idx == 3 and data.ai_draft_status == "unverified_ai_draft") else None)
        _style_paragraph(p, is_ar=is_ar, bold=(idx in {2, 3, 4}), font_size=9, color=color)

    if data.summary:
        p_sum_h = doc.add_heading(lbl["summary_heading"], level=2)
        _style_paragraph(p_sum_h, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
        p_sum = doc.add_paragraph(data.summary)
        _style_paragraph(p_sum, is_ar=is_ar, font_size=9.5)

    # 1. Option ranking summary table
    p_h1 = doc.add_heading(lbl["ranking_heading"], level=2)
    _style_paragraph(p_h1, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    rank_headers = [
        lbl["col_rank"],
        lbl["col_option"],
        lbl["col_vendor"],
        lbl["col_score"],
        lbl["col_mandatory"],
        lbl["col_missing"],
        lbl["col_mismatch"],
    ]
    rtbl = doc.add_table(rows=1, cols=len(rank_headers))
    _configure_rtl_table(rtbl, is_ar=is_ar)
    for idx, htxt in enumerate(rank_headers):
        rtbl.rows[0].cells[idx].text = htxt
        _shade_cell(rtbl.rows[0].cells[idx], "1E3A5F")
        _style_paragraph(rtbl.rows[0].cells[idx].paragraphs[0], is_ar=is_ar, bold=True, font_size=8.5, color=RGBColor(0xFF, 0xFF, 0xFF))
    for opt in data.matrix.options:
        rc = rtbl.add_row().cells
        mand_txt = lbl["pass"] if opt.mandatory_passed else f"{lbl['fail']} ({', '.join(opt.failed_mandatory_criteria)})"
        vals = [
            f"#{opt.advisory_rank}",
            f"[{opt.option_id}] {opt.name}",
            opt.vendor_or_source or NOT_PROVIDED_LABEL,
            f"{opt.total_weighted_score:.4f}",
            mand_txt,
            str(opt.missing_values_count),
            str(opt.unit_mismatch_count),
        ]
        for idx, v in enumerate(vals):
            rc[idx].text = v
            if idx == 4:
                _shade_cell(rc[idx], "DCFCE7" if opt.mandatory_passed else "FEE2E2")
            _style_paragraph(rc[idx].paragraphs[0], is_ar=is_ar, bold=(idx in {0, 3, 4}), font_size=8.5)

    # 2. Detailed criteria comparison matrix table
    p_h2 = doc.add_heading(lbl["matrix_heading"], level=2)
    _style_paragraph(p_h2, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    opt_list = data.matrix.options
    mat_headers = [lbl["col_criterion"], lbl["col_weight"], lbl["col_unit"]] + [
        f"[{o.option_id}] {o.name}" for o in opt_list
    ]
    mtbl = doc.add_table(rows=1, cols=len(mat_headers))
    _configure_rtl_table(mtbl, is_ar=is_ar)
    for idx, htxt in enumerate(mat_headers):
        mtbl.rows[0].cells[idx].text = htxt
        _shade_cell(mtbl.rows[0].cells[idx], "1E3A5F")
        _style_paragraph(mtbl.rows[0].cells[idx].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))

    for crit in data.criteria:
        rc = mtbl.add_row().cells
        mand_tag = " [MANDATORY]" if crit.is_mandatory else ""
        rc[0].text = f"{crit.label} ({crit.category}){mand_tag}\n{lbl['col_source']}: [{crit.source_kind}] {crit.source_ref}"
        rc[1].text = f"{crit.weight}%"
        rc[2].text = crit.target_unit
        _style_paragraph(rc[0].paragraphs[0], is_ar=is_ar, bold=crit.is_mandatory, font_size=8)
        _style_paragraph(rc[1].paragraphs[0], is_ar=is_ar, font_size=8)
        _style_paragraph(rc[2].paragraphs[0], is_ar=is_ar, font_size=8)

        for o_idx, opt in enumerate(opt_list):
            cell = next((c for c in opt.cells if c.criterion_id == crit.criterion_id), None)
            if not cell:
                rc[3 + o_idx].text = NOT_PROVIDED_LABEL
                _shade_cell(rc[3 + o_idx], "FEF3C7")
                _style_paragraph(rc[3 + o_idx].paragraphs[0], is_ar=is_ar, font_size=8)
                continue
            conv_bit = f" -> {cell.converted_value} {cell.target_unit}" if cell.unit_status == "converted_explicitly" and cell.converted_value else ""
            mand_bit = ""
            if cell.is_mandatory:
                mand_bit = " | PASS" if cell.mandatory_passed else " | FAIL"
            txt = (
                f"{cell.display_value} {cell.raw_unit}{conv_bit}\n"
                f"{lbl['col_norm']}: {cell.normalized_score:.2f} | {lbl['col_weighted']}: {cell.weighted_score:.4f}{mand_bit}\n"
                f"[{cell.source_kind}] {cell.source_ref}"
            )
            if cell.unit_status == "flagged_mismatch":
                _shade_cell(rc[3 + o_idx], "FEE2E2")
            elif cell.is_missing:
                _shade_cell(rc[3 + o_idx], "FEF3C7")
            rc[3 + o_idx].text = txt
            _style_paragraph(rc[3 + o_idx].paragraphs[0], is_ar=is_ar, font_size=7.5)

    # Totals footer row
    tot_rc = mtbl.add_row().cells
    tot_rc[0].text = "TOTAL WEIGHTED SCORE (Advisory)"
    tot_rc[1].text = f"{data.matrix.total_weight:.4f}%"
    tot_rc[2].text = "—"
    _shade_cell(tot_rc[0], "E2E8F0")
    _shade_cell(tot_rc[1], "E2E8F0")
    _shade_cell(tot_rc[2], "E2E8F0")
    _style_paragraph(tot_rc[0].paragraphs[0], is_ar=is_ar, bold=True, font_size=8.5)
    _style_paragraph(tot_rc[1].paragraphs[0], is_ar=is_ar, bold=True, font_size=8.5)
    _style_paragraph(tot_rc[2].paragraphs[0], is_ar=is_ar, bold=True, font_size=8.5)
    for o_idx, opt in enumerate(opt_list):
        tot_rc[3 + o_idx].text = f"#{opt.advisory_rank}: {opt.total_weighted_score:.4f} / 100"
        _shade_cell(tot_rc[3 + o_idx], "E2E8F0")
        _style_paragraph(tot_rc[3 + o_idx].paragraphs[0], is_ar=is_ar, bold=True, font_size=8.5)

    # 3. Flags & Risks
    p_h3 = doc.add_heading(lbl["flags_heading"], level=2)
    _style_paragraph(p_h3, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    all_flags = list(data.matrix.unit_mismatch_flags) + list(data.matrix.missing_mandatory_flags)
    if not all_flags:
        p_nf = doc.add_paragraph(lbl["none_flags"])
        _style_paragraph(p_nf, is_ar=is_ar, font_size=9)
    else:
        for fl in all_flags:
            pf = doc.add_paragraph(f"• {fl}")
            _style_paragraph(pf, is_ar=is_ar, bold=True, font_size=8.5, color=RGBColor(0xB9, 0x1C, 0x1C))

    p_h4 = doc.add_heading(lbl["risks_heading"], level=2)
    _style_paragraph(p_h4, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    for opt in opt_list:
        risk_str = "; ".join(opt.risks) if opt.risks else NOT_PROVIDED_LABEL
        pr = doc.add_paragraph(f"• [{opt.option_id}] {opt.name}: {risk_str}")
        _style_paragraph(pr, is_ar=is_ar, font_size=8.5)

    doc.save(str(out_path))


def generate_comparison_pdf(out_path: Path, data: ComparisonRenderData) -> None:
    """Render immutable bilingual Arabic RTL / English LTR vector PDF landscape matrix via PyMuPDF Story."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing comparison PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _CMP_LABELS[data.language]

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'CmpFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'CmpFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'CmpFont', Tahoma, sans-serif"
    else:
        font_face_css = ""
        font_stack = "sans-serif"

    rank_rows = ""
    for opt in data.matrix.options:
        badge_cls = "pass" if opt.mandatory_passed else "fail"
        mand_txt = lbl["pass"] if opt.mandatory_passed else f"{lbl['fail']} ({', '.join(opt.failed_mandatory_criteria)})"
        rank_rows += (
            f"<tr>"
            f"<td>{_esc_ltr(f'#{opt.advisory_rank}')}</td>"
            f"<td>{_esc_rtl_cell(opt.name, is_ar=is_ar)} ({_esc_ltr(opt.option_id)})</td>"
            f"<td>{_esc_rtl_cell(opt.vendor_or_source or NOT_PROVIDED_LABEL, is_ar=is_ar)}</td>"
            f"<td><strong>{_esc_ltr(f'{opt.total_weighted_score:.4f}')}</strong></td>"
            f"<td><span class='{badge_cls}'>{_esc(mand_txt)}</span></td>"
            f"<td>{_esc_ltr(opt.missing_values_count)}</td>"
            f"<td>{_esc_ltr(opt.unit_mismatch_count)}</td>"
            f"</tr>"
        )

    opt_headers_html = "".join(
        f"<th>{_esc_ltr(o.option_id)} — {_esc(o.name)}</th>" for o in data.matrix.options
    )
    matrix_rows = ""
    for crit in data.criteria:
        mand_badge = " <span class='badge'>MANDATORY</span>" if crit.is_mandatory else ""
        cells_html = ""
        for opt in data.matrix.options:
            c = next((x for x in opt.cells if x.criterion_id == crit.criterion_id), None)
            if not c:
                cells_html += f"<td class='warn'>{_esc_ltr(NOT_PROVIDED_LABEL)}</td>"
                continue
            cls_attr = " class='bad'" if c.unit_status == "flagged_mismatch" else (" class='warn'" if c.is_missing else "")
            conv_bit = f" -> {_esc_ltr(c.converted_value)} {_esc_ltr(c.target_unit)}" if c.unit_status == "converted_explicitly" and c.converted_value else ""
            mand_bit = ""
            if c.is_mandatory:
                mand_bit = " | PASS" if c.mandatory_passed else " | FAIL"
            cells_html += (
                f"<td{cls_attr}>"
                f"<strong>{_esc_ltr(c.display_value)} {_esc_ltr(c.raw_unit)}</strong>{conv_bit}<br/>"
                f"<span class='sub'>{_esc(lbl['col_norm'])}: {_esc_ltr(f'{c.normalized_score:.2f}')} | "
                f"{_esc(lbl['col_weighted'])}: {_esc_ltr(f'{c.weighted_score:.4f}')}{_esc_ltr(mand_bit)}</span><br/>"
                f"<span class='sub'>[{_esc_ltr(c.source_kind)}] {_esc_rtl_cell(c.source_ref, is_ar=is_ar)}</span>"
                f"</td>"
            )
        matrix_rows += (
            f"<tr>"
            f"<td><strong>{_esc_rtl_cell(crit.label, is_ar=is_ar)}</strong> ({_esc_ltr(crit.category)}){mand_badge}<br/>"
            f"<span class='sub'>[{_esc_ltr(crit.source_kind)}] {_esc_rtl_cell(crit.source_ref, is_ar=is_ar)}</span></td>"
            f"<td>{_esc_ltr(crit.weight)}%</td>"
            f"<td>{_esc_ltr(crit.target_unit)}</td>"
            f"{cells_html}"
            f"</tr>"
        )

    tot_cells = "".join(
        f"<td><strong>{_esc_ltr(f'#{o.advisory_rank}: {o.total_weighted_score:.4f} / 100')}</strong></td>"
        for o in data.matrix.options
    )
    all_flags = list(data.matrix.unit_mismatch_flags) + list(data.matrix.missing_mandatory_flags)
    flags_html = (
        f"<p>{_esc(lbl['none_flags'])}</p>"
        if not all_flags
        else "<ul>" + "".join(f"<li class='badtxt'>{_esc(fl)}</li>" for fl in all_flags) + "</ul>"
    )
    risks_html = "<ul>" + "".join(
        f"<li><strong>{_esc_ltr(f'[{o.option_id}]')} {_esc(o.name)}</strong>: {_esc('; '.join(o.risks) if o.risks else NOT_PROVIDED_LABEL)}</li>"
        for o in data.matrix.options
    ) + "</ul>"
    summary_html = (
        f"<h2>{_esc(lbl['summary_heading'])}</h2><p>{_esc(data.summary)}</p>" if data.summary else ""
    )

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 8.5pt; color: #0f172a; margin: 0; }}
.banner {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 6pt; margin-bottom: 8pt; }}
h1 {{ color: #1e3a5f; font-size: 13pt; margin: 0 0 4pt 0; }}
h2 {{ color: #1e3a5f; font-size: 10.5pt; margin: 9pt 0 4pt 0; }}
.badge {{ background-color: #1e3a5f; color: #ffffff; padding: 1pt 4pt; font-size: 7.5pt; font-weight: bold; }}
.pass {{ background-color: #15803d; color: #ffffff; padding: 1pt 5pt; font-size: 7.5pt; font-weight: bold; }}
.fail {{ background-color: #b91c1c; color: #ffffff; padding: 1pt 5pt; font-size: 7.5pt; font-weight: bold; }}
.disclaimer {{ color: #9a3412; font-weight: bold; font-size: 8.5pt; margin-top: 3pt; }}
.decision {{ color: #1e3a5f; font-weight: bold; font-size: 8.5pt; margin-top: 2pt; }}
.sub {{ color: #475569; font-size: 7pt; }}
table {{ width: 100%; border-collapse: collapse; margin: 4pt 0 8pt 0; font-size: 7.8pt; }}
th, td {{ border: 0.6pt solid #94a3b8; padding: 3.5pt; text-align: {align}; vertical-align: top; }}
th {{ background-color: #1e3a5f; color: #ffffff; font-weight: bold; }}
tr.tot td {{ background-color: #e2e8f0; }}
td.warn {{ background-color: #fef3c7; }}
td.bad {{ background-color: #fee2e2; }}
.badtxt {{ color: #b91c1c; font-weight: bold; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(data.title)} &nbsp; <span class="badge">{_esc(lbl['classification_prefix'])}: {_esc_ltr(data.classification)}</span></h1>
    <div>{_esc(lbl['project'])}: {_esc_ltr('[' + data.project_code + ']')} {_esc(data.project_name)} | {_esc(lbl['scope'])}: {_esc_ltr(data.comparison_scope)} | {_esc(lbl['discipline'])}: {_esc_ltr(data.discipline)} | {_esc(lbl['rev_ver'])}: {_esc_ltr(f'v{data.version} (Export v{data.export_version}, {data.revision})')}</div>
    <div class="disclaimer">{_esc(lbl['advisory_heading'])}: {_esc(ADVISORY_NOTICE_AR if is_ar else ADVISORY_NOTICE_EN)}</div>
    <div>{_esc(_ai_banner_text(data, lbl))}</div>
    <div class="decision">{_esc(_decision_banner_text(data, lbl))}</div>
  </div>
  {summary_html}
  <h2>{_esc(lbl['ranking_heading'])}</h2>
  <table>
    <thead><tr><th>{_esc(lbl['col_rank'])}</th><th>{_esc(lbl['col_option'])}</th><th>{_esc(lbl['col_vendor'])}</th><th>{_esc(lbl['col_score'])}</th><th>{_esc(lbl['col_mandatory'])}</th><th>{_esc(lbl['col_missing'])}</th><th>{_esc(lbl['col_mismatch'])}</th></tr></thead>
    <tbody>{rank_rows}</tbody>
  </table>
  <h2>{_esc(lbl['matrix_heading'])}</h2>
  <table>
    <thead><tr><th>{_esc(lbl['col_criterion'])}</th><th>{_esc(lbl['col_weight'])}</th><th>{_esc(lbl['col_unit'])}</th>{opt_headers_html}</tr></thead>
    <tbody>{matrix_rows}
      <tr class="tot"><td><strong>TOTAL WEIGHTED SCORE</strong></td><td><strong>{_esc_ltr(f'{data.matrix.total_weight:.4f}%')}</strong></td><td>—</td>{tot_cells}</tr>
    </tbody>
  </table>
  <h2>{_esc(lbl['flags_heading'])}</h2>
  {flags_html}
  <h2>{_esc(lbl['risks_heading'])}</h2>
  {risks_html}
</body>
</html>"""

    write_branded_story_pdf(
        out_path,
        html_doc=html_doc,
        fonts_dir=_WINDOWS_FONTS_DIR,
        landscape=True,
        classification=data.classification,
        language=data.language,
        side_margin=26.0,
        top_margin=60.0,
        bottom_margin=40.0,
        max_pages=100,
    )


def generate_comparison_xlsx(out_path: Path, data: ComparisonRenderData) -> None:
    """Export immutable bilingual live-formula XLSX workbook (Matrix Scoring + Source Provenance & Flags)."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing comparison XLSX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _CMP_LABELS[data.language]
    wb = Workbook()
    ws = wb.active
    ws.title = "مصفوفة المقارنة" if is_ar else "Evaluation Matrix"
    ws.views.sheetView[0].rightToLeft = is_ar

    navy_fill = PatternFill("solid", fgColor="1E3A5F")
    sub_fill = PatternFill("solid", fgColor="E2E8F0")
    warn_fill = PatternFill("solid", fgColor="FEF3C7")
    bad_fill = PatternFill("solid", fgColor="FEE2E2")
    ok_fill = PatternFill("solid", fgColor="DCFCE7")
    hdr_font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    bold_font = Font(name="Tahoma", size=10, bold=True)
    reg_font = Font(name="Tahoma", size=10)
    right_align = Alignment(horizontal="right" if is_ar else "left", vertical="center", wrap_text=True)

    meta_rows = [
        (lbl["project"], f"[{data.project_code}] {data.project_name}"),
        ("Title", data.title),
        (lbl["classification_prefix"], f"{data.classification} | v{data.version} ({data.revision})"),
        (lbl["advisory_heading"], ADVISORY_NOTICE_AR if is_ar else ADVISORY_NOTICE_EN),
        ("AI Status", _ai_banner_text(data, lbl)),
        ("Decision", _decision_banner_text(data, lbl)),
        (lbl["date"], data.issued_at_iso),
    ]
    for r_idx, (k_txt, v_txt) in enumerate(meta_rows, start=1):
        c1 = ws.cell(row=r_idx, column=1, value=_safe_xlsx_text(k_txt))
        c2 = ws.cell(row=r_idx, column=2, value=_safe_xlsx_text(v_txt))
        c1.font = bold_font
        c2.font = reg_font
        c1.alignment = right_align
        c2.alignment = right_align

    # Matrix starts at row 9
    header_row = 9
    base_headers = [
        "Criterion ID",
        "Category",
        lbl["col_criterion"],
        "Mandatory?",
        lbl["col_unit"],
        lbl["col_weight"],
    ]
    opt_list = data.matrix.options
    all_headers = list(base_headers)
    for opt in opt_list:
        tag = opt.option_id
        all_headers.extend(
            [
                f"{tag}: Display Value",
                f"{tag}: Raw Unit",
                f"{tag}: Norm (0-100)",
                f"{tag}: Weighted Score",
                f"{tag}: Mandatory Gate",
            ]
        )

    for col_idx, h_txt in enumerate(all_headers, start=1):
        c = ws.cell(row=header_row, column=col_idx, value=_safe_xlsx_text(h_txt))
        c.fill = navy_fill
        c.font = hdr_font
        c.alignment = right_align

    first_crit_row = header_row + 1
    row = first_crit_row
    for crit in data.criteria:
        ws.cell(row=row, column=1, value=_safe_xlsx_text(crit.criterion_id)).font = reg_font
        ws.cell(row=row, column=2, value=_safe_xlsx_text(crit.category)).font = reg_font
        ws.cell(row=row, column=3, value=_safe_xlsx_text(crit.label)).font = bold_font if crit.is_mandatory else reg_font
        ws.cell(row=row, column=4, value="YES" if crit.is_mandatory else "NO").font = reg_font
        ws.cell(row=row, column=5, value=_safe_xlsx_text(crit.target_unit)).font = reg_font
        w_cell = ws.cell(row=row, column=6, value=float(crit.weight))
        w_cell.font = reg_font
        w_cell.number_format = "0.00"

        for o_idx, opt in enumerate(opt_list):
            base_c = 7 + o_idx * 5
            cell = next((x for x in opt.cells if x.criterion_id == crit.criterion_id), None)
            if not cell:
                c_disp = ws.cell(row=row, column=base_c, value=NOT_PROVIDED_LABEL)
                c_disp.fill = warn_fill
                ws.cell(row=row, column=base_c + 1, value="")
                ws.cell(row=row, column=base_c + 2, value=0.0)
                norm_col_ltr = get_column_letter(base_c + 2)
                ws.cell(row=row, column=base_c + 3, value=f"=ROUND({norm_col_ltr}{row}*$F{row}/100,4)")
                ws.cell(row=row, column=base_c + 4, value="FAIL" if crit.is_mandatory else "N/A")
                continue

            if not cell.is_missing and cell.unit_status != "flagged_mismatch" and isinstance(cell.raw_value, (int, float)):
                disp_val: Any = float(cell.raw_value)
            elif not cell.is_missing and cell.converted_value and cell.unit_status in {"exact", "converted_explicitly"}:
                try:
                    disp_val = float(cell.converted_value) if cell.unit_status == "exact" else _safe_xlsx_text(f"{cell.display_value} (-> {cell.converted_value} {cell.target_unit})")
                except ValueError:
                    disp_val = _safe_xlsx_text(cell.display_value)
            else:
                disp_val = _safe_xlsx_text(cell.display_value)

            c_disp = ws.cell(row=row, column=base_c, value=disp_val)
            if cell.unit_status == "flagged_mismatch":
                c_disp.fill = bad_fill
            elif cell.is_missing:
                c_disp.fill = warn_fill

            ws.cell(row=row, column=base_c + 1, value=_safe_xlsx_text(cell.raw_unit))
            ws.cell(row=row, column=base_c + 2, value=round(float(cell.normalized_score), 4))
            norm_col_ltr = get_column_letter(base_c + 2)
            # Live Excel formula directly recomputing weighted score from Norm * Weight / 100
            ws.cell(row=row, column=base_c + 3, value=f"=ROUND({norm_col_ltr}{row}*$F{row}/100,4)")
            mand_lbl = "N/A" if not cell.is_mandatory else ("PASS" if cell.mandatory_passed else "FAIL")
            c_m = ws.cell(row=row, column=base_c + 4, value=mand_lbl)
            if cell.is_mandatory:
                c_m.fill = ok_fill if cell.mandatory_passed else bad_fill
        row += 1

    last_crit_row = row - 1
    tot_row = row
    ws.cell(row=tot_row, column=1, value="TOTAL").font = bold_font
    ws.cell(row=tot_row, column=3, value="Weights Sum & Total Option Weighted Scores").font = bold_font
    w_tot = ws.cell(row=tot_row, column=6, value=f"=SUM(F{first_crit_row}:F{last_crit_row})")
    w_tot.font = bold_font

    for col_i in range(1, len(all_headers) + 1):
        ws.cell(row=tot_row, column=col_i).fill = sub_fill

    for o_idx, opt in enumerate(opt_list):
        base_c = 7 + o_idx * 5
        wt_col_ltr = get_column_letter(base_c + 3)
        c_sum = ws.cell(
            row=tot_row,
            column=base_c + 3,
            value=f"=ROUND(SUM({wt_col_ltr}{first_crit_row}:{wt_col_ltr}{last_crit_row}),4)",
        )
        c_sum.font = bold_font
        c_gate = ws.cell(
            row=tot_row,
            column=base_c + 4,
            value=f'=IF(COUNTIF({get_column_letter(base_c + 4)}{first_crit_row}:{get_column_letter(base_c + 4)}{last_crit_row},"FAIL")=0,"PASS","FAIL")',
        )
        c_gate.font = bold_font
        c_gate.fill = ok_fill if opt.mandatory_passed else bad_fill

    # Weight Check Row
    chk_row = tot_row + 1
    ws.cell(row=chk_row, column=3, value="Weights Sum Check (must equal 100.00%)").font = bold_font
    w_chk = ws.cell(row=chk_row, column=6, value=f'=IF(ABS(F{tot_row}-100)<0.001,"VALID (100%)","INVALID WEIGHTS")')
    w_chk.font = bold_font
    w_chk.fill = ok_fill if data.matrix.weights_sum_valid else bad_fill

    # Auto column widths on Sheet 1
    for col_i in range(1, len(all_headers) + 1):
        ltr = get_column_letter(col_i)
        ws.column_dimensions[ltr].width = 24 if col_i == 3 else 17

    # Sheet 2: Full Source Provenance, Unit Conversion Log & Flags
    ws2 = wb.create_sheet(title="المصادر والتنبيهات" if is_ar else "Provenance & Flags")
    ws2.views.sheetView[0].rightToLeft = is_ar
    prov_headers = [
        "Option ID",
        "Option Name",
        "Criterion ID",
        "Category",
        "Display Value",
        "Raw Unit",
        "Target Unit",
        "Converted Value",
        "Unit Status",
        "Conversion Note",
        "Source Kind",
        "Source Reference",
        "BOQ Item ID",
        "Specification ID",
        "Calculation ID",
        "Research Source ID",
        "Risks",
    ]
    for col_idx, h_txt in enumerate(prov_headers, start=1):
        c = ws2.cell(row=1, column=col_idx, value=_safe_xlsx_text(h_txt))
        c.fill = navy_fill
        c.font = hdr_font
        c.alignment = right_align

    p_row = 2
    for opt in opt_list:
        risks_joined = "; ".join(opt.risks) if opt.risks else NOT_PROVIDED_LABEL
        for cell in opt.cells:
            vals = [
                opt.option_id,
                opt.name,
                cell.criterion_id,
                cell.category,
                cell.display_value,
                cell.raw_unit,
                cell.target_unit,
                cell.converted_value or "",
                cell.unit_status,
                cell.conversion_note or "",
                cell.source_kind,
                cell.source_ref,
                cell.boq_item_id or "",
                cell.specification_id or "",
                cell.calculation_id or "",
                cell.research_source_id or "",
                risks_joined,
            ]
            for c_idx, v in enumerate(vals, start=1):
                wc = ws2.cell(row=p_row, column=c_idx, value=_safe_xlsx_text(v))
                wc.font = reg_font
                if c_idx == 9 and cell.unit_status == "flagged_mismatch":
                    wc.fill = bad_fill
            p_row += 1

    for col_i in range(1, len(prov_headers) + 1):
        ltr = get_column_letter(col_i)
        ws2.column_dimensions[ltr].width = 30 if col_i in {10, 12, 17} else 16

    apply_xlsx_branding(
        wb,
        document_title=data.title,
        project_code=data.project_code,
        project_name=data.project_name,
        classification=data.classification,
        language=data.language,
    )
    wb.save(str(out_path))
