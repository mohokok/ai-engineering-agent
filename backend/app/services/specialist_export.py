"""Step 18 bilingual Arabic RTL / English LTR DOCX, vector PDF & live-formula XLSX exporter for HVAC, Fire & Healthcare preflight assessments."""

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

from app.schemas.reports import ReportLanguage
from app.schemas.specialist import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NOT_PROVIDED_LABEL,
    PRELIMINARY_ENGINEER_LABEL_AR,
    PRELIMINARY_ENGINEER_LABEL_EN,
    SpecialistReferenceOut,
)
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
class SpecialistRenderData:
    """Normalized immutable Step 18 payload for DOCX, PDF & XLSX exports."""

    project_code: str
    project_name: str
    title: str
    domain: str
    workflow_mode: str
    language: ReportLanguage
    classification: str
    revision: str
    version: int
    status: str
    checks_passed: bool
    standards_status: str
    software_recommendation: str
    ai_draft_status: str
    owner_approved_by: str | None
    issued_at_iso: str
    equations: list[str] = field(default_factory=list)
    methodology: str = ""
    preliminary_assumptions: list[str] = field(default_factory=list)
    prepared_items: list[dict[str, Any]] = field(default_factory=list)
    check_rows: list[dict[str, Any]] = field(default_factory=list)
    blocked_flags: list[str] = field(default_factory=list)
    references: list[SpecialistReferenceOut] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    summary: str | None = None
    report_heading: str | None = None
    preliminary_notice: str | None = None


_LABELS: dict[ReportLanguage, dict[str, str]] = {
    "ar": {
        "heading": "الخطوة 18: حزمة تحضير المدخلات وفحص المخرجات الأولية",
        "project": "المشروع",
        "domain": "التخصص / النطاق",
        "mode": "نمط التشغيل",
        "verdict": "الحكم الأولي",
        "software": "توصية البرمجيات الهندسية المعتمدة",
        "prelim": PRELIMINARY_ENGINEER_LABEL_AR,
        "ai_warn": AI_UNVERIFIED_DRAFT_LABEL_AR,
        "refs": "1. المعايير والمراجع المُتحقَّق منها",
        "checks": "2. نتائج فحص المخرجات واكتمال المدخلات",
        "prepared": "3. جدول المدخلات المحضّرة والقيم المحسوبة",
        "equations": "4. المعادلات والمنهجية والافتراضات الأولية",
    },
    "en": {
        "heading": "Step 18: Specialist Input Preparation & Output Check Report",
        "project": "Project",
        "domain": "Domain / Mode",
        "mode": "Workflow Mode",
        "verdict": "Preliminary Verdict",
        "software": "Validated Commercial Software Recommendation",
        "prelim": PRELIMINARY_ENGINEER_LABEL_EN,
        "ai_warn": AI_UNVERIFIED_DRAFT_LABEL_EN,
        "refs": "1. Standards & Verified References",
        "checks": "2. Output Checks & Missing-Input Gates",
        "prepared": "3. Prepared Inputs & Deterministic Quantities",
        "equations": "4. Equations, Methodology & Preliminary Assumptions",
    },
}


def _status_txt(data: SpecialistRenderData) -> str:
    if data.blocked_flags or data.status == "blocked_missing_inputs":
        return f"BLOCKED ({NOT_PROVIDED_LABEL}) — {len(data.blocked_flags)} gap(s)"
    return "PASS (PRELIMINARY — licensed engineer sign-off required)" if data.checks_passed else "FAIL — Review Needed"


def generate_specialist_docx(out_path: Path, data: SpecialistRenderData) -> None:
    """Export immutable bilingual RTL/LTR DOCX report for Step 18 HVAC/Fire/Healthcare assessment."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing DOCX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _LABELS[data.language]
    doc = Document()

    for section in doc.sections:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Inches(11.69)
        section.page_height = Inches(8.27)
        section.top_margin = Inches(0.55)
        section.bottom_margin = Inches(0.55)
        section.left_margin = Inches(0.55)
        section.right_margin = Inches(0.55)
        if is_ar:
            _set_element_tag(section._sectPr, "w:bidi")

    doc.styles["Normal"].font.name = "Tahoma"
    doc.styles["Normal"].font.size = Pt(9.0)

    apply_docx_branding(
        doc,
        language=data.language,
        classification=data.classification,
        document_title=data.title,
    )

    heading_txt = data.report_heading or lbl["heading"]
    prelim_txt = data.preliminary_notice or lbl["prelim"]

    _style_paragraph(
        doc.add_heading(f"{heading_txt}: {data.title} [{data.classification}]", level=1),
        is_ar=is_ar,
        bold=True,
        font_size=13,
        color=RGBColor(0x1E, 0x3A, 0x5F),
    )

    meta_lines = [
        f"{lbl['project']}: {data.project_code} — {data.project_name} | {data.revision} v{data.version}",
        f"{lbl['domain']}: {data.domain.upper()} | {lbl['mode']}: {data.workflow_mode} | {lbl['verdict']}: {_status_txt(data)}",
        f"{lbl['software']}: {data.software_recommendation}",
        prelim_txt,
    ]
    if data.ai_draft_status == "unverified_ai_draft":
        meta_lines.insert(0, lbl["ai_warn"])
    for idx, line in enumerate(meta_lines):
        _style_paragraph(
            doc.add_paragraph(line),
            is_ar=is_ar,
            bold=(idx < 3 or "AI DRAFT" in line),
            font_size=8.5,
            color=RGBColor(0xB9, 0x1C, 0x1C) if ("AI DRAFT" in line or "Preliminary" in line) else None,
        )

    _style_paragraph(doc.add_heading(lbl["refs"], level=2), is_ar=is_ar, bold=True, font_size=11)
    rtbl = doc.add_table(rows=1, cols=5)
    rtbl.style = "Table Grid"
    _configure_rtl_table(rtbl, is_ar=is_ar)
    for idx, htxt in enumerate(["Kind", "Code / Source", "Edition / Date", "Status", "Verification Label"]):
        rtbl.rows[0].cells[idx].text = htxt
        _shade_cell(rtbl.rows[0].cells[idx], "1E3A5F")
        _style_paragraph(rtbl.rows[0].cells[idx].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
    for ref in data.references:
        rc = rtbl.add_row().cells
        for i, v in enumerate((ref.source_kind, ref.code_or_source_name, ref.edition_or_date, ref.status, ref.verification_label)):
            rc[i].text = str(v)
            _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, font_size=7.5)

    _style_paragraph(doc.add_heading(lbl["checks"], level=2), is_ar=is_ar, bold=True, font_size=11)
    ctbl = doc.add_table(rows=1, cols=6)
    ctbl.style = "Table Grid"
    _configure_rtl_table(ctbl, is_ar=is_ar)
    for idx, htxt in enumerate(["Item", "Check", "Target / Expected", "Actual / Reported", "Status", "Notes"]):
        ctbl.rows[0].cells[idx].text = htxt
        _shade_cell(ctbl.rows[0].cells[idx], "1E3A5F")
        _style_paragraph(ctbl.rows[0].cells[idx].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
    for chk in data.check_rows:
        rc = ctbl.add_row().cells
        st_s = str(chk.get("status") or "")
        for i, key in enumerate(("item_id", "label", "expected", "actual", "status", "notes")):
            rc[i].text = str(chk.get(key, ""))
            if i == 4:
                if "PASS" in st_s:
                    _shade_cell(rc[i], "DCFCE7")
                elif "FAIL" in st_s:
                    _shade_cell(rc[i], "FEE2E2")
                elif "blocked" in st_s.lower():
                    _shade_cell(rc[i], "FEF3C7")
            _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, bold=(i in {0, 4}), font_size=7.5)

    _style_paragraph(doc.add_heading(lbl["prepared"], level=2), is_ar=is_ar, bold=True, font_size=11)
    if data.prepared_items:
        cols = list(data.prepared_items[0].keys())
        ptbl = doc.add_table(rows=1, cols=len(cols))
        ptbl.style = "Table Grid"
        _configure_rtl_table(ptbl, is_ar=is_ar)
        for idx, col in enumerate(cols):
            ptbl.rows[0].cells[idx].text = col
            _shade_cell(ptbl.rows[0].cells[idx], "1E3A5F")
            _style_paragraph(ptbl.rows[0].cells[idx].paragraphs[0], is_ar=is_ar, bold=True, font_size=7.0, color=RGBColor(0xFF, 0xFF, 0xFF))
        for item in data.prepared_items:
            rc = ptbl.add_row().cells
            for i, col in enumerate(cols):
                rc[i].text = str(item.get(col, NOT_PROVIDED_LABEL))
                _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, font_size=7.0)

    _style_paragraph(doc.add_heading(lbl["equations"], level=2), is_ar=is_ar, bold=True, font_size=11)
    for eq in data.equations:
        _style_paragraph(doc.add_paragraph(f"• {eq}"), is_ar=is_ar, font_size=8.0)
    for asm in data.preliminary_assumptions:
        _style_paragraph(doc.add_paragraph(f"Assumption: {asm}"), is_ar=is_ar, font_size=8.0)
    if data.summary:
        _style_paragraph(doc.add_paragraph(f"Summary / AI Note: {data.summary}"), is_ar=is_ar, font_size=8.0)

    doc.save(str(out_path))


def generate_specialist_pdf(out_path: Path, data: SpecialistRenderData) -> None:
    """Export immutable bilingual Arabic RTL / English LTR vector PDF for Step 18."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _LABELS[data.language]

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'SpFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'SpFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'SpFont', Tahoma, sans-serif"
    else:
        font_face_css = ""
        font_stack = "sans-serif"

    refs_html = "".join(
        f"<tr><td>{_esc_ltr(r.source_kind)}</td><td>{_esc_rtl_cell(r.code_or_source_name, is_ar=is_ar)}</td>"
        f"<td>{_esc_ltr(r.edition_or_date)}</td><td>{_esc_ltr(r.status)}</td>"
        f"<td>{_esc_rtl_cell(r.verification_label, is_ar=is_ar)}</td></tr>"
        for r in data.references
    )
    checks_html = "".join(
        f"<tr><td><strong>{_esc_ltr(c.get('item_id'))}</strong></td>"
        f"<td>{_esc_rtl_cell(c.get('label'), is_ar=is_ar)}</td>"
        f"<td>{_esc_ltr(c.get('expected'))}</td>"
        f"<td>{_esc_ltr(c.get('actual'))}</td>"
        f"<td class='{'ok' if 'PASS' in str(c.get('status')) else ('bad' if 'FAIL' in str(c.get('status')) else 'warn')}'>"
        f"<strong>{_esc_ltr(c.get('status'))}</strong></td>"
        f"<td>{_esc_rtl_cell(c.get('notes'), is_ar=is_ar)}</td></tr>"
        for c in data.check_rows
    )

    prep_head = ""
    prep_body = ""
    if data.prepared_items:
        cols = list(data.prepared_items[0].keys())
        prep_head = "".join(f"<th>{_esc_ltr(col)}</th>" for col in cols)
        prep_body = "".join(
            "<tr>" + "".join(f"<td>{_esc_ltr(item.get(col, NOT_PROVIDED_LABEL))}</td>" for col in cols) + "</tr>"
            for item in data.prepared_items
        )

    ai_banner = (
        f"<div class='badtxt'>{_esc(lbl['ai_warn'])}</div>"
        if data.ai_draft_status == "unverified_ai_draft"
        else ""
    )

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 7.8pt; color: #0f172a; margin: 0; }}
.hdr {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 5pt; margin-bottom: 6pt; }}
h1 {{ color: #1e3a5f; font-size: 11.5pt; margin: 0 0 3pt 0; }}
h2 {{ color: #1e3a5f; font-size: 9.5pt; margin: 7pt 0 3pt 0; }}
.prelim {{ color: #9a3412; font-weight: bold; font-size: 7.5pt; margin-top: 2pt; }}
.soft {{ background-color: #eff6ff; border: 0.5pt solid #93c5fd; padding: 4pt; margin: 4pt 0; font-size: 7.5pt; }}
.badtxt {{ color: #b91c1c; font-weight: bold; margin: 3pt 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 3pt 0 6pt 0; font-size: 6.8pt; }}
th, td {{ border: 0.5pt solid #94a3b8; padding: 2.5pt; text-align: {align}; vertical-align: top; }}
th {{ background-color: #1e3a5f; color: #ffffff; }}
td.ok {{ background-color: #dcfce7; color: #166534; }}
td.warn {{ background-color: #fef3c7; color: #92400e; }}
td.bad {{ background-color: #fee2e2; color: #991b1b; }}
</style>
</head>
<body>
  <div class="hdr">
    <h1>{_esc(data.report_heading or lbl['heading'])}: {_esc_rtl_cell(data.title, is_ar=is_ar)} [{_esc_ltr(data.classification)}]</h1>
    <div>{_esc(lbl['project'])}: {_esc_ltr(data.project_code)} — {_esc_rtl_cell(data.project_name, is_ar=is_ar)} | {_esc_ltr(data.revision)} v{_esc_ltr(data.version)} | {_esc_ltr(data.issued_at_iso)}</div>
    <div><strong>{_esc_ltr(data.domain.upper())}</strong> ({_esc_ltr(data.workflow_mode)}) — <strong>{_esc_ltr(_status_txt(data))}</strong></div>
    {ai_banner}
    <div class="prelim">{_esc(data.preliminary_notice or lbl['prelim'])}</div>
    <div class="soft"><strong>{_esc(lbl['software'])}:</strong> {_esc_ltr(data.software_recommendation)}</div>
  </div>
  <h2>{_esc(lbl['refs'])}</h2>
  <table><thead><tr><th>Kind</th><th>Code / Source</th><th>Edition</th><th>Status</th><th>Verification</th></tr></thead><tbody>{refs_html}</tbody></table>
  <h2>{_esc(lbl['checks'])}</h2>
  <table><thead><tr><th>Item</th><th>Check</th><th>Expected</th><th>Actual</th><th>Verdict</th><th>Notes</th></tr></thead><tbody>{checks_html}</tbody></table>
  <h2>{_esc(lbl['prepared'])}</h2>
  <table><thead><tr>{prep_head}</tr></thead><tbody>{prep_body}</tbody></table>
  <h2>{_esc(lbl['equations'])}</h2>
  <ul>{''.join(f"<li>{_esc_ltr(eq)}</li>" for eq in data.equations)}</ul>
  <ul>{''.join(f"<li>{_esc_ltr(a)}</li>" for a in data.preliminary_assumptions)}</ul>
</body>
</html>"""

    write_branded_story_pdf(
        out_path,
        html_doc=html_doc,
        fonts_dir=_WINDOWS_FONTS_DIR,
        landscape=True,
        classification=data.classification,
        language=data.language,
        side_margin=24.0,
        top_margin=60.0,
        bottom_margin=40.0,
        max_pages=120,
    )


def generate_specialist_xlsx(out_path: Path, data: SpecialistRenderData) -> None:
    """Export immutable bilingual live-formula XLSX workbook for Step 18 assessment."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing XLSX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _LABELS[data.language]
    wb = Workbook()
    ws = wb.active
    ws.title = "فحص التخصص" if is_ar else "Preflight Checks"
    ws.views.sheetView[0].rightToLeft = is_ar

    navy_fill = PatternFill("solid", fgColor="1E3A5F")
    ok_fill = PatternFill("solid", fgColor="DCFCE7")
    warn_fill = PatternFill("solid", fgColor="FEF3C7")
    bad_fill = PatternFill("solid", fgColor="FEE2E2")
    sub_fill = PatternFill("solid", fgColor="E2E8F0")
    hdr_font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    bold_font = Font(name="Tahoma", size=10, bold=True)
    reg_font = Font(name="Tahoma", size=10)
    align = Alignment(horizontal="right" if is_ar else "left", vertical="center", wrap_text=True)

    for r_i, (k, v) in enumerate(
        (
            (lbl["project"], f"{data.project_code} — {data.project_name}"),
            (lbl["domain"], f"{data.domain.upper()} / {data.workflow_mode} / {data.classification} / v{data.version}"),
            (lbl["verdict"], _status_txt(data)),
            ("Notice", data.preliminary_notice or lbl["prelim"]),
            (lbl["software"], data.software_recommendation),
        ),
        start=1,
    ):
        c1 = ws.cell(row=r_i, column=1, value=_safe_xlsx_text(k))
        c2 = ws.cell(row=r_i, column=2, value=_safe_xlsx_text(v))
        c1.font = bold_font
        c2.font = reg_font
        c1.alignment = align
        c2.alignment = align

    hdr_row = 7
    chk_headers = ["Item ID", "Check Label", "Expected / Target", "Actual / Reported", "Unit", "Status", "Notes"]
    for col_i, htxt in enumerate(chk_headers, start=1):
        c = ws.cell(row=hdr_row, column=col_i, value=_safe_xlsx_text(htxt))
        c.fill = navy_fill
        c.font = hdr_font
        c.alignment = align

    first_row = hdr_row + 1
    row = first_row
    for chk in data.check_rows:
        st_s = str(chk.get("status") or "")
        vals = [
            chk.get("item_id", ""),
            chk.get("label", ""),
            chk.get("expected", ""),
            chk.get("actual", ""),
            chk.get("unit", ""),
            st_s,
            chk.get("notes", ""),
        ]
        for col_i, v in enumerate(vals, start=1):
            wc = ws.cell(row=row, column=col_i, value=_safe_xlsx_text(v))
            wc.font = bold_font if col_i in {1, 6} else reg_font
            wc.alignment = align
            if col_i == 6:
                if "PASS" in st_s:
                    wc.fill = ok_fill
                elif "FAIL" in st_s:
                    wc.fill = bad_fill
                elif "blocked" in st_s.lower():
                    wc.fill = warn_fill
        row += 1

    last_row = max(first_row, row - 1)
    sum_row = row + 1
    ws.cell(row=sum_row, column=1, value="SUMMARY").font = bold_font
    ws.cell(row=sum_row, column=2, value="Passed / Failed / Blocked Counts").font = bold_font
    ws.cell(
        row=sum_row,
        column=3,
        value=f'=COUNTIF(F{first_row}:F{last_row},"PASS*")' if data.check_rows else 0,
    ).font = bold_font
    ws.cell(
        row=sum_row,
        column=4,
        value=f'=COUNTIF(F{first_row}:F{last_row},"FAIL*")' if data.check_rows else 0,
    ).font = bold_font
    ws.cell(
        row=sum_row,
        column=6,
        value=f'=COUNTIF(F{first_row}:F{last_row},"blocked*")' if data.check_rows else 0,
    ).font = bold_font
    for col_i in range(1, len(chk_headers) + 1):
        ws.cell(row=sum_row, column=col_i).fill = sub_fill
        ws.column_dimensions[get_column_letter(col_i)].width = 32 if col_i in {2, 7} else 20

    # Sheet 2: Prepared Inputs + References & Assumptions
    ws2 = wb.create_sheet(title="المدخلات والمراجع" if is_ar else "Inputs & Provenance")
    ws2.views.sheetView[0].rightToLeft = is_ar
    r2 = 1
    if data.prepared_items:
        pcols = list(data.prepared_items[0].keys())
        for ci, cname in enumerate(pcols, start=1):
            hc = ws2.cell(row=r2, column=ci, value=_safe_xlsx_text(cname))
            hc.fill = navy_fill
            hc.font = hdr_font
            ws2.column_dimensions[get_column_letter(ci)].width = 20
        r2 += 1
        for item in data.prepared_items:
            for ci, cname in enumerate(pcols, start=1):
                val = item.get(cname, NOT_PROVIDED_LABEL)
                if isinstance(val, (int, float)):
                    ws2.cell(row=r2, column=ci, value=val).font = reg_font
                else:
                    ws2.cell(row=r2, column=ci, value=_safe_xlsx_text(val)).font = reg_font
            r2 += 1

    r2 += 1
    ws2.cell(row=r2, column=1, value="Standards & Verification").font = bold_font
    r2 += 1
    for ref in data.references:
        ws2.cell(row=r2, column=1, value=_safe_xlsx_text(ref.source_kind)).font = reg_font
        ws2.cell(row=r2, column=2, value=_safe_xlsx_text(ref.code_or_source_name)).font = bold_font
        ws2.cell(row=r2, column=3, value=_safe_xlsx_text(ref.edition_or_date)).font = reg_font
        ws2.cell(row=r2, column=4, value=_safe_xlsx_text(ref.status)).font = reg_font
        ws2.cell(row=r2, column=5, value=_safe_xlsx_text(ref.verification_label)).font = reg_font
        r2 += 1

    r2 += 1
    for eq in data.equations:
        ws2.cell(row=r2, column=1, value="Equation").font = bold_font
        ws2.cell(row=r2, column=2, value=_safe_xlsx_text(eq)).font = reg_font
        r2 += 1
    for asm in data.preliminary_assumptions:
        ws2.cell(row=r2, column=1, value="Preliminary Assumption").font = bold_font
        ws2.cell(row=r2, column=2, value=_safe_xlsx_text(asm)).font = reg_font
        r2 += 1

    apply_xlsx_branding(
        wb,
        document_title=data.title,
        project_code=data.project_code,
        project_name=data.project_name,
        classification=data.classification,
        language=data.language,
    )
    wb.save(str(out_path))
