"""Tests for Step 18 HVAC, Fire & Healthcare skills (prepare & check only), hand-checked math, verified-only code gating, EN/AR exports, and QA defect traps."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pymupdf
import pytest

from app.core.config import Settings
from app.db.models import ResearchSource, SpecialistAssessment
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.specialist import (
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NOT_PROVIDED_LABEL,
    NO_VERIFIED_STANDARD_LABEL,
    PRELIMINARY_ENGINEER_LABEL_EN,
)
from app.services.workspace import resolve_project_file_path
from app.skills.specialist import (
    evaluate_specialist_assessment,
    get_synthetic_specialist_presets,
)


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


def _fake_specialist_ai_factory(captured_prompts: list[str]):
    class _Models:
        def list(self) -> list[Any]:
            return []

        def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
            captured_prompts.append(str(contents))
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "summary_prose": (
                            "Preliminary zone geometry and airflow sanity balance completed. "
                            "Submit prepared data to Carrier HAP and obtain licensed engineer sign-off."
                        )
                    }
                ),
                usage_metadata=SimpleNamespace(
                    prompt_token_count=110,
                    candidates_token_count=40,
                    total_token_count=150,
                ),
            )

    return lambda _api_key: SimpleNamespace(models=_Models())


def test_step18_hand_checked_hvac_fire_healthcare_and_missing_not_provided_blocks() -> None:
    """Verify hand-checked deterministic math across HVAC, Fire & Healthcare and missing-input 'not provided' blocking (SYNTHETIC ONLY)."""
    # -------------------------------------------------------------------------
    # HAND CHECK 1 — HVAC Zone Preparation & Sensible Airflow Balance:
    #   Synthetic zone Z-01: area = 60.0 m2, ceiling = 3.2 m -> volume = 60.0 * 3.2 = 192.0 m3.
    #   Owner OA rates: 8 persons * 7.5 L/s/p + 60.0 m2 * 0.6 L/s/m2 = 60.0 + 36.0 = 96.0 L/s.
    #   Reported OA = 100.0 L/s >= 96.0 -> PASS.
    #   Sensible heat Q = 6050.0 W, dT = 10.0 K, rho*cp factor = 1.21 kJ/(m3*K):
    #     expected_supply_airflow_ls = 6050.0 / (1.21 * 10.0) = 6050.0 / 12.1 = 500.0 L/s.
    #     supply_ach = (500.0 * 3.6) / 192.0 = 1800.0 / 192.0 = 9.375 ACH.
    #     sensible_w_per_m2 = 6050.0 / 60.0 = 100.8333 W/m2.
    #   If reported_supply_airflow_ls = 500.0 -> discrepancy = 0.0% <= 5.0% -> PASS.
    #   If reported_supply_airflow_ls = 400.0 -> discrepancy = |400-500|/500 * 100 = 20.0% > 5.0% -> FAIL.
    # -------------------------------------------------------------------------
    hvac_ok = evaluate_specialist_assessment(
        domain="hvac",
        workflow_mode="full_preflight",
        inputs={
            "air_heat_factor_kw_per_m3s": 1.21,
            "airflow_tolerance_pct": 5.0,
            "zones": [
                {
                    "zone_id": "Z-01",
                    "zone_name": "Synthetic Clinic Room",
                    "floor_area_m2": 60.0,
                    "ceiling_height_m": 3.2,
                    "occupancy_count": 8,
                    "oa_ls_per_person": 7.5,
                    "oa_ls_per_m2": 0.6,
                    "reported_sensible_load_w": 6050.0,
                    "supply_delta_t_k": 10.0,
                    "reported_supply_airflow_ls": 500.0,
                    "reported_outdoor_airflow_ls": 100.0,
                }
            ],
        },
    )
    assert hvac_ok.checks_passed is True
    assert hvac_ok.failed_checks_count == 0
    assert hvac_ok.blocked_missing_count == 0
    z_ok = hvac_ok.prepared_items[0]
    assert z_ok["room_volume_m3"] == pytest.approx(192.0, rel=1e-4)
    assert z_ok["expected_oa_ls"] == pytest.approx(96.0, rel=1e-4)
    assert z_ok["expected_supply_airflow_ls"] == pytest.approx(500.0, rel=1e-4)
    assert z_ok["supply_ach"] == pytest.approx(9.375, rel=1e-4)
    assert z_ok["sensible_w_per_m2"] == pytest.approx(100.8333, rel=1e-4)
    assert "Carrier HAP" in hvac_ok.software_recommendation
    assert any(PRELIMINARY_ENGINEER_LABEL_EN in a for a in hvac_ok.preliminary_assumptions)

    hvac_bad = evaluate_specialist_assessment(
        domain="hvac",
        workflow_mode="output_check",
        inputs={
            "zones": [
                {
                    "zone_id": "Z-01",
                    "zone_name": "Undersized Airflow Zone",
                    "floor_area_m2": 60.0,
                    "ceiling_height_m": 3.2,
                    "reported_sensible_load_w": 6050.0,
                    "supply_delta_t_k": 10.0,
                    "reported_supply_airflow_ls": 400.0,
                }
            ],
        },
    )
    assert hvac_bad.checks_passed is False
    assert hvac_bad.failed_checks_count == 1
    assert hvac_bad.prepared_items[0]["airflow_discrepancy_pct"] == pytest.approx(20.0, rel=1e-4)

    # -------------------------------------------------------------------------
    # HAND CHECK 2 — Fire Hydraulic Preparation & Pump / Tank Output Check:
    #   design_area = 200.0 m2, density = 4.1 mm/min -> sprinkler_flow = 200 * 4.1 = 820.0 L/min.
    #   hose_allowance = 380.0 L/min -> total_required_flow = 820.0 + 380.0 = 1200.0 L/min.
    #   duration = 60.0 min -> required_tank_volume_m3 = (1200.0 * 60.0) / 1000.0 = 72.0 m3.
    #   pump = 1250 >= 1200 (PASS), available 6.2 >= required 5.5 (+0.7 bar PASS), tank 75 >= 72 (PASS).
    # -------------------------------------------------------------------------
    fire_ok = evaluate_specialist_assessment(
        domain="fire",
        workflow_mode="full_preflight",
        inputs={
            "zones": [
                {
                    "zone_id": "FZ-01",
                    "zone_name": "Synthetic Fire Zone",
                    "design_area_m2": 200.0,
                    "design_density_mm_min": 4.1,
                    "hose_allowance_lpm": 380.0,
                    "duration_min": 60.0,
                    "reported_pump_flow_lpm": 1250.0,
                    "reported_available_pressure_bar": 6.2,
                    "required_system_pressure_bar": 5.5,
                    "reported_tank_volume_m3": 75.0,
                }
            ]
        },
    )
    assert fire_ok.checks_passed is True
    f_it = fire_ok.prepared_items[0]
    assert f_it["sprinkler_flow_lpm"] == pytest.approx(820.0, rel=1e-4)
    assert f_it["total_required_flow_lpm"] == pytest.approx(1200.0, rel=1e-4)
    assert f_it["required_tank_volume_m3"] == pytest.approx(72.0, rel=1e-4)
    assert "Elite Fire" in fire_ok.software_recommendation

    # -------------------------------------------------------------------------
    # HAND CHECK 3 — Healthcare Clinical Room Airflow, Pressure Polarity & Med Gas:
    #   Negative isolation room: 20.0 * 3.0 = 60.0 m3.
    #   supply = 180.0 L/s -> (180*3.6)/60 = 10.8 ACH; exhaust = 220.0 L/s -> (220*3.6)/60 = 13.2 ACH.
    #   effective_ach = max(10.8, 13.2) = 13.2 >= owner limit 12.0 -> PASS.
    #   oa = 50.0 L/s -> (50*3.6)/60 = 3.0 >= owner limit 2.0 -> PASS.
    #   air_balance_ls = 180.0 - 220.0 = -40.0 L/s (< 0 matches negative polarity -> PASS).
    #   measured_pressure_diff_pa = -5.0 <= -2.5 Pa -> PASS.
    #   Med gas O2: 4 * 20.0 * 0.75 = 60.0 L/min.
    # -------------------------------------------------------------------------
    hc_ok = evaluate_specialist_assessment(
        domain="healthcare",
        workflow_mode="full_preflight",
        inputs={
            "spaces": [
                {
                    "space_id": "HC-ISO-01",
                    "space_name": "Synthetic Isolation Room",
                    "floor_area_m2": 20.0,
                    "ceiling_height_m": 3.0,
                    "supply_airflow_ls": 180.0,
                    "exhaust_airflow_ls": 220.0,
                    "outdoor_airflow_ls": 50.0,
                    "required_total_ach": 12.0,
                    "required_oa_ach": 2.0,
                    "required_pressure_relationship": "negative",
                    "measured_pressure_diff_pa": -5.0,
                    "min_abs_pressure_diff_pa": 2.5,
                }
            ],
            "medical_gas_outlets": [
                {
                    "gas_name": "Synthetic O2",
                    "outlet_count": 4,
                    "flow_per_outlet_lpm": 20.0,
                    "diversity_factor": 0.75,
                }
            ],
        },
    )
    assert hc_ok.checks_passed is True
    hc_it = hc_ok.prepared_items[0]
    assert hc_it["room_volume_m3"] == pytest.approx(60.0, rel=1e-4)
    assert hc_it["supply_ach"] == pytest.approx(10.8, rel=1e-4)
    assert hc_it["exhaust_ach"] == pytest.approx(13.2, rel=1e-4)
    assert hc_it["effective_ach"] == pytest.approx(13.2, rel=1e-4)
    assert hc_it["oa_ach"] == pytest.approx(3.0, rel=1e-4)
    assert hc_it["air_balance_ls"] == pytest.approx(-40.0, rel=1e-4)
    assert hc_ok.metrics["total_diversified_medical_gas_lpm"] == pytest.approx(60.0, rel=1e-4)

    # -------------------------------------------------------------------------
    # MISSING INPUTS BLOCK CHECK -> 'not provided' (never guess ACH or geometry!)
    # -------------------------------------------------------------------------
    hc_missing = evaluate_specialist_assessment(
        domain="healthcare",
        workflow_mode="full_preflight",
        inputs={
            "spaces": [
                {
                    "space_id": "HC-MISS-01",
                    "space_name": "Missing Target ACH Room",
                    "floor_area_m2": 20.0,
                    "ceiling_height_m": 3.0,
                    "supply_airflow_ls": 180.0,
                    "exhaust_airflow_ls": 220.0,
                    "outdoor_airflow_ls": 50.0,
                    # Intentionally omit required_total_ach, required_oa_ach, required_pressure_relationship!
                }
            ]
        },
    )
    assert hc_missing.checks_passed is False
    assert hc_missing.status == "blocked_missing_inputs"
    assert hc_missing.blocked_missing_count == 3
    assert hc_missing.prepared_items[0]["required_total_ach"] == NOT_PROVIDED_LABEL
    assert hc_missing.prepared_items[0]["required_pressure_relationship"] == NOT_PROVIDED_LABEL

    presets = get_synthetic_specialist_presets()
    assert len(presets) == 3
    for p in presets:
        ev_p = evaluate_specialist_assessment(domain=p.domain, workflow_mode=p.workflow_mode, inputs=p.inputs)
        assert ev_p.checks_passed is True


def test_step18_api_standards_gating_zero_tokens_exports_en_ar_and_qa_pass(tmp_path: Path) -> None:
    """Verify verified-only standard citations (fallback 'no verified standard on file - verify against the locally adopted code'), 0 tokens default, EN/AR DOCX/PDF/XLSX exports, and QA pass."""
    app = create_app(
        settings=_test_settings(tmp_path),
        secret_store=_InMemorySecretStore(),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Synthetic Step 18 Clinic", "code": "SP-18", "classification": "Preliminary"},
        ).json()
        pid = project["id"]
        slug = project["workspace_slug"]

        # 1. Presets endpoint
        presets_res = client.get("/api/specialist-assessments/presets")
        assert presets_res.status_code == 200
        presets = presets_res.json()["presets"]
        assert len(presets) == 3

        # 2. Create HVAC assessment WITHOUT any verified standard -> MUST display exact fallback notice & 0 AI tokens!
        hvac_no_std = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "domain": "hvac",
                "workflow_mode": "full_preflight",
                "title": "HVAC Zone Preflight (No Standard On File)",
                "language": "en",
                "classification": "Preliminary",
                "inputs": presets[0]["inputs"],
                "references": [],
                "use_ai": False,
            },
        )
        assert hvac_no_std.status_code == 201, hvac_no_std.text
        h_data = hvac_no_std.json()
        assert h_data["tokens_used"] == 0
        assert h_data["standards_status"] == "no_verified_standard_on_file"
        assert h_data["references"][0]["verification_label"] == NO_VERIFIED_STANDARD_LABEL
        assert h_data["checks_passed"] is True
        assert "Carrier HAP" in h_data["software_recommendation"]

        # 3. Attempting to bind missing ResearchSource or StandardsLibrary ID rejects cleanly (422)
        bad_bind = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "domain": "healthcare",
                "workflow_mode": "output_check",
                "title": "Fake Standard Link Attempt",
                "inputs": presets[2]["inputs"],
                "references": [{"source_kind": "standard_library", "standard_library_id": "nonexistent-id"}],
            },
        )
        assert bad_bind.status_code == 422

        # 4. Register genuine verified WHO-SYN-2024 standard in Standards Library + reviewed FGI ResearchSource -> bind Healthcare assessment!
        std_who = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "WHO-SYN-2024",
                "title": "Synthetic Owner Healthcare Ventilation Standard",
                "issuing_body": "WHO Owner Licensed Copy",
                "edition_year": "2024",
                "status": "current",
                "adopted_locally": True,
            },
        ).json()

        with app.state.session_factory() as db:
            rs = ResearchSource(
                project_id=pid,
                source_name="FGI Synthetic Clinical Reference",
                url="https://standards.example.org/fgi-syn",
                publication_date="2022",
                query_text="healthcare room ach",
                relevant_info="Reviewed synthetic healthcare source note.",
                reliability_assessment="reputable",
                source_type="standards",
                source_priority_tier="standards_bodies",
                priority_rank=1,
                access_status="accessible",
                reviewed=True,
                untrusted_neutralized=True,
            )
            db.add(rs)
            db.commit()
            db.refresh(rs)
            rs_id = rs.id

        hc_res = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "domain": "healthcare",
                "workflow_mode": "full_preflight",
                "title": "Isolation & Clean Room Preflight (Verified WHO + FGI)",
                "language": "ar",
                "classification": "For Review",
                "inputs": presets[2]["inputs"],
                "references": [
                    {"source_kind": "standard_library", "standard_library_id": std_who["id"]},
                    {"source_kind": "verified_source_log", "research_source_id": rs_id},
                ],
                "use_ai": False,
            },
        )
        assert hc_res.status_code == 201, hc_res.text
        hc_data = hc_res.json()
        assert hc_data["standards_status"] == "verified_standards"
        assert hc_data["checks_passed"] is True
        aid = hc_data["id"]

        # 5. Export both AR RTL & EN LTR DOCX + PDF + live XLSX and verify SHA-256 + content + live formulas
        for exp_lang in ("ar", "en"):
            exp_res = client.post(
                f"/api/specialist-assessments/{aid}/export",
                json={"language": exp_lang},
            )
            assert exp_res.status_code == 201, exp_res.text
            exp_d = exp_res.json()
            for deliv_key in ("docx_deliverable", "pdf_deliverable", "xlsx_deliverable"):
                dm = exp_d[deliv_key]
                assert dm["folder_name"] == "04_Engineering_Calculations"
                p_disk = resolve_project_file_path(
                    _test_settings(tmp_path).workspaces_dir,
                    workspace_slug=slug,
                    relative_path=dm["relative_path"],
                )
                assert hashlib.sha256(p_disk.read_bytes()).hexdigest() == dm["sha256"]

            xlsx_p = resolve_project_file_path(
                _test_settings(tmp_path).workspaces_dir,
                workspace_slug=slug,
                relative_path=exp_d["xlsx_deliverable"]["relative_path"],
            )
            wb = load_workbook(xlsx_p, data_only=False)
            ws0 = wb["فحص التخصص" if exp_lang == "ar" else "Preflight Checks"]
            assert ws0.views.sheetView[0].rightToLeft is (exp_lang == "ar")
            all_vals = [cell.value for row in ws0.iter_rows() for cell in row]
            assert any(isinstance(v, str) and v.startswith("=COUNTIF(") for v in all_vals)

            pdf_p = resolve_project_file_path(
                _test_settings(tmp_path).workspaces_dir,
                workspace_slug=slug,
                relative_path=exp_d["pdf_deliverable"]["relative_path"],
            )
            with pymupdf.open(str(pdf_p)) as pdoc:
                pdf_raw = "\n".join(pg.get_text("text") for pg in pdoc)
            pdf_norm = " ".join(pdf_raw.replace("\xa0", " ").replace("\xad", "-").split())
            assert "WHO-SYN-2024" in pdf_norm
            assert "Carrier HAP" in pdf_norm

            docx_p = resolve_project_file_path(
                _test_settings(tmp_path).workspaces_dir,
                workspace_slug=slug,
                relative_path=exp_d["docx_deliverable"]["relative_path"],
            )
            ddoc = DocxDocument(str(docx_p))
            docx_txt = "\n".join(
                [p.text for p in ddoc.paragraphs]
                + [c.text for tbl in ddoc.tables for row in tbl.rows for c in row.cells]
            )
            assert "WHO-SYN-2024" in docx_txt

        # Also export hvac_no_std cleanly so both deliverables are complete on disk
        assert client.post(f"/api/specialist-assessments/{h_data['id']}/export", json={"language": "en"}).status_code == 201

        # 6. Run QA Agent -> MUST PASS and inspect both specialist assessments!
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_out = qa_res.json()
        assert qa_out["status"] == "passed", qa_out
        assert aid in qa_out["qa_context_summary"]["inspected_assessment_ids"]
        assert h_data["id"] in qa_out["qa_context_summary"]["inspected_assessment_ids"]


def test_step18_optional_ai_and_qa_catches_wrong_result_uncited_who_fgi_and_blocked_inputs(tmp_path: Path) -> None:
    """Verify optional AI draft requires owner approval and QA defect traps catch tampered/wrong math, uncited WHO/FGI/ASHRAE, and 'not provided' missing inputs."""
    captured_prompts: list[str] = []
    app = create_app(
        settings=_test_settings(tmp_path),
        secret_store=_InMemorySecretStore({"gemini": "AIzaSyntheticTestKey123456"}),
        provider_client_factory=_fake_specialist_ai_factory(captured_prompts),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Step 18 QA Trap Project", "code": "QASP-18", "classification": "For Review"},
        ).json()
        pid = project["id"]
        presets = client.get("/api/specialist-assessments/presets").json()["presets"]

        # 1. Optional AI draft -> UNVERIFIED AI DRAFT until explicit owner approval
        ai_res = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "domain": "fire",
                "workflow_mode": "full_preflight",
                "title": "Fire Preflight with Optional AI Note",
                "language": "en",
                "inputs": presets[1]["inputs"],
                "use_ai": True,
                "complexity": "fast",
            },
        )
        assert ai_res.status_code == 201, ai_res.text
        ai_d = ai_res.json()
        assert ai_d["tokens_used"] == 150
        assert len(captured_prompts) == 1
        assert ai_d["ai_draft_status"] == "unverified_ai_draft"
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in ai_d["ai_draft_label"]

        # Seed defect 1: Create assessment with tampered/wrong checks_passed & injected uncited WHO/ASHRAE text in DB
        bad_hvac = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "domain": "hvac",
                "workflow_mode": "output_check",
                "title": "Wrong Airflow & Uncited Standard Trap",
                "language": "en",
                "inputs": {
                    "zones": [
                        {
                            "zone_id": "Z-BAD",
                            "zone_name": "Wrong Supply Zone (ASHRAE 62.1 Uncited)",
                            "floor_area_m2": 60.0,
                            "ceiling_height_m": 3.2,
                            "reported_sensible_load_w": 6050.0,
                            "supply_delta_t_k": 10.0,
                            "reported_supply_airflow_ls": 350.0,  # Wrong (expected 500 -> 30% discrepancy -> FAIL)
                        }
                    ]
                },
            },
        ).json()
        assert bad_hvac["checks_passed"] is False

        # Tamper in DB to pretend checks_passed=True and inject uncited WHO/FGI citation without Standards Library / ResearchSource!
        with app.state.session_factory() as db:
            row = db.get(SpecialistAssessment, bad_hvac["id"])
            assert row is not None
            row.checks_passed = True
            row.failed_checks_count = 0
            row.summary = "Claiming compliance with WHO Guidelines and FGI 2022 without verification."
            db.add(row)
            db.commit()

        # Seed defect 2: Healthcare assessment missing required_total_ach ('not provided' blocks result)
        blocked_hc = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "domain": "healthcare",
                "workflow_mode": "full_preflight",
                "title": "Blocked Healthcare Missing ACH Trap",
                "language": "en",
                "inputs": {
                    "spaces": [
                        {
                            "space_id": "HC-BLK",
                            "space_name": "Missing Limits Isolation",
                            "floor_area_m2": 20.0,
                            "ceiling_height_m": 3.0,
                            "supply_airflow_ls": 180.0,
                            "exhaust_airflow_ls": 220.0,
                            "outdoor_airflow_ls": 50.0,
                        }
                    ]
                },
            },
        ).json()
        assert blocked_hc["status"] == "blocked_missing_inputs"
        assert blocked_hc["checks_passed"] is False

        # 2. Run QA Agent -> MUST return 'issues_found' catching:
        #    (a) arithmetic mismatch / tampered verdict on bad_hvac
        #    (b) unverified WHO / FGI / ASHRAE 62.1 citations absent from library & source log
        #    (c) blocked 'not provided' inputs + unapproved AI draft
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_out = qa_res.json()
        assert qa_out["status"] == "issues_found"

        cats = {i["check_category"] for i in qa_out["issues"]}
        assert "arithmetic" in cats
        assert "reference" in cats
        assert "schedule_consistency" in cats

        joined_refs = " | ".join(
            f"{i['title']} :: {i['description']}" for i in qa_out["issues"] if i["check_category"] == "reference"
        )
        assert "WHO" in joined_refs
        assert "FGI" in joined_refs
        assert "ASHRAE 62.1" in joined_refs

        joined_arith = " | ".join(
            f"{i['title']} :: {i['description']}" for i in qa_out["issues"] if i["check_category"] == "arithmetic"
        )
        assert "mismatch" in joined_arith.lower()
