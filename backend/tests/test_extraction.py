"""Tests for Step 06 deterministic extraction across PDF, DOCX, XLSX, CSV, PPTX, images, and OCR."""

from io import BytesIO
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
import openpyxl
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
import pymupdf
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AuditLog, FileExtraction
from app.main import create_app
from app.services.extraction import extract_project_file
from app.services.extractors.ocr import (
    TESSERACT_NOT_INSTALLED_STATUS,
    _resolve_tesseract_executable,
    detect_tesseract,
)


def _test_settings(tmp_path: Path, *, tesseract_cmd: str = "") -> Settings:
    return Settings(
        workspaces_dir=tmp_path / "workspaces",
        database_url="",
        tesseract_cmd=tesseract_cmd,
    )


def _create_project(client: TestClient) -> tuple[str, str]:
    res = client.post(
        "/api/projects",
        json={"name": "مشروع مستشفى بنغازي", "code": "EXT-06"},
    )
    assert res.status_code == 201
    data = res.json()
    return data["id"], data["workspace_slug"]


def _upload_file(
    client: TestClient,
    project_id: str,
    filename: str,
    content: bytes,
    mime_type: str = "application/octet-stream",
) -> dict:
    res = client.post(
        f"/api/projects/{project_id}/files",
        files=[("files", (filename, content, mime_type))],
    )
    assert res.status_code == 201, res.text
    return res.json()["items"][0]["file"]


def _build_two_page_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Structural Beam Schedule - Span 6.00 m | f'c = 30.0 MPa", fontsize=11)
    # Draw crisp 2x3 vector grid so pdfplumber extracts exact rows & units
    shape = p1.new_shape()
    shape.draw_rect(pymupdf.Rect(70, 110, 460, 200))
    shape.draw_line((70, 140), (460, 140))
    shape.draw_line((70, 170), (460, 170))
    shape.draw_line((200, 110), (200, 200))
    shape.draw_line((330, 110), (330, 200))
    shape.finish(color=(0, 0, 0))
    shape.commit()
    for y, row in zip((130, 160, 190), [["ID", "Length", "Load"], ["B1", "6.00 m", "18.50 kN/m"], ["B2", "4.25 m", "12.00 kN/m"]]):
        for x, val in zip((80, 210, 340), row):
            p1.insert_text((x, y), val, fontsize=10)

    p2 = doc.new_page()
    p2.insert_text((72, 72), "Page 2 Notes: Column C1 design load = 1250.00 kN", fontsize=11)
    raw = doc.tobytes()
    doc.close()
    return raw


def _build_scanned_only_pdf_bytes() -> bytes:
    """Create a 1-page PDF containing only an embedded PNG raster (zero vector text)."""
    img = Image.new("RGB", (400, 120), color=(255, 255, 255))
    img_buf = BytesIO()
    img.save(img_buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=120)
    page.insert_image(pymupdf.Rect(0, 0, 400, 120), stream=img_buf.getvalue())
    raw = doc.tobytes()
    doc.close()
    return raw


def _build_docx_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("مشروع مستشفى طرابلس التعليمي — عرض الممر الأساسي 2.40 m")
    doc.add_paragraph("Concrete Grade: f'c = 35.0 MPa | Cover = 40 mm")
    table = doc.add_table(rows=3, cols=3)
    headers = ["البند", "الكمية", "الوحدة"]
    rows_data = [
        headers,
        ["B1 Beam", "6.00", "m"],
        ["Slab S1", "125.50", "m2"],
    ]
    for r_i, row_vals in enumerate(rows_data):
        for c_i, cell_val in enumerate(row_vals):
            table.cell(r_i, c_i).text = cell_val
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_xlsx_with_formulas_and_cached_values_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "BOQ"
    ws1.append(["Description", "Qty", "Rate", "Total"])
    ws1.append(["خرسانة مسلحة للأساسات", 12.5, 250, "=B2*C2"])
    ws1["B2"].number_format = '0.00" m3"'
    ws1.append(["Steel reinforcement", 2.75, 1800, "=B3*C3"])
    ws1["B3"].number_format = '0.00" ton"'
    ws1.append(["Grand Total", None, None, "=SUM(D2:D3)"])

    ws2 = wb.create_sheet("Summary")
    ws2.append(["Sheet", "Unit", "Status"])
    ws2.append(["BOQ", "m3 / ton", "Preliminary"])

    raw_buf = BytesIO()
    wb.save(raw_buf)
    wb.close()

    # Inject pre-computed cached <v> values into sheet1 XML for D2 & D3 (leaving D4 uncached to test both cases!)
    out_buf = BytesIO()
    with zipfile.ZipFile(BytesIO(raw_buf.getvalue()), "r") as zin, zipfile.ZipFile(
        out_buf, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                xml_str = data.decode("utf-8")
                xml_str = xml_str.replace(
                    "<f>B2*C2</f>", "<f>B2*C2</f><v>3125</v>"
                ).replace("<f>B3*C3</f>", "<f>B3*C3</f><v>4950</v>")
                data = xml_str.encode("utf-8")
            zout.writestr(info, data)
    return out_buf.getvalue()


def _build_pptx_bytes() -> bytes:
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "عرض هندسي: Tripoli Tower"
    s1.placeholders[1].text = "Clear height = 4.20 m | Chilled water delta-T = 5.5 C"

    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Equipment Schedule"
    tbl = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(5), Inches(1.5)).table
    tbl.cell(0, 0).text = "Tag"
    tbl.cell(0, 1).text = "Capacity"
    tbl.cell(1, 0).text = "AHU-01"
    tbl.cell(1, 1).text = "15.50 L/s"
    s2.notes_slide.notes_text_frame.text = "Verify rooftop curb opening 1200x800 mm"

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_extract_pdf_text_tables_page_images_and_preserve_units(tmp_path: Path) -> None:
    """Multi-page PDF extraction captures exact counts, vector tables, rendered PNGs, and leaves original untouched."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    pdf_bytes = _build_two_page_pdf_bytes()

    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        uploaded = _upload_file(client, project_id, "beam_schedule.pdf", pdf_bytes, "application/pdf")
        file_id = uploaded["id"]
        orig_sha = uploaded["sha256"]

        res = client.post(f"/api/files/{file_id}/extract")
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["source_file"] == "beam_schedule.pdf"
        assert data["status"] == "extracted"
        assert data["ocr_status"] == "not_needed"
        assert data["classification"] == "Preliminary"
        assert data["sha256_before"] == orig_sha
        assert data["sha256_after"] == orig_sha
        assert data["original_unchanged"] is True

        # Exact verified manual counts: 2 pages, 2 PNGs, 2 native body text items, 1 vector table -> 3 items total
        assert data["counts"] == {
            "pages": 2,
            "sheets": 0,
            "slides": 0,
            "tables": 1,
            "formulas": 0,
            "text_items": 2,
            "ocr_items": 0,
            "rendered_page_images": 2,
            "total_items": 3,
        }
        assert len(data["rendered_page_images"]) == 2
        assert all(item["source_file"] == "beam_schedule.pdf" for item in data["items"])
        assert {item["page_or_sheet"] for item in data["items"]} == {"page:1", "page:2"}

        table_item = next(item for item in data["items"] if item["item_type"] == "table")
        assert table_item["page_or_sheet"] == "page:1"
        assert table_item["location"] == "table:1"
        assert table_item["raw_values"] == [
            ["ID", "Length", "Load"],
            ["B1", "6.00 m", "18.50 kN/m"],
            ["B2", "4.25 m", "12.00 kN/m"],
        ]

        text_p2 = next(
            item for item in data["items"] if item["page_or_sheet"] == "page:2" and item["item_type"] == "text"
        )
        assert "1250.00 kN" in text_p2["text"]

        # Rendered PNG is served safely and extraction artifact JSON exists in 03_Analysis
        png_res = client.get(f"/api/extractions/{data['id']}/pages/1")
        assert png_res.status_code == 200
        assert png_res.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.get(f"/api/extractions/{data['id']}/pages/99").status_code == 404

        orig_disk_path = settings.workspaces_dir / workspace_slug / uploaded["stored_relative_path"]
        assert not (orig_disk_path.stat().st_mode & stat.S_IWRITE)


def test_extract_scanned_pdf_and_image_ocr_fallback_plus_absent_tesseract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detect missing Tesseract cleanly ('not installed - pending owner') and verify ara+eng OCR fallback."""
    # 1. Force hermetic absent-Tesseract state regardless of host OS installation
    monkeypatch.setattr(
        "app.services.extractors.ocr._DEFAULT_WINDOWS_TESSERACT_PATHS",
        (),
    )
    monkeypatch.setattr(
        "app.services.extractors.ocr.shutil.which",
        lambda *_args, **_kwargs: None,
    )

    cap_missing = detect_tesseract("")
    assert cap_missing.installed is False
    assert cap_missing.status == TESSERACT_NOT_INSTALLED_STATUS
    assert "not installed - pending owner" in cap_missing.message

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    scanned_pdf = _build_scanned_only_pdf_bytes()

    png_buf = BytesIO()
    Image.new("RGB", (320, 160), color=(30, 80, 180)).save(png_buf, format="PNG")
    png_bytes = png_buf.getvalue()

    with TestClient(app) as client:
        cap_res = client.get("/api/extraction/capabilities")
        assert cap_res.status_code == 200
        cap_json = cap_res.json()
        assert cap_json["ocr"]["status"] == "not installed - pending owner"

        project_id, _ = _create_project(client)
        scan_file = _upload_file(client, project_id, "scanned_sheet.pdf", scanned_pdf, "application/pdf")
        img_file = _upload_file(client, project_id, "detail_scan.png", png_bytes, "image/png")

        # Without Tesseract installed, API reports 'partial_ocr_unavailable' cleanly (never fails 500)
        res_scan_no_ocr = client.post(f"/api/files/{scan_file['id']}/extract")
        assert res_scan_no_ocr.status_code == 201
        d_no_ocr = res_scan_no_ocr.json()
        assert d_no_ocr["status"] == "partial_ocr_unavailable"
        assert d_no_ocr["ocr_status"] == "not installed - pending owner"
        assert d_no_ocr["counts"]["rendered_page_images"] == 1
        assert any("not installed - pending owner" in w for w in d_no_ocr["warnings"])

        res_img_no_ocr = client.post(f"/api/files/{img_file['id']}/extract")
        assert res_img_no_ocr.status_code == 201
        d_img = res_img_no_ocr.json()
        assert d_img["status"] == "partial_ocr_unavailable"
        assert d_img["ocr_status"] == "not installed - pending owner"
        assert "width=320px, height=160px" in d_img["items"][0]["text"]

    # 2. Arabic + English OCR fallback checked via injected ara+eng OCR callback cleanly
    seen_langs: list[str] = []

    def fake_ara_eng_ocr(_img_bytes: bytes, lang: str) -> str:
        seen_langs.append(lang)
        return "مراجعة العمود C1 — الحمل التصميمي 1250.00 kN | Beam B2 = 6.00 m"

    with app.state.session_factory() as db:
        ocr_pdf_res = extract_project_file(
            db, settings, scan_file["id"], ocr_runner=fake_ara_eng_ocr
        )
        assert ocr_pdf_res.status == "extracted"
        assert ocr_pdf_res.ocr_status == "ocr_applied"
        assert ocr_pdf_res.counts.ocr_items == 1
        assert seen_langs[-1] == "ara+eng"
        assert "مراجعة العمود C1" in ocr_pdf_res.items[0].text
        assert "1250.00 kN" in ocr_pdf_res.items[0].text

        ocr_img_res = extract_project_file(
            db, settings, img_file["id"], ocr_runner=fake_ara_eng_ocr
        )
        assert ocr_img_res.status == "extracted"
        assert ocr_img_res.counts.ocr_items == 1
        assert "6.00 m" in ocr_img_res.items[1].text

    # 3. Also verify installed+ara+eng probe parser using mocked subprocess
    monkeypatch.setattr(
        "app.services.extractors.ocr._resolve_tesseract_executable",
        lambda _cmd="": "tesseract",
    )
    monkeypatch.setattr(
        "app.services.extractors.ocr.subprocess.run",
        lambda args, **_kw: SimpleNamespace(
            stdout="tesseract 5.4.0\n"
            if "--version" in args
            else "List of available languages in ...\nara\neng\n",
            stderr="",
        ),
    )
    cap_ok = detect_tesseract()
    assert cap_ok.installed is True
    assert cap_ok.status == "installed"
    assert cap_ok.ara_installed is True
    assert cap_ok.eng_installed is True


def test_extract_docx_xlsx_csv_pptx_preserving_exact_counts_formulas_and_arabic_units(
    tmp_path: Path,
) -> None:
    """DOCX, XLSX (formulas + cached values), CSV (UTF-8 + cp1256), and PPTX extract exact counts and values."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)

    docx_bytes = _build_docx_bytes()
    xlsx_bytes = _build_xlsx_with_formulas_and_cached_values_bytes()
    csv_utf8 = (
        "البند,Length,Area,Cost\r\n"
        "جسر خرساني B1,6.00 m,1.80 m2,1250.50\r\n"
        "عمود C2,3.50 m,0.005 m3,980.00\r\n"
    ).encode("utf-8-sig")
    csv_cp1256 = "الصنف,الكمية\nخرسانة عادية,14.50 m3\n".encode("cp1256")
    pptx_bytes = _build_pptx_bytes()

    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_docx = _upload_file(
            client,
            project_id,
            "spec_ar.docx",
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        f_xlsx = _upload_file(
            client,
            project_id,
            "boq_calc.xlsx",
            xlsx_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        f_csv1 = _upload_file(client, project_id, "items_utf8.csv", csv_utf8, "text/csv")
        f_csv2 = _upload_file(client, project_id, "items_cp1256.csv", csv_cp1256, "text/csv")
        f_pptx = _upload_file(
            client,
            project_id,
            "deck.pptx",
            pptx_bytes,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

        # 1. DOCX: 2 paragraphs + 1 table -> 3 items
        r_docx = client.post(f"/api/files/{f_docx['id']}/extract").json()
        assert r_docx["counts"]["text_items"] == 2
        assert r_docx["counts"]["tables"] == 1
        assert r_docx["counts"]["total_items"] == 3
        assert "2.40 m" in r_docx["items"][0]["text"]
        assert "35.0 MPa" in r_docx["items"][1]["text"]
        assert r_docx["items"][2]["raw_values"][2] == ["Slab S1", "125.50", "m2"]

        # 2. XLSX: 2 sheets, 2 sheet tables, 3 formulas (D2 cached=3125, D3 cached=4950, D4 uncached)
        r_xlsx = client.post(f"/api/files/{f_xlsx['id']}/extract").json()
        assert r_xlsx["counts"]["sheets"] == 2
        assert r_xlsx["counts"]["tables"] == 2
        assert r_xlsx["counts"]["formulas"] == 3
        assert r_xlsx["counts"]["total_items"] == 5
        boq_tbl = next(i for i in r_xlsx["items"] if i["page_or_sheet"] == "sheet:BOQ" and i["item_type"] == "table")
        assert boq_tbl["raw_values"][1][1] == "12.50"  # trailing zero preserved via 0.00" m3" format!
        f_items = {i["location"]: i for i in r_xlsx["items"] if i["item_type"] == "cell_formula"}
        assert f_items["cell:D2"]["formula"] == "=B2*C2"
        assert f_items["cell:D2"]["cached_value"] == "3125"
        assert f_items["cell:D3"]["formula"] == "=B3*C3"
        assert f_items["cell:D3"]["cached_value"] == "4950"
        assert f_items["cell:D4"]["formula"] == "=SUM(D2:D3)"
        assert f_items["cell:D4"]["cached_value"] is None
        assert any("no pre-computed cached value" in w for w in r_xlsx["warnings"])

        # 3. CSV UTF-8 & cp1256 exact string preservation
        r_csv1 = client.post(f"/api/files/{f_csv1['id']}/extract").json()
        assert r_csv1["counts"]["sheets"] == 1
        assert r_csv1["counts"]["tables"] == 1
        assert r_csv1["items"][0]["raw_values"][1] == ["جسر خرساني B1", "6.00 m", "1.80 m2", "1250.50"]
        assert r_csv1["items"][0]["raw_values"][2] == ["عمود C2", "3.50 m", "0.005 m3", "980.00"]

        r_csv2 = client.post(f"/api/files/{f_csv2['id']}/extract").json()
        assert r_csv2["items"][0]["raw_values"][1] == ["خرسانة عادية", "14.50 m3"]

        # 4. PPTX: 2 slides, 1 table, slide text frames + speaker notes
        r_pptx = client.post(f"/api/files/{f_pptx['id']}/extract").json()
        assert r_pptx["counts"]["slides"] == 2
        assert r_pptx["counts"]["tables"] == 1
        note_item = next(i for i in r_pptx["items"] if i["item_type"] == "slide_note")
        assert note_item["page_or_sheet"] == "slide:2"
        assert note_item["location"] == "notes"
        assert "1200x800 mm" in note_item["text"]

        # Re-extracting creates versioned r2 without overwriting r1; history returns newest first
        r_csv1_v2 = client.post(f"/api/files/{f_csv1['id']}/extract").json()
        assert r_csv1_v2["extraction_version"] == 2
        assert r_csv1_v2["artifact_relative_path"] != r_csv1["artifact_relative_path"]
        hist = client.get(f"/api/files/{f_csv1['id']}/extractions").json()
        assert hist["total"] == 2
        assert [item["extraction_version"] for item in hist["extractions"]] == [2, 1]


def test_extraction_rejects_cad_deferred_formats_and_logs_corrupt_file_failures(
    tmp_path: Path,
) -> None:
    """CAD/BIM formats clearly point to Step 07; corrupted PDF returns HTTP 422 and logs failure."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)

    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        dxf_file = _upload_file(client, project_id, "plan.dxf", b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", "application/dxf")
        corrupt_pdf = _upload_file(client, project_id, "broken.pdf", b"NOT-A-VALID-PDF-HEADER", "application/pdf")

        cad_res = client.post(f"/api/files/{dxf_file['id']}/extract")
        assert cad_res.status_code == 400
        assert "Step 07" in cad_res.json()["detail"]

        bad_res = client.post(f"/api/files/{corrupt_pdf['id']}/extract")
        assert bad_res.status_code == 422

        with app.state.session_factory() as db:
            failed_rows = db.scalars(
                select(FileExtraction).where(FileExtraction.file_id == corrupt_pdf["id"])
            ).all()
            assert len(failed_rows) == 1
            assert failed_rows[0].status == "failed"
            assert failed_rows[0].error_message is not None
            fail_audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.entity_type == "file_extraction",
                    AuditLog.entity_id == failed_rows[0].id,
                    AuditLog.action == "file.extraction_failed",
                )
            )
            assert fail_audit is not None

        assert client.get("/api/files/nonexistent-file/extractions").status_code == 404
        assert client.get("/api/extractions/nonexistent-ext").status_code == 404


def test_tesseract_resolution_priority_and_live_ara_eng_ocr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify configured -> PATH -> default folder priority and run real Tesseract 5.x ara+eng OCR."""
    custom_exe = tmp_path / "custom_tesseract.exe"
    custom_exe.write_bytes(b"stub")
    default_exe = tmp_path / "default_tesseract.exe"
    default_exe.write_bytes(b"stub")

    with monkeypatch.context() as m:
        m.setattr("app.services.extractors.ocr._DEFAULT_WINDOWS_TESSERACT_PATHS", (default_exe,))
        m.setattr("app.services.extractors.ocr.shutil.which", lambda _cmd: "path_tesseract.exe")
        # 1. Configured path takes highest precedence over PATH and default folder
        assert _resolve_tesseract_executable(str(custom_exe)) == str(custom_exe)
        # 2. Blank setting falls back to PATH before default folder
        assert _resolve_tesseract_executable("") == "path_tesseract.exe"
        # 3. Absent from PATH falls back to default install folder
        m.setattr("app.services.extractors.ocr.shutil.which", lambda _cmd: None)
        assert _resolve_tesseract_executable("") == str(default_exe)

    # Verify live installed Tesseract 5.5.3 (not on PATH, found in default Program Files folder)
    live_cap = detect_tesseract("")
    assert live_cap.installed is True
    assert live_cap.status == "installed"
    assert live_cap.ara_installed is True
    assert live_cap.eng_installed is True
    assert "ara" in live_cap.languages and "eng" in live_cap.languages

    # Build a sanitized Arabic + English raster image (250 DPI) and a scanned-only PDF wrapping it
    fonts_dir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    archive = pymupdf.Archive(str(fonts_dir))
    render_doc = pymupdf.open()
    render_page = render_doc.new_page(width=700, height=280)
    html = """
    <style>
    @font-face { font-family: WinTahoma; src: url("tahoma.ttf"); }
    body { font-family: WinTahoma; font-size: 26px; padding: 20px; }
    </style>
    <body>
      <div dir="ltr">Beam Span = 6.00 m | Load = 18.50 kN/m</div>
      <div dir="rtl" lang="ar" style="margin-top: 20px;">مشروع مستشفى طرابلس التعليمي</div>
    </body>
    """
    render_page.insert_htmlbox(pymupdf.Rect(10, 10, 690, 270), html, archive=archive)
    png_bytes = render_page.get_pixmap(dpi=250).tobytes("png")
    render_doc.close()

    scanned_doc = pymupdf.open()
    scanned_page = scanned_doc.new_page(width=700, height=280)
    scanned_page.insert_image(pymupdf.Rect(0, 0, 700, 280), stream=png_bytes)
    scanned_pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()

    app = create_app(_test_settings(tmp_path))
    with TestClient(app) as client:
        caps = client.get("/api/extraction/capabilities").json()
        assert caps["ocr"]["status"] == "installed"
        assert caps["ocr"]["ara_installed"] is True
        assert caps["ocr"]["eng_installed"] is True

        project_id, _ = _create_project(client)
        f_png = _upload_file(client, project_id, "sample_bilingual.png", png_bytes, "image/png")
        f_pdf = _upload_file(client, project_id, "sample_bilingual_scan.pdf", scanned_pdf_bytes, "application/pdf")

        res_png = client.post(f"/api/files/{f_png['id']}/extract")
        assert res_png.status_code == 201
        d_png = res_png.json()
        assert d_png["status"] == "extracted"
        assert d_png["ocr_status"] == "ocr_applied"
        assert d_png["original_unchanged"] is True
        assert d_png["counts"]["ocr_items"] == 1
        png_ocr = next(i["text"] for i in d_png["items"] if i["item_type"] == "ocr_text")
        assert "6.00" in png_ocr and "18.50" in png_ocr
        assert "مستشفى" in png_ocr and "طرابلس" in png_ocr

        res_pdf = client.post(f"/api/files/{f_pdf['id']}/extract")
        assert res_pdf.status_code == 201
        d_pdf = res_pdf.json()
        assert d_pdf["status"] == "extracted"
        assert d_pdf["ocr_status"] == "ocr_applied"
        assert d_pdf["original_unchanged"] is True
        assert d_pdf["counts"]["ocr_items"] == 1
        pdf_ocr = next(i["text"] for i in d_pdf["items"] if i["item_type"] == "ocr_text")
        assert "6.00" in pdf_ocr and "18.50" in pdf_ocr
        assert "مستشفى" in pdf_ocr and "طرابلس" in pdf_ocr
