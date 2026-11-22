"""Step 17 bilingual Arabic RTL / English LTR DOCX, PDF & live-formula XLSX Standards Register exporter."""

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
from app.schemas.standards import StandardDocumentOut
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
class StandardsRegisterRenderData:
    """Normalized immutable Step 17 standards library register payload for DOCX, PDF & XLSX."""

    scope_label: str
    language: ReportLanguage
    classification: str
    issued_at_iso: str
    standards: list[StandardDocumentOut] = field(default_factory=list)


_REG_LABELS: dict[ReportLanguage, dict[str, str]] = {
    "ar": {
        "title": "سجل مكتبة المعايير والأكواد المعتمد من المالك (Step 17 — Standards Register)",
        "notice": "إشعار حقوق النشر والمصداقية: يتضمن هذا السجل فقط بيانات المعايير المرفوعة أو المُدخلة من المالك وبصمات SHA-256 وحالة السريان والاعتماد المحلي ومواضع الاستشهاد والمقتطفات القصيرة المعتمدة (<= 300 حرف مع رقم الصفحة) — لا يُعاد نشر أي نصوص معيارية محمية كاملة ولا يُختلق أي بند من الذاكرة.",
        "scope": "النطاق",
        "classification": "التصنيف",
        "date": "تاريخ التصدير (UTC)",
        "table_heading": "1. جدول المعايير وحالتها ومواضع الاستشهاد",
        "excerpts_heading": "2. المقتطفات القصيرة المختارة من المالك (<= 300 حرف) وبصمات الملفات",
        "warnings_heading": "3. تنبيهات الاستشهاد بمعايير ملغاة أو مسحوبة أو غير مؤكدة",
        "no_warnings": "لا توجد تنبيهات استشهاد بمعايير ملغاة أو مسحوبة أو غير مؤكدة.",
    },
    "en": {
        "title": "Owner-Supplied Standards Library Register (Step 17 — Audit & Citation Ledger)",
        "notice": "Copyright & Provenance Notice: This register reproduces ONLY owner-supplied/licensed standard metadata, SHA-256 document digests, status/supersession links, local-adoption flags, deliverable citation locations, and short owner-selected excerpts (<= 300 chars with page ref) — never full copyrighted texts or memory-invented clauses.",
        "scope": "Scope",
        "classification": "Classification",
        "date": "Export Date (UTC)",
        "table_heading": "1. Registered Standards Inventory, Status & Where Cited",
        "excerpts_heading": "2. Short Owner-Selected Excerpts (<= 300 chars) & File SHA-256 Hashes",
        "warnings_heading": "3. Citation Warnings (Superseded / Withdrawn / Unknown / Unconfirmed)",
        "no_warnings": "No citation warnings for superseded, withdrawn, unknown-edition, or unconfirmed standards.",
    },
}


def _where_cited_text(std: StandardDocumentOut) -> str:
    if not std.where_cited:
        return "None / لا يوجد"
    return "; ".join(
        f"[{h.module}] {h.artifact_title} @ {h.location}" + (f" ({h.flagged_status})" if h.flagged_status != "ok" else "")
        for h in std.where_cited
    )


def generate_standards_register_docx(out_path: Path, data: StandardsRegisterRenderData) -> None:
    """Export immutable bilingual Arabic RTL / English LTR DOCX Standards Register."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing register DOCX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _REG_LABELS[data.language]
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

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Tahoma"
    normal_style.font.size = Pt(9.0)

    apply_docx_branding(
        doc,
        language=data.language,
        classification=data.classification,
        document_title=lbl["title"],
    )

    p_t = doc.add_heading(f"{lbl['title']} [{data.classification}]", level=1)
    _style_paragraph(p_t, is_ar=is_ar, bold=True, font_size=13, color=RGBColor(0x1E, 0x3A, 0x5F))

    for idx, line in enumerate(
        (
            f"{lbl['scope']}: {data.scope_label} | {lbl['classification']}: {data.classification} | {lbl['date']}: {data.issued_at_iso}",
            lbl["notice"],
        )
    ):
        p = doc.add_paragraph(line)
        _style_paragraph(
            p,
            is_ar=is_ar,
            bold=(idx == 1),
            font_size=8.5,
            color=RGBColor(0x9A, 0x34, 0x12) if idx == 1 else None,
        )

    p_h1 = doc.add_heading(lbl["table_heading"], level=2)
    _style_paragraph(p_h1, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))

    headers = [
        "Standard #",
        "Title",
        "Issuing Body",
        "Edition",
        "Status",
        "Superseded By",
        "Jurisdiction / Local?",
        "Metadata Status",
        "File SHA-256",
        "Where Cited",
    ]
    tbl = doc.add_table(rows=1, cols=len(headers))
    _configure_rtl_table(tbl, is_ar=is_ar)
    for i, htxt in enumerate(headers):
        tbl.rows[0].cells[i].text = htxt
        _shade_cell(tbl.rows[0].cells[i], "1E3A5F")
        _style_paragraph(tbl.rows[0].cells[i].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))

    for std in data.standards:
        rc = tbl.add_row().cells
        row_vals = [
            f"{std.standard_number} (v{std.version})",
            std.title,
            std.issuing_body or "—",
            std.edition_year or "unknown",
            std.status.upper(),
            std.superseded_by_number or "—",
            f"{std.jurisdiction or '—'} / {'YES' if std.adopted_locally else 'NO'}",
            std.metadata_label or std.metadata_status,
            std.file_sha256[:12] if std.file_sha256 else "owner metadata",
            _where_cited_text(std),
        ]
        for i, val in enumerate(row_vals):
            rc[i].text = val
            if i == 4:
                if std.status == "current":
                    _shade_cell(rc[i], "DCFCE7")
                elif std.status in {"superseded", "unknown"}:
                    _shade_cell(rc[i], "FEF3C7")
                elif std.status == "withdrawn":
                    _shade_cell(rc[i], "FEE2E2")
            _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, bold=(i in {0, 4}), font_size=7.5)

    p_h2 = doc.add_heading(lbl["warnings_heading"], level=2)
    _style_paragraph(p_h2, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    all_warnings = [w for s in data.standards for w in s.citation_warnings]
    if not all_warnings:
        _style_paragraph(doc.add_paragraph(lbl["no_warnings"]), is_ar=is_ar, font_size=8.5)
    else:
        for w in all_warnings:
            _style_paragraph(doc.add_paragraph(f"• {w}"), is_ar=is_ar, bold=True, font_size=8.5, color=RGBColor(0xB9, 0x1C, 0x1C))

    p_h3 = doc.add_heading(lbl["excerpts_heading"], level=2)
    _style_paragraph(p_h3, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
    for std in data.standards:
        if not std.owner_excerpts:
            continue
        for ex in std.owner_excerpts:
            _style_paragraph(
                doc.add_paragraph(f"• [{std.standard_number} | {ex.page_ref}] \"{ex.text[:300]}\""),
                is_ar=is_ar,
                font_size=8.0,
            )

    doc.save(str(out_path))


def generate_standards_register_pdf(out_path: Path, data: StandardsRegisterRenderData) -> None:
    """Export immutable bilingual Arabic RTL / English LTR vector PDF Standards Register."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing register PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _REG_LABELS[data.language]

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'StdFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'StdFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'StdFont', Tahoma, sans-serif"
    else:
        font_face_css = ""
        font_stack = "sans-serif"

    rows_html = ""
    for std in data.standards:
        st_cls = "ok" if std.status == "current" else ("bad" if std.status == "withdrawn" else "warn")
        rows_html += (
            f"<tr>"
            f"<td><strong>{_esc_ltr(std.standard_number)}</strong> (v{_esc_ltr(std.version)})</td>"
            f"<td>{_esc_rtl_cell(std.title, is_ar=is_ar)}</td>"
            f"<td>{_esc_rtl_cell(std.issuing_body or '—', is_ar=is_ar)}</td>"
            f"<td>{_esc_ltr(std.edition_year or 'unknown')}</td>"
            f"<td class='{st_cls}'><strong>{_esc_ltr(std.status.upper())}</strong></td>"
            f"<td>{_esc_ltr(std.superseded_by_number or '—')}</td>"
            f"<td>{_esc_rtl_cell(std.jurisdiction or '—', is_ar=is_ar)} ({_esc_ltr('Local' if std.adopted_locally else 'Not Adopted')})</td>"
            f"<td>{_esc_rtl_cell(std.metadata_label or std.metadata_status, is_ar=is_ar)}</td>"
            f"<td>{_esc_ltr(std.file_sha256[:12] if std.file_sha256 else 'owner-entered')}</td>"
            f"<td>{_esc_rtl_cell(_where_cited_text(std), is_ar=is_ar)}</td>"
            f"</tr>"
        )

    all_warnings = [w for s in data.standards for w in s.citation_warnings]
    warnings_html = (
        f"<p>{_esc(lbl['no_warnings'])}</p>"
        if not all_warnings
        else "<ul>" + "".join(f"<li class='badtxt'>{_esc(w)}</li>" for w in all_warnings) + "</ul>"
    )
    excerpt_items = [
        f"<li><strong>{_esc_ltr(f'[{std.standard_number} | {ex.page_ref}]')}</strong> &ldquo;{_esc(ex.text[:300])}&rdquo;</li>"
        for std in data.standards
        for ex in std.owner_excerpts
    ]
    excerpts_html = "<ul>" + "".join(excerpt_items) + "</ul>" if excerpt_items else f"<p>{_esc_ltr('—')}</p>"

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 8pt; color: #0f172a; margin: 0; }}
.banner {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 5pt; margin-bottom: 7pt; }}
h1 {{ color: #1e3a5f; font-size: 12pt; margin: 0 0 3pt 0; }}
h2 {{ color: #1e3a5f; font-size: 9.8pt; margin: 8pt 0 3pt 0; }}
.notice {{ color: #9a3412; font-weight: bold; font-size: 7.8pt; margin-top: 3pt; }}
table {{ width: 100%; border-collapse: collapse; margin: 3pt 0 7pt 0; font-size: 7.2pt; }}
th, td {{ border: 0.5pt solid #94a3b8; padding: 3pt; text-align: {align}; vertical-align: top; }}
th {{ background-color: #1e3a5f; color: #ffffff; font-weight: bold; }}
td.ok {{ background-color: #dcfce7; color: #166534; }}
td.warn {{ background-color: #fef3c7; color: #92400e; }}
td.bad {{ background-color: #fee2e2; color: #991b1b; }}
.badtxt {{ color: #b91c1c; font-weight: bold; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(lbl['title'])} [{_esc_ltr(data.classification)}]</h1>
    <div>{_esc(lbl['scope'])}: {_esc_rtl_cell(data.scope_label, is_ar=is_ar)} | {_esc(lbl['date'])}: {_esc_ltr(data.issued_at_iso)}</div>
    <div class="notice">{_esc(lbl['notice'])}</div>
  </div>
  <h2>{_esc(lbl['table_heading'])}</h2>
  <table>
    <thead>
      <tr>
        <th>Number</th><th>Title</th><th>Issuer</th><th>Edition</th><th>Status</th>
        <th>Superseded By</th><th>Jurisdiction / Local</th><th>Metadata</th><th>SHA-256</th><th>Where Cited</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <h2>{_esc(lbl['warnings_heading'])}</h2>
  {warnings_html}
  <h2>{_esc(lbl['excerpts_heading'])}</h2>
  {excerpts_html}
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


def generate_standards_register_xlsx(out_path: Path, data: StandardsRegisterRenderData) -> None:
    """Export immutable bilingual live-formula XLSX Standards Register (Inventory + Citations/Excerpts)."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing register XLSX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _REG_LABELS[data.language]
    wb = Workbook()
    ws = wb.active
    ws.title = "سجل المعايير" if is_ar else "Standards Register"
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
            (lbl["scope"], data.scope_label),
            (lbl["classification"], data.classification),
            (lbl["date"], data.issued_at_iso),
            ("Notice", lbl["notice"]),
        ),
        start=1,
    ):
        c1 = ws.cell(row=r_i, column=1, value=_safe_xlsx_text(k))
        c2 = ws.cell(row=r_i, column=2, value=_safe_xlsx_text(v))
        c1.font = bold_font
        c2.font = reg_font
        c1.alignment = align
        c2.alignment = align

    hdr_row = 6
    headers = [
        "Standard Number",
        "Title",
        "Issuing Body",
        "Edition Year",
        "Status",
        "Superseded By",
        "Supersession Note",
        "Jurisdiction",
        "Adopted Locally?",
        "Metadata Status",
        "File SHA-256",
        "Citations Count",
        "Where Cited",
    ]
    for col_i, h_txt in enumerate(headers, start=1):
        c = ws.cell(row=hdr_row, column=col_i, value=_safe_xlsx_text(h_txt))
        c.fill = navy_fill
        c.font = hdr_font
        c.alignment = align

    first_row = hdr_row + 1
    row = first_row
    for std in data.standards:
        ws.cell(row=row, column=1, value=_safe_xlsx_text(std.standard_number)).font = bold_font
        ws.cell(row=row, column=2, value=_safe_xlsx_text(std.title)).font = reg_font
        ws.cell(row=row, column=3, value=_safe_xlsx_text(std.issuing_body or "—")).font = reg_font
        ws.cell(row=row, column=4, value=_safe_xlsx_text(std.edition_year or "unknown")).font = reg_font
        c_st = ws.cell(row=row, column=5, value=_safe_xlsx_text(std.status))
        c_st.font = bold_font
        if std.status == "current":
            c_st.fill = ok_fill
        elif std.status == "withdrawn":
            c_st.fill = bad_fill
        else:
            c_st.fill = warn_fill
        ws.cell(row=row, column=6, value=_safe_xlsx_text(std.superseded_by_number or "—")).font = reg_font
        ws.cell(row=row, column=7, value=_safe_xlsx_text(std.supersession_note or "")).font = reg_font
        ws.cell(row=row, column=8, value=_safe_xlsx_text(std.jurisdiction or "—")).font = reg_font
        ws.cell(row=row, column=9, value="YES" if std.adopted_locally else "NO").font = reg_font
        ws.cell(row=row, column=10, value=_safe_xlsx_text(std.metadata_status)).font = reg_font
        ws.cell(row=row, column=11, value=_safe_xlsx_text(std.file_sha256 or "—")).font = reg_font
        ws.cell(row=row, column=12, value=len(std.where_cited)).font = reg_font
        ws.cell(row=row, column=13, value=_safe_xlsx_text(_where_cited_text(std))).font = reg_font
        row += 1

    last_row = max(first_row, row - 1)
    sum_row = row + 1
    ws.cell(row=sum_row, column=1, value="SUMMARY").font = bold_font
    ws.cell(row=sum_row, column=2, value="Current Standards").font = bold_font
    ws.cell(row=sum_row, column=5, value=f'=COUNTIF(E{first_row}:E{last_row},"current")' if data.standards else 0).font = bold_font
    ws.cell(row=sum_row, column=9, value=f'=COUNTIF(I{first_row}:I{last_row},"YES")' if data.standards else 0).font = bold_font
    ws.cell(row=sum_row, column=12, value=f"=SUM(L{first_row}:L{last_row})" if data.standards else 0).font = bold_font

    sup_row = sum_row + 1
    ws.cell(row=sup_row, column=2, value="Superseded + Withdrawn").font = bold_font
    ws.cell(
        row=sup_row,
        column=5,
        value=f'=COUNTIF(E{first_row}:E{last_row},"superseded")+COUNTIF(E{first_row}:E{last_row},"withdrawn")' if data.standards else 0,
    ).font = bold_font

    for col_i in range(1, len(headers) + 1):
        ws.cell(row=sum_row, column=col_i).fill = sub_fill
        ws.column_dimensions[get_column_letter(col_i)].width = 30 if col_i in {2, 13} else 17

    # Sheet 2: Permitted Owner Excerpts & Detailed Citation Locations
    ws2 = wb.create_sheet(title="المقتطفات والاستشهادات" if is_ar else "Excerpts & Citations")
    ws2.views.sheetView[0].rightToLeft = is_ar
    s2_hdrs = ["Record Type", "Standard Number", "Module / Page Ref", "Detail / Permitted Excerpt (<=300 chars)", "Flag / Status"]
    for col_i, h_txt in enumerate(s2_hdrs, start=1):
        c = ws2.cell(row=1, column=col_i, value=_safe_xlsx_text(h_txt))
        c.fill = navy_fill
        c.font = hdr_font
    r2 = 2
    for std in data.standards:
        for hit in std.where_cited:
            vals = ["Citation Hit", std.standard_number, f"{hit.module}: {hit.artifact_title}", hit.location, hit.flagged_status]
            for c_i, v in enumerate(vals, start=1):
                wc = ws2.cell(row=r2, column=c_i, value=_safe_xlsx_text(v))
                wc.font = reg_font
                if c_i == 5 and hit.flagged_status != "ok":
                    wc.fill = bad_fill
            r2 += 1
        for ex in std.owner_excerpts:
            vals = ["Owner Excerpt", std.standard_number, ex.page_ref, ex.text[:300], "Owner-selected (<=300 chars)"]
            for c_i, v in enumerate(vals, start=1):
                ws2.cell(row=r2, column=c_i, value=_safe_xlsx_text(v)).font = reg_font
            r2 += 1
    for col_i in range(1, len(s2_hdrs) + 1):
        ws2.column_dimensions[get_column_letter(col_i)].width = 42 if col_i == 4 else 20

    apply_xlsx_branding(
        wb,
        document_title="Standards Library Register",
        project_code=data.scope_label,
        project_name=data.scope_label,
        classification=data.classification,
        language=data.language,
    )
    wb.save(str(out_path))
