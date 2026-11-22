"""Tests for Step 19 structural assessment support & I/O checking ONLY (takedown, owner load combos, simple statics, verified-only codes, EN/AR exports, and QA traps)."""

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
from app.db.models import ResearchSource, StructuralAssessment
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.structural import (
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NOT_PROVIDED_LABEL,
    NO_VERIFIED_STANDARD_LABEL,
    PRELIMINARY_STRUCTURAL_LABEL_EN,
)
from app.services.workspace import resolve_project_file_path
from app.skills.structural import (
    evaluate_structural_assessment,
    get_synthetic_structural_presets,
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


def _fake_structural_ai_factory(captured_prompts: list[str]):
    class _Models:
        def list(self) -> list[Any]:
            return []

        def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
            captured_prompts.append(str(contents))
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "summary_prose": (
                            "Preliminary assessment support check shows software statics align with simple span formulas. "
                            "Final code design and safety review remain with ETABS and a licensed structural engineer."
                        )
                    }
                ),
                usage_metadata=SimpleNamespace(
                    prompt_token_count=105,
                    candidates_token_count=35,
                    total_token_count=140,
                ),
            )

    return lambda _api_key: SimpleNamespace(models=_Models())


def test_step19_hand_checked_takedown_combinations_beam_statics_and_not_provided_blocks() -> None:
    """Verify hand-checked column load takedown, owner load combos, simple span statics, software discrepancy check, and 'not provided' blocks (SYNTHETIC ONLY)."""
    # -------------------------------------------------------------------------
    # HAND CHECK A — Tributary Area Column Takedown (owner intensities + factors):
    #   area = 25.0 m2, floors = 3 -> total tributary area = 75.0 m2
    #   owner dead_load_kpa = 8.0 -> unfactored_dead_kn = 75.0 * 8.0 = 600.0 kN
    #   owner live_load_kpa = 3.0 -> unfactored_live_kn = 75.0 * 3.0 = 225.0 kN
    #   owner dead_factor = 1.2, live_factor = 1.6:
    #     factored_axial_kn = 1.2 * 600.0 + 1.6 * 225.0 = 720.0 + 360.0 = 1080.0 kN
    #   owner_axial_capacity_kn = 1200.0 -> utilization_ratio = 1080.0 / 1200.0 = 0.90 <= 1.00 (PASS PRELIMINARY).
    #
    # HAND CHECK B — Linear Load Combinations (owner factors):
    #   unfactored D=100.0, L=50.0, W=30.0
    #   C1: 1.4*100 = 140.0
    #   C2: 1.2*100 + 1.6*50 = 120 + 80 = 200.0 (governing!)
    #   C3: 1.2*100 + 0.5*50 + 1.0*30 = 120 + 25 + 30 = 175.0
    #
    # HAND CHECK C — Simply Supported UDL Beam Statics:
    #   span L = 6.0 m, factored UDL w_u = 40.0 kN/m, service UDL w_s = 28.0 kN/m
    #   E = 25000.0 MPa, I = 1.6e9 mm4 -> EI = 25000 * 1.6e9 * 1e-9 = 40000.0 kN*m2
    #   R = V_max = w_u * L / 2 = 40.0 * 6.0 / 2 = 120.0 kN
    #   M_max = w_u * L^2 / 8 = 40.0 * 36.0 / 8 = 180.0 kN*m
    #   delta_max = 5 * 28.0 * 6.0^4 / (384 * 40000.0) * 1000 = 181440 / 15360000 * 1000 = 11.8125 mm
    #
    # HAND CHECK D — Simply Supported Midspan Point Load:
    #   L = 8.0 m, P_u = 50.0 kN, P_s = 30.0 kN, EI = 20000.0 kN*m2
    #   R = V_max = 50.0 / 2 = 25.0 kN
    #   M_max = 50.0 * 8.0 / 4 = 100.0 kN*m
    #   delta_max = 30.0 * 8.0^3 / (48 * 20000.0) * 1000 = 15360 / 960000 * 1000 = 16.0 mm
    #
    # HAND CHECK E — Cantilever UDL:
    #   L = 4.0 m, w_u = 15.0 kN/m, w_s = 10.0 kN/m, EI = 32000.0 kN*m2
    #   R = V_max = 15.0 * 4.0 = 60.0 kN; M_max = 15.0 * 16.0 / 2 = 120.0 kN*m
    #   delta_max = 10.0 * 256.0 / (8 * 32000.0) * 1000 = 10.0 mm
    # -------------------------------------------------------------------------
    ev_full = evaluate_structural_assessment(
        assessment_type="full_structural_check",
        inputs={
            "discrepancy_tolerance_pct": 2.0,
            "takedown_elements": [
                {
                    "element_id": "COL-A1",
                    "element_name": "Synthetic Col A1",
                    "tributary_area_m2": 25.0,
                    "floors_count": 3,
                    "dead_load_kpa": 8.0,
                    "live_load_kpa": 3.0,
                    "dead_factor": 1.2,
                    "live_factor": 1.6,
                    "reported_factored_axial_kn": 1080.0,
                    "owner_axial_capacity_kn": 1200.0,
                }
            ],
            "load_combinations": [
                {
                    "member_id": "FR-1",
                    "member_name": "Frame Shear",
                    "unit": "kN",
                    "unfactored_actions": {"D": 100.0, "L": 50.0, "W": 30.0},
                    "combinations": [
                        {"combo_name": "C1", "factors": {"D": 1.4}},
                        {"combo_name": "C2", "factors": {"D": 1.2, "L": 1.6}},
                        {"combo_name": "C3", "factors": {"D": 1.2, "L": 0.5, "W": 1.0}},
                    ],
                    "reported_governing_value": 200.0,
                    "owner_capacity": 250.0,
                }
            ],
            "beams": [
                {
                    "beam_id": "BM-01",
                    "beam_name": "UDL Girder",
                    "support_condition": "simply_supported_udl",
                    "span_m": 6.0,
                    "factored_load_kn_or_knm": 40.0,
                    "service_load_kn_or_knm": 28.0,
                    "e_mpa": 25000.0,
                    "i_mm4": 1.6e9,
                    "reported_reaction_kn": 120.0,
                    "reported_shear_kn": 120.0,
                    "reported_moment_kn_m": 180.0,
                    "reported_deflection_mm": 11.8125,
                    "owner_moment_capacity_kn_m": 200.0,
                    "owner_shear_capacity_kn": 150.0,
                    "owner_deflection_limit_mm": 25.0,
                },
                {
                    "beam_id": "BM-PT",
                    "beam_name": "Midspan Point Span",
                    "support_condition": "simply_supported_midspan_point",
                    "span_m": 8.0,
                    "factored_load_kn_or_knm": 50.0,
                    "service_load_kn_or_knm": 30.0,
                    "ei_kn_m2": 20000.0,
                    "reported_reaction_kn": 25.0,
                    "reported_shear_kn": 25.0,
                    "reported_moment_kn_m": 100.0,
                    "reported_deflection_mm": 16.0,
                    "owner_moment_capacity_kn_m": 120.0,
                    "owner_shear_capacity_kn": 40.0,
                    "owner_deflection_limit_mm": 20.0,
                },
                {
                    "beam_id": "CB-01",
                    "beam_name": "Cantilever Beam",
                    "support_condition": "cantilever_udl",
                    "span_m": 4.0,
                    "factored_load_kn_or_knm": 15.0,
                    "service_load_kn_or_knm": 10.0,
                    "ei_kn_m2": 32000.0,
                    "reported_reaction_kn": 60.0,
                    "reported_shear_kn": 60.0,
                    "reported_moment_kn_m": 120.0,
                    "reported_deflection_mm": 10.0,
                    "owner_moment_capacity_kn_m": 140.0,
                    "owner_shear_capacity_kn": 80.0,
                    "owner_deflection_limit_mm": 16.0,
                },
            ],
        },
    )
    assert ev_full.checks_passed is True
    assert ev_full.failed_checks_count == 0
    assert ev_full.blocked_missing_count == 0
    assert PRELIMINARY_STRUCTURAL_LABEL_EN in ev_full.preliminary_assumptions
    assert "ETABS" in ev_full.software_recommendation

    by_id = {it["item_id"]: it for it in ev_full.prepared_items}
    assert by_id["COL-A1"]["unfactored_dead_kn"] == pytest.approx(600.0, rel=1e-4)
    assert by_id["COL-A1"]["unfactored_live_kn"] == pytest.approx(225.0, rel=1e-4)
    assert by_id["COL-A1"]["factored_axial_kn"] == pytest.approx(1080.0, rel=1e-4)
    assert by_id["COL-A1"]["axial_utilization_ratio"] == pytest.approx(0.9, rel=1e-4)

    assert by_id["FR-1"]["governing_combo"] == "C2"
    assert by_id["FR-1"]["governing_value"] == pytest.approx(200.0, rel=1e-4)

    assert by_id["BM-01"]["ei_kn_m2"] == pytest.approx(40000.0, rel=1e-4)
    assert by_id["BM-01"]["reaction_kn"] == pytest.approx(120.0, rel=1e-4)
    assert by_id["BM-01"]["max_moment_kn_m"] == pytest.approx(180.0, rel=1e-4)
    assert by_id["BM-01"]["elastic_deflection_mm"] == pytest.approx(11.8125, rel=1e-4)

    assert by_id["BM-PT"]["max_moment_kn_m"] == pytest.approx(100.0, rel=1e-4)
    assert by_id["BM-PT"]["elastic_deflection_mm"] == pytest.approx(16.0, rel=1e-4)

    assert by_id["CB-01"]["max_moment_kn_m"] == pytest.approx(120.0, rel=1e-4)
    assert by_id["CB-01"]["elastic_deflection_mm"] == pytest.approx(10.0, rel=1e-4)

    # Software moment mismatch (reported 150 vs hand-checked 180 -> FAIL!)
    ev_bad = evaluate_structural_assessment(
        assessment_type="simple_statics_beam",
        inputs={
            "discrepancy_tolerance_pct": 2.0,
            "beams": [
                {
                    "beam_id": "BM-ERR",
                    "beam_name": "Bad Moment Beam",
                    "support_condition": "simply_supported_udl",
                    "span_m": 6.0,
                    "factored_load_kn_or_knm": 40.0,
                    "reported_moment_kn_m": 150.0,
                    "owner_moment_capacity_kn_m": 200.0,
                    "owner_shear_capacity_kn": 150.0,
                }
            ],
        },
    )
    assert ev_bad.checks_passed is False
    assert ev_bad.failed_checks_count == 1

    # Missing load factor / owner capacity -> strictly 'not provided' & blocked!
    ev_missing = evaluate_structural_assessment(
        assessment_type="takedown_check",
        inputs={
            "takedown_elements": [
                {
                    "element_id": "COL-MISS",
                    "element_name": "Omitted Factor Col",
                    "tributary_area_m2": 25.0,
                    "floors_count": 3,
                    "dead_load_kpa": 8.0,
                    "live_load_kpa": 3.0,
                    # Intentionally omit dead_factor, live_factor, owner_axial_capacity_kn!
                }
            ]
        },
    )
    assert ev_missing.checks_passed is False
    assert ev_missing.status == "blocked_missing_inputs"
    assert ev_missing.blocked_missing_count == 1
    assert ev_missing.prepared_items[0]["dead_factor"] == NOT_PROVIDED_LABEL
    assert ev_missing.prepared_items[0]["factored_axial_kn"] == NOT_PROVIDED_LABEL

    presets = get_synthetic_structural_presets()
    assert len(presets) == 2
    for p in presets:
        assert evaluate_structural_assessment(assessment_type=p.assessment_type, inputs=p.inputs).checks_passed is True


def test_step19_api_verified_only_codes_zero_tokens_exports_en_ar_and_qa_pass(tmp_path: Path) -> None:
    """Verify verified-only standard bindings, exact fallback string when absent, 0 AI tokens default, EN/AR DOCX/PDF/XLSX exports, and QA pass."""
    app = create_app(
        settings=_test_settings(tmp_path),
        secret_store=_InMemorySecretStore(),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Step 19 Synthetic Structural Frame", "code": "ST-19", "classification": "Preliminary"},
        ).json()
        pid = project["id"]
        slug = project["workspace_slug"]

        presets = client.get("/api/structural-assessments/presets").json()["presets"]
        assert len(presets) == 2

        # 1. Create without Standards Library / ResearchSource -> exact fallback label + 0 AI tokens + PRELIMINARY
        no_std_res = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "simple_statics_beam",
                "title": "Cantilever Statics Check (No Verified Standard)",
                "language": "en",
                "classification": "Preliminary",
                "inputs": presets[1]["inputs"],
                "references": [],
                "use_ai": False,
            },
        )
        assert no_std_res.status_code == 201, no_std_res.text
        d_nostd = no_std_res.json()
        assert d_nostd["tokens_used"] == 0
        assert d_nostd["standards_status"] == "no_verified_standard_on_file"
        assert d_nostd["references"][0]["verification_label"] == NO_VERIFIED_STANDARD_LABEL
        assert d_nostd["preliminary_label"] == PRELIMINARY_STRUCTURAL_LABEL_EN
        assert d_nostd["checks_passed"] is True

        # 2. Binding missing StandardLibrary ID fails cleanly (422)
        bad_res = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "simple_statics_beam",
                "title": "Bad Standard Bind",
                "inputs": presets[1]["inputs"],
                "references": [{"source_kind": "standard_library", "standard_library_id": "nonexistent-id"}],
            },
        )
        assert bad_res.status_code == 422

        # 3. Register verified Standards Library entry + reviewed ResearchSource -> bind full structural assessment
        std_struct = client.post(
            "/api/standards",
            json={
                "project_id": pid,
                "standard_number": "SYN-STRUCT-2024",
                "title": "Owner Adopted Synthetic Structural Factor Document",
                "issuing_body": "Synthetic Owner Structural Board",
                "edition_year": "2024",
                "status": "current",
                "adopted_locally": True,
            },
        ).json()

        with app.state.session_factory() as db:
            rs = ResearchSource(
                project_id=pid,
                source_name="Owner Reviewed Structural Basis",
                url="https://standards.example.org/struct-syn",
                publication_date="2024",
                query_text="synthetic structural checks",
                relevant_info="Reviewed synthetic structural basis note.",
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

        full_res = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "full_structural_check",
                "title": "Grid A1 Takedown & Statics Verification (Verified Standard)",
                "language": "ar",
                "classification": "For Review",
                "inputs": presets[0]["inputs"],
                "references": [
                    {"source_kind": "standard_library", "standard_library_id": std_struct["id"]},
                    {"source_kind": "verified_source_log", "research_source_id": rs_id},
                ],
                "use_ai": False,
            },
        )
        assert full_res.status_code == 201, full_res.text
        d_full = full_res.json()
        assert d_full["standards_status"] == "verified_standards"
        assert d_full["checks_passed"] is True
        sid = d_full["id"]

        # 4. Export AR RTL & EN LTR DOCX + PDF + Live XLSX & verify SHA-256 + content
        for exp_lang in ("ar", "en"):
            exp_res = client.post(f"/api/structural-assessments/{sid}/export", json={"language": exp_lang})
            assert exp_res.status_code == 201, exp_res.text
            exp_d = exp_res.json()
            for k in ("docx_deliverable", "pdf_deliverable", "xlsx_deliverable"):
                dm = exp_d[k]
                assert dm["folder_name"] == "04_Engineering_Calculations"
                disk_p = resolve_project_file_path(
                    _test_settings(tmp_path).workspaces_dir,
                    workspace_slug=slug,
                    relative_path=dm["relative_path"],
                )
                assert hashlib.sha256(disk_p.read_bytes()).hexdigest() == dm["sha256"]

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
            assert "SYN-STRUCT-2024" in pdf_norm
            assert "ETABS" in pdf_norm

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
            assert "SYN-STRUCT-2024" in docx_txt

        # Export first assessment cleanly so QA finds complete exported deliverables
        assert client.post(f"/api/structural-assessments/{d_nostd['id']}/export", json={"language": "en"}).status_code == 201

        # 5. QA Agent passes and inspects both structural assessments!
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_out = qa_res.json()
        assert qa_out["status"] == "passed", qa_out
        assert sid in qa_out["qa_context_summary"]["inspected_structural_ids"]
        assert d_nostd["id"] in qa_out["qa_context_summary"]["inspected_structural_ids"]


def test_step19_optional_ai_and_qa_catches_tampered_verdict_uncited_aci_ec_and_blocked_inputs(tmp_path: Path) -> None:
    """Verify optional AI UNVERIFIED gate & QA defect traps catch tampered structural verdict, uncited ACI/Eurocode/AISC, and 'not provided' missing inputs."""
    captured_prompts: list[str] = []
    app = create_app(
        settings=_test_settings(tmp_path),
        secret_store=_InMemorySecretStore({"gemini": "AIzaSyntheticStructKey99999"}),
        provider_client_factory=_fake_structural_ai_factory(captured_prompts),
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Step 19 QA Defect Project", "code": "QAST-19", "classification": "For Review"},
        ).json()
        pid = project["id"]
        presets = client.get("/api/structural-assessments/presets").json()["presets"]

        # 1. Optional AI draft -> tagged UNVERIFIED AI DRAFT
        ai_res = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "simple_statics_beam",
                "title": "Cantilever AI Note Test",
                "language": "en",
                "inputs": presets[1]["inputs"],
                "use_ai": True,
                "complexity": "fast",
            },
        )
        assert ai_res.status_code == 201, ai_res.text
        ai_d = ai_res.json()
        assert ai_d["tokens_used"] == 140
        assert len(captured_prompts) == 1
        assert ai_d["ai_draft_status"] == "unverified_ai_draft"
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in ai_d["ai_draft_label"]

        # 2. Seed failing beam software moment & tamper DB verdict + inject uncited ACI 318 & Eurocode 2!
        bad_beam = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "simple_statics_beam",
                "title": "Tampered Girder & Uncited Code Trap",
                "language": "en",
                "inputs": {
                    "beams": [
                        {
                            "beam_id": "BM-BAD",
                            "beam_name": "Bad Girder (Per ACI 318)",
                            "support_condition": "simply_supported_udl",
                            "span_m": 6.0,
                            "factored_load_kn_or_knm": 40.0,
                            "reported_moment_kn_m": 140.0,  # Wrong (expected 180 -> 22.22% > 2% FAIL)
                            "owner_moment_capacity_kn_m": 200.0,
                            "owner_shear_capacity_kn": 150.0,
                        }
                    ]
                },
            },
        ).json()
        assert bad_beam["checks_passed"] is False

        with app.state.session_factory() as db:
            row = db.get(StructuralAssessment, bad_beam["id"])
            assert row is not None
            row.checks_passed = True
            row.failed_checks_count = 0
            row.summary = "Claiming compliance with Eurocode 2 and AISC 360 without verification."
            db.add(row)
            db.commit()

        # 3. Seed missing owner_axial_capacity_kn -> 'not provided' blocks result!
        blk_res = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "assessment_type": "takedown_check",
                "title": "Blocked Takedown Missing Capacity",
                "language": "en",
                "inputs": {
                    "takedown_elements": [
                        {
                            "element_id": "COL-BLK",
                            "element_name": "Missing Capacity Column",
                            "tributary_area_m2": 25.0,
                            "floors_count": 3,
                            "dead_load_kpa": 8.0,
                            "live_load_kpa": 3.0,
                            "dead_factor": 1.2,
                            "live_factor": 1.6,
                        }
                    ]
                },
            },
        ).json()
        assert blk_res["status"] == "blocked_missing_inputs"
        assert blk_res["checks_passed"] is False

        # 4. Run QA Agent -> MUST return 'issues_found' catching tampered verdict, uncited ACI 318 / Eurocode / AISC, blocked 'not provided', and unapproved AI draft!
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
        assert "ACI 318" in joined_refs
        assert "Eurocode" in joined_refs
        assert "AISC" in joined_refs

        joined_arith = " | ".join(
            f"{i['title']} :: {i['description']}" for i in qa_out["issues"] if i["check_category"] == "arithmetic"
        )
        assert "mismatch" in joined_arith.lower()
