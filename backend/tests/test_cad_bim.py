"""Tests for Step 07 CAD (DXF/DWG via ODA), BIM (IFC), and Gemini vision drawing summary."""

from io import StringIO
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any

import ezdxf
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AuditLog, FileExtraction
from app.main import create_app
from app.providers.secrets import SecretStore
from app.services.extractors.oda import (
    ODA_NOT_INSTALLED_STATUS,
    _resolve_oda_executable,
    detect_oda,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class _InMemorySecretStore(SecretStore):
    def __init__(self, initial_key: str | None = None) -> None:
        self._keys: dict[str, str] = {}
        if initial_key:
            self._keys["gemini"] = initial_key

    def backend_name(self) -> str:
        return "InMemoryTestKeyring"

    def set_api_key(self, provider: str, api_key: str) -> None:
        self._keys[provider] = api_key

    def get_api_key(self, provider: str) -> str | None:
        return self._keys.get(provider)

    def delete_api_key(self, provider: str) -> None:
        self._keys.pop(provider, None)


def _test_settings(tmp_path: Path, *, oda_path: str = "") -> Settings:
    return Settings(
        workspaces_dir=tmp_path / "workspaces",
        database_url="",
        oda_file_converter_path=oda_path,
    )


def _create_project(client: TestClient) -> tuple[str, str]:
    res = client.post(
        "/api/projects",
        json={"name": "مشروع مستشفى بنغازي 07", "code": "CAD-07"},
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
) -> dict[str, Any]:
    res = client.post(
        f"/api/projects/{project_id}/files",
        files=[("files", (filename, content, mime_type))],
    )
    assert res.status_code == 201, res.text
    return res.json()["items"][0]["file"]


def test_capabilities_oda_resolution_priority_absent_dwg_and_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify configured -> PATH -> Program Files ODA discovery, matrix claims, and absent ODA failure logging."""
    custom_exe = tmp_path / "custom_oda.exe"
    custom_exe.write_bytes(b"stub")
    prog_root = tmp_path / "ODA"
    ver_dir = prog_root / "ODAFileConverter 27.10.0"
    ver_dir.mkdir(parents=True)
    default_exe = ver_dir / "ODAFileConverter.exe"
    default_exe.write_bytes(b"stub")

    with monkeypatch.context() as m:
        m.setattr("app.services.extractors.oda._DEFAULT_ODA_SEARCH_ROOTS", (prog_root,))
        m.setattr("app.services.extractors.oda.shutil.which", lambda _cmd: "path_oda.exe")
        assert _resolve_oda_executable(str(custom_exe)) == str(custom_exe)
        assert _resolve_oda_executable("") == "path_oda.exe"
        m.setattr("app.services.extractors.oda.shutil.which", lambda _cmd: None)
        assert _resolve_oda_executable("") == str(default_exe)

    # Force absent ODA hermetically
    monkeypatch.setattr("app.services.extractors.oda._DEFAULT_ODA_SEARCH_ROOTS", ())
    monkeypatch.setattr("app.services.extractors.oda.shutil.which", lambda *_a, **_kw: None)

    cap_missing = detect_oda("")
    assert cap_missing.installed is False
    assert cap_missing.status == ODA_NOT_INSTALLED_STATUS

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    dwg_bytes = (FIXTURES_DIR / "sample_clinic_plan.dwg").read_bytes()

    with TestClient(app) as client:
        caps = client.get("/api/extraction/capabilities").json()
        assert caps["oda"]["status"] == "not installed - pending owner"
        matrix = {row["extension"]: row for row in caps["format_support_matrix"]}
        assert matrix[".dxf"]["support_level"] == "native"
        assert matrix[".ifc"]["support_level"] == "native"
        assert matrix[".dwg"]["support_level"] == "converted_via_oda"
        assert ".rvt" in matrix[".rvt / .rfa / .rte"]["extension"]
        assert matrix[".rvt / .rfa / .rte"]["support_level"] == "not_supported"

        project_id, _ = _create_project(client)
        f_dwg = _upload_file(client, project_id, "missing_oda.dwg", dwg_bytes, "application/acad")
        res = client.post(f"/api/files/{f_dwg['id']}/extract")
        assert res.status_code == 422
        assert "not installed - pending owner" in res.json()["detail"].lower()

        with app.state.session_factory() as db:
            row = db.scalar(select(FileExtraction).where(FileExtraction.file_id == f_dwg["id"]))
            assert row is not None
            assert row.status == "failed"
            assert row.payload_json["converter_status"] == ODA_NOT_INSTALLED_STATUS
            assert row.payload_json["original_unchanged"] is True


def test_extract_dxf_inventory_arabic_units_deterministic_areas_and_edge_limits(
    tmp_path: Path,
) -> None:
    """DXF extraction inventories layers, Arabic blocks/text, dimensions, exact closed areas, PNG, and limits."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    dxf_bytes = (FIXTURES_DIR / "sample_clinic_plan.dxf").read_bytes()

    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_dxf = _upload_file(client, project_id, "clinic_plan.dxf", dxf_bytes, "application/dxf")
        orig_sha = f_dxf["sha256"]

        res = client.post(f"/api/files/{f_dxf['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["status"] == "extracted"
        assert data["sha256_before"] == orig_sha
        assert data["sha256_after"] == orig_sha
        assert data["original_unchanged"] is True
        assert data["cad_units"] == "m ($INSUNITS=6)"
        assert data["counts"]["layers"] >= 4
        assert data["counts"]["blocks"] >= 1
        assert data["counts"]["block_inserts"] >= 2
        assert data["counts"]["closed_areas"] == 2
        assert data["counts"]["dimensions"] == 1
        assert data["counts"]["rendered_page_images"] == 1

        inv = data["drawing_inventory"]
        assert inv["kind"] == "cad_dxf"
        layer_names = {layer["name"] for layer in inv["layers"]}
        assert {"جدران-معمارية", "محاور-Grids", "أبعاد-Dims"}.issubset(layer_names)
        blocks_by_name = {blk["name"]: blk for blk in inv["blocks"]}
        assert "DOOR_باب_D1" in blocks_by_name
        assert blocks_by_name["DOOR_باب_D1"]["insert_count"] == 2

        # Computed areas must deterministically match the CAD-annotated room areas (24.00 m2 and 14.00 m2)
        areas_sorted = sorted(round(a["area_native"], 4) for a in inv["closed_areas"])
        assert areas_sorted == [14.0, 24.0]
        assert all(a["area_m2"] == a["area_native"] for a in inv["closed_areas"])

        all_texts = " | ".join(i["text"] for i in data["items"] if i["text"])
        assert "غرفة العمليات الرئيسية" in all_texts
        assert "مختبر التحاليل" in all_texts
        assert "DOOR_TAG=D-01" in all_texts
        assert "Dimension measured=6.0 m" in all_texts
        assert any("PaperSpace layouts contain" in w for w in data["warnings"])

        png_res = client.get(f"/api/extractions/{data['id']}/pages/1")
        assert png_res.status_code == 200
        assert png_res.content[:8] == b"\x89PNG\r\n\x1a\n"

        orig_path = settings.workspaces_dir / workspace_slug / f_dxf["stored_relative_path"]
        assert not (orig_path.stat().st_mode & stat.S_IWRITE)

        # Unitless ($INSUNITS=0) + external XREF DXF must not invent metric area and must warn explicitly
        unitless_doc = ezdxf.new("R2018")
        unitless_doc.header["$INSUNITS"] = 0
        unitless_doc.add_xref_def("./site_ref.dwg", "XREF_SITE_BOUNDARY")
        unitless_doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True)
        unitless_buf = StringIO()
        unitless_doc.write(unitless_buf)

        f_u = _upload_file(client, project_id, "unitless_xref.dxf", unitless_buf.getvalue().encode("utf-8"), "application/dxf")
        res_u = client.post(f"/api/files/{f_u['id']}/extract").json()
        assert res_u["cad_units"] == "unitless ($INSUNITS=0)"
        assert res_u["units_doubtful"] is True
        assert res_u["units_status"] == "unitless"
        assert any("$INSUNITS=0 (unitless)" in w for w in res_u["warnings"])
        assert any("units doubtful - owner must confirm drawing unit" in w for w in res_u["warnings"])
        assert any("External XREF block(s) detected" in w for w in res_u["warnings"])
        area_entry = res_u["drawing_inventory"]["closed_areas"][0]
        assert area_entry["area_native"] == 50.0
        assert area_entry["area_m2"] is None


def test_dwg_conversion_pipeline_mocked_preserves_original_and_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DWG extraction converts to DXF via ODA into versioned r{n}/converted/, preserving original read-only DWG."""
    fake_oda = tmp_path / "ODAFileConverter.exe"
    fake_oda.write_bytes(b"stub")
    dxf_bytes = (FIXTURES_DIR / "sample_clinic_plan.dxf").read_bytes()
    dwg_bytes = (FIXTURES_DIR / "sample_clinic_plan.dwg").read_bytes()

    def fake_convert_run(cmd: list[str], **_kw: Any) -> SimpleNamespace:
        out_dir = Path(cmd[2])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "site_plan.dxf").write_bytes(dxf_bytes)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.extractors.oda.subprocess.run", fake_convert_run)

    settings = _test_settings(tmp_path, oda_path=str(fake_oda))
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_dwg = _upload_file(client, project_id, "site_plan.dwg", dwg_bytes, "application/acad")
        orig_sha = f_dwg["sha256"]

        res = client.post(f"/api/files/{f_dwg['id']}/extract")
        assert res.status_code == 201, res.text
        d1 = res.json()
        assert d1["converter_status"] == "installed"
        assert d1["converted_artifact_relative_path"].endswith("/r1/converted/site_plan.dxf")
        assert d1["sha256_before"] == orig_sha
        assert d1["sha256_after"] == orig_sha
        assert d1["original_unchanged"] is True
        assert any(i["extraction_method"] == "converted_oda" for i in d1["items"])
        assert sorted(a["area_native"] for a in d1["drawing_inventory"]["closed_areas"]) == [14.0, 24.0]

        conv_disk = settings.workspaces_dir / workspace_slug / d1["converted_artifact_relative_path"]
        assert conv_disk.is_file()

        res2 = client.post(f"/api/files/{f_dwg['id']}/extract")
        assert res2.status_code == 201
        assert res2.json()["extraction_version"] == 2


_RUN_REAL_ODA = os.getenv("RUN_REAL_ODA", "").strip().lower() in {"1", "true", "yes"}
_ODA_CAP = detect_oda("")


@pytest.mark.real_oda
@pytest.mark.skipif(
    not (_RUN_REAL_ODA and _ODA_CAP.installed),
    reason="Opt-in test: set RUN_REAL_ODA=1 with ODA File Converter installed to execute live DWG conversion",
)
def test_optin_real_oda_converter_dwg_to_dxf(tmp_path: Path) -> None:
    """Opt-in live ODA File Converter test on committed sanitized DWG fixture."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    dwg_bytes = (FIXTURES_DIR / "sample_clinic_plan.dwg").read_bytes()

    with TestClient(app) as client:
        caps = client.get("/api/extraction/capabilities").json()
        assert caps["oda"]["installed"] is True
        assert caps["oda"]["status"] == "installed"

        project_id, workspace_slug = _create_project(client)
        f_dwg = _upload_file(client, project_id, "sample_clinic_plan.dwg", dwg_bytes, "application/acad")
        res = client.post(f"/api/files/{f_dwg['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["status"] == "extracted"
        assert data["original_unchanged"] is True
        assert data["converter_status"] == "installed"
        assert data["cad_units"] == "m ($INSUNITS=6)"
        assert data["converted_artifact_relative_path"].endswith("/r1/converted/sample_clinic_plan.dxf")
        assert (settings.workspaces_dir / workspace_slug / data["converted_artifact_relative_path"]).is_file()

        inv = data["drawing_inventory"]
        assert "جدران-معمارية" in {layer["name"] for layer in inv["layers"]}
        assert sorted(round(a["area_native"], 4) for a in inv["closed_areas"]) == [14.0, 24.0]
        print(
            f"\nREAL ODA CONVERTER: version={caps['oda']['version']} | "
            f"units={data['cad_units']} | layers={data['counts']['layers']} | "
            f"blocks={data['counts']['blocks']} | closed_areas={sorted(round(a['area_native'], 4) for a in inv['closed_areas'])} | "
            f"converted={data['converted_artifact_relative_path']}"
        )


def test_extract_ifc_spaces_areas_elements_properties_and_known_limits(tmp_path: Path) -> None:
    """IFC extraction reads spaces with areas, walls/doors/windows, Pset/Qto, and flags missing areas/limits."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    ifc_bytes = (FIXTURES_DIR / "sample_clinic_model.ifc").read_bytes()

    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_ifc = _upload_file(client, project_id, "clinic_model.ifc", ifc_bytes, "application/x-step")
        orig_sha = f_ifc["sha256"]

        res = client.post(f"/api/files/{f_ifc['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()

        assert data["status"] == "extracted"
        assert data["sha256_before"] == orig_sha
        assert data["sha256_after"] == orig_sha
        assert data["original_unchanged"] is True
        assert "length=m" in data["cad_units"]
        assert "area=m2" in data["cad_units"]
        assert data["counts"]["ifc_spaces"] == 2
        assert data["counts"]["ifc_walls"] == 1
        assert data["counts"]["ifc_doors"] == 1
        assert data["counts"]["ifc_windows"] == 1

        inv = data["drawing_inventory"]
        assert inv["kind"] == "bim_ifc"
        assert inv["schema"] == "IFC4"
        spaces_by_name = {sp["name"]: sp for sp in inv["spaces"]}
        assert spaces_by_name["غرفة الفحص 01"]["area"] == 18.75
        assert spaces_by_name["غرفة الفحص 01"]["area_source"] == "Qto_SpaceBaseQuantities.NetFloorArea"
        assert spaces_by_name["غرفة الانتظار"]["area"] is None
        assert spaces_by_name["غرفة الانتظار"]["area_source"] == "not_provided_in_ifc"

        wall_item = next(i for i in data["items"] if i["item_type"] == "bim_element" and "IfcWall" in i["location"])
        assert wall_item["properties"]["Pset_WallCommon"]["LoadBearing"] is True
        assert wall_item["quantities"]["Qto_WallBaseQuantities"]["NetSideArea"] == 21.0
        assert any("IfcSpace entity(ies) had no explicit Qto/property area" in w for w in data["warnings"])
        assert any("IfcSlab=1" in w for w in data["warnings"])
        assert any("Known IFC limit:" in w for w in data["warnings"])


def test_drawing_gemini_vision_summary_non_measurement_disclaimer_and_cap(tmp_path: Path) -> None:
    """Gemini Vision summary attaches non-measurement disclaimer, persists JSON artifact, and honors usage caps."""
    secret_store = _InMemorySecretStore("mock-vision-key-999")

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                return []

            def generate_content(self, **_kwargs: Any) -> Any:
                return SimpleNamespace(
                    text="{}",
                    parsed={
                        "drawing_title": "Sanitized Clinic Plan A-101",
                        "discipline_guess": "Architectural",
                        "visible_labels_and_notes": ["Operating Theatre", "AREA=24.00 m2 label"],
                        "key_elements_observed": ["Closed rectangular room perimeter", "Two door symbols"],
                        "uncertainty_notes": ["Visual interpretation only; exact CAD scale not measured by vision"],
                    },
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=120,
                        candidates_token_count=45,
                        total_token_count=165,
                        thoughts_token_count=0,
                        cached_content_token_count=0,
                    ),
                )

        return SimpleNamespace(models=_Models())

    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=secret_store, provider_client_factory=client_factory)
    dxf_bytes = (FIXTURES_DIR / "sample_clinic_plan.dxf").read_bytes()

    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_dxf = _upload_file(client, project_id, "vision_plan.dxf", dxf_bytes, "application/dxf")
        ext_data = client.post(f"/api/files/{f_dxf['id']}/extract").json()
        extraction_id = ext_data["id"]

        vis_res = client.post(
            f"/api/extractions/{extraction_id}/vision-summary",
            json={"page_number": 1, "complexity": "fast"},
        )
        assert vis_res.status_code == 201, vis_res.text
        vis = vis_res.json()
        assert vis["ai_interpretation_only"] is True
        assert "not a verified engineering measurement" in vis["disclaimer"].lower()
        assert vis["drawing_title"] == "Sanitized Clinic Plan A-101"
        assert vis["discipline_guess"] == "Architectural"
        assert vis["token_usage"]["total_tokens"] == 165
        assert (settings.workspaces_dir / workspace_slug / vis["artifact_relative_path"]).is_file()

        detail = client.get(f"/api/extractions/{extraction_id}").json()
        assert len(detail["vision_summaries"]) == 1

        # Missing page image returns 404 cleanly
        assert (
            client.post(
                f"/api/extractions/{extraction_id}/vision-summary",
                json={"page_number": 99},
            ).status_code
            == 404
        )


def test_extract_dxf_hatch_with_island_subtracts_hole_area(tmp_path: Path) -> None:
    """HATCH extractor computes NET area (outermost loop minus island holes) on committed fixture."""
    settings = _test_settings(tmp_path)
    app = create_app(settings)
    hatch_dxf = (FIXTURES_DIR / "sample_hatch_island.dxf").read_bytes()

    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_dxf = _upload_file(client, project_id, "hatch_island.dxf", hatch_dxf, "application/dxf")
        res = client.post(f"/api/files/{f_dxf['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()

        areas = data["drawing_inventory"]["closed_areas"]
        assert len(areas) == 1
        h = areas[0]
        assert h["type"] == "HATCH"
        assert h["gross_area_native"] == 100.0
        assert h["net_subtracted_area_native"] == 20.0
        assert "island_hole_area_native" not in h
        assert h["area_native"] == 80.0
        assert h["area_m2"] == 80.0
        assert h["island_count"] == 1
        assert h["area_basis"] == "net_outer_minus_islands"
        assert any("island hole(s); net area=80.0 m2" in w for w in data["warnings"])


def test_dwg_refuses_existing_converted_run_dir_with_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-existing r{n}/converted directory returns HTTP 409 and leaves its files completely untouched."""
    from app.services.extractors.oda import OdaProbe, convert_dwg_to_dxf
    from app.schemas.extraction import OdaCapabilityOut

    fake_oda = tmp_path / "ODAFileConverter.exe"
    fake_oda.write_bytes(b"stub")
    dwg_bytes = (FIXTURES_DIR / "sample_clinic_plan.dwg").read_bytes()

    called_subprocess = {"count": 0}

    def fake_convert_run(*_args: Any, **_kw: Any) -> SimpleNamespace:
        called_subprocess["count"] += 1
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.extractors.oda.subprocess.run", fake_convert_run)

    settings = _test_settings(tmp_path, oda_path=str(fake_oda))
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_dwg = _upload_file(client, project_id, "conflict_plan.dwg", dwg_bytes, "application/acad")

        converted_dir = (
            settings.workspaces_dir
            / workspace_slug
            / "03_Analysis"
            / "extractions"
            / f_dwg["id"]
            / "v1"
            / "r1"
            / "converted"
        )
        converted_dir.mkdir(parents=True, exist_ok=True)
        existing_file = converted_dir / "existing.dxf"
        existing_file.write_text("PRESERVE-ME-CONFLICT", encoding="utf-8")

        res = client.post(f"/api/files/{f_dwg['id']}/extract")
        assert res.status_code == 409
        assert "refusing to reuse or overwrite" in res.json()["detail"].lower()
        assert called_subprocess["count"] == 0
        assert existing_file.read_text(encoding="utf-8") == "PRESERVE-ME-CONFLICT"

    # Also prove direct convert_dwg_to_dxf refuses an existing converted target folder
    existing_only = tmp_path / "direct_converted"
    existing_only.mkdir(parents=True)
    (existing_only / "keep.dxf").write_text("DO-NOT-TOUCH", encoding="utf-8")
    src_dwg = tmp_path / "dummy.dwg"
    src_dwg.write_bytes(dwg_bytes)
    probe = OdaProbe(
        executable=str(fake_oda),
        capability=OdaCapabilityOut(
            installed=True, status="installed", version="27.10.0", message="ok"
        ),
    )
    with pytest.raises(FileExistsError):
        convert_dwg_to_dxf(src_dwg, output_dxf_dir=existing_only, source_filename="dummy.dwg", oda_probe=probe)
    assert (existing_only / "keep.dxf").read_text(encoding="utf-8") == "DO-NOT-TOUCH"


def test_extract_dxf_doubtful_inches_sets_null_area_m2_and_owner_confirm_unit(
    tmp_path: Path,
) -> None:
    """DXF declaring inches ($INSUNITS=1) with metric dimensions/areas must null area_m2 until owner confirms."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 1  # inches (suspect when dims are 3.0, 4.0, 4.9 and area=7032.67)
    msp = doc.modelspace()
    msp.add_linear_dim(base=(0, 10), p1=(0, 0), p2=(3.0, 0)).render()
    msp.add_linear_dim(base=(0, 12), p1=(0, 0), p2=(4.0, 0)).render()
    msp.add_linear_dim(base=(0, 14), p1=(0, 0), p2=(4.9, 0)).render()
    # Exact rectangle: w + h = 206.25 -> perimeter = 412.5, w * h = 7032.67 -> area = 7032.67
    w_rect = 163.14246109
    h_rect = 43.10753891
    msp.add_lwpolyline([(0, 0), (w_rect, 0), (w_rect, h_rect), (0, h_rect)], close=True)
    buf = StringIO()
    doc.write(buf)
    dxf_bytes = buf.getvalue().encode("utf-8")

    # Also build a genuinely mm-scaled plan (3000 x 4000 mm -> 12.0 m2) to verify no false positive
    mm_doc = ezdxf.new("R2018")
    mm_doc.header["$INSUNITS"] = 4
    mm_msp = mm_doc.modelspace()
    mm_msp.add_linear_dim(base=(0, 4500), p1=(0, 0), p2=(3000.0, 0)).render()
    mm_msp.add_linear_dim(base=(-500, 0), p1=(0, 0), p2=(0, 4000.0), angle=90).render()
    mm_msp.add_lwpolyline([(0, 0), (3000.0, 0), (3000.0, 4000.0), (0, 4000.0)], close=True)
    mm_buf = StringIO()
    mm_doc.write(mm_buf)

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, workspace_slug = _create_project(client)
        f_bad = _upload_file(client, project_id, "synthetic_inches_metric_scale.dxf", dxf_bytes, "application/dxf")
        orig_sha = f_bad["sha256"]

        res = client.post(f"/api/files/{f_bad['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["units_doubtful"] is True
        assert data["units_status"] == "doubtful"
        assert data["owner_confirmed_unit"] is None
        assert any("units doubtful - owner must confirm drawing unit" in w for w in data["warnings"])

        area_inv = data["drawing_inventory"]["closed_areas"][0]
        assert area_inv["area_native"] == pytest.approx(7032.67, abs=1e-2)
        assert area_inv["area_native_unit"] == "sq_in"
        assert area_inv["perimeter_native"] == pytest.approx(412.5, abs=1e-2)
        assert area_inv["area_m2"] is None
        area_items = [i for i in data["items"] if i["item_type"] == "cad_polyline_area"]
        assert len(area_items) == 1
        assert area_items[0]["quantities"]["area_m2"] is None

        # Owner explicitly confirms unit = 'm' per extraction
        conf_res = client.post(
            f"/api/extractions/{data['id']}/confirm-unit",
            json={"confirmed_unit": "m"},
        )
        assert conf_res.status_code == 200, conf_res.text
        confirmed = conf_res.json()
        assert confirmed["units_doubtful"] is False
        assert confirmed["units_status"] == "owner_confirmed"
        assert confirmed["owner_confirmed_unit"] == "m"
        assert "owner confirmed" in confirmed["cad_units"].lower()
        assert confirmed["sha256_after"] == orig_sha
        assert confirmed["original_unchanged"] is True

        conf_area = confirmed["drawing_inventory"]["closed_areas"][0]
        assert conf_area["area_native"] == pytest.approx(7032.67, abs=1e-2)
        assert conf_area["area_native_unit"] == "sq_in"
        assert conf_area["area_m2"] == pytest.approx(7032.67, abs=1e-2)
        conf_item = [i for i in confirmed["items"] if i["item_type"] == "cad_polyline_area"][0]
        assert conf_item["quantities"]["area_m2"] == pytest.approx(7032.67, abs=1e-2)

        conf_artifact = (
            settings.workspaces_dir
            / workspace_slug
            / f"03_Analysis/extractions/{f_bad['id']}/v1/r1/unit_confirmation_s1.json"
        )
        assert conf_artifact.is_file()
        with app.state.session_factory() as db:
            aud = db.scalar(
                select(AuditLog).where(
                    AuditLog.entity_id == data["id"],
                    AuditLog.action == "file.drawing_unit_confirmed",
                )
            )
            assert aud is not None
            assert aud.details_json["confirmed_unit"] == "m"

        # Re-extract passing confirmed_unit directly yields r2 already confirmed
        res_r2 = client.post(
            f"/api/files/{f_bad['id']}/extract",
            json={"confirmed_unit": "m"},
        )
        assert res_r2.status_code == 201
        d2 = res_r2.json()
        assert d2["extraction_version"] == 2
        assert d2["units_doubtful"] is False
        assert d2["owner_confirmed_unit"] == "m"
        assert d2["drawing_inventory"]["closed_areas"][0]["area_m2"] == pytest.approx(7032.67, abs=1e-2)

        # Genuine millimeter drawing is NOT flagged as doubtful
        f_mm = _upload_file(client, project_id, "valid_mm_room.dxf", mm_buf.getvalue().encode("utf-8"), "application/dxf")
        mm_data = client.post(f"/api/files/{f_mm['id']}/extract").json()
        assert mm_data["units_doubtful"] is False
        assert mm_data["units_status"] == "plausible"
        assert mm_data["drawing_inventory"]["closed_areas"][0]["area_m2"] == 12.0


def test_extract_dxf_cp1256_mojibake_arabic_and_preserves_raw_and_latin(tmp_path: Path) -> None:
    """CP1256 mojibake decoded from Latin-1/ANSI_1252 is recovered across blocks/layers/text while keeping raw strings."""
    mojibake_block = "ÔÌÑÉ ãáæäÉ"  # 'شجرة ملونة'.encode('cp1256').decode('latin-1')
    mojibake_phrase = "ÛÑÝÉ æ ãÎÒä"  # 'غرفة و مخزن'.encode('cp1256').decode('latin-1') (includes 1-letter 'و')
    mojibake_layer = "ÃÚãÏÉ_Arch"  # 'أعمدة_Arch'

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.header["$DWGCODEPAGE"] = "ANSI_1252"  # simulates ODA output losing CP1256 codepage
    doc.layers.add(mojibake_layer)
    blk = doc.blocks.new(mojibake_block)
    blk.add_circle((0, 0), radius=0.5)
    blk.add_attdef("TYPE", (0, 1))

    msp = doc.modelspace()
    ins = msp.add_blockref(mojibake_block, (2, 2))
    ins.add_auto_attribs({"TYPE": mojibake_block})
    msp.add_text(mojibake_phrase, dxfattribs={"layer": mojibake_layer, "insert": (1, 1)})
    msp.add_text("Café", dxfattribs={"insert": (1, 2)})
    msp.add_text("Résumé", dxfattribs={"insert": (1, 3)})
    msp.add_text("Ø 20mm", dxfattribs={"insert": (1, 4)})
    msp.add_text("20 m²", dxfattribs={"insert": (1, 5)})
    msp.add_mtext(mojibake_block, dxfattribs={"layer": mojibake_layer, "insert": (2, 4)})
    msp.add_linear_dim(
        base=(0, 8),
        p1=(0, 0),
        p2=(5.0, 0),
        text=mojibake_phrase,
    ).render()

    buf = StringIO()
    doc.write(buf)
    dxf_bytes = buf.getvalue().encode("utf-8")

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        project_id, _ = _create_project(client)
        f_dxf = _upload_file(client, project_id, "cp1256_mojibake.dxf", dxf_bytes, "application/dxf")
        res = client.post(f"/api/files/{f_dxf['id']}/extract")
        assert res.status_code == 201, res.text
        data = res.json()

        inv = data["drawing_inventory"]
        blocks_by_name = {b["name"]: b for b in inv["blocks"]}
        assert "شجرة ملونة" in blocks_by_name
        assert blocks_by_name["شجرة ملونة"]["raw_name"] == mojibake_block
        assert blocks_by_name["شجرة ملونة"]["encoding_recovered"] == "cp1256_mojibake_decoded"
        assert blocks_by_name["شجرة ملونة"]["insert_count"] == 1

        layers_by_name = {l["name"]: l for l in inv["layers"]}
        assert "أعمدة_Arch" in layers_by_name
        assert layers_by_name["أعمدة_Arch"]["raw_name"] == mojibake_layer

        text_items = [i for i in data["items"] if i["item_type"] == "text"]
        texts = {i["text"]: i for i in text_items}
        assert "غرفة و مخزن" in texts
        assert texts["غرفة و مخزن"]["raw_text"] == mojibake_phrase
        assert texts["غرفة و مخزن"]["layer"] == "أعمدة_Arch"
        assert texts["غرفة و مخزن"]["raw_layer"] == mojibake_layer
        assert "شجرة ملونة" in texts
        assert texts["شجرة ملونة"]["layer"] == "أعمدة_Arch"
        assert "TYPE=شجرة ملونة" in texts
        assert texts["TYPE=شجرة ملونة"]["block_name"] == "شجرة ملونة"
        assert texts["TYPE=شجرة ملونة"]["raw_block_name"] == mojibake_block
        assert texts["TYPE=شجرة ملونة"]["raw_text"] == mojibake_block

        dim_inv = inv["dimensions"][0]
        assert dim_inv["override_text"] == "غرفة و مخزن"
        assert dim_inv["raw_override_text"] == mojibake_phrase

        # European Latin / diameter / unit symbols must NOT be falsely decoded as Arabic
        assert "Café" in texts
        assert "Résumé" in texts
        assert "Ø 20mm" in texts
        assert "20 m²" in texts
