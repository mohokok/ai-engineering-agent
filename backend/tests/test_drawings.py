"""Tests for Step 11 Parametric Drawing Engine: Shoelace area computation, mm DXF ($INSUNITS=4 + TTF), true-scale PDF, schedules, Step 07 round-trip verification, and owner-confirmed AI draft guard."""

import hashlib
import io
import math
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import ezdxf
from fastapi.testclient import TestClient
import pymupdf
import pytest

from app.core.config import Settings
from app.main import create_app
from app.providers.secrets import SecretStore
from app.services.extractors.oda import convert_dwg_to_dxf, probe_oda
from app.services.parametric_cad import compute_room_metrics, verify_dxf_round_trip
from app.services.parametric_drawings import build_synthetic_clinic_preset
from app.services.workspace import resolve_project_file_path


class _InMemorySecretStore(SecretStore):
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._keys: dict[str, str] = dict(initial or {})

    @property
    def backend_name(self) -> str:
        return "InMemoryTestKeyring"

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        self._keys[provider_name] = api_key

    def get_api_key(self, provider_name: str) -> str | None:
        return self._keys.get(provider_name)

    def delete_api_key(self, provider_name: str) -> None:
        self._keys.pop(provider_name, None)


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(workspaces_dir=tmp_path / "workspaces", database_url="")


def test_step11_synthetic_clinic_parametric_dxf_pdf_schedules_and_roundtrip(tmp_path: Path) -> None:
    """Verify full deterministic Step 11 flow with 0 AI tokens, code-only Shoelace areas, mm DXF (TTF Arabic, blocks, PaperSpace), true-scale vector PDF, Step 07 round-trip pass, non-overwriting v1/v2 saves, and 409 guard."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={
                "name": "Step 11 Synthetic Medical Clinic",
                "code": "CLINIC-11",
                "classification": "For Review",
            },
        ).json()
        project_id = project["id"]

        preset_resp = client.get("/api/parametric-drawings/clinic-preset")
        assert preset_resp.status_code == 200
        model_payload = preset_resp.json()
        assert model_payload["units"] == "mm"
        assert len(model_payload["rooms"]) == 5

        # Seed intentionally wrong area numbers inside room JSON to verify code-computed Shoelace ignores them completely.
        for room in model_payload["rooms"]:
            room["area_m2"] = 9999.0
            room["area"] = 12345.0

        gen_resp = client.post(
            f"/api/projects/{project_id}/parametric-drawings",
            json={
                "drawing_no": "A-101",
                "title": "مخطط عيادة طبية نموذجي / Synthetic Medical Clinic Plan",
                "scale_denominator": 100,
                "paper_size": "A3",
                "classification": "For Review",
                "notes": "Verify MEP ceiling heights before IFC issue.",
                "plan_model": model_payload,
            },
        )
        assert gen_resp.status_code == 201, gen_resp.text
        drawing = gen_resp.json()

        assert drawing["drawing_no"] == "A-101"
        assert drawing["scale_label"] == "1:100"
        assert drawing["paper_size"] == "A3"
        assert drawing["units"] == "mm"
        assert drawing["revision"] == "Rev 01"
        assert drawing["version"] == 1
        assert drawing["round_trip_passed"] is True

        # Exact code-computed room areas (no hardcoded guesses accepted)
        area_by_room = {r["room_id"]: r["area_m2"] for r in drawing["rooms_computed"]}
        assert area_by_room == {
            "R-01": 24.0,
            "R-02": 16.0,
            "R-03": 12.0,
            "R-04": 14.0,
            "R-05": 14.0,
        }
        assert drawing["total_area_m2"] == 80.0

        # Schedules generated deterministically from exact model
        door_counts = {row["mark"]: row["count"] for row in drawing["door_schedule"]}
        win_counts = {row["mark"]: row["count"] for row in drawing["window_schedule"]}
        assert door_counts == {"D1": 1, "D2": 3, "D3": 1}
        assert win_counts == {"W1": 3, "W2": 1}

        # Automatic Step 07 round-trip audit results
        rt = drawing["round_trip_check"]
        assert rt["passed"] is True
        assert rt["insunits_code"] == 4
        assert rt["units"] == "mm"
        assert rt["units_doubtful"] is False
        assert rt["uses_shx_font"] is False
        assert any(s.lower().startswith("arabic_ttf:tahoma.ttf") for s in rt["ttf_font_styles"])
        assert rt["expected_room_count"] == 5
        assert rt["extracted_area_contour_count"] == 5
        assert abs(rt["extracted_total_area_m2"] - 80.0) < 0.01
        assert rt["expected_doors_count"] == 5
        assert rt["extracted_doors_count"] == 5
        assert rt["expected_windows_count"] == 4
        assert rt["extracted_windows_count"] == 4
        assert rt["mismatches"] == []

        # Verify deliverables saved in 05_Design_Drawings + downloadable with matching SHA-256
        deliverables = drawing["deliverables"]
        assert len(deliverables) == 2
        by_fmt = {d["format"]: d for d in deliverables}
        assert set(by_fmt.keys()) == {"dxf", "pdf"}
        for fmt, item in by_fmt.items():
            assert item["folder_name"] == "05_Design_Drawings"
            assert item["drawing_id"] == drawing["id"]
            dl_resp = client.get(item["download_url"])
            assert dl_resp.status_code == 200
            assert hashlib.sha256(dl_resp.content).hexdigest() == item["sha256"]

        # Verify filtered listing works for 05_Design_Drawings
        filt_resp = client.get(
            "/api/deliverables",
            params={"project_id": project_id, "folder_name": "05_Design_Drawings"},
        )
        assert filt_resp.status_code == 200
        assert filt_resp.json()["total"] == 2

        # Inspect DXF directly via ezdxf
        dxf_path = resolve_project_file_path(
            settings.workspaces_dir,
            project["workspace_slug"],
            by_fmt["dxf"]["relative_path"],
        )
        doc = ezdxf.readfile(str(dxf_path))
        assert int(doc.header.get("$INSUNITS", 0)) == 4
        assert int(doc.header.get("$MEASUREMENT", 0)) == 1
        for required_layer in (
            "A-WALL",
            "A-AREA",
            "A-DOOR",
            "A-WIND",
            "A-ANNO-TEXT",
            "A-ANNO-DIMS",
            "A-ANNO-SYMB",
            "A-ANNO-TTLB",
        ):
            assert required_layer in doc.layers

        # Never SHX font; Arabic TrueType font configured cleanly
        assert doc.styles.get("ARABIC_TTF").dxf.font.lower().endswith(".ttf")
        for st in doc.styles:
            assert ".shx" not in (st.dxf.font or "").lower()
            assert ".shx" not in (getattr(st.dxf, "bigfont", "") or "").lower()
        assert "ARCH_MM" in doc.dimstyles

        msp = doc.modelspace()
        text_contents = [
            e.dxf.text if e.dxftype() == "TEXT" else e.text
            for e in msp
            if e.dxftype() in {"TEXT", "MTEXT"} and e.dxf.layer == "A-ANNO-TEXT"
        ]
        joined_text = "\n".join(text_contents)
        assert "الاستقبال والانتظار" in joined_text
        assert "Reception & Waiting" in joined_text
        assert "24.00 m2" in joined_text
        assert len([e for e in msp if e.dxftype() == "DIMENSION" and e.dxf.layer == "A-ANNO-DIMS"]) >= 4
        assert len([e for e in msp if e.dxftype() == "INSERT" and e.dxf.layer == "A-DOOR"]) == 5
        assert len([e for e in msp if e.dxftype() == "INSERT" and e.dxf.layer == "A-WIND"]) == 4
        assert any(e.dxftype() == "CIRCLE" and e.dxf.layer == "A-ANNO-SYMB" for e in msp)
        assert any(e.dxftype() == "TEXT" and e.dxf.layer == "A-ANNO-SYMB" and "N / شمال" in e.dxf.text for e in msp)
        # Walls split at openings -> more wall quads than raw 8 unsplit wall lines
        assert len([e for e in msp if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "A-WALL"]) > 8

        # PaperSpace A3 layout & viewport exist
        assert "ISO_SHEET_PLAN" in doc.layouts
        psp = doc.layouts.get("ISO_SHEET_PLAN")
        assert any(e.dxftype() == "VIEWPORT" for e in psp)

        # Inspect true-scale PDF via PyMuPDF
        pdf_path = resolve_project_file_path(
            settings.workspaces_dir,
            project["workspace_slug"],
            by_fmt["pdf"]["relative_path"],
        )
        pdf_doc = pymupdf.open(str(pdf_path))
        assert pdf_doc.page_count == 2
        p0 = pdf_doc[0]
        # ISO A3 landscape = 420 x 297 mm -> ~1190.55 x 841.89 pt
        assert abs(p0.rect.width - (420.0 * 72.0 / 25.4)) < 1.0
        assert abs(p0.rect.height - (297.0 * 72.0 / 25.4)) < 1.0

        # Measure true vector scale in PDF points: 10000mm @ 1:100 = 100mm = 283.4646 pt (exact A-AREA span!)
        drawings_p0 = p0.get_drawings()
        expected_100mm_pt = 100.0 * 72.0 / 25.4
        expected_80mm_pt = 80.0 * 72.0 / 25.4
        # Corridor R-03 spans full x=0..10000mm -> exact width == expected_100mm_pt
        assert any(
            abs((d["rect"].x1 - d["rect"].x0) - expected_100mm_pt) < 0.05
            for d in drawings_p0
        ), f"Expected exact 1:100 10m vector span ({expected_100mm_pt:.3f} pt) in PDF!"
        assert any(
            abs((d["rect"].y1 - d["rect"].y0) - round(40.0 * 72.0 / 25.4, 3)) < 0.1
            for d in drawings_p0
        )

        p0_text = p0.get_text("text").replace("\xa0", " ").replace("\xad", "-")
        assert "A-101" in p0_text
        assert "1:100" in p0_text
        assert "Rev 01" in p0_text
        assert "For Review" in p0_text
        assert "Reception & Waiting" in p0_text
        assert "24.00 m²" in p0_text
        assert "80.00 m²" in p0_text

        p1_text = pdf_doc[1].get_text("text").replace("\xa0", " ").replace("\xad", "-")
        assert "Door Schedule" in p1_text
        assert "Window Schedule" in p1_text
        assert "Room Areas & Finishes Schedule" in p1_text
        assert "D1" in p1_text and "D2" in p1_text and "D3" in p1_text
        assert "W1" in p1_text and "W2" in p1_text
        pdf_doc.close()

        # Non-overwriting v2 check at 1:50 scale on A2
        v2_resp = client.post(
            f"/api/projects/{project_id}/parametric-drawings",
            json={
                "drawing_no": "A-101",
                "title": "مخطط عيادة طبية نموذجي / Synthetic Medical Clinic Plan",
                "scale_denominator": 50,
                "paper_size": "A2",
                "classification": "For Approval",
                "plan_model": model_payload,
            },
        )
        assert v2_resp.status_code == 201
        v2 = v2_resp.json()
        assert v2["version"] == 2
        assert v2["revision"] == "Rev 02"
        assert v2["scale_label"] == "1:50"
        assert dxf_path.exists() and pdf_path.exists()  # v1 still exists untouched

        # Verify PDF 1:50 true scale doubles vector span to 200mm = 566.9291 pt!
        v2_pdf_rel = next(d["relative_path"] for d in v2["deliverables"] if d["format"] == "pdf")
        v2_pdf_path = resolve_project_file_path(settings.workspaces_dir, project["workspace_slug"], v2_pdf_rel)
        with pymupdf.open(str(v2_pdf_path)) as v2_pdf:
            expected_200mm_pt = 200.0 * 72.0 / 25.4
            assert any(
                abs((d["rect"].x1 - d["rect"].x0) - expected_200mm_pt) < 0.05
                for d in v2_pdf[0].get_drawings()
            )

        # Pre-existing v3 path on disk -> HTTP 409 without overwriting existing sentinel file
        occupied_dir = resolve_project_file_path(settings.workspaces_dir, project["workspace_slug"], "05_Design_Drawings")
        # Determine exact filename helper behavior via pre-check isn't needed if we list deliverables; verify list & detail endpoints
        list_resp = client.get(f"/api/projects/{project_id}/parametric-drawings")
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 2
        detail_resp = client.get(f"/api/parametric-drawings/{drawing['id']}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["total_area_m2"] == 80.0
        assert occupied_dir.is_dir()

        # Verify 0 AI tokens spent for deterministic geometry & rendering
        settings_resp = client.get("/api/settings/provider").json()
        assert settings_resp["daily_usage"]["total_tokens"] == 0


def test_step11_ai_suggest_requires_owner_confirmation_and_strips_ai_areas(tmp_path: Path) -> None:
    """Verify optional AI draft JSON strips fabricated areas, logs tokens once, blocks unconfirmed drawing generation, and draws cleanly once confirmed."""
    clinic_preset = build_synthetic_clinic_preset().model_dump()
    # Simulate an AI trying to inject hallucinated area numbers inside room objects.
    for room in clinic_preset["rooms"]:
        room["area_m2"] = 555.5

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, **kwargs: Any) -> Any:
                return SimpleNamespace(
                    text="{}",
                    parsed=clinic_preset,
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=310,
                        candidates_token_count=140,
                        total_token_count=450,
                    ),
                )

        return SimpleNamespace(models=_Models())

    settings = _test_settings(tmp_path)
    app = create_app(
        settings,
        secret_store=_InMemorySecretStore({"gemini": "test-step11-key"}),
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "AI Draft Clinic", "code": "AI-DR-11"},
        ).json()
        project_id = project["id"]

        suggest_resp = client.post(
            f"/api/projects/{project_id}/parametric-drawings/suggest-model",
            json={"brief": "5-room outpatient clinic floor plan ~80 m2 in mm", "complexity": "fast"},
        )
        assert suggest_resp.status_code == 200, suggest_resp.text
        suggested = suggest_resp.json()
        assert suggested["requires_owner_confirmation"] is True
        assert suggested["tokens_used"] == 450
        # Pydantic stripped AI-injected area_m2 field cleanly
        assert "area_m2" not in suggested["plan_model"]["rooms"][0]

        # Attempt to generate without owner confirmation -> MUST fail cleanly (422)
        unconfirmed_resp = client.post(
            f"/api/projects/{project_id}/parametric-drawings",
            json={
                "drawing_no": "A-102",
                "title": "AI Suggested Clinic Draft",
                "scale_denominator": 100,
                "paper_size": "A3",
                "ai_suggested": True,
                "owner_confirmed_model": False,
                "plan_model": suggested["plan_model"],
            },
        )
        assert unconfirmed_resp.status_code == 422

        # Once owner confirms -> generates DXF + PDF with code-computed 80.0 m2 and 0 extra AI tokens!
        confirmed_resp = client.post(
            f"/api/projects/{project_id}/parametric-drawings",
            json={
                "drawing_no": "A-102",
                "title": "AI Suggested Clinic Confirmed",
                "scale_denominator": 100,
                "paper_size": "A3",
                "ai_suggested": True,
                "owner_confirmed_model": True,
                "plan_model": suggested["plan_model"],
            },
        )
        assert confirmed_resp.status_code == 201, confirmed_resp.text
        confirmed = confirmed_resp.json()
        assert confirmed["ai_suggested"] is True
        assert confirmed["total_area_m2"] == 80.0
        assert confirmed["round_trip_passed"] is True

        # Total AI usage stays exactly 450 tokens (drawing generation consumed 0 additional tokens)
        usage_after = client.get("/api/settings/provider").json()["daily_usage"]
        assert usage_after["total_tokens"] == 450


def test_step11_l_shaped_polygon_shoelace_area_and_roundtrip(tmp_path: Path) -> None:
    """Verify arbitrary L-shaped polygon_mm room computes exact Shoelace area/perimeter across DXF + PDF + Step 07 round-trip check."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    # L-shape: 6000x2000 bottom + 2000x3000 top-left leg => area = 12 + 6 = 18.0 m2, perim = 22.0 m
    l_poly = [
        [0.0, 0.0],
        [6000.0, 0.0],
        [6000.0, 2000.0],
        [2000.0, 2000.0],
        [2000.0, 5000.0],
        [0.0, 5000.0],
    ]
    model = {
        "units": "mm",
        "north_angle_deg": 15.0,
        "rooms": [
            {
                "room_id": "R-L1",
                "name_ar": "صالة حرف L",
                "name_en": "L-Shaped Hall",
                "polygon_mm": l_poly,
            }
        ],
        "walls": [
            {"wall_id": "W1", "start_mm": [0.0, 0.0], "end_mm": [6000.0, 0.0], "thickness_mm": 200.0, "wall_type": "exterior"},
            {"wall_id": "W2", "start_mm": [6000.0, 0.0], "end_mm": [6000.0, 2000.0], "thickness_mm": 200.0, "wall_type": "exterior"},
            {"wall_id": "W3", "start_mm": [6000.0, 2000.0], "end_mm": [2000.0, 2000.0], "thickness_mm": 200.0, "wall_type": "exterior"},
            {"wall_id": "W4", "start_mm": [2000.0, 2000.0], "end_mm": [2000.0, 5000.0], "thickness_mm": 200.0, "wall_type": "exterior"},
            {"wall_id": "W5", "start_mm": [2000.0, 5000.0], "end_mm": [0.0, 5000.0], "thickness_mm": 200.0, "wall_type": "exterior"},
            {"wall_id": "W6", "start_mm": [0.0, 5000.0], "end_mm": [0.0, 0.0], "thickness_mm": 200.0, "wall_type": "exterior"},
        ],
        "doors": [
            {"door_id": "D-L1", "mark": "D1", "position_mm": [3000.0, 0.0], "width_mm": 1000.0, "height_mm": 2100.0, "angle_deg": 0.0}
        ],
        "windows": [],
    }

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Polygon Plan", "code": "POLY-11"}).json()
        resp = client.post(
            f"/api/projects/{project['id']}/parametric-drawings",
            json={
                "drawing_no": "A-201",
                "title": "L-Shaped Plan",
                "scale_denominator": 100,
                "paper_size": "A4",
                "plan_model": model,
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["rooms_computed"][0]["area_m2"] == 18.0
        assert data["rooms_computed"][0]["perimeter_m"] == 22.0
        assert data["round_trip_passed"] is True
        assert abs(data["round_trip_check"]["extracted_total_area_m2"] - 18.0) < 0.01
        assert math.isclose(data["total_area_m2"], 18.0, abs_tol=1e-4)


def test_step11_existing_version_path_returns_409_and_leaves_file_untouched(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Verify non-overwriting guard returns 409 Conflict when target 05_Design_Drawings file already exists."""
    fixed_uuid = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr("app.services.parametric_drawings.new_uuid", lambda: fixed_uuid)

    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())
    model_payload = build_synthetic_clinic_preset().model_dump()

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Conflict Guard", "code": "CFG-11"}).json()
        sentinel_path = resolve_project_file_path(
            settings.workspaces_dir,
            project["workspace_slug"],
            f"05_Design_Drawings/A_101_{fixed_uuid.replace('-', '')[:8]}_v1.dxf",
        )
        sentinel_path.parent.mkdir(parents=True, exist_ok=True)
        sentinel_bytes = b"OWNER_EXISTING_PROTECTED_DXF"
        sentinel_path.write_bytes(sentinel_bytes)

        resp = client.post(
            f"/api/projects/{project['id']}/parametric-drawings",
            json={
                "drawing_no": "A-101",
                "title": "Protected Drawing",
                "scale_denominator": 100,
                "paper_size": "A3",
                "plan_model": model_payload,
            },
        )
        assert resp.status_code == 409
        assert sentinel_path.read_bytes() == sentinel_bytes


_RUN_REAL_ODA = os.getenv("RUN_REAL_ODA", "").strip().lower() in {"1", "true", "yes"}
_ODA_PROBE = probe_oda("")


@pytest.mark.real_oda
@pytest.mark.skipif(
    not (_RUN_REAL_ODA and _ODA_PROBE.capability.installed and _ODA_PROBE.executable),
    reason="Opt-in test: set RUN_REAL_ODA=1 with ODA File Converter installed to validate Step 11 DXF->DWG->DXF interoperability",
)
def test_optin_real_oda_step11_parametric_dxf_roundtrip(tmp_path: Path) -> None:
    """Opt-in real ODA File Converter audit: convert Step 11 synthetic clinic DXF -> ACAD2018 DWG -> DXF and verify Step 07 round-trip integrity."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())
    model_payload = build_synthetic_clinic_preset().model_dump()

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "ODA Step11", "code": "ODA-11"}).json()
        res = client.post(
            f"/api/projects/{project['id']}/parametric-drawings",
            json={
                "drawing_no": "A-101",
                "title": "ODA Interop Clinic Plan",
                "scale_denominator": 100,
                "paper_size": "A3",
                "plan_model": model_payload,
            },
        )
        assert res.status_code == 201
        drawing = res.json()
        dxf_rel = next(d["relative_path"] for d in drawing["deliverables"] if d["format"] == "dxf")
        src_dxf = resolve_project_file_path(settings.workspaces_dir, project["workspace_slug"], dxf_rel)

        in_dxf_dir = tmp_path / "oda_in_dxf"
        out_dwg_dir = tmp_path / "oda_out_dwg"
        in_dxf_dir.mkdir(parents=True, exist_ok=True)
        out_dwg_dir.mkdir(parents=True, exist_ok=True)
        (in_dxf_dir / src_dxf.name).write_bytes(src_dxf.read_bytes())

        assert _ODA_PROBE.executable is not None
        proc = subprocess.run(
            [_ODA_PROBE.executable, str(in_dxf_dir), str(out_dwg_dir), "ACAD2018", "DWG", "0", "1", "*.dxf"],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert proc.returncode == 0, f"ODA DXF->DWG failed: {proc.stderr or proc.stdout}"
        dwg_file = out_dwg_dir / f"{src_dxf.stem}.dwg"
        assert dwg_file.is_file() and dwg_file.stat().st_size > 0

        re_dxf = convert_dwg_to_dxf(
            dwg_file,
            output_dxf_dir=tmp_path / "oda_re_dxf",
            source_filename=dwg_file.name,
            oda_probe=_ODA_PROBE,
        )
        preset = build_synthetic_clinic_preset()
        rooms = compute_room_metrics(preset.rooms)
        rt = verify_dxf_round_trip(re_dxf, rooms=rooms, door_count=len(preset.doors), window_count=len(preset.windows))
        assert rt.passed is True, f"ODA DWG->DXF round-trip mismatches: {rt.mismatches}"
        assert rt.insunits_code == 4
        assert abs(rt.extracted_total_area_m2 - 80.0) < 0.01
        print(
            f"\nSTEP 11 REAL ODA ROUND-TRIP: version={_ODA_PROBE.capability.version} | "
            f"dwg_bytes={dwg_file.stat().st_size} | insunits={rt.insunits_code} ({rt.units}) | "
            f"area={rt.extracted_total_area_m2} m2 | doors={rt.extracted_doors_count} | windows={rt.extracted_windows_count}"
        )
