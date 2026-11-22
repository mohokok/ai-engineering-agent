"""Tests for Step 16 deterministic WBS/CPM engine, Libya weekend calendar, missing-duration branch blocking, Gantt PDF + live XLSX exports, baseline variance, and QA checks."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pymupdf

from app.core.config import Settings
from app.db.models import ProjectSchedule, ResearchSource, Task
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.planning import (
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    ActivityDependencyIn,
    NOT_PROVIDED_LABEL,
    ScheduleActivityIn,
    WbsItemIn,
    WorkCalendarIn,
)
from app.services.calc_export import sha256_file
from app.services.workspace import resolve_project_file_path
from app.skills.planning import PlanningInputError, evaluate_project_schedule


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


def test_cpm_hand_checked_network_libya_weekend_holidays_and_missing_duration_block() -> None:
    """Hand-checked CPM forward/backward pass, float, FS+lag, Libya Fri-Sat calendar, holidays, cycles & 'not provided' branch block."""
    wbs = [
        WbsItemIn(wbs_code="1", title="Master Clinic Schedule"),
        WbsItemIn(wbs_code="1.1", title="Substructure & MEP", parent_code="1"),
    ]
    # Hand-checked CPM Network:
    # M0 (0d) -> A1 (4d) -> { A2 (3d), A3 (5d) } -> A4 (4d, preds: A2 FS+0, A3 FS+1) -> M1 (0d)
    # Forward pass:
    #   M0: ES=0, EF=0
    #   A1: ES=0, EF=4 (Libya start Sun 2026-11-22 -> finish Wed 2026-11-25)
    #   A2: ES=4, EF=7 (Thu 2026-11-26, skip Fri/Sat, Sun Nov 29, Mon Nov 30)
    #   A3: ES=4, EF=9 (Thu 2026-11-26 .. Wed Dec 2)
    #   A4: ES=max(7+0, 9+1)=10, EF=14 (Thu Dec 3 is lag day; skip Fri Dec 4 + Sat Dec 5; Sun Dec 6 .. Wed Dec 9)
    #   M1: ES=14, EF=14 (target 2026-12-09)
    # Backward pass (PF=14):
    #   M1: LS=14, LF=14, TF=0 (CRIT)
    #   A4: LS=10, LF=14, TF=0 (CRIT)
    #   A3: LF=10-1=9, LS=4, TF=0 (CRIT)
    #   A2: LF=10-0=10, LS=7, TF=3 (3 working days float!)
    #   A1: LF=min(7, 4)=4, LS=0, TF=0 (CRIT)
    #   M0: LF=0, LS=0, TF=0 (CRIT)
    activities = [
        ScheduleActivityIn(activity_id="M0", wbs_code="1", name="Kickoff", is_milestone=True, duration_days=0, source_ref="Owner notice"),
        ScheduleActivityIn(
            activity_id="A1",
            wbs_code="1.1",
            name="Excavation & Trenching",
            duration_days=4,
            predecessors=[ActivityDependencyIn(predecessor_id="M0", lag_days=0)],
            source_ref="Owner civil foreman estimate",
        ),
        ScheduleActivityIn(
            activity_id="A2",
            wbs_code="1.1",
            name="MDB Mounting",
            duration_days=3,
            predecessors=[ActivityDependencyIn(predecessor_id="A1", lag_days=0)],
            source_ref="Owner electrical lead estimate",
        ),
        ScheduleActivityIn(
            activity_id="A3",
            wbs_code="1.1",
            name="Floor Screed & Tiling",
            duration_days=5,
            predecessors=[ActivityDependencyIn(predecessor_id="A1", lag_days=0)],
            source_ref="Owner finish trade estimate",
        ),
        ScheduleActivityIn(
            activity_id="A4",
            wbs_code="1.1",
            name="Doors & Commissioning",
            duration_days=4,
            predecessors=[
                ActivityDependencyIn(predecessor_id="A2", lag_days=0),
                ActivityDependencyIn(predecessor_id="A3", lag_days=1),
            ],
            source_ref="Owner commissioning schedule + 1 wd cure lag",
        ),
        ScheduleActivityIn(
            activity_id="M1",
            wbs_code="1",
            name="Handover Readiness",
            is_milestone=True,
            duration_days=0,
            predecessors=[ActivityDependencyIn(predecessor_id="A4", lag_days=0)],
            source_ref="Owner handover target",
        ),
    ]

    libya_cal = WorkCalendarIn(preset="libya_sun_thu", weekend_days=[4, 5], holidays=[], hours_per_day=8.0)
    res = evaluate_project_schedule(
        start_date="2026-11-22",
        calendar=libya_cal,
        wbs_items=wbs,
        activities=activities,
    )
    assert res.critical_path_complete is True
    assert res.total_duration_wd == 14
    assert res.effective_start_date == "2026-11-22"
    assert res.project_finish_date == "2026-12-09"
    assert res.critical_path_ids == ["M0", "A1", "A3", "A4", "M1"]

    acts = {a.activity_id: a for a in res.activities}
    assert (acts["A1"].early_start_wd, acts["A1"].early_finish_wd) == (0, 4)
    assert (acts["A1"].planned_start, acts["A1"].planned_finish) == ("2026-11-22", "2026-11-25")
    assert (acts["A2"].early_start_wd, acts["A2"].early_finish_wd, acts["A2"].total_float_wd) == (4, 7, 3)
    assert (acts["A2"].planned_start, acts["A2"].planned_finish) == ("2026-11-26", "2026-11-30")
    assert acts["A2"].is_critical is False
    assert (acts["A3"].early_start_wd, acts["A3"].early_finish_wd, acts["A3"].total_float_wd) == (4, 9, 0)
    assert (acts["A3"].planned_start, acts["A3"].planned_finish) == ("2026-11-26", "2026-12-02")
    assert (acts["A4"].early_start_wd, acts["A4"].early_finish_wd, acts["A4"].total_float_wd) == (10, 14, 0)
    assert (acts["A4"].planned_start, acts["A4"].planned_finish) == ("2026-12-06", "2026-12-09")
    assert (acts["M1"].planned_start, acts["M1"].planned_finish) == ("2026-12-09", "2026-12-09")

    # Explicit owner holiday on Sun 2026-12-06 shifts A4 by 1 calendar working day -> finishes Thu 2026-12-10
    hol_cal = WorkCalendarIn(preset="libya_sun_thu", weekend_days=[4, 5], holidays=["2026-12-06"])
    hol_res = evaluate_project_schedule(
        start_date="2026-11-22",
        calendar=hol_cal,
        wbs_items=wbs,
        activities=activities,
    )
    assert hol_res.project_finish_date == "2026-12-10"
    assert next(a for a in hol_res.activities if a.activity_id == "A4").planned_start == "2026-12-07"

    # Disjoint branch with omitted duration ('not provided') blocks ONLY that branch while clean branch computes CPM!
    mixed_acts = list(activities) + [
        ScheduleActivityIn(
            activity_id="B1",
            wbs_code="1.1",
            name="Custom HVAC Chiller Fabrication",
            duration_days=None,  # NOT PROVIDED!
            predecessors=[],
            source_ref="Awaiting OEM factory lead time",
        ),
        ScheduleActivityIn(
            activity_id="B2",
            wbs_code="1.1",
            name="Chiller Rigging",
            duration_days=2,
            predecessors=[ActivityDependencyIn(predecessor_id="B1", lag_days=0)],
            source_ref="Owner rigging estimate",
        ),
    ]
    partial_res = evaluate_project_schedule(
        start_date="2026-11-22",
        calendar=libya_cal,
        wbs_items=wbs,
        activities=mixed_acts,
    )
    assert partial_res.critical_path_complete is False
    assert partial_res.total_duration_wd is None
    assert partial_res.project_finish_date is None
    assert partial_res.critical_path_ids == ["M0", "A1", "A3", "A4", "M1"]
    assert len(partial_res.missing_duration_flags) == 1
    assert len(partial_res.blocked_branch_flags) == 1
    p_acts = {a.activity_id: a for a in partial_res.activities}
    assert p_acts["B1"].display_duration == NOT_PROVIDED_LABEL
    assert p_acts["B1"].cpm_status == "blocked_missing_duration"
    assert p_acts["B2"].cpm_status == "blocked_missing_duration"
    assert p_acts["B2"].late_start_wd is None
    assert p_acts["B2"].is_critical is False
    assert p_acts["A4"].cpm_status == "computed"

    # Cycle must raise cleanly in strict mode
    cyclic_acts = [
        ScheduleActivityIn(
            activity_id="C1",
            wbs_code="1",
            name="Step 1",
            duration_days=2,
            predecessors=[ActivityDependencyIn(predecessor_id="C2")],
            source_ref="Owner test",
        ),
        ScheduleActivityIn(
            activity_id="C2",
            wbs_code="1",
            name="Step 2",
            duration_days=2,
            predecessors=[ActivityDependencyIn(predecessor_id="C1")],
            source_ref="Owner test",
        ),
    ]
    try:
        evaluate_project_schedule(start_date="2026-11-22", calendar=libya_cal, wbs_items=wbs, activities=cyclic_acts)
        raise AssertionError("Expected PlanningInputError on dependency cycle")
    except PlanningInputError as exc:
        assert "cycle" in str(exc).lower()


def test_step16_api_project_grounding_baseline_variance_gantt_pdf_xlsx_and_qa_pass(tmp_path: Path) -> None:
    """Full end-to-end API flow linking real BOQ/Spec/Calc/ResearchSource -> Arabic RTL & English LTR Gantt PDF + Live XLSX, Baseline Comparison, QA Pass."""
    settings = _test_settings(tmp_path)
    app = create_app(settings=settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        proj = client.post(
            "/api/projects",
            json={"name": "مشروع تأهيل عيادة", "code": "CLN-PLAN", "classification": "For Review"},
        ).json()
        pid = proj["id"]

        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="Clinic Construction Scheduling",
                prompt="Build CPM WBS schedule & Gantt export",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={"expected_deliverables": ["Project WBS CPM Schedule Gantt PDF XLSX"]},
            )
            rs = ResearchSource(
                project_id=pid,
                source_name="Owner Approved Site Workhours Memorandum",
                url="https://example.org/workhours-memo",
                publication_date="2026-01-15",
                accessed_at=datetime.now(timezone.utc),
                relevant_info="Libya Sunday-Thursday 8h/day site shift basis.",
                reliability_assessment="reputable",
                source_type="web",
                source_priority_tier="owner_provided",
                priority_rank=1,
                access_status="owner_provided",
                reviewed=True,
                http_status=200,
                untrusted_neutralized=True,
            )
            db.add_all([task, rs])
            db.commit()
            tid = task.id
            rs_id = rs.id

        preset_model = client.get("/api/parametric-drawings/clinic-preset").json()
        assert client.post(
            f"/api/projects/{pid}/parametric-drawings",
            json={
                "task_id": tid,
                "drawing_no": "A-101",
                "title": "Clinic Plan",
                "scale_denominator": 100,
                "paper_size": "A3",
                "classification": "For Review",
                "plan_model": preset_model,
            },
        ).status_code == 201

        boq = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={
                "task_id": tid,
                "title": "Clinic Renovation BOQ",
                "currency": "LYD",
                "classification": "For Review",
                "include_dxf_ifc": False,
                "include_boq_imports": False,
            },
        ).json()
        item_res = client.post(
            f"/api/boq-sheets/{boq['id']}/items",
            json={
                "item_no": "C-01",
                "description": "Concrete reinforced ground beam & screed works",
                "unit": "m3",
                "quantity": 32.0,
                "unit_rate": 380.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner BOQ unit rate",
                "discipline": "structural",
                "verification_status": "Manual",
            },
        ).json()
        boq_item_id = next(it["id"] for it in item_res["items"] if it["item_no"] == "C-01")
        assert client.post(f"/api/boq-sheets/{boq['id']}/export", json={"language": "en"}).status_code == 201

        spec_res = client.post(
            f"/api/projects/{pid}/specifications",
            json={
                "task_id": tid,
                "title": "Clinic Civil & Finish Specs",
                "discipline": "structural",
                "language": "en",
                "classification": "For Review",
                "boq_sheet_ids": [boq["id"]],
                "research_source_ids": [rs_id],
                "use_ai": False,
            },
        )
        assert spec_res.status_code == 201
        spec_id = spec_res.json()["id"]

        calc_res = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "calculation_type": "electrical_load_schedule",
                "title": "Clinic Panel Load Calc",
                "language": "en",
                "classification": "For Review",
                "inputs": {
                    "panel_name": "MDB-01",
                    "supply_phase": "3ph",
                    "system_voltage_v": 400,
                    "spare_margin_pct": 10,
                    "max_phase_unbalance_pct": 10,
                    "circuits": [
                        {
                            "circuit_id": "L1",
                            "description": "Clinic lighting & HVAC",
                            "phase": "3ph",
                            "connected_load_kw": 30,
                            "demand_factor": 0.9,
                            "power_factor": 0.85,
                        }
                    ],
                },
                "references": [
                    {
                        "source_kind": "owner_supplied",
                        "source_name": "Owner Panel Demand Input",
                        "source_ref": "Clinic load estimate sheet",
                    }
                ],
            },
        )
        assert calc_res.status_code == 201
        calc_id = calc_res.json()["id"]

        presets = client.get("/api/planning/presets").json()
        assert len(presets["presets"]) >= 1

        # 1. Create Baseline Schedule (Arabic RTL, Libya calendar, 0 AI tokens)
        base_payload = {
            "task_id": tid,
            "title": "الجدول المرجعي الأساسي للعيادة",
            "discipline": "multidisciplinary",
            "language": "ar",
            "classification": "For Review",
            "start_date": "2026-11-22",
            "set_as_baseline": True,
            "use_ai": False,
            "calendar": {
                "preset": "libya_sun_thu",
                "weekend_days": [4, 5],
                "holidays": [],
                "hours_per_day": 8.0,
                "source_ref": "Owner-approved Libya Sun-Thu calendar",
            },
            "wbs_items": [
                {"wbs_code": "1", "title": "البرنامج العام للعيادة", "discipline": "multidisciplinary"},
                {"wbs_code": "1.1", "title": "أعمال الخرسانة والكهرباء", "parent_code": "1", "discipline": "structural"},
            ],
            "activities": [
                {
                    "activity_id": "M0",
                    "wbs_code": "1",
                    "name": "استلام الموقع والانطلاق",
                    "is_milestone": True,
                    "duration_days": 0,
                    "predecessors": [],
                    "source_kind": "research_source",
                    "source_ref": "Owner Workhours Memo",
                    "research_source_id": rs_id,
                },
                {
                    "activity_id": "A1",
                    "wbs_code": "1.1",
                    "name": "أعمال القواعد والخرسانة المسلحة",
                    "duration_days": 5,
                    "quantity": 32.0,
                    "unit": "m3",
                    "predecessors": [{"predecessor_id": "M0", "dep_type": "FS", "lag_days": 0}],
                    "source_kind": "boq_item",
                    "source_ref": "BOQ C-01 (32 m3) + Owner 5 wd crew basis",
                    "boq_item_id": boq_item_id,
                },
                {
                    "activity_id": "A2",
                    "wbs_code": "1.1",
                    "name": "تركيب اللوحة الكهربائية والاختبارات",
                    "duration_days": 3,
                    "predecessors": [{"predecessor_id": "A1", "dep_type": "FS", "lag_days": 0}],
                    "source_kind": "calculation",
                    "source_ref": "MDB-01 Load Schedule + Owner 3 wd commissioning",
                    "calculation_id": calc_id,
                },
                {
                    "activity_id": "A3",
                    "wbs_code": "1.1",
                    "name": "فحص واعتماد المواصفات والتسليم",
                    "duration_days": 4,
                    "predecessors": [{"predecessor_id": "A1", "dep_type": "FS", "lag_days": 1}],
                    "source_kind": "specification",
                    "source_ref": "Clinic Specs Acceptance + Owner 4 wd QA test",
                    "specification_id": spec_id,
                },
            ],
        }
        base_res = client.post(f"/api/projects/{pid}/schedules", json=base_payload)
        assert base_res.status_code == 201, base_res.text
        base_data = base_res.json()
        base_id = base_data["id"]
        assert base_data["tokens_used"] == 0
        assert base_data["is_baseline"] is True
        assert base_data["schedule_result"]["critical_path_ids"] == ["M0", "A1", "A3"]
        assert base_data["schedule_result"]["total_duration_wd"] == 10  # A1(5) + lag(1) + A3(4) = 10

        # Check Arabic RTL Gantt PDF & Live-Formula XLSX on disk & SHA-256
        delivs = {d["format"]: d for d in base_data["deliverables"]}
        assert {"pdf", "xlsx"}.issubset(delivs.keys())
        for d_rec in delivs.values():
            fpath = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], d_rec["relative_path"])
            assert fpath.is_file()
            assert sha256_file(fpath) == d_rec["sha256"]

        pdf_doc = pymupdf.open(
            str(resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], delivs["pdf"]["relative_path"]))
        )
        pdf_txt = " ".join("\n".join(p.get_text("text") for p in pdf_doc).replace("\xa0", " ").replace("\xad", "-").split())
        pdf_doc.close()
        assert "10" in pdf_txt and "A1" in pdf_txt and "A3" in pdf_txt

        wb = load_workbook(
            str(resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], delivs["xlsx"]["relative_path"])),
            data_only=False,
        )
        ws = wb.active
        assert ws.views.sheetView[0].rightToLeft is True
        formulas = [
            ws.cell(row=r, column=c).value
            for r in range(1, ws.max_row + 1)
            for c in range(1, ws.max_column + 1)
            if isinstance(ws.cell(row=r, column=c).value, str) and ws.cell(row=r, column=c).value.startswith("=")
        ]
        assert any(f.startswith("=IF(") for f in formulas)
        assert any(f.startswith("=COUNTIF(") for f in formulas)
        wb.close()

        # Run independent QA review on Baseline Schedule -> MUST PASS!
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid, "classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_data = qa_res.json()
        assert base_id in qa_data["qa_context_summary"]["inspected_schedule_ids"]
        assert qa_data["status"] == "passed", qa_data["issues"]

        # Verify Task gate succeeds cleanly!
        assert client.post(f"/api/tasks/{tid}/verify", json={"qa_review_id": qa_data["id"]}).status_code == 200

        # 2. Create Current Update Schedule (English LTR) with A3 delayed +2 wd & Baseline Comparison
        upd_payload = {
            **base_payload,
            "title": "Current Progress Revision 02",
            "language": "en",
            "set_as_baseline": False,
            "baseline_schedule_id": base_id,
            "activities": [
                act if act["activity_id"] != "A3" else {**act, "duration_days": 6}
                for act in base_payload["activities"]
            ],
        }
        upd_res = client.post(f"/api/projects/{pid}/schedules", json=upd_payload)
        assert upd_res.status_code == 201, upd_res.text
        upd_data = upd_res.json()
        assert upd_data["schedule_result"]["baseline_schedule_id"] == base_id
        assert upd_data["schedule_result"]["total_duration_wd"] == 12
        assert upd_data["schedule_result"]["project_finish_variance_wd"] == 2
        upd_a3 = next(a for a in upd_data["schedule_result"]["activities"] if a["activity_id"] == "A3")
        assert upd_a3["finish_variance_wd"] == 2
        assert upd_a3["variance_status"] == "delayed"

        # Export English LTR Gantt PDF + XLSX -> export_version 2
        exp_res = client.post(f"/api/schedules/{upd_data['id']}/export", json={"language": "en"})
        assert exp_res.status_code == 201
        assert exp_res.json()["schedule"]["export_version"] == 2
        assert exp_res.json()["pdf_deliverable"]["folder_name"] == "03_Analysis"


def test_step16_optional_ai_unverified_and_qa_catches_all_seeded_schedule_defects(tmp_path: Path) -> None:
    """Verify optional AI UNVERIFIED AI DRAFT tag and QA catching cycles, orphans, missing durations, unsourced activities, date/CP tampering, & corrupt XLSX."""
    settings = _test_settings(tmp_path)
    app = create_app(settings=settings, secret_store=_InMemorySecretStore({"gemini": "mock-key"}))

    def fake_factory(api_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, **kwargs: Any) -> Any:
                return SimpleNamespace(
                    text='{"executive_summary": "Main branch spans 5 wd; Branch B awaiting OEM duration."}',
                    usage_metadata=SimpleNamespace(prompt_token_count=140, candidates_token_count=35, total_token_count=175),
                )

        return SimpleNamespace(models=_Models())

    app.state.provider_client_factory = fake_factory

    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Schedule Defect Trap", "code": "CLN-SCH-TRAP"}).json()
        pid = proj["id"]

        # API must reject dependency cycle & dangling BOQ reference with 422
        cyc_res = client.post(
            f"/api/projects/{pid}/schedules",
            json={
                "start_date": "2026-11-22",
                "calendar": {"preset": "libya_sun_thu", "holidays": [], "hours_per_day": 8},
                "wbs_items": [{"wbs_code": "1", "title": "Root"}],
                "activities": [
                    {
                        "activity_id": "A",
                        "wbs_code": "1",
                        "name": "Step A",
                        "duration_days": 2,
                        "predecessors": [{"predecessor_id": "B", "dep_type": "FS", "lag_days": 0}],
                        "source_kind": "owner_entered",
                        "source_ref": "Test",
                    },
                    {
                        "activity_id": "B",
                        "wbs_code": "1",
                        "name": "Step B",
                        "duration_days": 2,
                        "predecessors": [{"predecessor_id": "A", "dep_type": "FS", "lag_days": 0}],
                        "source_kind": "owner_entered",
                        "source_ref": "Test",
                    },
                ],
            },
        )
        assert cyc_res.status_code == 422

        # Create schedule with optional AI + missing duration ('not provided') on Branch B
        s_res = client.post(
            f"/api/projects/{pid}/schedules",
            json={
                "title": "Partial Schedule With Defects",
                "language": "en",
                "start_date": "2026-11-22",
                "use_ai": True,
                "calendar": {"preset": "libya_sun_thu", "holidays": [], "hours_per_day": 8},
                "wbs_items": [{"wbs_code": "1", "title": "Master WBS"}],
                "activities": [
                    {
                        "activity_id": "A1",
                        "wbs_code": "1",
                        "name": "Clean Activity",
                        "duration_days": 5,
                        "predecessors": [],
                        "source_kind": "owner_entered",
                        "source_ref": "Owner schedule A1",
                    },
                    {
                        "activity_id": "B1",
                        "wbs_code": "1",
                        "name": "Pending Lead Time Item",
                        "duration_days": None,
                        "predecessors": [],
                        "source_kind": "owner_entered",
                        "source_ref": "Awaiting supplier quote",
                    },
                ],
            },
        )
        assert s_res.status_code == 201, s_res.text
        s_data = s_res.json()
        assert s_data["ai_draft_status"] == "unverified_ai_draft"
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in s_data["summary"]
        assert s_data["tokens_used"] == 175

        # Tamper DB payload with dependency cycle, orphan WBS, missing source_ref, tampered dates, tampered critical path, + corrupt XLSX!
        xlsx_deliv = next(d for d in s_data["deliverables"] if d["format"] == "xlsx")
        xlsx_path = resolve_project_file_path(settings.workspaces_dir, proj["workspace_slug"], xlsx_deliv["relative_path"])
        xlsx_path.write_bytes(b"corrupt-non-zip-schedule-xlsx")

        with app.state.session_factory() as db:
            row = db.get(ProjectSchedule, s_data["id"])
            assert row is not None
            acts = [dict(a) for a in row.activities_json]
            # Seed orphan WBS + blank source_ref on A1 + cycle between B1 <-> A1!
            acts[0]["source_ref"] = ""
            acts[0]["predecessors"] = [{"predecessor_id": "B1", "dep_type": "FS", "lag_days": 0}]
            acts[1]["wbs_code"] = "99-ORPHAN"
            acts[1]["predecessors"] = [{"predecessor_id": "A1", "dep_type": "FS", "lag_days": 0}]
            row.activities_json = acts

            res_tamper = dict(row.schedule_result_json)
            res_tamper["effective_start_date"] = "1999-01-01"
            res_tamper["critical_path_ids"] = ["FAKE_NODE"]
            row.schedule_result_json = res_tamper
            db.commit()

        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_data = qa_res.json()
        assert qa_data["status"] != "passed"
        titles = {iss["title"] for iss in qa_data["issues"]}
        assert "Dependency cycle detected in project schedule" in titles
        assert "Orphan activity or broken WBS/dependency link in project schedule" in titles
        assert "Missing activity duration ('not provided') blocks critical path in project schedule" in titles
        assert "Project schedule activity missing source reference" in titles
        assert "Project schedule date or float arithmetic mismatch" in titles
        assert "Project schedule critical path mismatch" in titles
        assert "AI-drafted schedule summary pending owner approval" in titles
        assert "Exported XLSX unreadable or missing" in titles
