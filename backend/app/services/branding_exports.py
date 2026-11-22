"""Shared corporate branding helpers for DOCX, PDF, XLSX, and CAD exports."""

from __future__ import annotations

import html
from io import BytesIO
from pathlib import Path
from typing import Any

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
import pymupdf

from app.core.branding import (
    BACKEND_LOGO_PATH,
    COMPANY_BILINGUAL_LINE,
    COMPANY_FULL_AR,
    COMPANY_FULL_EN,
    DEFAULT_CLASSIFICATION,
    build_classification_footer,
)

_WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")

# DOCX & XLSX RGB/Hex corporate tokens
BROWN_RGB = RGBColor(0x5A, 0x3A, 0x1A)
GOLD_DARK_RGB = RGBColor(0x8C, 0x65, 0x10)
MUTED_RGB = RGBColor(0x6E, 0x58, 0x41)

BROWN_HEX = "5A3A1A"
GOLD_HEX = "E0AE1B"
CREAM_HEX = "FAF7F0"
WARM_SURFACE_HEX = "F4EFE4"
TEXT_DARK_HEX = "2C1D0D"

# PyMuPDF normalized 0..1 colors
_PDF_BROWN = (0x5A / 255.0, 0x3A / 255.0, 0x1A / 255.0)
_PDF_GOLD = (0xE0 / 255.0, 0xAE / 255.0, 0x1B / 255.0)
_PDF_CREAM = (0xFA / 255.0, 0xF7 / 255.0, 0xF0 / 255.0)


def _set_xml_tag(parent: Any, tag_name: str, attrs: dict[str, str] | None = None) -> Any:
    el = parent.find(qn(tag_name))
    if el is None:
        el = OxmlElement(tag_name)
        parent.append(el)
    if attrs:
        for k, v in attrs.items():
            el.set(qn(k), v)
    return el


def _style_run_bilingual(
    run: Any,
    *,
    is_ar: bool,
    bold: bool = False,
    font_size: float = 9.0,
    color: RGBColor = BROWN_RGB,
) -> None:
    run.bold = bold
    run.font.size = Pt(font_size)
    run.font.color.rgb = color
    run.font.name = "Tahoma" if is_ar else "Calibri"
    r_pr = run._r.get_or_add_rPr()
    _set_xml_tag(
        r_pr,
        "w:rFonts",
        {
            "w:ascii": "Tahoma" if is_ar else "Calibri",
            "w:hAnsi": "Tahoma" if is_ar else "Calibri",
            "w:cs": "Tahoma",
        },
    )
    if is_ar:
        _set_xml_tag(r_pr, "w:rtl")


def _style_para(
    paragraph: Any,
    *,
    is_ar: bool,
    align_override: WD_ALIGN_PARAGRAPH | None = None,
) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    if is_ar:
        _set_xml_tag(p_pr, "w:bidi")
        paragraph.alignment = align_override or WD_ALIGN_PARAGRAPH.RIGHT
    else:
        paragraph.alignment = align_override or WD_ALIGN_PARAGRAPH.LEFT


def _set_cell_borders_header(cell: Any, *, bottom_color: str = GOLD_HEX, bottom_sz: str = "12") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = _set_xml_tag(tc_pr, "w:tcBorders")
    for side in ("top", "left", "right", "insideH", "insideV"):
        _set_xml_tag(borders, f"w:{side}", {"w:val": "none"})
    _set_xml_tag(
        borders,
        "w:bottom",
        {"w:val": "single", "w:sz": bottom_sz, "w:space": "0", "w:color": bottom_color},
    )
    _set_xml_tag(tc_pr, "w:shd", {"w:val": "clear", "w:color": "auto", "w:fill": CREAM_HEX})


def apply_docx_branding(
    doc: Any,
    *,
    language: str = "ar",
    classification: str = DEFAULT_CLASSIFICATION,
    document_title: str = "",
) -> None:
    """Attach the ALHARAM ALDAHABY / الهرم الذهبي header (logo + bilingual name) and classification footer to DOCX."""
    if not doc.sections:
        return
    is_ar = language == "ar"
    footer_text = build_classification_footer(classification, language)
    logo_str = str(BACKEND_LOGO_PATH) if BACKEND_LOGO_PATH.is_file() else ""

    for section in doc.sections:
        section.header_distance = Inches(0.22)
        section.footer_distance = Inches(0.22)
        if section.top_margin is None or section.top_margin < Inches(0.85):
            section.top_margin = Inches(0.85)
        if section.bottom_margin is None or section.bottom_margin < Inches(0.75):
            section.bottom_margin = Inches(0.75)

        page_w_in = float(section.page_width.inches) if section.page_width else 8.27
        left_in = float(section.left_margin.inches) if section.left_margin else 0.6
        right_in = float(section.right_margin.inches) if section.right_margin else 0.6
        usable_in = max(5.2, page_w_in - left_in - right_in)

        # Header table: cell 0 = start side (logo -> RIGHT in RTL, LEFT in LTR); cell 1 = company identity
        header = section.header
        header.is_linked_to_previous = False
        for idx in range(len(header.paragraphs) - 1, 0, -1):
            p_el = header.paragraphs[idx]._p
            p_el.getparent().remove(p_el)
        if header.paragraphs:
            header.paragraphs[0].text = ""
            p_pr = header.paragraphs[0]._p.get_or_add_pPr()
            _set_xml_tag(p_pr, "w:spacing", {"w:before": "0", "w:after": "0"})

        hdr_tbl = header.add_table(rows=1, cols=2, width=Inches(usable_in))
        hdr_tbl.alignment = WD_TABLE_ALIGNMENT.RIGHT if is_ar else WD_TABLE_ALIGNMENT.LEFT
        tbl_pr = hdr_tbl._tbl.tblPr
        if is_ar and tbl_pr is not None:
            _set_xml_tag(tbl_pr, "w:bidiVisual")

        logo_col_w = Inches(min(2.05, usable_in * 0.34))
        text_col_w = Inches(max(3.0, usable_in - logo_col_w.inches))
        cell_logo = hdr_tbl.rows[0].cells[0]
        cell_text = hdr_tbl.rows[0].cells[1]
        cell_logo.width = logo_col_w
        cell_text.width = text_col_w
        _set_cell_borders_header(cell_logo)
        _set_cell_borders_header(cell_text)

        p_logo = cell_logo.paragraphs[0]
        p_logo.text = ""
        _style_para(p_logo, is_ar=is_ar, align_override=WD_ALIGN_PARAGRAPH.RIGHT if is_ar else WD_ALIGN_PARAGRAPH.LEFT)
        if logo_str:
            r_logo = p_logo.add_run()
            r_logo.add_picture(logo_str, width=Inches(1.72))

        p_name = cell_text.paragraphs[0]
        p_name.text = ""
        # Place company name on opposite side of logo cleanly
        _style_para(p_name, is_ar=is_ar, align_override=WD_ALIGN_PARAGRAPH.LEFT if is_ar else WD_ALIGN_PARAGRAPH.RIGHT)
        primary_title = COMPANY_FULL_AR if is_ar else COMPANY_FULL_EN
        secondary_title = COMPANY_FULL_EN if is_ar else COMPANY_FULL_AR

        r1 = p_name.add_run(primary_title)
        _style_run_bilingual(r1, is_ar=is_ar, bold=True, font_size=10.0, color=BROWN_RGB)
        r_br = p_name.add_run("\n" + secondary_title)
        _style_run_bilingual(r_br, is_ar=False, bold=False, font_size=8.5, color=GOLD_DARK_RGB)
        if document_title:
            r_doc = p_name.add_run(f"\n{document_title[:90]}")
            _style_run_bilingual(r_doc, is_ar=is_ar, bold=False, font_size=7.5, color=MUTED_RGB)

        # Footer band with gold top rule + classification text
        footer = section.footer
        footer.is_linked_to_previous = False
        for idx in range(len(footer.paragraphs) - 1, 0, -1):
            p_el = footer.paragraphs[idx]._p
            p_el.getparent().remove(p_el)
        p_foot = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        p_foot.text = ""
        _style_para(p_foot, is_ar=is_ar)
        fp_pr = p_foot._p.get_or_add_pPr()
        fp_bdr = _set_xml_tag(fp_pr, "w:pBdr")
        _set_xml_tag(fp_bdr, "w:top", {"w:val": "single", "w:sz": "8", "w:space": "4", "w:color": GOLD_HEX})
        r_foot = p_foot.add_run(footer_text)
        _style_run_bilingual(r_foot, is_ar=is_ar, bold=False, font_size=7.8, color=BROWN_RGB)


def _pdf_font_archive(fonts_dir: Path | None) -> tuple[pymupdf.Archive | None, str]:
    target = fonts_dir or _WINDOWS_FONTS_DIR
    tahoma = target / "tahoma.ttf"
    if tahoma.is_file():
        tahoma_bold = target / "tahomabd.ttf"
        bold_css = (
            "@font-face { font-family: 'BrandFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if tahoma_bold.is_file()
            else ""
        )
        css = (
            "@font-face { font-family: 'BrandFont'; src: url('tahoma.ttf'); font-weight: normal; } "
            + bold_css
        )
        return pymupdf.Archive(str(target)), css
    return None, ""


def stamp_pdf_branding(
    pdf_doc: pymupdf.Document,
    *,
    classification: str = DEFAULT_CLASSIFICATION,
    language: str = "ar",
    fonts_dir: Path | None = None,
    compact: bool = False,
) -> None:
    """Stamp corporate logo + bilingual header + classification footer on every page of a PyMuPDF Document."""
    total_pages = len(pdf_doc)
    if total_pages == 0:
        return

    is_ar = language == "ar"
    archive, font_css = _pdf_font_archive(fonts_dir)
    font_family = "'BrandFont', Tahoma, sans-serif" if font_css else "Tahoma, Arial, sans-serif"
    footer_msg = html.escape(build_classification_footer(classification, language))

    side_margin = 34.0 if compact else 28.0
    top_y0 = 6.0 if compact else 8.0
    header_h = 24.0 if compact else 42.0
    bottom_h = 20.0 if compact else 28.0
    logo_h = 18.0 if compact else 24.0
    logo_w = logo_h * (1193.0 / 210.0)

    logo_bytes = BACKEND_LOGO_PATH.read_bytes() if BACKEND_LOGO_PATH.is_file() else b""
    shared_logo_xref: int | None = None

    for idx, page in enumerate(pdf_doc, start=1):
        pw = float(page.rect.width)
        ph = float(page.rect.height)
        header_y1 = top_y0 + header_h

        # Header bar background + top brown hairline + bottom gold accent rule
        shape = page.new_shape()
        hdr_bg = pymupdf.Rect(side_margin, top_y0, pw - side_margin, header_y1)
        shape.draw_rect(hdr_bg)
        shape.finish(color=_PDF_BROWN, fill=_PDF_CREAM, width=0.5)
        shape.draw_line(pymupdf.Point(side_margin, header_y1), pymupdf.Point(pw - side_margin, header_y1))
        shape.finish(color=_PDF_GOLD, width=1.6)

        footer_y0 = ph - (bottom_h + 6.0)
        shape.draw_line(pymupdf.Point(side_margin, footer_y0), pymupdf.Point(pw - side_margin, footer_y0))
        shape.finish(color=_PDF_GOLD, width=1.0)
        shape.commit(overlay=True)

        # Logo placement on start edge: RIGHT for RTL Arabic, LEFT for LTR English
        logo_y0 = top_y0 + max(2.0, (header_h - logo_h) * 0.5)
        if is_ar:
            logo_rect = pymupdf.Rect(pw - side_margin - logo_w - 6.0, logo_y0, pw - side_margin - 6.0, logo_y0 + logo_h)
            text_rect = pymupdf.Rect(side_margin + 6.0, top_y0 + 2.0, logo_rect.x0 - 8.0, header_y1 - 2.0)
            text_align = "left"
            text_dir = "rtl"
        else:
            logo_rect = pymupdf.Rect(side_margin + 6.0, logo_y0, side_margin + 6.0 + logo_w, logo_y0 + logo_h)
            text_rect = pymupdf.Rect(logo_rect.x1 + 8.0, top_y0 + 2.0, pw - side_margin - 6.0, header_y1 - 2.0)
            text_align = "right"
            text_dir = "ltr"

        if logo_bytes:
            if shared_logo_xref is None:
                shared_logo_xref = int(page.insert_image(logo_rect, stream=logo_bytes, keep_proportion=True, overlay=True))
            else:
                page.insert_image(logo_rect, xref=shared_logo_xref, keep_proportion=True, overlay=True)

        if compact:
            hdr_html = (
                f'<div dir="{text_dir}" style="font-family:{font_family};text-align:{text_align};'
                f'font-size:6.8pt;line-height:1.15;color:#5A3A1A;">'
                f'<strong>{html.escape(COMPANY_FULL_EN)}</strong> &nbsp;|&nbsp; '
                f'<strong dir="rtl">{html.escape(COMPANY_FULL_AR)}</strong>'
                f'</div>'
            )
        else:
            primary_name = html.escape(COMPANY_FULL_AR if is_ar else COMPANY_FULL_EN)
            secondary_name = html.escape(COMPANY_FULL_EN if is_ar else COMPANY_FULL_AR)
            hdr_html = (
                f'<div dir="{text_dir}" style="font-family:{font_family};text-align:{text_align};'
                f'line-height:1.25;">'
                f'<div style="font-size:8.6pt;font-weight:bold;color:#5A3A1A;">{primary_name}</div>'
                f'<div style="font-size:7.3pt;font-weight:bold;color:#8C6510;">{secondary_name}</div>'
                f'</div>'
            )

        page.insert_htmlbox(text_rect, hdr_html, css=font_css, archive=archive, overlay=True)

        page_label = (
            f"صفحة {idx} من {total_pages}"
            if is_ar
            else f"Page {idx} of {total_pages}"
        )
        foot_rect = pymupdf.Rect(side_margin + 2.0, footer_y0 + 3.0, pw - side_margin - 2.0, ph - 4.0)
        foot_font_sz = "6.2pt" if compact else "7.0pt"
        foot_html = (
            f'<div dir="{"rtl" if is_ar else "ltr"}" style="font-family:{font_family};'
            f'font-size:{foot_font_sz};color:#5A3A1A;line-height:1.2;">'
            f'<table style="width:100%;border-collapse:collapse;border:none;"><tr>'
            f'<td style="border:none;padding:0;text-align:{"right" if is_ar else "left"};width:82%;">{footer_msg}</td>'
            f'<td style="border:none;padding:0;text-align:{"left" if is_ar else "right"};width:18%;font-weight:bold;color:#8C6510;">'
            f'{html.escape(page_label)}</td>'
            f'</tr></table></div>'
        )
        page.insert_htmlbox(foot_rect, foot_html, css=font_css, archive=archive, overlay=True)


def write_branded_story_pdf(
    out_path: Path,
    *,
    html_doc: str,
    fonts_dir: Path | None = None,
    page_size: str = "a4",
    landscape: bool = False,
    classification: str = DEFAULT_CLASSIFICATION,
    language: str = "ar",
    side_margin: float = 28.0,
    top_margin: float = 60.0,
    bottom_margin: float = 42.0,
    max_pages: int = 150,
) -> None:
    """Render a PyMuPDF Story HTML payload, stamp company header + footer across every page, and save to disk."""
    archive, _ = _pdf_font_archive(fonts_dir)
    story = pymupdf.Story(html=html_doc, archive=archive)
    buf = BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.Rect(0, 0, 842, 595) if landscape else pymupdf.paper_rect(page_size)
    where = mediabox + (side_margin, top_margin, -side_margin, -bottom_margin)
    try:
        more = True
        page_guard = 0
        while more and page_guard < max_pages:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            page_guard += 1
    finally:
        writer.close()

    pdf_doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    try:
        stamp_pdf_branding(
            pdf_doc,
            classification=classification,
            language=language,
            fonts_dir=fonts_dir,
            compact=False,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_doc.save(str(out_path), deflate=True)
    finally:
        pdf_doc.close()


def apply_xlsx_branding(
    wb: Any,
    *,
    document_title: str,
    project_code: str,
    project_name: str,
    classification: str = DEFAULT_CLASSIFICATION,
    language: str = "ar",
) -> None:
    """Apply corporate branding across all worksheets without shifting existing row indices or sheet counts."""
    is_ar = language == "ar"
    footer_line = build_classification_footer(classification, language)
    logo_ok = BACKEND_LOGO_PATH.is_file()

    brand_font = Font(name="Tahoma" if is_ar else "Calibri", size=9, bold=True, color=BROWN_HEX)
    footer_font = Font(name="Tahoma" if is_ar else "Calibri", size=9, bold=True, color=BROWN_HEX)
    cream_fill = PatternFill(start_color=CREAM_HEX, end_color=CREAM_HEX, fill_type="solid")
    align_side = Alignment(horizontal="right" if is_ar else "left", vertical="center")

    for ws in wb.worksheets:
        ws.oddHeader.left.text = f"[{project_code}] {project_name}"
        ws.oddHeader.center.text = COMPANY_BILINGUAL_LINE
        ws.oddHeader.right.text = document_title[:60]
        ws.oddFooter.center.text = footer_line

        anchor_col = max(ws.max_column + 1, 7)
        anchor_col_ltr = get_column_letter(anchor_col)
        ws.row_dimensions[1].height = max(float(ws.row_dimensions[1].height or 28.0), 44.0)
        ws.column_dimensions[anchor_col_ltr].width = max(float(ws.column_dimensions[anchor_col_ltr].width or 14.0), 36.0)

        if logo_ok:
            img = OpenpyxlImage(str(BACKEND_LOGO_PATH))
            img.height = 38
            img.width = round(38 * (1193.0 / 210.0))
            ws.add_image(img, f"{anchor_col_ltr}1")

        c_name = ws.cell(row=2, column=anchor_col)
        if c_name.value in (None, ""):
            c_name.value = COMPANY_BILINGUAL_LINE
            c_name.font = brand_font
            c_name.fill = cream_fill
            c_name.alignment = align_side

        # Append classification footer banner ONLY in column 1 at max_row + 2 so arithmetic QA loops safely skip it
        foot_row = ws.max_row + 2
        c_foot = ws.cell(row=foot_row, column=1, value=footer_line)
        c_foot.font = footer_font
        c_foot.fill = cream_fill
        c_foot.alignment = align_side
