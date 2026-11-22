"""Bilingual Arabic RTL / English LTR DOCX and vector PDF exporter for independent QA Review reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Literal

from docx import Document
from docx.shared import Inches, Pt, RGBColor

from app.schemas.qa import IssueOut, QaCheckMetricOut, QaContextIsolationReport
from app.services.branding_exports import apply_docx_branding, write_branded_story_pdf
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

ReportLang = Literal["ar", "en"]

_QA_LABELS: dict[ReportLang, dict[str, str]] = {
    "ar": {
        "title": "تقرير مراجعة وضبط الجودة المستقل (QA Agent)",
        "project": "المشروع",
        "status": "الحالة",
        "classification": "التصنيف",
        "open_issues": "ملاحظات مفتوحة",
        "opened_issues": "ملاحظات مسجلة في هذه المراجعة",
        "date": "تاريخ الإصدار",
        "tokens": "التوكنات المستخدمة",
        "disclaimer": "ملاحظة: مخرج مراجعة ضبط الجودة حتمي بـ 0 توكن؛ ويبقى المستند أولياً لحين المراجعة والاعتماد من مهندس مرخص.",
        "sec_isolation": "١. إثبات عزل سياق المراجعة المستقلة",
        "sec_checks": "٢. ملخص فحوصات الجودة الحتمية",
        "sec_issues": "٣. سجل الملاحظات والتوصيات التصحيحية",
        "col_check": "فئة الفحص",
        "col_passed": "نجاح",
        "col_failed": "فشل / تنبيه",
        "col_notes": "التفاصيل",
        "col_num": "الرقم",
        "col_sev": "الأهمية",
        "col_title": "العنوان",
        "col_state": "الحالة",
        "col_action": "الإجراء التصحيحي",
        "no_issues": "لا توجد ملاحظات مسجلة في هذه المراجعة.",
        "excluded_lbl": "حقول المنتج المستبعدة من سياق QA:",
    },
    "en": {
        "title": "Independent QA Review & Issue Register Report",
        "project": "Project",
        "status": "Verdict",
        "classification": "Classification",
        "open_issues": "Open Issues",
        "opened_issues": "Issues Opened in Review",
        "date": "Issued Date",
        "tokens": "AI Tokens Used",
        "disclaimer": "Advisory Notice: Deterministic 0-token QA verification report; outputs remain PRELIMINARY until licensed engineer review.",
        "sec_isolation": "1. Context Isolation Proof (Producer Reasoning Excluded)",
        "sec_checks": "2. Deterministic QA Check Summary",
        "sec_issues": "3. Issue Register & Corrective Actions",
        "col_check": "Check Category",
        "col_passed": "Passed",
        "col_failed": "Failed / Flagged",
        "col_notes": "Notes",
        "col_num": "Issue #",
        "col_sev": "Severity",
        "col_title": "Title",
        "col_state": "Status",
        "col_action": "Corrective Action",
        "no_issues": "No issues were opened during this QA review.",
        "excluded_lbl": "Producer fields excluded from QA context:",
    },
}


@dataclass(frozen=True)
class QaReportRenderData:
    """Normalized immutable payload for branded QA review DOCX and PDF exports."""

    review_id: str
    project_code: str
    project_name: str
    classification: str
    review_status: str
    open_issues_count: int
    issues_opened_count: int
    tokens_used: int
    language: ReportLang
    version: int
    issued_at_iso: str
    context_summary: QaContextIsolationReport
    checks: list[QaCheckMetricOut]
    issues: list[IssueOut]


def file_sha256_and_size(path: Path) -> tuple[str, int]:
    """Compute SHA-256 hex digest and byte size of a generated export file."""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def generate_qa_report_docx(out_path: Path, data: QaReportRenderData) -> None:
    """Render branded Arabic RTL / English LTR DOCX QA review report."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing QA DOCX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _QA_LABELS[data.language]
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

    apply_docx_branding(
        doc,
        language=data.language,
        classification=data.classification,
        document_title=lbl["title"],
    )

    h = doc.add_heading(f"{lbl['title']} — v{data.version} [{data.classification}]", level=1)
    _style_paragraph(h, is_ar=is_ar, bold=True, font_size=14, color=RGBColor(0x5A, 0x3A, 0x1A))

    meta_line = (
        f"{lbl['project']}: [{data.project_code}] {data.project_name} | "
        f"{lbl['status']}: {data.review_status} | "
        f"{lbl['open_issues']}: {data.open_issues_count} / {data.issues_opened_count} | "
        f"{lbl['tokens']}: {data.tokens_used} | "
        f"{lbl['date']}: {data.issued_at_iso}"
    )
    _style_paragraph(doc.add_paragraph(meta_line), is_ar=is_ar, font_size=9, color=RGBColor(0x43, 0x2A, 0x12))
    _style_paragraph(doc.add_paragraph(lbl["disclaimer"]), is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0x9A, 0x34, 0x12))

    # 1. Context isolation
    _style_paragraph(doc.add_heading(lbl["sec_isolation"], level=2), is_ar=is_ar, bold=True, font_size=11.5, color=RGBColor(0x5A, 0x3A, 0x1A))
    iso_txt = (
        f"producer_reasoning_excluded={data.context_summary.producer_reasoning_excluded} | "
        f"{lbl['excluded_lbl']} {', '.join(data.context_summary.excluded_fields)}"
    )
    _style_paragraph(doc.add_paragraph(iso_txt), is_ar=is_ar, font_size=9)

    # 2. Check metrics table
    _style_paragraph(doc.add_heading(lbl["sec_checks"], level=2), is_ar=is_ar, bold=True, font_size=11.5, color=RGBColor(0x5A, 0x3A, 0x1A))
    t_chk = doc.add_table(rows=1, cols=4)
    _configure_rtl_table(t_chk, is_ar=is_ar)
    for idx, head_txt in enumerate((lbl["col_check"], lbl["col_passed"], lbl["col_failed"], lbl["col_notes"])):
        c = t_chk.rows[0].cells[idx]
        c.text = head_txt
        _shade_cell(c, "5A3A1A")
        _style_paragraph(c.paragraphs[0], is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0xFF, 0xFF, 0xFF))
    for chk in data.checks:
        rc = t_chk.add_row().cells
        vals = [chk.category, str(chk.checked_count), str(chk.failed_count), chk.details or "—"]
        for i, v in enumerate(vals):
            rc[i].text = v
            _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, font_size=9)

    # 3. Issues table
    _style_paragraph(doc.add_heading(lbl["sec_issues"], level=2), is_ar=is_ar, bold=True, font_size=11.5, color=RGBColor(0x5A, 0x3A, 0x1A))
    if not data.issues:
        _style_paragraph(doc.add_paragraph(lbl["no_issues"]), is_ar=is_ar, font_size=9.5, color=RGBColor(0x16, 0x65, 0x34))
    else:
        t_iss = doc.add_table(rows=1, cols=5)
        _configure_rtl_table(t_iss, is_ar=is_ar)
        for idx, head_txt in enumerate((lbl["col_num"], lbl["col_sev"], lbl["col_state"], lbl["col_title"], lbl["col_action"])):
            c = t_iss.rows[0].cells[idx]
            c.text = head_txt
            _shade_cell(c, "5A3A1A")
            _style_paragraph(c.paragraphs[0], is_ar=is_ar, bold=True, font_size=8.5, color=RGBColor(0xFF, 0xFF, 0xFF))
        for iss in data.issues:
            rc = t_iss.add_row().cells
            vals = [
                iss.issue_number,
                str(iss.severity),
                str(iss.status),
                iss.title or iss.description[:80],
                iss.corrective_action or iss.recommended_action or "—",
            ]
            for i, v in enumerate(vals):
                rc[i].text = v
                _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, font_size=8.5)

    doc.save(str(out_path))


def generate_qa_report_pdf(out_path: Path, data: QaReportRenderData) -> None:
    """Render branded Arabic RTL / English LTR vector PDF QA review report."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing QA PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _QA_LABELS[data.language]
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    font_face = (
        "@font-face { font-family: 'QaFont'; src: url('tahoma.ttf'); font-weight: normal; }"
        + ("@font-face { font-family: 'QaFont'; src: url('tahomabd.ttf'); font-weight: bold; }" if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file() else "")
        if has_win_tahoma
        else ""
    )
    font_stack = "'QaFont', Tahoma, sans-serif" if has_win_tahoma else "sans-serif"

    chk_rows = "".join(
        f"<tr><td>{_esc_rtl_cell(c.category, is_ar=is_ar)}</td>"
        f"<td>{_esc_ltr(c.checked_count)}</td><td>{_esc_ltr(c.failed_count)}</td>"
        f"<td>{_esc_rtl_cell(c.details or '—', is_ar=is_ar)}</td></tr>"
        for c in data.checks
    )

    if not data.issues:
        issues_html = f"<p style='color:#166534;font-weight:bold;'>{_esc(lbl['no_issues'])}</p>"
    else:
        iss_rows = "".join(
            f"<tr><td>{_esc_ltr(i.issue_number)}</td><td>{_esc_ltr(i.severity)}</td>"
            f"<td>{_esc_ltr(i.status)}</td><td>{_esc_rtl_cell(i.title or i.description[:80], is_ar=is_ar)}</td>"
            f"<td>{_esc_rtl_cell(i.corrective_action or i.recommended_action or '—', is_ar=is_ar)}</td></tr>"
            for i in data.issues
        )
        issues_html = (
            f"<table><thead><tr>"
            f"<th>{_esc(lbl['col_num'])}</th><th>{_esc(lbl['col_sev'])}</th><th>{_esc(lbl['col_state'])}</th>"
            f"<th>{_esc(lbl['col_title'])}</th><th>{_esc(lbl['col_action'])}</th>"
            f"</tr></thead><tbody>{iss_rows}</tbody></table>"
        )

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{data.language}">
<head>
<meta charset="utf-8"/>
<style>
{font_face}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 9pt; color: #2C1D0D; margin: 0; }}
.banner {{ border: 1pt solid #E2D6BE; border-bottom: 2pt solid #E0AE1B; background-color: #FAF7F0; padding: 7pt; margin-bottom: 10pt; }}
h1 {{ color: #5A3A1A; font-size: 13pt; margin: 0 0 4pt 0; }}
h2 {{ color: #5A3A1A; font-size: 10.5pt; margin: 10pt 0 4pt 0; border-bottom: 0.8pt solid #E2D6BE; padding-bottom: 2pt; }}
.meta {{ font-size: 8.5pt; color: #6E5841; }}
.disclaimer {{ color: #9A3412; font-weight: bold; font-size: 8.2pt; margin-top: 4pt; }}
table {{ width: 100%; border-collapse: collapse; margin: 4pt 0 8pt 0; font-size: 8.2pt; }}
th {{ background-color: #5A3A1A; color: #FFFFFF; padding: 4pt; border: 0.5pt solid #5A3A1A; text-align: {align}; }}
td {{ padding: 4pt; border: 0.5pt solid #E2D6BE; text-align: {align}; vertical-align: top; }}
tr:nth-child(even) td {{ background-color: #FAF7F0; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(lbl['title'])} — v{data.version} [{_esc(data.classification)}]</h1>
    <div class="meta">
      {_esc(lbl['project'])}: [{_esc_ltr(data.project_code)}] {_esc_rtl_cell(data.project_name, is_ar=is_ar)} |
      {_esc(lbl['status'])}: {_esc_ltr(data.review_status)} |
      {_esc(lbl['open_issues'])}: {_esc_ltr(data.open_issues_count)} / {_esc_ltr(data.issues_opened_count)} |
      {_esc(lbl['tokens'])}: {_esc_ltr(data.tokens_used)} |
      {_esc(lbl['date'])}: {_esc_ltr(data.issued_at_iso)}
    </div>
    <div class="disclaimer">{_esc(lbl['disclaimer'])}</div>
  </div>
  <h2>{_esc(lbl['sec_isolation'])}</h2>
  <p>producer_reasoning_excluded={_esc_ltr(data.context_summary.producer_reasoning_excluded)} — {_esc(lbl['excluded_lbl'])} {_esc_ltr(', '.join(data.context_summary.excluded_fields))}</p>
  <h2>{_esc(lbl['sec_checks'])}</h2>
  <table><thead><tr><th>{_esc(lbl['col_check'])}</th><th>{_esc(lbl['col_passed'])}</th><th>{_esc(lbl['col_failed'])}</th><th>{_esc(lbl['col_notes'])}</th></tr></thead><tbody>{chk_rows}</tbody></table>
  <h2>{_esc(lbl['sec_issues'])}</h2>
  {issues_html}
</body>
</html>"""

    write_branded_story_pdf(
        out_path,
        html_doc=html_doc,
        fonts_dir=_WINDOWS_FONTS_DIR,
        page_size="a4",
        landscape=False,
        classification=data.classification,
        language=data.language,
        side_margin=32.0,
        top_margin=62.0,
        bottom_margin=42.0,
        max_pages=80,
    )


def utc_issued_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
