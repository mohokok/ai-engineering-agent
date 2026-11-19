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


def _build_scanned_only_pdf_bytes(pages: int = 1) -> bytes:
    """Create a multi-page or single-page PDF containing only embedded PNG rasters (zero vector text)."""
    img = Image.new("RGB", (400, 120), color=(255, 255, 255))
    img_buf = BytesIO()
    img.save(img_buf, format="PNG")
    doc = pymupdf.open()
    for _ in range(pages):
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
    scanned_pdf = _build_scanned_only_pdf_bytes(pages=2)

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
        assert d_no_ocr["ocr_dpi"] is None
        assert d_no_ocr["counts"]["rendered_page_images"] == 2
        # OCR unavailable warning must be de-duplicated across multiple scanned pages
        assert len(d_no_ocr["warnings"]) == 1
        assert "not installed - pending owner" in d_no_ocr["warnings"][0]

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
        assert ocr_pdf_res.ocr_dpi == 300
        assert ocr_pdf_res.counts.ocr_items == 2
        assert seen_langs[-1] == "ara+eng"
        assert ocr_pdf_res.items[0].ocr_dpi == 300
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


def test_tesseract_resolution_priority_single_probe_and_300dpi_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify configured -> PATH -> default priority, single Tesseract probe per run, and separate 300 DPI OCR render."""
    custom_exe = tmp_path / "custom_tesseract.exe"
    custom_exe.write_bytes(b"stub")
    default_exe = tmp_path / "default_tesseract.exe"
    default_exe.write_bytes(b"stub")

    with monkeypatch.context() as m:
        m.setattr("app.services.extractors.ocr._DEFAULT_WINDOWS_TESSERACT_PATHS", (default_exe,))
        m.setattr("app.services.extractors.ocr.shutil.which", lambda _cmd: "path_tesseract.exe")
        assert _resolve_tesseract_executable(str(custom_exe)) == str(custom_exe)
        assert _resolve_tesseract_executable("") == "path_tesseract.exe"
        m.setattr("app.services.extractors.ocr.shutil.which", lambda _cmd: None)
        assert _resolve_tesseract_executable("") == str(default_exe)

    # Probe count check: a 3-page scanned PDF must probe Tesseract (--version/--list-langs) only ONCE per run
    subprocess_calls: list[list[str]] = []

    def counting_run(args: list[str], **_kw: object) -> SimpleNamespace:
        subprocess_calls.append(list(args))
        return SimpleNamespace(
            stdout="tesseract 5.5.3\n"
            if "--version" in args
            else "List of available languages in ...\nara\neng\n",
            stderr="",
        )

    monkeypatch.setattr(
        "app.services.extractors.ocr._resolve_tesseract_executable",
        lambda _cmd="": "fake-tesseract",
    )
    monkeypatch.setattr("app.services.extractors.ocr.subprocess.run", counting_run)

    ocr_sizes: list[tuple[int, int]] = []

    def fake_pytesseract_ocr(img: Image.Image, lang: str = "ara+eng") -> str:
        ocr_sizes.append(img.size)
        return "Beam Span = 6.00 m"

    monkeypatch.setattr(
        "app.services.extractors.ocr.pytesseract.image_to_string",
        fake_pytesseract_ocr,
    )

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    scanned_3p = _build_scanned_only_pdf_bytes(pages=3)
    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_scan = _upload_file(client, project_id, "three_page_scan.pdf", scanned_3p, "application/pdf")
        res = client.post(f"/api/files/{f_scan['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["ocr_dpi"] == 300
        assert data["counts"]["ocr_items"] == 3

        # 1 version call + 1 list-langs call = 2 subprocess calls total (NOT 3x per page!)
        version_calls = [c for c in subprocess_calls if "--version" in c]
        lang_calls = [c for c in subprocess_calls if "--list-langs" in c]
        assert len(version_calls) == 1
        assert len(lang_calls) == 1

        # Verify OCR received dedicated 300 DPI renders (~2x dimensions of 150 DPI preview PNGs, accounting for integer point rounding)
        preview_path = settings.workspaces_dir / workspace_slug / data["rendered_page_images"][0]
        with Image.open(preview_path) as prev_img:
            prev_w, prev_h = prev_img.size
        assert len(ocr_sizes) == 3
        for ocr_w, ocr_h in ocr_sizes:
            assert abs(ocr_w - prev_w * 2) <= 2
            assert abs(ocr_h - prev_h * 2) <= 2


_RUN_REAL_OCR = os.getenv("RUN_REAL_OCR", "").strip().lower() in {"1", "true", "yes"}
_REAL_CAP = detect_tesseract("")
_REAL_OCR_AVAILABLE = bool(_REAL_CAP.installed and _REAL_CAP.ara_installed and _REAL_CAP.eng_installed)


@pytest.mark.real_ocr
@pytest.mark.skipif(
    not (_RUN_REAL_OCR and _REAL_OCR_AVAILABLE),
    reason="Opt-in test: set RUN_REAL_OCR=1 with Tesseract ara+eng installed to execute live OCR",
)
def test_optin_real_tesseract_ara_eng_on_committed_fixture(tmp_path: Path) -> None:
    """Opt-in live Tesseract ara+eng OCR check against committed non-client Arabic+English sample image."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "bilingual_engineering_sample.png"
    assert fixture_path.is_file(), f"Missing committed fixture image: {fixture_path}"
    png_bytes = fixture_path.read_bytes()

    scanned_doc = pymupdf.open()
    scanned_page = scanned_doc.new_page(width=700, height=280)
    scanned_page.insert_image(pymupdf.Rect(0, 0, 700, 280), stream=png_bytes)
    scanned_pdf_bytes = scanned_doc.tobytes()
    scanned_doc.close()

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        caps = client.get("/api/extraction/capabilities").json()
        assert caps["ocr"]["installed"] is True
        assert caps["ocr"]["ara_installed"] is True
        assert caps["ocr"]["eng_installed"] is True

        project_id, _ = _create_project(client)
        f_png = _upload_file(client, project_id, "bilingual_engineering_sample.png", png_bytes, "image/png")
        f_pdf = _upload_file(client, project_id, "bilingual_engineering_scan.pdf", scanned_pdf_bytes, "application/pdf")

        res_png = client.post(f"/api/files/{f_png['id']}/extract")
        assert res_png.status_code == 201, res_png.text
        d_png = res_png.json()
        assert d_png["status"] == "extracted"
        assert d_png["ocr_status"] == "ocr_applied"
        assert d_png["original_unchanged"] is True
        png_ocr = next(i["text"] for i in d_png["items"] if i["item_type"] == "ocr_text")
        assert "Beam Span = 6.00 m" in png_ocr
        assert "18.50 kN/m" in png_ocr
        assert "مستشفى" in png_ocr and "طرابلس" in png_ocr

        res_pdf = client.post(f"/api/files/{f_pdf['id']}/extract")
        assert res_pdf.status_code == 201, res_pdf.text
        d_pdf = res_pdf.json()
        assert d_pdf["status"] == "extracted"
        assert d_pdf["ocr_status"] == "ocr_applied"
        assert d_pdf["ocr_dpi"] == 300
        assert d_pdf["original_unchanged"] is True
        pdf_ocr = next(i["text"] for i in d_pdf["items"] if i["item_type"] == "ocr_text")
        assert "Beam Span = 6.00 m" in pdf_ocr
        assert "18.50 kN/m" in pdf_ocr
        assert "مستشفى" in pdf_ocr and "طرابلس" in pdf_ocr
        print(f"\nREAL OCR VERSION: {caps['ocr']['version']} | LANGS: {caps['ocr']['languages']}")
        print(f"PNG OCR TEXT: {png_ocr!r}")
        print(f"PDF OCR TEXT (DPI={d_pdf['ocr_dpi']}): {pdf_ocr!r}")


def test_extract_csv_multiline_quoted_arabic_and_offset_traceability(tmp_path: Path) -> None:
    """CSV uses StringIO(newline=''), preserves quoted multiline Arabic+units cells, and records exact rows/start col."""
    csv_bytes = (
        "\r\n"
        ",,,,\r\n"
        ',,"  البند  ","Details & Units","Total "\r\n'
        ',,"جسر خرساني B1","Span = 6.00 m\nحمل 18.50 kN/m","1250.50"\r\n'
        ",,,,\r\n"
        ',,"عمود C2","f\'c = 30.0 MPa","980.00"\r\n'
    ).encode("utf-8-sig")

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_csv = _upload_file(client, project_id, "multiline_offset.csv", csv_bytes, "text/csv")
        res = client.post(f"/api/files/{f_csv['id']}/extract")
        assert res.status_code == 201, res.text
        tbl = res.json()["items"][0]

        assert tbl["start_row"] == 3
        assert tbl["start_column"] == 3
        assert tbl["start_column_letter"] == "C"
        assert tbl["row_numbers"] == [3, 4, 6]
        assert tbl["location"] == "range:C3:E6"
        assert tbl["raw_values"] == [
            ["البند", "Details & Units", "Total"],
            ["جسر خرساني B1", "Span = 6.00 m\nحمل 18.50 kN/m", "1250.50"],
            ["عمود C2", "f'c = 30.0 MPa", "980.00"],
        ]
        # Outer whitespace trimming recorded with raw_uncollapsed_values preserved beside it
        assert tbl["normalization_applied"] == "outer_whitespace_trimmed"
        assert tbl["raw_uncollapsed_values"][0] == ["  البند  ", "Details & Units", "Total "]


def test_extract_xlsx_reset_dimensions_offset_cells_chartsheet_and_hidden(tmp_path: Path) -> None:
    """XLSX calls reset_dimensions(), maps offset cells + blank rows accurately, handles hidden sheets and Chartsheet."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CalcGrid"
    # Data starts at C4..E7 with blank row 5
    ws["C4"] = "Item"
    ws["D4"] = "Length (m)"
    ws["E4"] = "Force (kN)"
    ws["C6"] = "جسر B1"
    ws["D6"] = 6.0
    ws["D6"].number_format = "0.00"
    ws["E6"] = 18.5
    ws["E6"].number_format = "0.00"
    ws["C7"] = "Total"
    ws["D7"] = None
    ws["E7"] = "=D6*E6"

    ws_hidden = wb.create_sheet("RatesHidden")
    ws_hidden.sheet_state = "hidden"
    ws_hidden["B2"] = "Unit Rate"
    ws_hidden["C2"] = 450.25

    wb.create_chartsheet("SummaryChart")

    raw_buf = BytesIO()
    wb.save(raw_buf)
    wb.close()

    # Corrupt worksheet dimension XML tag intentionally to A1:A1 to prove reset_dimensions() prevents truncation!
    patched_buf = BytesIO()
    with zipfile.ZipFile(BytesIO(raw_buf.getvalue()), "r") as zin, zipfile.ZipFile(
        patched_buf, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                xml_str = data.decode("utf-8")
                xml_str = xml_str.replace('<dimension ref="C4:E7"/>', '<dimension ref="A1:A1"/>')
                assert '<dimension ref="A1:A1"/>' in xml_str
                data = xml_str.encode("utf-8")
            zout.writestr(info, data)

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_xlsx = _upload_file(
            client,
            project_id,
            "offset_chart_hidden.xlsx",
            patched_buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        res = client.post(f"/api/files/{f_xlsx['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["status"] == "extracted"
        assert data["counts"]["sheets"] == 3
        assert data["counts"]["tables"] == 2
        assert any("chartsheet" in w.lower() for w in data["warnings"])
        assert any("sheet_state='hidden'" in w for w in data["warnings"])

        grid_tbl = next(i for i in data["items"] if i["page_or_sheet"] == "sheet:CalcGrid" and i["item_type"] == "table")
        assert grid_tbl["start_row"] == 4
        assert grid_tbl["start_column"] == 3
        assert grid_tbl["start_column_letter"] == "C"
        assert grid_tbl["row_numbers"] == [4, 6, 7]
        assert grid_tbl["location"] == "range:C4:E7"
        assert grid_tbl["raw_values"] == [
            ["Item", "Length (m)", "Force (kN)"],
            ["جسر B1", "6.00", "18.50"],
            ["Total", "", "=D6*E6"],
        ]
        # Verify exact cell mapping from (row_numbers[i], start_column + j) -> C4, D6, E7
        from openpyxl.utils import get_column_letter

        mapped_cells = {
            f"{get_column_letter(grid_tbl['start_column'] + c_off)}{grid_tbl['row_numbers'][r_off]}": val
            for r_off, row_vals in enumerate(grid_tbl["raw_values"])
            for c_off, val in enumerate(row_vals)
            if val != ""
        }
        assert mapped_cells["C4"] == "Item"
        assert mapped_cells["C6"] == "جسر B1"
        assert mapped_cells["D6"] == "6.00"
        assert mapped_cells["E7"] == "=D6*E6"


def test_extraction_hash_mismatch_and_refuse_existing_run_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SHA-256 mismatch persists failed FileExtraction + audit log; existing r{n} dir is never reused/overwritten."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)

    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_txt = _upload_file(client, project_id, "notes.txt", b"Design load = 18.50 kN/m\n", "text/plain")

        # 1. Pre-create existing r1 run directory with sentinel file -> extraction MUST refuse (409) without modifying it
        r1_dir = (
            settings.workspaces_dir
            / workspace_slug
            / "03_Analysis"
            / "extractions"
            / f_txt["id"]
            / "v1"
            / "r1"
        )
        r1_dir.mkdir(parents=True, exist_ok=True)
        sentinel = r1_dir / "sentinel.txt"
        sentinel.write_text("do-not-overwrite", encoding="utf-8")

        conflict_res = client.post(f"/api/files/{f_txt['id']}/extract")
        assert conflict_res.status_code == 409
        assert "refusing to reuse or overwrite" in conflict_res.json()["detail"].lower()
        assert sentinel.read_text(encoding="utf-8") == "do-not-overwrite"
        assert not (r1_dir / "extraction.json").exists()

    # Clean up sentinel and test mid-run SHA-256 mismatch handling cleanly on fresh file
    f_txt2_bytes = b"Column C1 capacity = 1250.00 kN\n"
    with TestClient(app) as client:
        f_txt2 = _upload_file(client, project_id, "col_check.txt", f_txt2_bytes, "text/plain")
        orig_hash = f_txt2["sha256"]
        call_counter = {"n": 0}

        def simulated_hash_tamper(_path: Path) -> str:
            call_counter["n"] += 1
            return orig_hash if call_counter["n"] == 1 else "tampered-" + ("f" * 55)

        monkeypatch.setattr("app.services.extraction._compute_sha256", simulated_hash_tamper)

        bad_hash_res = client.post(f"/api/files/{f_txt2['id']}/extract")
        assert bad_hash_res.status_code == 422
        assert "sha-256 changed" in bad_hash_res.json()["detail"].lower()

        with app.state.session_factory() as db:
            row = db.scalar(select(FileExtraction).where(FileExtraction.file_id == f_txt2["id"]))
            assert row is not None
            assert row.status == "failed"
            assert row.artifact_relative_path is None
            assert row.payload_json["original_unchanged"] is False
            assert row.payload_json["sha256_before"] == orig_hash
            assert row.payload_json["sha256_after"] != orig_hash

            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.entity_type == "file_extraction",
                    AuditLog.entity_id == row.id,
                    AuditLog.action == "file.extraction_failed",
                )
            )
            assert audit is not None
            assert audit.details_json["sha256_before"] == orig_hash
            assert audit.details_json["sha256_after"] != orig_hash


def test_pptx_grouped_shapes_and_multiframe_tiff_warning(tmp_path: Path) -> None:
    """Grouped PPTX shapes extract recursively and multi-frame TIFFs warn cleanly about frame-1 extraction."""
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[6])
    grp = s1.shapes.add_group_shape()
    tb = grp.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    tb.text_frame.text = "Grouped Note: Span 5.50 m | Arabic نموذج"
    pptx_buf = BytesIO()
    prs.save(pptx_buf)

    f1 = Image.new("RGB", (200, 100), color=(255, 255, 255))
    f2 = Image.new("RGB", (200, 100), color=(240, 240, 240))
    tiff_buf = BytesIO()
    f1.save(tiff_buf, format="TIFF", save_all=True, append_images=[f2])

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_pptx = _upload_file(
            client,
            project_id,
            "grouped.pptx",
            pptx_buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        f_tiff = _upload_file(client, project_id, "multi_frame.tiff", tiff_buf.getvalue(), "image/tiff")

        r_pptx = client.post(f"/api/files/{f_pptx['id']}/extract").json()
        assert any("group:" in item["location"] and "5.50 m" in (item["text"] or "") for item in r_pptx["items"])

        r_tiff = client.post(f"/api/files/{f_tiff['id']}/extract").json()
        assert any("Multi-frame TIFF/image detected (2 frames)" in w for w in r_tiff["warnings"])
