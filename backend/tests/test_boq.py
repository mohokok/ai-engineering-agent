"""Tests for Step 10 Bill of Quantities: DXF/IFC quantities, unit confirmation respect, XLSX/PDF import, unsourced-rate blocking, checks, and live-formula XLSX + CSV export."""

import csv
import io
import math
from pathlib import Path
from typing import Any

import ezdxf
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
import pymupdf
import pytest

from app.core.config import Settings
from app.db.models import BoqItem, ResearchRun, ResearchSource
from app.main import create_app
from app.services.workspace import resolve_project_file_path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspaces_dir=tmp_path / "workspaces",
        database_url="",
    )


def _make_doubtful_linear_area_dxf() -> bytes:
    """Create a synthetic DXF with doubtful $INSUNITS=1 (in) plus metric-scale coordinates (A-AREA 60, LINE 12, ARC r=2 90deg, 4 block inserts)."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 1  # Doubtful inches for building-scale dims -> requires confirm-unit!
    doc.layers.add("A-AREA")
    doc.layers.add("A-WALL")
    doc.layers.add("DIMENSIONS")
    blk = doc.blocks.new(name="DOOR_SINGLE")
    blk.add_line((0, 0), (1, 0))

    msp = doc.modelspace()
    # Closed area: 10 x 6 = 60.0 native on A-AREA
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 6), (0, 6)], close=True, dxfattribs={"layer": "A-AREA"})
    # Linear wall LINE = 12.0 native + ARC r=2, 0..90 deg = pi (3.141593) native on A-WALL
    msp.add_line((0, 0), (12, 0), dxfattribs={"layer": "A-WALL"})
    msp.add_arc(center=(0, 0), radius=2.0, start_angle=0.0, end_angle=90.0, dxfattribs={"layer": "A-WALL"})
    # Annotation line on DIMENSIONS (excluded from structural linear quantities)
    msp.add_line((0, -2), (10, -2), dxfattribs={"layer": "DIMENSIONS"})
    # Dimension entities so unit plausibility knows dims look metric despite $INSUNITS=1
    dim1 = msp.add_linear_dim(base=(5, 7), p1=(0, 6), p2=(10, 6), dxfattribs={"layer": "DIMENSIONS"})
    dim1.render()
    # 4 DOOR_SINGLE block inserts
    for k in range(4):
        msp.add_blockref("DOOR_SINGLE", (k * 2.0, 0.0), dxfattribs={"layer": "A-WALL"})

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _make_boq_xlsx_bytes() -> bytes:
    """Create a synthetic Arabic+English XLSX BOQ including a seeded arithmetic mismatch and missing unit row."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Bill of Quantities"
    ws.append(["Project Clinic BOQ — Preliminary"])
    ws.append(["Item No.", "Description", "Unit", "Quantity", "Unit Rate", "Total", "Technical Ref", "Drawing Ref", "Remarks"])
    # Row 3: valid priced line
    ws.append(["01.01", "أعمال الخرسانة المسلحة للقواعد", "m3", 25.5, 420.0, 10710.0, "BS 8110", "S-101", "C35 concrete"])
    # Row 4: arithmetic discrepancy (10 * 50 = 500, stated 999)
    ws.append(["01.02", "Ceramic floor tiling (60x60cm)", "m2", 10.0, 50.0, 999.0, "Spec Sec 09", "A-201", "Check vendor rate"])
    # Row 5: missing unit -> triggers Extracted-Needs-Check & missing_item check!
    ws.append(["01.03", "Supply and fix fire exit signage", "", 6, 35.0, 210.0, "NFPA 101", "A-105", ""])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _make_boq_pdf_bytes() -> bytes:
    """Create a synthetic PDF containing a crisp bordered BOQ grid table extractable cleanly by pdfplumber."""
    doc = pymupdf.open()
    pg = doc.new_page(width=620, height=400)
    headers = ["Item No.", "Description", "Unit", "Quantity", "Unit Rate", "Total"]
    rows = [
        headers,
        ["02.01", "External gypsum partition walls", "m2", "80.0", "110.0", "8800.0"],
        ["02.02", "Solid core timber door set D1", "nos", "5", "", ""],
    ]
    col_x = [20, 80, 310, 370, 440, 520, 600]
    y_top = 40
    row_h = 28
    for r_i, row in enumerate(rows):
        y0 = y_top + r_i * row_h
        y1 = y0 + row_h
        for c_i, val in enumerate(row):
            rect = pymupdf.Rect(col_x[c_i], y0, col_x[c_i + 1], y1)
            pg.draw_rect(rect, color=(0, 0, 0), width=0.8)
            pg.insert_text((col_x[c_i] + 5, y0 + 18), val, fontsize=9)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_step10_dxf_ifc_quantities_respect_confirmed_unit_and_never_silent_convert(tmp_path: Path) -> None:
    """Doubtful CAD DXF never silently converts to m/m2; confirming unit unlocks deterministic areas/lengths/counts alongside IFC."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    dxf_bytes = _make_doubtful_linear_area_dxf()
    ifc_bytes = (FIXTURES_DIR / "sample_clinic_model.ifc").read_bytes()

    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "مستشفى الخطوة العاشرة", "code": "BOQ-10A"}).json()
        pid = proj["id"]
        up = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("doubtful_plan.dxf", dxf_bytes, "application/dxf")),
                ("files", ("sample_clinic_model.ifc", ifc_bytes, "application/octet-stream")),
            ],
        ).json()
        f_dxf_id = up["items"][0]["file"]["id"]
        f_ifc_id = up["items"][1]["file"]["id"]

        ext_dxf = client.post(f"/api/files/{f_dxf_id}/extract", json={}).json()
        assert ext_dxf["units_doubtful"] is True
        assert client.post(f"/api/files/{f_ifc_id}/extract", json={}).status_code == 201

        # 1. Build BOQ BEFORE confirming doubtful DXF unit -> MUST NOT convert to m/m2; tagged Extracted-Needs-Check & pricing blocked!
        boq_res = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={
                "language": "en",
                "classification": "For Review",
                "file_ids": [f_dxf_id, f_ifc_id],
            },
        )
        assert boq_res.status_code == 201, boq_res.text
        boq = boq_res.json()
        assert boq["currency"] == "LYD"  # configurable default = LYD

        dxf_items = [it for it in boq["items"] if it["source_file_id"] == f_dxf_id]
        assert len(dxf_items) == 4  # A-AREA poly + A-WALL LINE + A-WALL ARC + DOOR_SINGLE block count
        for dit in dxf_items:
            assert dit["verification_status"] == "Extracted-Needs-Check"
            if dit["discipline"] in ("cad_area", "cad_length"):
                assert dit["unit"] not in {"m", "m2"}
                assert "unconfirmed" in dit["unit"]
                assert "BLOCKED METRIC CONVERSION" in (dit["remarks"] or "")
                # Native quantity preserved untouched (60.0 area, NOT 60 * 0.0254^2!)
                if dit["discipline"] == "cad_area":
                    assert dit["quantity"] == pytest.approx(60.0, rel=1e-4)

        # Pricing an unconfirmed-unit item is strictly BLOCKED (422)!
        area_item = next(it for it in dxf_items if it["discipline"] == "cad_area")
        blk_price = client.patch(
            f"/api/boq-sheets/{boq['id']}/items/{area_item['id']}",
            json={
                "unit_rate": 100.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner baseline",
            },
        )
        assert blk_price.status_code == 422
        assert boq["checks"]["high_issues_count"] >= 1
        assert area_item["id"] in boq["checks"]["flagged_item_ids"]

        # Check IFC items too: one authored space 18.75 m2 Extracted-Verified, one missing area Extracted-Needs-Check, walls 21.0 m2 + doors/windows!
        ifc_items = [it for it in boq["items"] if it["source_file_id"] == f_ifc_id]
        assert any(
            it["discipline"] == "bim_space" and it["quantity"] == pytest.approx(18.75, rel=1e-4) and it["verification_status"] == "Extracted-Verified"
            for it in ifc_items
        )
        assert any(
            it["discipline"] == "bim_space" and it["quantity"] == 0.0 and it["verification_status"] == "Extracted-Needs-Check"
            for it in ifc_items
        )
        assert any(
            it["discipline"] == "bim_wall" and it["quantity"] == pytest.approx(21.0, rel=1e-4) and it["verification_status"] == "Extracted-Verified"
            for it in ifc_items
        )
        assert any(
            it["layer_or_category"] == "IfcDoor" and it["quantity"] == 1.0 and it["unit"] == "nos" and it["verification_status"] == "Extracted-Verified"
            for it in ifc_items
        )

        # 2. Owner confirms drawing unit = 'm', then re-imports deterministically -> now DXF areas, LINE & ARC lengths, and block counts become Extracted-Verified in m2 / m / nos!
        assert client.post(
            f"/api/extractions/{ext_dxf['id']}/confirm-unit",
            json={"confirmed_unit": "m"},
        ).status_code == 200

        reimp = client.post(
            f"/api/boq-sheets/{boq['id']}/import-extractions",
            json={"file_ids": [f_dxf_id], "replace_extracted": True},
        )
        assert reimp.status_code == 200, reimp.text
        updated_boq = reimp.json()
        dxf_after = updated_boq["items"]

        area_after = next(it for it in dxf_after if it["discipline"] == "cad_area")
        assert area_after["unit"] == "m2"
        assert area_after["quantity"] == pytest.approx(60.0, rel=1e-4)
        assert area_after["verification_status"] == "Extracted-Verified"

        line_after = next(it for it in dxf_after if it["discipline"] == "cad_length" and "LINE" in it["drawing_reference"])
        arc_after = next(it for it in dxf_after if it["discipline"] == "cad_length" and "ARC" in it["drawing_reference"])
        assert line_after["unit"] == "m" and line_after["quantity"] == pytest.approx(12.0, rel=1e-4)
        assert arc_after["unit"] == "m" and arc_after["quantity"] == pytest.approx(math.pi, rel=1e-3)
        assert line_after["verification_status"] == "Extracted-Verified"
        assert arc_after["verification_status"] == "Extracted-Verified"

        blk_after = next(it for it in dxf_after if it["discipline"] == "cad_count")
        assert blk_after["unit"] == "nos"
        assert blk_after["quantity"] == 4.0
        assert blk_after["verification_status"] == "Extracted-Verified"


def test_step10_unsourced_rates_blocked_sourced_accepted_configurable_currency_and_xlsx_live_formulas(tmp_path: Path) -> None:
    """Unsourced/undated/unreviewed rates are strictly blocked; owner & dated research rates price cleanly; XLSX exports live formulas + CSV into 06_BOQ."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    dxf_bytes = (FIXTURES_DIR / "sample_clinic_plan.dxf").read_bytes()

    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Pricing & Excel Gate", "code": "BOQ-10B"}).json()
        pid = proj["id"]
        slug = proj["workspace_slug"]

        f_dxf = client.post(
            f"/api/projects/{pid}/files",
            files=[("files", ("clinic.dxf", dxf_bytes, "application/dxf"))],
        ).json()["items"][0]["file"]
        assert client.post(f"/api/files/{f_dxf['id']}/extract", json={}).status_code == 201

    # Seed one unreviewed research source + one reviewed research source
    with app.state.session_factory() as db:
        rr = ResearchRun(project_id=pid, query="clinic rates", search_provider="duckduckgo_lite", classification="Preliminary", status="completed")
        db.add(rr)
        db.flush()
        bad_src = ResearchSource(
            research_run_id=rr.id,
            project_id=pid,
            source_name="Blocked 403 Supplier",
            url="https://blocked.example.com/rates",
            reviewed=False,
            access_status="blocked",
            reliability_assessment="unreviewed",
        )
        ok_src = ResearchSource(
            research_run_id=rr.id,
            project_id=pid,
            source_name="Libya Construction Cost Index",
            url="https://costs.example.org/lyd-2026",
            publication_date="2026-10-01",
            reviewed=True,
            access_status="accessible",
            reliability_assessment="medium_reputable",
        )
        db.add_all([bad_src, ok_src])
        db.commit()

    with TestClient(app) as client:
        boq = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={"language": "ar", "currency": "USD", "classification": "For Approval", "file_ids": [f_dxf["id"]]},
        ).json()
        boq_id = boq["id"]
        assert boq["currency"] == "USD"

        # Change configurable currency back to LYD cleanly
        upd_curr = client.patch(f"/api/boq-sheets/{boq_id}", json={"currency": "LYD"})
        assert upd_curr.status_code == 200 and upd_curr.json()["currency"] == "LYD"

        # 1. Block unsourced manual item (rate without rate_source_kind)
        assert client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={"item_no": "M-01", "description": "Testing", "unit": "m2", "quantity": 10.0, "unit_rate": 99.0},
        ).status_code == 422

        # 2. Block owner_input without attribution ref
        assert client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={"item_no": "M-01", "description": "Testing", "unit": "m2", "quantity": 10.0, "unit_rate": 99.0, "rate_source_kind": "owner_input"},
        ).status_code == 422

        # 3. Block dated_research without date
        assert client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={"item_no": "M-01", "description": "Testing", "unit": "m2", "quantity": 10.0, "unit_rate": 99.0, "rate_source_kind": "dated_research", "rate_source_ref": "https://costs.example.org/lyd-2026"},
        ).status_code == 422

        # 4. Block dated_research citing an UNREVIEWED source URL in the project log
        assert client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={
                "item_no": "M-01",
                "description": "Testing",
                "unit": "m2",
                "quantity": 10.0,
                "unit_rate": 99.0,
                "rate_source_kind": "dated_research",
                "rate_source_ref": "https://blocked.example.com/rates",
                "rate_source_date": "2026-11-01",
            },
        ).status_code == 422

        # 5. Accept owner_input rate on extracted area item + dated_research (reviewed + dated!) on Manual item
        area_item = next(it for it in boq["items"] if it["discipline"] == "cad_area")
        r_own = client.patch(
            f"/api/boq-sheets/{boq_id}/items/{area_item['id']}",
            json={
                "unit_rate": 150.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner Schedule Quote #2026-11",
                "rate_source_date": "2026-11-20",
            },
        )
        assert r_own.status_code == 200, r_own.text

        r_res = client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={
                "item_no": "MAN-01",
                "description": "دهان بلاستيك داخلي 3 أوجه",
                "unit": "m2",
                "quantity": 100.0,
                "unit_rate": 22.5,
                "rate_source_kind": "dated_research",
                "rate_source_ref": "https://costs.example.org/lyd-2026",
                "rate_source_date": "2026-10-01",
                "technical_reference": "RES-Reviewed 2026-10-01",
                "verification_status": "Manual",
            },
        )
        assert r_res.status_code == 201, r_res.text
        after_items = r_res.json()["items"]
        priced_sum = round(sum(float(i["total"]) for i in after_items if i["total"] is not None), 4)
        assert r_res.json()["grand_total"] == pytest.approx(priced_sum, rel=1e-4)

        # 6. Export XLSX (live formulas) + CSV into 06_BOQ
        exp_res = client.post(f"/api/boq-sheets/{boq_id}/export", json={"language": "en"})
        assert exp_res.status_code == 201, exp_res.text
        exp_data = exp_res.json()
        xlsx_d = exp_data["xlsx_deliverable"]
        csv_d = exp_data["csv_deliverable"]
        assert xlsx_d["folder_name"] == "06_BOQ"
        assert csv_d["folder_name"] == "06_BOQ"
        assert client.get(xlsx_d["download_url"]).status_code == 200
        assert client.get(csv_d["download_url"]).status_code == 200

        xlsx_path = resolve_project_file_path(settings.workspaces_dir, slug, xlsx_d["relative_path"])
        csv_path = resolve_project_file_path(settings.workspaces_dir, slug, csv_d["relative_path"])
        assert xlsx_path.is_file() and csv_path.is_file()

        # Verify live Excel formulas verbatim inside XLSX (F{r} and SUM / SUMIF / COUNTIF)
        wb = load_workbook(xlsx_path, data_only=False)
        ws = wb.active
        assert ws["F6"].value == "=IF(ISNUMBER(E6),ROUND(D6*E6,4),0)"
        all_formulas = [
            str(cell.value)
            for row in ws.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
        assert any(f.startswith("=SUM(F6:F") for f in all_formulas)
        assert any("=SUMIF(" in f for f in all_formulas)

        ws_chk = wb["Checks & Flagged Items"]
        chk_formulas = [
            str(cell.value)
            for row in ws_chk.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
        assert any("=COUNTIF(" in f for f in chk_formulas)
        wb.close()

        # Verify UTF-8 CSV without BOM & content
        csv_bytes = csv_path.read_bytes()
        assert not csv_bytes.startswith(b"\xef\xbb\xbf")
        csv_rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"), newline="")))
        assert any("Unit Rate (LYD)" in r for r in csv_rows)
        assert any("MAN-01" in r and "2250.0" in r for r in csv_rows)

        # Exporting again produces v2 without overwriting v1
        exp_v2 = client.post(f"/api/boq-sheets/{boq_id}/export", json={}).json()
        assert exp_v2["xlsx_deliverable"]["version"] == 2
        assert xlsx_path.is_file()


def test_step10_import_xlsx_and_pdf_boqs_and_seeded_checks_duplicates_missing_units_arithmetic(tmp_path: Path) -> None:
    """Import XLSX & PDF BOQs deterministically and verify duplicate, missing-item, unit-consistency, and arithmetic checks fire."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    xlsx_bytes = _make_boq_xlsx_bytes()
    pdf_bytes = _make_boq_pdf_bytes()
    ifc_bytes = (FIXTURES_DIR / "sample_clinic_model.ifc").read_bytes()

    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Seeded Checks BOQ", "code": "BOQ-10C"}).json()
        pid = proj["id"]
        up = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("existing_boq.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                ("files", ("schedule_boq.pdf", pdf_bytes, "application/pdf")),
                ("files", ("clinic_model.ifc", ifc_bytes, "application/octet-stream")),
            ],
        ).json()
        f_xlsx_id = up["items"][0]["file"]["id"]
        f_pdf_id = up["items"][1]["file"]["id"]
        f_ifc_id = up["items"][2]["file"]["id"]

        boq = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={"language": "en", "file_ids": [f_xlsx_id, f_pdf_id, f_ifc_id]},
        ).json()
        boq_id = boq["id"]

        items_by_no = {it["item_no"]: it for it in boq["items"]}
        # Imported XLSX checks: 01.01 verified, 01.02 flagged for 999 != 500 arithmetic mismatch, 01.03 missing unit
        assert items_by_no["01.01"]["quantity"] == pytest.approx(25.5, rel=1e-4)
        assert items_by_no["01.01"]["unit"] == "m3"
        assert items_by_no["01.01"]["verification_status"] == "Extracted-Verified"
        assert items_by_no["01.02"]["reported_total"] == pytest.approx(999.0, rel=1e-4)
        assert items_by_no["01.02"]["total"] == pytest.approx(500.0, rel=1e-4)
        assert items_by_no["01.02"]["verification_status"] == "Extracted-Needs-Check"
        assert items_by_no["01.03"]["verification_status"] == "Extracted-Needs-Check"

        # Imported PDF checks: 02.01 verified 80.0 m2, 02.02 unpriced nos
        assert items_by_no["02.01"]["quantity"] == pytest.approx(80.0, rel=1e-4) and items_by_no["02.01"]["unit"] == "m2"
        assert items_by_no["02.02"]["unit"] == "nos" and items_by_no["02.02"]["quantity"] == pytest.approx(5.0, rel=1e-4)

        chk_types = {iss["check_type"] for iss in boq["checks"]["issues"]}
        assert "arithmetic_total" in chk_types  # 01.02 999 vs 500 discrepancy caught!
        assert "missing_item" in chk_types      # 01.03 missing unit + IFC room missing Qto area

        # Seed: duplicate item_no + incompatible unit family ('cm2' mixed with 'm2') + count-on-area mismatch, AND delete one IFC Door count item so missing coverage fires!
        client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={
                "item_no": "01.01",  # duplicate item_no!
                "description": "أعمال الخرسانة المسلحة للقواعد",
                "unit": "m3",
                "quantity": 25.5,
                "unit_rate": 420.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Seeded duplicate",
                "verification_status": "Manual",
            },
        )
        client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={
                "item_no": "09.01",
                "description": "Ceramic floor tiling area check",
                "unit": "cm2",  # mixed imperial/submetric unit system against m2!
                "quantity": 5000.0,
                "verification_status": "Manual",
            },
        )
        door_item = next(it for it in boq["items"] if it["layer_or_category"] == "IfcDoor")
        client.delete(f"/api/boq-sheets/{boq_id}/items/{door_item['id']}")

    # Corrupt stored total directly in DB on one row to test Python arithmetic audit check too!
    with app.state.session_factory() as db:
        row_01 = db.query(BoqItem).filter(BoqItem.boq_sheet_id == boq_id, BoqItem.item_no == "01.01").first()
        assert row_01 is not None
        row_01.total = 12345.0
        db.commit()

    with TestClient(app) as client:
        rechecked = client.post(f"/api/boq-sheets/{boq_id}/checks").json()

    issues = rechecked["checks"]["issues"]
    types_after = {iss["check_type"] for iss in issues}
    assert "duplicate_item" in types_after
    assert "missing_item" in types_after
    assert "unit_consistency" in types_after
    assert "arithmetic_total" in types_after
    assert any("IfcDoor" in iss["message"] for iss in issues if iss["check_type"] == "missing_item")
    assert any("stored total (12345.0)" in iss["message"] for iss in issues if iss["check_type"] == "arithmetic_total")
    assert len(rechecked["checks"]["flagged_items"]) >= 3
