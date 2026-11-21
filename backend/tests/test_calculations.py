"""Tests for Step 13 deterministic engineering calculation framework (electrical & plumbing), sourced references, DOCX/PDF/XLSX export, and QA Agent checks."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pymupdf
import pytest

from app.core.config import Settings
from app.db.models import Calculation, Deliverable, ResearchSource, Task
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.calculations import (
    BUILTIN_DATA_PROVENANCE,
    OWNER_DATA_PROVENANCE,
    VERIFY_CODE_LABEL,
)
from app.services.calc_export import sha256_file
from app.services.workspace import resolve_project_file_path
from app.skills.calculations import (
    calculate_electrical_cable_sizing,
    calculate_electrical_load_schedule,
    calculate_electrical_voltage_drop,
    calculate_plumbing_pipe_sizing,
    calculate_plumbing_water_demand,
)


class _InMemorySecretStore(SecretStore):
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

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


def test_step13_hand_checked_electrical_and_plumbing_unit_calculations() -> None:
    """Verify all 5 deterministic Python calculators against hand-checked engineering examples."""
    # 1. Electrical Load Schedule
    load_ev = calculate_electrical_load_schedule(
        {
            "panel_name": "MDB-CLINIC-01",
            "system_voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "spare_capacity_pct": 20.0,
            "max_phase_unbalance_pct": 15.0,
            "feeder_capacity_a": 100.0,
            "circuits": [
                {"circuit_id": "C-01", "description": "Lighting", "connected_load_kw": 6.0, "demand_factor": 0.9, "phase": "L1"},
                {"circuit_id": "C-02", "description": "Small Power", "connected_load_kw": 8.0, "demand_factor": 0.7, "phase": "L2"},
                {"circuit_id": "C-03", "description": "Diagnostics", "connected_load_kw": 7.5, "demand_factor": 0.8, "phase": "L3"},
                {"circuit_id": "C-04", "description": "HVAC", "connected_load_kw": 18.0, "demand_factor": 0.85, "phase": "3ph"},
            ],
        }
    )
    assert load_ev.acceptance_passed is True
    assert load_ev.results["total_connected_kw"] == pytest.approx(39.5, rel=1e-4)
    assert load_ev.results["total_demand_kw"] == pytest.approx(32.3, rel=1e-4)
    assert load_ev.results["design_load_kw"] == pytest.approx(38.76, rel=1e-4)
    assert load_ev.results["design_apparent_kva"] == pytest.approx(45.5999, rel=1e-3)
    assert load_ev.results["design_current_a"] == pytest.approx(65.8178, rel=1e-3)
    assert load_ev.results["phase_l1_kw"] == pytest.approx(10.5, rel=1e-4)
    assert load_ev.results["phase_l2_kw"] == pytest.approx(10.7, rel=1e-4)
    assert load_ev.results["phase_l3_kw"] == pytest.approx(11.1, rel=1e-4)
    assert load_ev.results["phase_unbalance_pct"] == pytest.approx(5.5728, rel=1e-3)
    assert load_ev.results["data_provenance"] == OWNER_DATA_PROVENANCE
    assert load_ev.results["acceptance_outcome_label"] == "PASS"
    assert load_ev.equations and load_ev.method and load_ev.assumptions and load_ev.units and load_ev.acceptance_criteria

    # 2. Electrical Cable Sizing (ampacity-governed vs voltage-drop-governed; built-in baseline table)
    cable_short = calculate_electrical_cable_sizing(
        {
            "circuit_name": "FEEDER-HVAC-01",
            "design_power_kw": 18.0,
            "voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "length_m": 45.0,
            "conductor_material": "copper",
            "insulation_type": "XLPE_90C",
            "ambient_temp_factor": 0.87,
            "grouping_factor": 0.80,
            "max_voltage_drop_pct": 3.0,
        }
    )
    assert cable_short.acceptance_passed is True
    assert cable_short.results["design_current_a"] == pytest.approx(30.5655, rel=1e-3)
    assert cable_short.results["breaker_rating_a"] == 32.0
    assert cable_short.results["total_derating_factor"] == pytest.approx(0.696, rel=1e-4)
    assert cable_short.results["selected_cable_size_mm2"] == 6.0
    assert cable_short.results["voltage_drop_pct"] == pytest.approx(1.88, rel=1e-2)
    assert cable_short.results["governing_criterion"] == "ampacity"
    assert cable_short.results["data_provenance"] == BUILTIN_DATA_PROVENANCE
    assert cable_short.results["acceptance_outcome_label"] == "PRELIMINARY PASS (built-in baseline data)"

    # Long run forces step-up due to 3% voltage drop cap
    cable_long = calculate_electrical_cable_sizing(
        {
            "circuit_name": "FEEDER-LONG-01",
            "design_power_kw": 18.0,
            "voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "length_m": 100.0,
            "conductor_material": "copper",
            "insulation_type": "XLPE_90C",
            "ambient_temp_factor": 0.87,
            "grouping_factor": 0.80,
            "max_voltage_drop_pct": 3.0,
        }
    )
    assert cable_long.acceptance_passed is True
    assert cable_long.results["selected_cable_size_mm2"] == 10.0
    assert cable_long.results["governing_criterion"] == "voltage_drop"
    assert cable_long.results["data_provenance"] == BUILTIN_DATA_PROVENANCE

    # 3. Electrical Voltage Drop (hand-checked 16 mm2 Cu at 70C; built-in resistance physics when r_ohm_per_km omitted)
    vd_ev = calculate_electrical_voltage_drop(
        {
            "circuit_name": "SUBMAIN-LAB-01",
            "load_current_a": 45.0,
            "voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "length_m": 80.0,
            "cable_size_mm2": 16.0,
            "conductor_material": "copper",
            "conductor_temp_c": 70.0,
            "x_ohm_per_km": 0.08,
            "upstream_drop_pct": 1.0,
            "max_total_drop_pct": 5.0,
        }
    )
    assert vd_ev.acceptance_passed is True
    assert vd_ev.results["resistance_ohm_per_km"] == pytest.approx(1.2893, rel=1e-3)
    assert vd_ev.results["voltage_drop_v"] == pytest.approx(7.0962, rel=1e-3)
    assert vd_ev.results["circuit_voltage_drop_pct"] == pytest.approx(1.7740, rel=1e-3)
    assert vd_ev.results["total_voltage_drop_pct"] == pytest.approx(2.7740, rel=1e-3)
    assert vd_ev.results["receiving_voltage_v"] == pytest.approx(388.904, rel=1e-3)
    assert vd_ev.results["data_provenance"] == BUILTIN_DATA_PROVENANCE
    assert vd_ev.results["acceptance_outcome_label"] == "PRELIMINARY PASS (built-in baseline data)"

    # Failing voltage drop when limit is tight
    vd_fail = calculate_electrical_voltage_drop(
        {
            "circuit_name": "SUBMAIN-FAIL",
            "load_current_a": 45.0,
            "voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "length_m": 80.0,
            "cable_size_mm2": 16.0,
            "upstream_drop_pct": 4.0,
            "max_total_drop_pct": 5.0,
        }
    )
    assert vd_fail.acceptance_passed is False
    assert vd_fail.results["acceptance_outcome_label"] == "PRELIMINARY FAIL (built-in baseline data)"

    # 4. Plumbing Water Demand (21.5 WSFU Hunter flush-tank interpolation; built-in WSFU + Hunter table)
    wd_ev = calculate_plumbing_water_demand(
        {
            "system_name": "CWS-CLINIC-01",
            "building_type": "clinic_office",
            "conversion_method": "hunter_flush_tank",
            "fixtures": [
                {"fixture_type": "wc_flush_tank", "count": 4},
                {"fixture_type": "lavatory", "count": 6},
                {"fixture_type": "service_sink", "count": 1},
                {"fixture_type": "kitchen_sink", "count": 2},
            ],
            "occupants_or_units": 45,
            "daily_demand_l_per_person": 80.0,
            "storage_autonomy_days": 1.0,
            "static_head_m": 12.0,
            "friction_and_residual_head_m": 18.0,
            "pump_efficiency": 0.65,
        }
    )
    assert wd_ev.acceptance_passed is True
    assert wd_ev.results["total_wsfu"] == pytest.approx(21.5, rel=1e-4)
    assert wd_ev.results["peak_flow_gpm"] == pytest.approx(17.675, rel=1e-4)
    assert wd_ev.results["peak_flow_lps"] == pytest.approx(1.1151, rel=1e-3)
    assert wd_ev.results["daily_demand_m3"] == pytest.approx(3.6, rel=1e-4)
    assert wd_ev.results["storage_tank_m3"] == pytest.approx(3.6, rel=1e-4)
    assert wd_ev.results["hydraulic_power_kw"] == pytest.approx(0.3281, rel=1e-2)
    assert wd_ev.results["pump_shaft_power_kw"] == pytest.approx(0.5048, rel=1e-2)
    assert wd_ev.results["data_provenance"] == BUILTIN_DATA_PROVENANCE
    assert wd_ev.results["acceptance_outcome_label"] == "PRELIMINARY PASS (built-in baseline data)"

    # 5. Plumbing Pipe Sizing (1.5 L/s PPR_PN20 SDR 6 auto-selects DN63 — NOT DN40!)
    # Hand calculation (PPR_PN20 SDR 6, Q = 1.5 L/s = 0.0015 m3/s, eps = 0.0015 mm, nu = 1.004e-6 m2/s):
    #   DN40 (OD = 40.0 mm, wall = 6.7 mm, ID = 40.0 - 2*6.7 = 26.6 mm):
    #     A = pi * (0.0266)^2 / 4 = 5.557163e-4 m^2
    #     v = 0.0015 / 5.557163e-4 = 2.6992 m/s  (> 1.5 m/s limit -> FAIL!)
    #   DN50 (OD = 50.0 mm, wall = 8.3 mm, ID = 50.0 - 2*8.3 = 33.4 mm):
    #     A = pi * (0.0334)^2 / 4 = 8.761588e-4 m^2
    #     v = 0.0015 / 8.761588e-4 = 1.7120 m/s  (> 1.5 m/s limit -> FAIL!)
    #   DN63 (OD = 63.0 mm, wall = 10.5 mm, ID = 63.0 - 2*10.5 = 42.0 mm):
    #     A = pi * (0.0420)^2 / 4 = 1.385442e-3 m^2
    #     v = 0.0015 / 1.385442e-3 = 1.0827 m/s  (<= 1.5 m/s -> PASS!)
    #     Re = 1.082687 * 0.042 / 1.004e-6 = 45291.7 ; f = 0.021370 ; hf_100 = 3.041 m/100m (<= 5.0 -> PASS!)
    pipe_ev = calculate_plumbing_pipe_sizing(
        {
            "pipe_run_name": "RISER-CWS-MAIN",
            "flow_rate_lps": 1.5,
            "pipe_length_m": 35.0,
            "pipe_material": "PPR_PN20",
            "max_velocity_mps": 1.5,
            "max_head_loss_m_per_100m": 5.0,
            "minor_loss_allowance_pct": 15.0,
        }
    )
    assert pipe_ev.acceptance_passed is True
    assert pipe_ev.results["selected_nominal_diameter_mm"] == 63.0
    assert pipe_ev.results["outer_diameter_mm"] == 63.0
    assert pipe_ev.results["wall_thickness_mm"] == 10.5
    assert pipe_ev.results["internal_diameter_mm"] == 42.0
    assert pipe_ev.results["velocity_mps"] == pytest.approx(1.0827, rel=1e-3)
    assert pipe_ev.results["head_loss_m_per_100m"] == pytest.approx(3.041, rel=1e-3)
    assert pipe_ev.results["data_provenance"] == BUILTIN_DATA_PROVENANCE
    assert pipe_ev.results["acceptance_outcome_label"] == "PRELIMINARY PASS (built-in baseline data)"
    assert any(
        r["nominal_diameter_mm"] == 40.0 and r["internal_diameter_mm"] == 26.6 and "PRELIMINARY FAIL" in r["status"]
        for r in pipe_ev.results["evaluated_sizes"]
    )

    # Explicit check: PPR_PN20 DN40 at 1.5 L/s has ID=26.6 mm, v=2.6992 m/s and FAILS the 1.5 m/s limit!
    pipe_dn40 = calculate_plumbing_pipe_sizing(
        {
            "pipe_run_name": "RISER-PPR-DN40-CHECK",
            "flow_rate_lps": 1.5,
            "pipe_length_m": 35.0,
            "pipe_material": "PPR_PN20",
            "nominal_diameter_mm": 40.0,
            "max_velocity_mps": 1.5,
        }
    )
    assert pipe_dn40.acceptance_passed is False
    assert pipe_dn40.results["outer_diameter_mm"] == 40.0
    assert pipe_dn40.results["wall_thickness_mm"] == 6.7
    assert pipe_dn40.results["internal_diameter_mm"] == 26.6
    assert pipe_dn40.results["velocity_mps"] == pytest.approx(2.6992, rel=1e-3)
    assert pipe_dn40.results["velocity_mps"] > 1.5
    assert pipe_dn40.results["data_provenance"] == BUILTIN_DATA_PROVENANCE
    assert pipe_dn40.results["acceptance_outcome_label"] == "PRELIMINARY FAIL (built-in baseline data)"


def test_step13_owner_supplied_overrides_and_data_provenance() -> None:
    """Verify owner-supplied inputs bypass built-in preliminary baseline labels across calculators."""
    # 1. Cable sizing with custom_ampacity_a (+ custom R/X) -> owner_supplied + PASS
    cable_owner = calculate_electrical_cable_sizing(
        {
            "circuit_name": "FEEDER-OWNER-01",
            "design_power_kw": 18.0,
            "voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "length_m": 45.0,
            "selected_size_mm2": 10.0,
            "custom_ampacity_a": 70.0,
            "custom_r_ohm_per_km": 1.83,
            "custom_x_ohm_per_km": 0.08,
            "ambient_temp_factor": 0.87,
            "grouping_factor": 0.80,
            "max_voltage_drop_pct": 3.0,
        }
    )
    assert cable_owner.acceptance_passed is True
    assert cable_owner.results["data_provenance"] == OWNER_DATA_PROVENANCE
    assert cable_owner.results["acceptance_outcome_label"] == "PASS"

    # 2. Voltage drop with custom r_ohm_per_km -> owner_supplied
    vd_owner = calculate_electrical_voltage_drop(
        {
            "circuit_name": "SUBMAIN-OWNER-01",
            "load_current_a": 45.0,
            "voltage_v": 400.0,
            "phases": "3ph",
            "power_factor": 0.85,
            "length_m": 80.0,
            "cable_size_mm2": 16.0,
            "r_ohm_per_km": 1.15,
            "x_ohm_per_km": 0.08,
            "upstream_drop_pct": 4.5,
            "max_total_drop_pct": 5.0,
        }
    )
    assert vd_owner.acceptance_passed is False
    assert vd_owner.results["data_provenance"] == OWNER_DATA_PROVENANCE
    assert vd_owner.results["acceptance_outcome_label"] == "FAIL"

    # 3. Water demand: wsfu_per_unit alone still uses built-in Hunter curve -> preliminary;
    #    wsfu_per_unit + custom_peak_flow_lps -> owner_supplied
    wd_partial = calculate_plumbing_water_demand(
        {
            "system_name": "CWS-HUNTER-ONLY",
            "fixtures": [{"fixture_type": "custom_wc", "count": 4, "wsfu_per_unit": 2.5}],
        }
    )
    assert wd_partial.results["data_provenance"] == BUILTIN_DATA_PROVENANCE
    assert wd_partial.results["acceptance_outcome_label"] == "PRELIMINARY PASS (built-in baseline data)"

    wd_owner = calculate_plumbing_water_demand(
        {
            "system_name": "CWS-OWNER-FULL",
            "fixtures": [{"fixture_type": "custom_wc", "count": 4, "wsfu_per_unit": 2.5}],
            "custom_peak_flow_lps": 1.25,
        }
    )
    assert wd_owner.results["data_provenance"] == OWNER_DATA_PROVENANCE
    assert wd_owner.results["acceptance_outcome_label"] == "PASS"

    # 4. Pipe sizing with owner internal_diameter_mm=40.0 -> bypasses table, yields v=1.1937 m/s, owner_supplied + PASS
    pipe_owner = calculate_plumbing_pipe_sizing(
        {
            "pipe_run_name": "RISER-CUSTOM-ID",
            "flow_rate_lps": 1.5,
            "pipe_length_m": 35.0,
            "pipe_material": "PPR_PN20",
            "nominal_diameter_mm": 63.0,
            "internal_diameter_mm": 40.0,
            "max_velocity_mps": 1.5,
        }
    )
    assert pipe_owner.acceptance_passed is True
    assert pipe_owner.results["internal_diameter_mm"] == 40.0
    assert pipe_owner.results["wall_thickness_mm"] == pytest.approx(11.5, rel=1e-4)
    assert pipe_owner.results["velocity_mps"] == pytest.approx(1.1937, rel=1e-3)
    assert pipe_owner.results["data_provenance"] == OWNER_DATA_PROVENANCE
    assert pipe_owner.results["acceptance_outcome_label"] == "PASS"

    # Also check uPVC and copper tables use internal bore ID rather than nominal OD/DN
    upvc_40 = calculate_plumbing_pipe_sizing(
        {
            "pipe_run_name": "UPVC-DN40",
            "flow_rate_lps": 1.5,
            "pipe_length_m": 20.0,
            "pipe_material": "uPVC",
            "nominal_diameter_mm": 40.0,
        }
    )
    assert upvc_40.results["outer_diameter_mm"] == 40.0
    assert upvc_40.results["internal_diameter_mm"] == 32.6
    assert upvc_40.acceptance_passed is False  # v ~ 1.797 m/s > 1.5 m/s
    copper_40 = calculate_plumbing_pipe_sizing(
        {
            "pipe_run_name": "CU-DN40",
            "flow_rate_lps": 1.5,
            "pipe_length_m": 20.0,
            "pipe_material": "copper",
            "nominal_diameter_mm": 40.0,
        }
    )
    assert copper_40.results["internal_diameter_mm"] == 38.3
    assert copper_40.acceptance_passed is True  # v ~ 1.302 m/s <= 1.5 m/s


def test_step13_reference_validation_exports_docx_pdf_xlsx_and_qa_checks(tmp_path: Path) -> None:
    """Verify API lifecycle, strict owner/verified-log reference gating, DOCX/PDF/XLSX export, and Step 12 QA Agent checks."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "مشروع حسابات العيادة", "code": "CALC-13", "classification": "For Review"},
        ).json()
        pid = project["id"]
        ws_slug = project["workspace_slug"]

        # Seed one reviewed ResearchSource + one unreviewed (HTTP 403) ResearchSource + one Task
        with app.state.session_factory() as db:
            rev_src = ResearchSource(
                project_id=pid,
                source_name="Verified Electrical Engineering Guide",
                url="https://standards.example.org/verified-guide",
                publication_date="2025-05-01",
                accessed_at=datetime.now(timezone.utc),
                reliability_assessment="reputable",
                source_type="web",
                source_priority_tier="standards_bodies",
                priority_rank=2,
                access_status="accessible",
                reviewed=True,
                http_status=200,
                untrusted_neutralized=True,
            )
            unrev_src = ResearchSource(
                project_id=pid,
                source_name="Unreviewed Paywalled Source",
                url="https://blocked.example.invalid/code",
                accessed_at=datetime.now(timezone.utc),
                reliability_assessment="unreviewed",
                source_type="web",
                source_priority_tier="unverified",
                priority_rank=99,
                access_status="inaccessible",
                reviewed=False,
                http_status=403,
                untrusted_neutralized=True,
            )
            task = Task(
                project_id=pid,
                title="MEP Electrical & Plumbing Calculations",
                prompt="Run deterministic electrical and plumbing calculations",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={
                    "expected_deliverables": ["Engineering Calculation"],
                },
            )
            db.add_all([rev_src, unrev_src, task])
            db.commit()
            rev_src_id = rev_src.id
            unrev_src_id = unrev_src.id
            tid = task.id

        # 1. Presets endpoint returns all 5 synthetic presets
        presets_res = client.get("/api/calculations/presets")
        assert presets_res.status_code == 200
        presets = presets_res.json()["presets"]
        assert len(presets) == 5

        sample_inputs = presets[0]["inputs"]

        # 2. Missing, unreviewed, or fabricated URL references MUST be rejected HTTP 422
        assert client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "title": "No Refs Calc",
                "calculation_type": "electrical_load_schedule",
                "inputs": sample_inputs,
                "references": [],
            },
        ).status_code == 422

        assert client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "title": "Unreviewed Ref Calc",
                "calculation_type": "electrical_load_schedule",
                "inputs": sample_inputs,
                "references": [
                    {
                        "source_kind": "verified_source_log",
                        "source_name": "Paywalled",
                        "source_ref": "https://blocked.example.invalid/code",
                        "research_source_id": unrev_src_id,
                    }
                ],
            },
        ).status_code == 422

        assert client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "title": "Fake URL in Owner Ref",
                "calculation_type": "electrical_load_schedule",
                "inputs": sample_inputs,
                "references": [
                    {
                        "source_kind": "owner_supplied",
                        "source_name": "Fake Web Claim",
                        "source_ref": "https://invented-clause.invalid/999",
                    }
                ],
            },
        ).status_code == 422

        # 3. Create valid calculations (Arabic load schedule + English pipe sizing with verified_source_log)
        calc_ar_res = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "title": "جدول أحمال العيادة الرئيسي",
                "calculation_type": "electrical_load_schedule",
                "language": "ar",
                "classification": "For Review",
                "inputs": sample_inputs,
                "references": [presets[0]["default_reference"]],
            },
        )
        assert calc_ar_res.status_code == 201, calc_ar_res.text
        calc_ar = calc_ar_res.json()
        cid_ar = calc_ar["id"]
        assert calc_ar["tokens_used"] == 0
        assert calc_ar["acceptance_passed"] is True
        assert calc_ar["data_provenance"] == OWNER_DATA_PROVENANCE
        assert calc_ar["acceptance_outcome_label"] == "PASS"
        assert calc_ar["references"][0]["verification_label"] == VERIFY_CODE_LABEL
        assert VERIFY_CODE_LABEL in calc_ar["references_text"]

        calc_en_res = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "title": "Main Cold Water Riser Sizing",
                "calculation_type": "plumbing_pipe_sizing",
                "language": "en",
                "classification": "For Review",
                "inputs": presets[4]["inputs"],
                "references": [
                    {
                        "source_kind": "verified_source_log",
                        "source_name": "Verified Electrical Engineering Guide",
                        "source_ref": "https://standards.example.org/verified-guide",
                        "research_source_id": rev_src_id,
                    }
                ],
            },
        )
        assert calc_en_res.status_code == 201, calc_en_res.text
        calc_en = calc_en_res.json()
        cid_en = calc_en["id"]
        assert calc_en["data_provenance"] == BUILTIN_DATA_PROVENANCE
        assert calc_en["acceptance_outcome_label"] == "PRELIMINARY PASS (built-in baseline data)"
        assert calc_en["results"]["selected_nominal_diameter_mm"] == 63.0
        assert calc_en["results"]["internal_diameter_mm"] == 42.0

        # 4. Update calculation inputs via PATCH increments version cleanly
        patch_res = client.patch(
            f"/api/calculations/{cid_en}",
            json={"inputs": {**presets[4]["inputs"], "pipe_length_m": 42.0}},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["version"] == 2
        assert patch_res.json()["inputs"]["pipe_length_m"] == 42.0

        # 5. Export both Arabic and English calculations to DOCX + PDF + XLSX in 04_Engineering_Calculations
        for cid_target, exp_lang in ((cid_ar, "ar"), (cid_en, "en")):
            exp_res = client.post(f"/api/calculations/{cid_target}/export", json={"language": exp_lang})
            assert exp_res.status_code == 201, exp_res.text
            exp_data = exp_res.json()
            for fmt_key in ("docx_deliverable", "pdf_deliverable", "xlsx_deliverable"):
                deliv = exp_data[fmt_key]
                assert deliv["folder_name"] == "04_Engineering_Calculations"
                assert deliv["calculation_id"] == cid_target
                dl = client.get(deliv["download_url"])
                assert dl.status_code == 200
                disk_p = resolve_project_file_path(settings.workspaces_dir, ws_slug, deliv["relative_path"])
                assert disk_p.is_file()

        # Verify DOCX, PDF, and XLSX live Excel formulas for load schedule
        ar_detail = client.get(f"/api/calculations/{cid_ar}").json()
        by_fmt = {d["format"]: d for d in ar_detail["deliverables"]}
        docx_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, by_fmt["docx"]["relative_path"])
        pdf_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, by_fmt["pdf"]["relative_path"])
        xlsx_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, by_fmt["xlsx"]["relative_path"])

        doc = DocxDocument(str(docx_path))
        docx_txt = "\n".join(p.text for p in doc.paragraphs)
        assert VERIFY_CODE_LABEL in docx_txt
        assert "جدول أحمال العيادة الرئيسي" in docx_txt

        with pymupdf.open(str(pdf_path)) as pdf_doc:
            pdf_txt = "\n".join(page.get_text("text") for page in pdf_doc)
        pdf_norm = " ".join(pdf_txt.replace("\xa0", " ").replace("\xad", "-").split())
        assert VERIFY_CODE_LABEL in pdf_norm
        assert "MDB-CLINIC-01" in pdf_norm

        wb = load_workbook(str(xlsx_path), data_only=False)
        try:
            ws = wb.active
            assert ws is not None
            assert OWNER_DATA_PROVENANCE in str(ws["A4"].value)
            formulas = [
                ws.cell(row=r, column=c).value
                for r in range(1, ws.max_row + 1)
                for c in range(1, ws.max_column + 1)
                if isinstance(ws.cell(row=r, column=c).value, str)
                and str(ws.cell(row=r, column=c).value).startswith("=")
            ]
            assert any("SUM(" in f for f in formulas)
            assert any("SQRT(3)" in f for f in formulas)
            assert len(wb.sheetnames) == 2
        finally:
            wb.close()

        # Verify DOCX, PDF, and XLSX headers/formulas for pipe sizing (cid_en — built-in preliminary data + internal bore ID)
        en_detail = client.get(f"/api/calculations/{cid_en}").json()
        en_by_fmt = {d["format"]: d for d in en_detail["deliverables"]}
        en_docx_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, en_by_fmt["docx"]["relative_path"])
        en_pdf_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, en_by_fmt["pdf"]["relative_path"])
        en_xlsx_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, en_by_fmt["xlsx"]["relative_path"])

        en_doc = DocxDocument(str(en_docx_path))
        en_docx_txt = "\n".join(p.text for p in en_doc.paragraphs)
        assert BUILTIN_DATA_PROVENANCE in en_docx_txt
        assert "PRELIMINARY PASS (built-in baseline data)" in en_docx_txt

        with pymupdf.open(str(en_pdf_path)) as en_pdf:
            en_pdf_txt = "\n".join(page.get_text("text") for page in en_pdf)
        en_pdf_norm = " ".join(en_pdf_txt.replace("\xa0", " ").replace("\xad", "-").split())
        assert BUILTIN_DATA_PROVENANCE in en_pdf_norm
        assert "PRELIMINARY PASS (built-in baseline data)" in en_pdf_norm

        en_wb = load_workbook(str(en_xlsx_path), data_only=False)
        try:
            en_ws = en_wb.active
            assert en_ws is not None
            assert BUILTIN_DATA_PROVENANCE in str(en_ws["A4"].value)
            assert "PRELIMINARY PASS (built-in baseline data)" in str(en_ws["A4"].value)
            id_row = [
                r for r in range(1, en_ws.max_row + 1) if en_ws.cell(row=r, column=1).value == "internal_diameter_mm"
            ][-1]
            area_formula = next(
                str(en_ws.cell(row=r, column=2).value)
                for r in range(1, en_ws.max_row + 1)
                if en_ws.cell(row=r, column=1).value == "Internal Pipe Area (m2)"
            )
            assert f"POWER(B{id_row}/1000,2)" in area_formula
            live_verdict = next(
                str(en_ws.cell(row=r, column=2).value)
                for r in range(1, en_ws.max_row + 1)
                if en_ws.cell(row=r, column=1).value == "Live Acceptance Check"
            )
            assert "PRELIMINARY PASS (built-in baseline data)" in live_verdict
        finally:
            en_wb.close()

        # 6. Run Step 12 QA Agent on clean exported Step 13 calculations -> PASSES at 0 AI tokens and allows /verify
        qa_pass_res = client.post(
            f"/api/projects/{pid}/qa-reviews",
            json={"task_id": tid, "classification": "For Review"},
        )
        assert qa_pass_res.status_code == 201, qa_pass_res.text
        qa_pass = qa_pass_res.json()
        assert qa_pass["status"] == "passed"
        assert qa_pass["tokens_used"] == 0
        assert set(qa_pass["qa_context_summary"]["inspected_calculation_ids"]) == {cid_ar, cid_en}
        assert qa_pass["task_verification_status"] == "qa_passed"

        verify_ok = client.post(
            f"/api/tasks/{tid}/verify",
            json={"qa_review_id": qa_pass["id"], "verifier_note": "Calculations QA passed"},
        )
        assert verify_ok.status_code == 200
        assert verify_ok.json()["verification_status"] == "verified"

        # 7. Seed defects onto Calculation in DB and verify QA Agent catches arithmetic tampering, unit error, missing label/bad ref, and corrupt XLSX!
        with app.state.session_factory() as db:
            bad_calc = db.get(Calculation, cid_en)
            assert bad_calc is not None
            tampered = dict(bad_calc.results_json)
            tampered["velocity_mps"] = 0.25  # wrong velocity vs deterministic 1.0827 m/s
            tampered["acceptance_passed"] = False
            bad_calc.results_json = tampered
            bad_calc.acceptance_passed = False
            bad_units = dict(bad_calc.units_json or {})
            bad_units["pressure_drop_kpa"] = "psi"
            bad_calc.units_json = bad_units
            bad_calc.references_json = [
                {
                    "source_kind": "verified_source_log",
                    "source_name": "Tampered",
                    "source_ref": "https://fake-calc-source.invalid/bad",
                    "verification_label": "",
                }
            ]
            bad_calc.references_text = "https://fake-calc-source.invalid/bad"

            # Corrupt exported XLSX for cid_en (with updated sha256 to specifically trigger XLSX integrity check)
            xlsx_deliv = (
                db.query(Deliverable)
                .filter(Deliverable.calculation_id == cid_en, Deliverable.format == "xlsx")
                .first()
            )
            assert xlsx_deliv is not None and xlsx_deliv.relative_path
            corrupt_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, xlsx_deliv.relative_path)
            corrupt_path.write_bytes(b"CORRUPT_CALC_XLSX")
            xlsx_deliv.sha256 = sha256_file(corrupt_path)
            db.commit()

        qa_fail_res = client.post(
            f"/api/projects/{pid}/qa-reviews",
            json={"task_id": tid, "classification": "For Review"},
        )
        assert qa_fail_res.status_code == 201
        qa_fail = qa_fail_res.json()
        assert qa_fail["status"] == "issues_found"
        assert qa_fail["task_verification_status"] == "qa_failed"
        cats = {it["check_category"] for it in qa_fail["issues"]}
        assert "arithmetic" in cats
        assert "unit" in cats
        assert "reference" in cats
        assert "schedule_consistency" in cats
        assert "integrity" in cats
