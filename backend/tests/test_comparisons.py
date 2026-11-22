"""Tests for Step 15 deterministic Decimal technical comparison module, unit normalization, SHA-256 DOCX/PDF/XLSX exports, owner decision gate, and QA checks."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pymupdf

from app.core.config import Settings
from app.db.models import ResearchSource, Task, TechnicalComparison
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.comparisons import (
    ADVISORY_NOTICE_EN,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    ComparisonCellIn,
    ComparisonCriterionIn,
    ComparisonOptionIn,
    NOT_PROVIDED_LABEL,
)
from app.services.calc_export import sha256_file
from app.services.workspace import resolve_project_file_path
from app.skills.comparisons import ComparisonInputError, evaluate_technical_comparison


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


def test_deterministic_decimal_scoring_hand_checked_units_and_missing_values() -> None:
    """Hand-checked Decimal scoring, explicit W->kW conversion, currency mismatch flagging, mandatory gating, and 'not provided'."""
    criteria = [
        ComparisonCriterionIn(
            criterion_id="c_comp",
            category="compliance",
            label="Emergency Transfer Compliance",
            weight="20",
            is_mandatory=True,
            direction="boolean_pass",
            target_unit="bool",
            mandatory_expected_bool=True,
            source_kind="owner_entered",
            source_ref="Clinic emergency specification clause",
        ),
        ComparisonCriterionIn(
            criterion_id="c_perf",
            category="performance",
            label="Continuous Output Rating",
            weight="25",
            is_mandatory=True,
            direction="higher_better",
            target_unit="kW",
            mandatory_min=100.0,
            source_kind="owner_entered",
            source_ref="Peak standby kW load schedule",
        ),
        ComparisonCriterionIn(
            criterion_id="c_init",
            category="initial_cost",
            label="Capital Cost",
            weight="20",
            is_mandatory=False,
            direction="lower_better",
            target_unit="USD",
            source_kind="owner_entered",
            source_ref="Vendor quote baseline",
        ),
        ComparisonCriterionIn(
            criterion_id="c_oper",
            category="operating_cost",
            label="Annual O&M Cost",
            weight="15",
            is_mandatory=False,
            direction="lower_better",
            target_unit="USD",
            source_kind="owner_entered",
            source_ref="Annual service sheet",
        ),
        ComparisonCriterionIn(
            criterion_id="c_life",
            category="lifecycle_cost",
            label="10-Year Lifecycle Cost",
            weight="10",
            is_mandatory=False,
            direction="lower_better",
            target_unit="USD",
            source_kind="calculation",
            source_ref="Derived deterministically: initial_cost + annual operating_cost * 10 yr",
        ),
        ComparisonCriterionIn(
            criterion_id="c_risk",
            category="risks",
            label="Risk Resilience Score",
            weight="10",
            is_mandatory=False,
            direction="direct_score_0_100",
            target_unit="score_0_100",
            source_kind="owner_entered",
            source_ref="Risk evaluation rubric",
        ),
    ]

    # Hand Check (lifecycle_years = 10):
    # Option A: comp=100*0.2=20; perf=120/150*100=80 *0.25=20; init=10000/10000*100=100 *0.2=20;
    #   oper=1000/1500*100=66.6667 *0.15=10.0000; life=25000 -> 22500/25000*100=90 *0.1=9.0000;
    #   risk=85*0.1=8.5000 => TOTAL = 87.5000
    # Option B: comp=20; perf=150000W->150kW => 100*0.25=25; init=10000/12500*100=80 *0.2=16;
    #   oper=1000->100*0.15=15; life=22500->100*0.1=10; risk=OMITTED ('not provided')->0 => TOTAL = 86.0000
    opt_a = ComparisonOptionIn(
        option_id="opt_a",
        name="Offer Alpha",
        vendor_or_source="Alpha Power",
        risks=["Sea freight delay"],
        cells=[
            ComparisonCellIn(criterion_id="c_comp", value=True, unit="bool", source_kind="owner_entered", source_ref="Alpha submittal"),
            ComparisonCellIn(criterion_id="c_perf", value=120, unit="kW", source_kind="owner_entered", source_ref="Alpha datasheet"),
            ComparisonCellIn(criterion_id="c_init", value=10000, unit="USD", source_kind="owner_entered", source_ref="Alpha quote #1"),
            ComparisonCellIn(criterion_id="c_oper", value=1500, unit="USD", source_kind="owner_entered", source_ref="Alpha O&M #1"),
            ComparisonCellIn(criterion_id="c_risk", value=85, unit="score_0_100", source_kind="owner_entered", source_ref="Risk review"),
        ],
    )
    opt_b = ComparisonOptionIn(
        option_id="opt_b",
        name="Offer Beta",
        vendor_or_source="Beta Power",
        risks=[],
        cells=[
            ComparisonCellIn(criterion_id="c_comp", value=True, unit="bool", source_kind="owner_entered", source_ref="Beta submittal"),
            ComparisonCellIn(criterion_id="c_perf", value=150000, unit="W", source_kind="owner_entered", source_ref="Beta datasheet in Watts"),
            ComparisonCellIn(criterion_id="c_init", value=12500, unit="USD", source_kind="owner_entered", source_ref="Beta quote #2"),
            ComparisonCellIn(criterion_id="c_oper", value=1000, unit="USD", source_kind="owner_entered", source_ref="Beta O&M #2"),
        ],
    )

    matrix = evaluate_technical_comparison(
        criteria=criteria,
        options=[opt_a, opt_b],
        language="en",
        lifecycle_years=10.0,
    )
    assert matrix.weights_sum_valid is True
    assert matrix.total_weight == 100.0
    assert ADVISORY_NOTICE_EN in matrix.advisory_notice
    assert matrix.leading_option_id == "opt_a"

    res_a = next(o for o in matrix.options if o.option_id == "opt_a")
    res_b = next(o for o in matrix.options if o.option_id == "opt_b")
    assert res_a.advisory_rank == 1
    assert Decimal(str(res_a.total_weighted_score)) == Decimal("87.5")
    assert res_b.advisory_rank == 2
    assert Decimal(str(res_b.total_weighted_score)) == Decimal("86.0")

    b_perf = next(c for c in res_b.cells if c.criterion_id == "c_perf")
    assert b_perf.unit_status == "converted_explicitly"
    assert b_perf.converted_value == "150.0000"

    b_life = next(c for c in res_b.cells if c.criterion_id == "c_life")
    assert Decimal(b_life.display_value) == Decimal("22500")
    assert b_life.source_kind == "calculation"

    b_risk = next(c for c in res_b.cells if c.criterion_id == "c_risk")
    assert b_risk.is_missing is True
    assert b_risk.display_value == NOT_PROVIDED_LABEL
    assert b_risk.weighted_score == 0.0

    # Non-100 weights must fail strictly
    bad_criteria = list(criteria)
    bad_criteria[0] = bad_criteria[0].model_copy(update={"weight": "10"})
    try:
        evaluate_technical_comparison(criteria=bad_criteria, options=[opt_a, opt_b])
        raise AssertionError("Expected ComparisonInputError for non-100 weights")
    except ComparisonInputError as exc:
        assert "100" in str(exc)

    # Currency mismatch (LYD vs USD) must NEVER convert silently and must flag unit mismatch + leave lifecycle_cost 'not provided'
    opt_lyd = ComparisonOptionIn(
        option_id="opt_c",
        name="Offer Gamma LYD",
        vendor_or_source="Local Offer",
        risks=[],
        cells=[
            ComparisonCellIn(criterion_id="c_comp", value=True, unit="bool", source_kind="owner_entered", source_ref="Gamma submittal"),
            ComparisonCellIn(criterion_id="c_perf", value=90, unit="kW", source_kind="owner_entered", source_ref="Gamma kW (fails 100kW min)"),
            ComparisonCellIn(criterion_id="c_init", value=55000, unit="LYD", source_kind="owner_entered", source_ref="Gamma LYD quote"),
            ComparisonCellIn(criterion_id="c_oper", value=4000, unit="USD", source_kind="owner_entered", source_ref="Gamma USD O&M"),
        ],
    )
    mix_matrix = evaluate_technical_comparison(
        criteria=criteria,
        options=[opt_a, opt_lyd],
        language="en",
        lifecycle_years=10.0,
    )
    assert len(mix_matrix.unit_mismatch_flags) == 1
    assert "LYD vs USD" in mix_matrix.unit_mismatch_flags[0]
    res_c = next(o for o in mix_matrix.options if o.option_id == "opt_c")
    assert res_c.mandatory_passed is False
    c_life = next(c for c in res_c.cells if c.criterion_id == "c_life")
    assert c_life.display_value == NOT_PROVIDED_LABEL


def test_step15_api_project_grounding_exports_owner_decision_and_qa_pass(tmp_path: Path) -> None:
    """Full end-to-end API flow linking real BOQ, Spec, Calc, reviewed ResearchSource -> Arabic RTL + English LTR DOCX/PDF/XLSX + QA Pass."""
    settings = _test_settings(tmp_path)
    app = create_app(settings=settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        proj = client.post(
            "/api/projects",
            json={"name": "Clinic Equipment Eval", "code": "CLN-CMP", "classification": "For Review"},
        ).json()
        pid = proj["id"]

        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="Equipment Technical Evaluation",
                prompt="Evaluate clinic generator alternatives",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={"expected_deliverables": ["Technical comparison matrix DOCX PDF XLSX"]},
            )
            rs = ResearchSource(
                project_id=pid,
                source_name="Local Utility Standby Interconnection Code",
                url="https://example.org/utility-standby-code",
                publication_date="2025-05-01",
                accessed_at=datetime.now(timezone.utc),
                relevant_info="ATS interlock & earth bonding mandatory (verify against locally adopted code).",
                reliability_assessment="reputable",
                source_type="web",
                source_priority_tier="standards_bodies",
                priority_rank=2,
                access_status="accessible",
                reviewed=True,
                http_status=200,
                untrusted_neutralized=True,
            )
            db.add_all([task, rs])
            db.commit()
            tid = task.id
            rs_id = rs.id

        # Drawing needed for BOQ-linked Spec QA consistency
        preset_model = client.get("/api/parametric-drawings/clinic-preset").json()
        dwg_res = client.post(
            f"/api/projects/{pid}/parametric-drawings",
            json={
                "task_id": tid,
                "drawing_no": "A-101",
                "title": "Clinic Layout",
                "scale_denominator": 100,
                "paper_size": "A3",
                "classification": "For Review",
                "plan_model": preset_model,
            },
        )
        assert dwg_res.status_code == 201, dwg_res.text

        # Seed real BOQ item and export BOQ cleanly
        boq = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={
                "task_id": tid,
                "title": "Clinic Electrical BOQ",
                "currency": "USD",
                "classification": "For Review",
                "include_dxf_ifc": False,
                "include_boq_imports": False,
            },
        ).json()
        item_res = client.post(
            f"/api/boq-sheets/{boq['id']}/items",
            json={
                "item_no": "E-GEN-01",
                "description": "Electrical standby generator MDB panel acoustic 150 kVA with ATS",
                "unit": "nos",
                "quantity": 1,
                "unit_rate": 40000.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Clinic Tender BOQ Baseline",
                "discipline": "electrical",
                "verification_status": "Manual",
            },
        ).json()
        boq_item_id = next(it["id"] for it in item_res["items"] if it["item_no"] == "E-GEN-01")
        assert client.post(f"/api/boq-sheets/{boq['id']}/export", json={"language": "en"}).status_code == 201

        calc_res = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "calculation_type": "electrical_load_schedule",
                "title": "Clinic Standby Load Schedule",
                "language": "en",
                "classification": "For Review",
                "inputs": {
                    "panel_name": "EM-MDB-01",
                    "supply_phase": "3ph",
                    "system_voltage_v": 400,
                    "spare_margin_pct": 15,
                    "max_phase_unbalance_pct": 10,
                    "circuits": [
                        {
                            "circuit_id": "EM-1",
                            "description": "Medical clinic essential panel",
                            "phase": "3ph",
                            "connected_load_kw": 80,
                            "demand_factor": 0.9,
                            "power_factor": 0.85,
                        }
                    ],
                },
                "references": [
                    {
                        "source_kind": "verified_source_log",
                        "research_source_id": rs_id,
                        "source_name": "Local Utility Standby Interconnection Code",
                        "source_ref": "Verified demand allowance baseline",
                    }
                ],
            },
        )
        assert calc_res.status_code == 201, calc_res.text
        calc_id = calc_res.json()["id"]

        spec_res = client.post(
            f"/api/projects/{pid}/specifications",
            json={
                "task_id": tid,
                "title": "Clinic Electrical & Generator Specs",
                "discipline": "electrical",
                "language": "en",
                "classification": "For Review",
                "boq_sheet_ids": [boq["id"]],
                "research_source_ids": [rs_id],
                "use_ai": False,
            },
        )
        assert spec_res.status_code == 201, spec_res.text
        spec_id = spec_res.json()["id"]

        presets_res = client.get("/api/comparisons/presets")
        assert presets_res.status_code == 200
        assert len(presets_res.json()["presets"]) >= 2

        # Create Step 15 comparison grounded across ALL real project sources (0 AI tokens)
        cmp_payload = {
            "task_id": tid,
            "title": "مقارنة فنية لمولد العيادة الاحتياطي",
            "comparison_scope": "equipment",
            "discipline": "electrical",
            "language": "ar",
            "classification": "For Review",
            "lifecycle_years": 10.0,
            "use_ai": False,
            "criteria": [
                {
                    "criterion_id": "comp",
                    "category": "compliance",
                    "label": "المطابقة لكود الربط واللوحات",
                    "weight": "30",
                    "is_mandatory": True,
                    "direction": "boolean_pass",
                    "target_unit": "bool",
                    "mandatory_expected_bool": True,
                    "source_kind": "specification",
                    "source_ref": "Clinic Electrical & Generator Specs (SPEC-05)",
                    "specification_id": spec_id,
                },
                {
                    "criterion_id": "perf",
                    "category": "performance",
                    "label": "القدرة المستمرة",
                    "weight": "35",
                    "is_mandatory": True,
                    "direction": "higher_better",
                    "target_unit": "kW",
                    "mandatory_min": 100.0,
                    "source_kind": "calculation",
                    "source_ref": "Clinic Standby Load Schedule",
                    "calculation_id": calc_id,
                },
                {
                    "criterion_id": "cost",
                    "category": "initial_cost",
                    "label": "التكلفة التوريدية",
                    "weight": "25",
                    "is_mandatory": False,
                    "direction": "lower_better",
                    "target_unit": "USD",
                    "source_kind": "boq_item",
                    "source_ref": "BOQ E-GEN-01 Baseline",
                    "boq_item_id": boq_item_id,
                },
                {
                    "criterion_id": "safety",
                    "category": "safety",
                    "label": "اشتراطات السلامة والتشابك",
                    "weight": "10",
                    "is_mandatory": True,
                    "direction": "direct_score_0_100",
                    "target_unit": "score_0_100",
                    "mandatory_min": 80.0,
                    "source_kind": "research_source",
                    "source_ref": "Local Utility Standby Interconnection Code",
                    "research_source_id": rs_id,
                },
            ],
            "options": [
                {
                    "option_id": "opt_1",
                    "name": "Synthetic Gen-Set Alpha",
                    "vendor_or_source": "Synthetic Offer 1",
                    "risks": ["Lead time 8 weeks"],
                    "cells": [
                        {
                            "criterion_id": "comp",
                            "value": True,
                            "unit": "bool",
                            "source_kind": "specification",
                            "source_ref": "Submittal compliance",
                            "specification_id": spec_id,
                        },
                        {
                            "criterion_id": "perf",
                            "value": 120,
                            "unit": "kW",
                            "source_kind": "calculation",
                            "source_ref": "Calc demand check",
                            "calculation_id": calc_id,
                        },
                        {
                            "criterion_id": "cost",
                            "value": 40000,
                            "unit": "USD",
                            "source_kind": "boq_item",
                            "source_ref": "BOQ E-GEN-01 Commercial",
                            "boq_item_id": boq_item_id,
                        },
                        {
                            "criterion_id": "safety",
                            "value": 92,
                            "unit": "score_0_100",
                            "source_kind": "research_source",
                            "source_ref": "Utility checklist",
                            "research_source_id": rs_id,
                        },
                    ],
                },
                {
                    "option_id": "opt_2",
                    "name": "Synthetic Gen-Set Beta",
                    "vendor_or_source": "Synthetic Offer 2",
                    "risks": ["Higher noise dBA"],
                    "cells": [
                        {
                            "criterion_id": "comp",
                            "value": True,
                            "unit": "bool",
                            "source_kind": "specification",
                            "source_ref": "Submittal compliance B",
                            "specification_id": spec_id,
                        },
                        {
                            "criterion_id": "perf",
                            "value": 110000,
                            "unit": "W",
                            "source_kind": "owner_entered",
                            "source_ref": "Beta datasheet in Watts (converted)",
                        },
                        {
                            "criterion_id": "cost",
                            "value": 36000,
                            "unit": "USD",
                            "source_kind": "owner_entered",
                            "source_ref": "Beta commercial sheet",
                        },
                        {
                            "criterion_id": "safety",
                            "value": 85,
                            "unit": "score_0_100",
                            "source_kind": "owner_entered",
                            "source_ref": "HSE inspection score",
                        },
                    ],
                },
            ],
        }

        cmp_res = client.post(f"/api/projects/{pid}/comparisons", json=cmp_payload)
        assert cmp_res.status_code == 201, cmp_res.text
        cmp_data = cmp_res.json()
        cmp_id = cmp_data["id"]
        assert cmp_data["tokens_used"] == 0
        assert cmp_data["ai_draft_status"] == "not_used"
        assert cmp_data["owner_decision_status"] == "pending_owner_decision"
        assert len(cmp_data["deliverables"]) == 3  # DOCX + PDF + XLSX

        # Check exported Arabic RTL DOCX, PDF, and Live-Formula XLSX on disk & SHA-256
        delivs = {d["format"]: d for d in cmp_data["deliverables"]}
        assert {"docx", "pdf", "xlsx"}.issubset(delivs.keys())
        for d_rec in delivs.values():
            fpath = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], d_rec["relative_path"])
            assert fpath.is_file()
            assert sha256_file(fpath) == d_rec["sha256"]

        docx_path = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], delivs["docx"]["relative_path"])
        doc = DocxDocument(str(docx_path))
        sect_pr = doc.sections[0]._sectPr
        assert any(ch.tag == qn("w:bidi") for ch in sect_pr)

        pdf_path = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], delivs["pdf"]["relative_path"])
        pdf_doc = pymupdf.open(str(pdf_path))
        pdf_txt = "\n".join(pg.get_text("text") for pg in pdf_doc)
        pdf_doc.close()
        pdf_norm = " ".join(pdf_txt.replace("\xa0", " ").replace("\xad", "-").split())
        assert "Synthetic Gen-Set Alpha" in pdf_norm
        assert "96.7000" in pdf_norm

        xlsx_path = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], delivs["xlsx"]["relative_path"])
        wb = load_workbook(str(xlsx_path), data_only=False)
        ws = wb.active
        assert ws.views.sheetView[0].rightToLeft is True
        formulas = [
            ws.cell(row=r, column=c).value
            for r in range(1, ws.max_row + 1)
            for c in range(1, ws.max_column + 1)
            if isinstance(ws.cell(row=r, column=c).value, str) and ws.cell(row=r, column=c).value.startswith("=")
        ]
        assert any(f.startswith("=SUM(") for f in formulas)
        assert any(f.startswith("=ROUND(") for f in formulas)
        wb.close()

        # Export additional English LTR revision -> e2
        exp_en = client.post(f"/api/comparisons/{cmp_id}/export", json={"language": "en"})
        assert exp_en.status_code == 201, exp_en.text
        assert exp_en.json()["comparison"]["export_version"] == 2
        assert exp_en.json()["xlsx_deliverable"]["folder_name"] == "09_Comparisons"

        # Run independent QA review -> MUST PASS with zero comparison findings!
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid, "classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_data = qa_res.json()
        assert cmp_id in qa_data["qa_context_summary"]["inspected_comparison_ids"]
        assert qa_data["status"] == "passed", qa_data["issues"]

        # Verify task gate succeeds cleanly after QA passes
        ver_res = client.post(f"/api/tasks/{tid}/verify", json={"qa_review_id": qa_data["id"]})
        assert ver_res.status_code == 200

        # Record Owner Decision -> transitions owner_decision_status to owner_selected + exports e3
        dec_res = client.post(
            f"/api/comparisons/{cmp_id}/decide",
            json={
                "selected_option_id": "opt_1",
                "decided_by": "Lead Electrical Engineer / Owner",
                "decision_note": "Selected Alpha due to verified 120kW margin and service support.",
                "export_after_decision": True,
            },
        )
        assert dec_res.status_code == 200, dec_res.text
        dec_data = dec_res.json()
        assert dec_data["owner_decision_status"] == "owner_selected"
        assert dec_data["owner_selected_option_id"] == "opt_1"
        assert dec_data["export_version"] == 3


def test_step15_optional_ai_unverified_tag_and_qa_catches_comparison_defects(tmp_path: Path) -> None:
    """Verify optional AI narrative is UNVERIFIED AI DRAFT until owner approval, and QA detects every seeded Step 15 defect."""
    settings = _test_settings(tmp_path)
    app = create_app(settings=settings, secret_store=_InMemorySecretStore({"gemini": "mock-key"}))

    def fake_factory(api_key: str) -> Any:
        class _Models:
            def generate_content(self, **kwargs: Any) -> Any:
                return SimpleNamespace(
                    text='{"executive_note": "Offer Alpha achieves highest standby rating; Owner decides final award."}',
                    usage_metadata=SimpleNamespace(prompt_token_count=180, candidates_token_count=45, total_token_count=225),
                )

        return SimpleNamespace(models=_Models())

    app.state.provider_client_factory = fake_factory

    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Comparison Defect Trap", "code": "CLN-TRAP"}).json()
        pid = proj["id"]

        # Reject dangling BOQ reference cleanly with 422
        bad_ref_res = client.post(
            f"/api/projects/{pid}/comparisons",
            json={
                "comparison_scope": "equipment",
                "language": "en",
                "criteria": [
                    {
                        "criterion_id": "c1",
                        "category": "performance",
                        "label": "Capacity",
                        "weight": 100,
                        "is_mandatory": True,
                        "direction": "higher_better",
                        "target_unit": "kW",
                        "source_kind": "boq_item",
                        "source_ref": "Bad BOQ",
                        "boq_item_id": "non-existent-id",
                    }
                ],
                "options": [
                    {"option_id": "a", "name": "A", "cells": []},
                    {"option_id": "b", "name": "B", "cells": []},
                ],
            },
        )
        assert bad_ref_res.status_code == 422

        # Create comparison WITH optional AI + currency mismatch + missing mandatory value
        cmp_res = client.post(
            f"/api/projects/{pid}/comparisons",
            json={
                "comparison_scope": "vendor_offer",
                "title": "Offer Comparison With Defects",
                "language": "en",
                "use_ai": True,
                "criteria": [
                    {
                        "criterion_id": "mand_comp",
                        "category": "compliance",
                        "label": "Mandatory Certificate",
                        "weight": 50,
                        "is_mandatory": True,
                        "direction": "boolean_pass",
                        "target_unit": "bool",
                        "source_kind": "owner_entered",
                        "source_ref": "Clinic spec",
                    },
                    {
                        "criterion_id": "cost_usd",
                        "category": "initial_cost",
                        "label": "Offer Price",
                        "weight": 50,
                        "is_mandatory": False,
                        "direction": "lower_better",
                        "target_unit": "USD",
                        "source_kind": "owner_entered",
                        "source_ref": "Commercial offer",
                    },
                ],
                "options": [
                    {
                        "option_id": "opt_a",
                        "name": "Alpha",
                        "cells": [
                            {"criterion_id": "mand_comp", "value": True, "unit": "bool", "source_kind": "owner_entered", "source_ref": "Cert A"},
                            {"criterion_id": "cost_usd", "value": 10000, "unit": "USD", "source_kind": "owner_entered", "source_ref": "Quote A"},
                        ],
                    },
                    {
                        "option_id": "opt_b",
                        "name": "Beta",
                        "cells": [
                            # mand_comp omitted -> 'not provided' on mandatory criterion!
                            {"criterion_id": "cost_usd", "value": 45000, "unit": "LYD", "source_kind": "owner_entered", "source_ref": "Quote B LYD"},
                        ],
                    },
                ],
            },
        )
        assert cmp_res.status_code == 201, cmp_res.text
        cmp_data = cmp_res.json()
        assert cmp_data["ai_draft_status"] == "unverified_ai_draft"
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in cmp_data["summary"]
        assert cmp_data["tokens_used"] == 225

        # Now tamper directly with stored comparison DB weights, score arithmetic, and corrupt its XLSX file to test every QA trap!
        xlsx_deliv = next(d for d in cmp_data["deliverables"] if d["format"] == "xlsx")
        xlsx_path = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], xlsx_deliv["relative_path"])
        xlsx_path.write_bytes(b"corrupt-non-zip-xlsx-content")

        with app.state.session_factory() as db:
            row = db.get(TechnicalComparison, cmp_data["id"])
            assert row is not None
            tampered_crit = list(row.criteria_json)
            tampered_crit[0] = {**tampered_crit[0], "weight": 30}  # weights now sum to 80 != 100!
            row.criteria_json = tampered_crit
            tampered_mat = dict(row.matrix_result_json)
            tampered_mat["options"] = [
                {
                    **o,
                    "total_weighted_score": 999.0,  # tampered score!
                    "cells": [
                        {**c, "source_ref": ""} if (o["option_id"] == "opt_a" and c["criterion_id"] == "cost_usd") else c
                        for c in o["cells"]
                    ],
                }
                for o in tampered_mat["options"]
            ]
            row.matrix_result_json = tampered_mat
            db.commit()

        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_data = qa_res.json()
        assert qa_data["status"] != "passed"
        issue_titles = {iss["title"] for iss in qa_data["issues"]}
        assert "Technical comparison criteria weights do not sum to 100" in issue_titles
        assert "Technical comparison score arithmetic mismatch" in issue_titles
        assert "Mixed or incompatible units in technical comparison" in issue_titles
        assert "Unsourced metric value in technical comparison" in issue_titles
        assert "Missing mandatory criterion value ('not provided') in technical comparison" in issue_titles
        assert "AI-drafted comparison summary pending owner approval" in issue_titles
        assert "Exported XLSX unreadable or missing" in issue_titles
