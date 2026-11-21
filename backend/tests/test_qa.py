"""Tests for Step 12 QA Agent and Issue Register: producer-reasoning isolation, seeded error detection (wrong total, wrong unit, fake reference, schedule mismatch, missing deliverables), issue closure lifecycle, and verification gate."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.agents.qa_agent import build_isolated_qa_context, serialize_isolated_qa_prompt_context
from app.core.config import Settings
from app.db.models import BoqItem, Deliverable, ParametricDrawing, Project, ResearchSource, ReviewReport, Task, TaskStep
from app.main import create_app
from app.providers.secrets import SecretStore
from app.services.parametric_cad import sha256_file
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


def test_step12_qa_context_excludes_producer_reasoning_and_task_never_verified_by_generation_alone(
    tmp_path: Path,
) -> None:
    """Verify QA context never sees producer reasoning, task stays unverified on generation alone, passing clean deliverables allows /verify at 0 AI tokens."""
    secret_marker = "PRODUCER_SECRET_CHAIN_OF_THOUGHT_DO_NOT_LEAK_777"

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, **kwargs: Any) -> Any:
                return SimpleNamespace(
                    text="{}",
                    parsed={
                        "language_detected": "en",
                        "restated_assignment": f"Prepare parametric clinic plan and coordinated BOQ ({secret_marker}).",
                        "primary_discipline": "architecture",
                        "secondary_disciplines": ["quantity_surveying"],
                        "expected_deliverables": ["Parametric Drawing", "Bill of Quantities"],
                        "input_files": [],
                        "applicable_standards_to_verify": ["NFPA 101"],
                        "missing_information": [],
                        "assumptions": [f"Assumption (to confirm with owner): {secret_marker}"],
                        "clarification_needed": False,
                        "clarifying_questions": [],
                        "recommended_next_steps": [f"Producer reasoning step: {secret_marker}"],
                        "suggested_classification": "For Review",
                    },
                    usage_metadata=SimpleNamespace(prompt_token_count=120, candidates_token_count=80, total_token_count=200),
                )

        return SimpleNamespace(models=_Models())

    settings = _test_settings(tmp_path)
    app = create_app(
        settings,
        secret_store=_InMemorySecretStore({"gemini": "test-step12-key"}),
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Clean Step 12 Clinic", "code": "CLN-QA-12", "classification": "For Review"},
        ).json()
        pid = project["id"]

        task_res = client.post(
            "/api/tasks",
            json={
                "project_id": pid,
                "title": "Clinic CAD & BOQ Package",
                "prompt": "Generate coordinated clinic plan (A-101) and clean BOQ.",
                "classification": "For Review",
            },
        )
        assert task_res.status_code == 201, task_res.text
        task = task_res.json()
        tid = task["id"]

        # Task generation MUST leave verification_status == "unverified"
        assert task["verification_status"] == "unverified"

        # Attempting to verify immediately by generation alone MUST fail (HTTP 422)
        premature_verify = client.post(f"/api/tasks/{tid}/verify", json={})
        assert premature_verify.status_code == 422
        assert "generation alone" in premature_verify.json()["detail"].lower()

        # Produce clean coordinated deliverables linked to this task:
        # 1) Step 11 parametric drawing (5 doors, 4 windows, 80.0 m2)
        clinic_model = build_synthetic_clinic_preset().model_dump()
        dwg_res = client.post(
            f"/api/projects/{pid}/parametric-drawings",
            json={
                "task_id": tid,
                "drawing_no": "A-101",
                "title": "Clinic Ground Plan",
                "scale_denominator": 100,
                "paper_size": "A3",
                "classification": "For Review",
                "plan_model": clinic_model,
            },
        )
        assert dwg_res.status_code == 201, dwg_res.text

        # 2) Clean consistent BOQ linked to same task (5 doors, 4 windows, 80 m2 floor finish, exported XLSX/CSV)
        boq_res = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={
                "task_id": tid,
                "title": "Clinic Coordinated BOQ",
                "currency": "LYD",
                "language": "en",
                "classification": "For Review",
            },
        )
        assert boq_res.status_code == 201, boq_res.text
        boq_id = boq_res.json()["id"]

        for item_payload in (
            {
                "item_no": "A-01",
                "description": "Flush timber and entrance doors per A-101 schedule",
                "unit": "nos",
                "quantity": 5.0,
                "unit_rate": 450.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner vendor quotation",
                "drawing_reference": "A-101",
            },
            {
                "item_no": "A-02",
                "description": "Double-glazed aluminum windows per A-101 schedule",
                "unit": "nos",
                "quantity": 4.0,
                "unit_rate": 600.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner window quotation",
                "drawing_reference": "A-101",
            },
            {
                "item_no": "A-03",
                "description": "Ground floor finish porcelain & vinyl across rooms",
                "unit": "m2",
                "quantity": 80.0,
                "unit_rate": 95.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner finish schedule",
                "drawing_reference": "A-101",
            },
        ):
            add_r = client.post(f"/api/boq-sheets/{boq_id}/items", json=item_payload)
            assert add_r.status_code == 201, add_r.text

        exp_r = client.post(f"/api/boq-sheets/{boq_id}/export", json={"language": "en"})
        assert exp_r.status_code == 201, exp_r.text

        # Seed secret marker into TaskStep notes directly to also test step notes isolation
        with app.state.session_factory() as db:
            step = db.query(TaskStep).filter(TaskStep.task_id == tid).first()
            if step is not None:
                step.notes = f"Producer chain note: {secret_marker}"
                db.commit()
            proj_row = db.get(Project, pid)
            task_row = db.get(Task, tid)
            assert proj_row is not None and task_row is not None
            isolated_ctx = build_isolated_qa_context(db, proj_row, task=task_row)
            serialized_ctx = serialize_isolated_qa_prompt_context(isolated_ctx)
            # Producer reasoning markers MUST NOT leak into QA context!
            assert secret_marker not in serialized_ctx
            assert "Producer reasoning step" not in serialized_ctx

        usage_before = client.get("/api/settings/provider").json()["daily_usage"]["total_tokens"]

        # Run independent QA review (0 AI tokens!)
        qa_res = client.post(
            f"/api/projects/{pid}/qa-reviews",
            json={"task_id": tid, "classification": "For Review"},
        )
        assert qa_res.status_code == 201, qa_res.text
        qa_data = qa_res.json()
        assert qa_data["producer_reasoning_excluded"] is True
        assert qa_data["tokens_used"] == 0
        assert qa_data["status"] == "passed"
        assert qa_data["open_issues_count"] == 0
        assert qa_data["task_verification_status"] == "qa_passed"

        usage_after = client.get("/api/settings/provider").json()["daily_usage"]["total_tokens"]
        assert usage_after == usage_before  # 0 Gemini tokens consumed by deterministic QA checks

        # Now task verification gate accepts verification cleanly
        ver_res = client.post(
            f"/api/tasks/{tid}/verify",
            json={"qa_review_id": qa_data["id"], "verifier_note": "Independent QA passed cleanly"},
        )
        assert ver_res.status_code == 200, ver_res.text
        assert ver_res.json()["verification_status"] == "verified"

        task_after = client.get(f"/api/tasks/{tid}").json()
        assert task_after["verification_status"] == "verified"


def test_step12_qa_catches_all_seeded_errors_and_manages_issue_register_lifecycle(
    tmp_path: Path,
) -> None:
    """Verify QA Agent catches all 5 seeded defects: wrong total, wrong unit, fake reference, schedule mismatch, and missing deliverable; verify issue close/reopen lifecycle."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Seeded Defects Hospital Wing", "code": "SEED-QA-12", "classification": "For Review"},
        ).json()
        pid = project["id"]
        workspace_slug = project["workspace_slug"]

        # Create task directly in DB + valid ParametricDrawing + BOQ + ReviewReport + unreviewed ResearchSource
        clinic_model = build_synthetic_clinic_preset().model_dump()
        dwg_res = client.post(
            f"/api/projects/{pid}/parametric-drawings",
            json={
                "drawing_no": "A-101",
                "title": "Seeded Defects Clinic Plan",
                "scale_denominator": 100,
                "paper_size": "A3",
                "plan_model": clinic_model,
            },
        )
        assert dwg_res.status_code == 201
        dwg = dwg_res.json()

        boq_res = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={"title": "Seeded Defects BOQ", "currency": "LYD", "language": "en"},
        )
        assert boq_res.status_code == 201
        boq_id = boq_res.json()["id"]

        # Remember one PDF path to restore later when fixing defects for QA re-run verification
        pdf_paths_deleted: list[tuple[str, str]] = []
        saved_pdf_bytes: bytes = b""
        with app.state.session_factory() as db:
            for deliv in db.query(Deliverable).filter(Deliverable.drawing_id == dwg["id"]).all():
                if deliv.format == "pdf" and deliv.relative_path:
                    pdf_disk = resolve_project_file_path(settings.workspaces_dir, workspace_slug, deliv.relative_path)
                    pdf_paths_deleted.append((deliv.id, deliv.relative_path))
                    break

        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="Seeded Defect Check Task",
                prompt="Prepare drawings, BOQ, and structural calculation report",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                plan_summary="PRODUCER_ONLY_PLAN_HIDDEN_FROM_QA",
                result_summary="PRODUCER_ONLY_RESULT_HIDDEN_FROM_QA",
                structured_output_json={
                    "expected_deliverables": ["Review Report", "Parametric Drawing", "Bill of Quantities"],
                    "recommended_next_steps": ["PRODUCER_REASONING_HIDDEN"],
                },
            )
            db.add(task)
            db.flush()
            tid = task.id

            # Link existing drawing + BOQ to this task
            dwg_row = db.get(ParametricDrawing, dwg["id"])
            assert dwg_row is not None
            dwg_row.task_id = tid
            # SEED ERROR (1a): Wrong stored area total on ParametricDrawing vs Shoelace 80.0 m2
            bad_metrics = dict(dwg_row.computed_metrics_json)
            bad_metrics["total_area_m2"] = 123.45
            dwg_row.computed_metrics_json = bad_metrics

            for deliv in db.query(Deliverable).filter(Deliverable.drawing_id == dwg_row.id).all():
                deliv.task_id = tid
                # SEED ERROR (5a): Remove PDF deliverable file from disk to trigger missing deliverable check!
                if deliv.format == "pdf" and deliv.relative_path:
                    pdf_disk = resolve_project_file_path(settings.workspaces_dir, workspace_slug, deliv.relative_path)
                    if pdf_disk.is_file():
                        saved_pdf_bytes = pdf_disk.read_bytes()
                        pdf_disk.unlink()

            # Unreviewed research source in log (HTTP 403 paywall -> reviewed=False)
            unrev_rs = ResearchSource(
                project_id=pid,
                source_name="Unreviewed Blocked Spec",
                url="https://blocked.invalid/iec-60439",
                accessed_at=datetime.now(timezone.utc),
                reliability_assessment="unreviewed",
                source_type="web",
                source_priority_tier="unverified",
                priority_rank=99,
                access_status="inaccessible",
                reviewed=False,
                http_status=403,
                failure_reason="HTTP 403",
                untrusted_neutralized=True,
            )
            db.add(unrev_rs)

            # SEED ERROR (1b) Wrong Total, (2) Wrong Unit, (3) Fake Reference, (4) Schedule Mismatch in BOQ items!
            db.add_all(
                [
                    BoqItem(
                        boq_sheet_id=boq_id,
                        row_order=1,
                        item_no="B-01",
                        description="Supply and install doors per A-101 schedule",
                        unit="nos",
                        quantity=9.0,  # SEED ERROR (4): Drawing A-101 has 5 doors, BOQ quantifies 9!
                        unit_rate=200.0,
                        total=9999.0,  # SEED ERROR (1): Wrong total (9 * 200 = 1800 != 9999)
                        reported_total=8888.0,  # SEED ERROR (1): Wrong reported_total
                        drawing_reference="A-101",
                        verification_status="Manual",
                        rate_source_kind="owner_input",
                        rate_source_ref="Owner quote",
                        discipline="architecture",
                    ),
                    BoqItem(
                        boq_sheet_id=boq_id,
                        row_order=2,
                        item_no="B-02",
                        description="Interior flush door frame assembly",
                        unit="m2",  # SEED ERROR (2): Incompatible area unit on countable door
                        quantity=2.0,
                        unit_rate=None,
                        drawing_reference="DWG-FAKE-999",  # SEED ERROR (3): Nonexistent drawing reference
                        technical_reference="https://fake-source.invalid/not-in-log",  # SEED ERROR (3): Fake URL not in reviewed logs
                        verification_status="Manual",
                        discipline="architecture",
                    ),
                    BoqItem(
                        boq_sheet_id=boq_id,
                        row_order=3,
                        item_no="B-03",
                        description="Switchroom copper cabling",
                        unit="unconfirmed (ft)",  # SEED ERROR (2): Unconfirmed/doubtful non-metric unit
                        quantity=25.0,
                        unit_rate=50.0,
                        total=1250.0,
                        rate_source_kind="dated_research",
                        rate_source_ref="https://blocked.invalid/iec-60439",  # SEED ERROR (3): Cites UNREVIEWED source
                        rate_source_date="2026-01-10",
                        verification_status="Extracted-Needs-Check",
                        discipline="electrical",
                    ),
                ]
            )

            # SEED ERROR (3b): ReviewReport referencing non-existent source ID 'EXT-999'
            rep = ReviewReport(
                project_id=pid,
                task_id=tid,
                title="Seeded Review Report",
                discipline="multidisciplinary",
                classification="For Review",
                revision="Rev 01",
                version=1,
                status="generated",
                structured_payload_json={
                    "findings": [
                        {
                            "finding_id": "F-BAD",
                            "discipline": "electrical",
                            "severity": "high",
                            "location_or_drawing_ref": "Switchroom",
                            "evidence": "Fake citation test",
                            "recommendation": "Verify",
                            "source_ref_ids": ["EXT-999"],
                        }
                    ],
                    "verified_facts": [],
                    "calculated_items": [],
                    "source_registry": [],
                },
            )
            db.add(rep)
            db.commit()

        # Execute independent QA review (0 AI tokens)
        qa_res = client.post(
            f"/api/projects/{pid}/qa-reviews",
            json={"task_id": tid, "classification": "For Review"},
        )
        assert qa_res.status_code == 201, qa_res.text
        qa_out = qa_res.json()

        assert qa_out["tokens_used"] == 0
        assert qa_out["status"] == "issues_found"
        assert qa_out["task_verification_status"] == "qa_failed"
        assert qa_out["producer_reasoning_excluded"] is True

        categories_found = {it["check_category"] for it in qa_out["issues"]}
        assert "arithmetic" in categories_found
        assert "unit" in categories_found
        assert "reference" in categories_found
        assert "schedule_consistency" in categories_found
        assert "missing_deliverable" in categories_found

        descriptions_joined = "\n".join(it["description"] for it in qa_out["issues"])
        assert "9999" in descriptions_joined or "1800" in descriptions_joined
        assert "123.45" in descriptions_joined
        assert "m2" in descriptions_joined and "unconfirmed" in descriptions_joined
        assert "DWG-FAKE-999" in descriptions_joined
        assert "https://fake-source.invalid/not-in-log" in descriptions_joined
        assert "EXT-999" in descriptions_joined
        assert "5 door(s)" in descriptions_joined and "9 door(s)" in descriptions_joined

        # Verify every issue carries all required Issue Register fields cleanly
        for it in qa_out["issues"]:
            assert it["issue_number"].startswith("QA-")
            assert it["description"]
            assert it["discipline"]
            assert it["severity"] in {"critical", "high", "medium", "low", "info"}
            assert it["reference"]
            assert it["corrective_action"]
            assert it["status"] == "open"

        # Attempting /verify while open issues remain MUST be rejected cleanly (HTTP 422)
        blocked_verify = client.post(f"/api/tasks/{tid}/verify", json={})
        assert blocked_verify.status_code == 422

        # Create one additional manual issue via POST /issues
        manual_res = client.post(
            f"/api/projects/{pid}/issues",
            json={
                "task_id": tid,
                "description": "Manual QA check: add fire-stopping collar detail at corridor wall",
                "discipline": "fire_life_safety",
                "severity": "medium",
                "reference": "Drawing A-101 Corridor R-03",
                "corrective_action": "Add UL-listed firestop collar detail to sheet A-101.",
            },
        )
        assert manual_res.status_code == 201
        manual_issue = manual_res.json()
        assert manual_issue["issue_number"].startswith("QA-")

        # Filterable issue register listing
        list_open = client.get(f"/api/projects/{pid}/issues", params={"status": "open"}).json()
        assert list_open["open_count"] == len(qa_out["issues"]) + 1
        assert list_open["closed_count"] == 0

        # Closing without a note or with <10 chars MUST return HTTP 422
        first_issue_id = list_open["issues"][0]["id"]
        no_note_close = client.patch(f"/api/issues/{first_issue_id}", json={"status": "closed"})
        assert no_note_close.status_code == 422
        short_note_close = client.patch(
            f"/api/issues/{first_issue_id}",
            json={"status": "closed", "closure_note": "too short"},
        )
        assert short_note_close.status_code == 422

        # Close every open issue via PATCH /api/issues/{id} with valid >=10-char closure_note
        for issue_row in list_open["issues"]:
            close_res = client.patch(
                f"/api/issues/{issue_row['id']}",
                json={"status": "closed", "closure_note": f"Resolved {issue_row['issue_number']} in revision."},
            )
            assert close_res.status_code == 200
            closed = close_res.json()
            assert closed["status"] == "closed"
            assert closed["closed_at"] is not None
            assert "Resolved" in closed["closure_note"]

        # Closing issues MUST NOT flip the QA review to "passed" or verify without a QA re-run
        list_after_close = client.get(f"/api/projects/{pid}/issues").json()
        assert list_after_close["open_count"] == 0
        assert list_after_close["closed_count"] == len(qa_out["issues"]) + 1

        stale_review = client.get(f"/api/qa-reviews/{qa_out['id']}").json()
        assert stale_review["status"] == "issues_found"
        assert stale_review["open_issues_count"] == 0

        verify_without_rerun = client.post(f"/api/tasks/{tid}/verify", json={"verifier_note": "Attempt before re-run"})
        assert verify_without_rerun.status_code == 422
        assert "re-run" in verify_without_rerun.json()["detail"].lower()

        # Now actually fix the underlying seeded defects so a QA re-run can pass
        with app.state.session_factory() as db:
            dwg_fix = db.get(ParametricDrawing, dwg["id"])
            assert dwg_fix is not None
            fixed_metrics = dict(dwg_fix.computed_metrics_json)
            fixed_metrics["total_area_m2"] = 80.0
            dwg_fix.computed_metrics_json = fixed_metrics
            for _deliv_id, rel_p in pdf_paths_deleted:
                restore_disk = resolve_project_file_path(settings.workspaces_dir, workspace_slug, rel_p)
                restore_disk.parent.mkdir(parents=True, exist_ok=True)
                restore_disk.write_bytes(saved_pdf_bytes)
            for b_item in db.query(BoqItem).filter(BoqItem.boq_sheet_id == boq_id).all():
                if b_item.item_no == "B-01":
                    b_item.quantity = 5.0
                    b_item.total = 1000.0
                    b_item.reported_total = 1000.0
                elif b_item.item_no == "B-02":
                    b_item.description = "Acoustic firestop collar assembly"
                    b_item.unit = "nos"
                    b_item.drawing_reference = "A-101"
                    b_item.technical_reference = "Owner vendor schedule"
                elif b_item.item_no == "B-03":
                    b_item.unit = "m"
                    b_item.rate_source_kind = "owner_input"
                    b_item.rate_source_ref = "Owner cable quote"
            # Remove the incomplete seeded ReviewReport stub & remove report expectation so task has clean drawing+BOQ
            db.query(ReviewReport).filter(ReviewReport.task_id == tid).delete()
            t_fix = db.get(Task, tid)
            assert t_fix is not None
            t_fix.structured_output_json = {
                "expected_deliverables": ["Parametric Drawing", "Bill of Quantities"],
            }
            db.commit()

        # Re-run independent QA after closing all issues and fixing defects
        rerun_res = client.post(
            f"/api/projects/{pid}/qa-reviews",
            json={"task_id": tid, "classification": "For Review"},
        )
        assert rerun_res.status_code == 201, rerun_res.text
        rerun_out = rerun_res.json()
        assert rerun_out["status"] == "passed"
        assert rerun_out["task_verification_status"] == "qa_passed"

        # Now task verification gate accepts verification cleanly
        verify_ok = client.post(f"/api/tasks/{tid}/verify", json={"verifier_note": "All issues resolved and QA re-run passed"})
        assert verify_ok.status_code == 200, verify_ok.text
        assert verify_ok.json()["verification_status"] == "verified"

        # Reopening an issue invalidates task verification status cleanly
        reopen_res = client.patch(f"/api/issues/{manual_issue['id']}", json={"status": "open"})
        assert reopen_res.status_code == 200
        assert reopen_res.json()["status"] == "open"
        assert client.get(f"/api/tasks/{tid}").json()["verification_status"] == "qa_failed"


def test_step12_empty_project_qa_is_no_evidence_and_verify_returns_422(tmp_path: Path) -> None:
    """Fix (1): Empty project or task with zero inspected artefacts / missing expected deliverables must NEVER pass QA or verify."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Empty QA Project", "code": "EMP-QA-12", "classification": "Preliminary"},
        ).json()
        pid = project["id"]

        # Create a task in the empty project (with non-keyword expected_deliverables too)
        with app.state.session_factory() as db:
            empty_task = Task(
                project_id=pid,
                title="Empty Task With No Deliverables",
                prompt="Check empty project",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="Preliminary",
                structured_output_json={
                    "expected_deliverables": ["Structural Calculation Sheet", "Bill of Quantities"],
                },
            )
            db.add(empty_task)
            db.commit()
            tid = empty_task.id

        # 1) Project-level QA on completely empty project (0 BOQ/drawing/report/deliverable)
        proj_qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={})
        assert proj_qa_res.status_code == 201, proj_qa_res.text
        proj_qa = proj_qa_res.json()
        assert proj_qa["status"] == "no_evidence"
        assert proj_qa["status"] != "passed"

        # Attempting /verify referencing the empty-project QA review MUST return 422
        verify_proj_empty = client.post(
            f"/api/tasks/{tid}/verify",
            json={"qa_review_id": proj_qa["id"]},
        )
        assert verify_proj_empty.status_code == 422

        # 2) Task-level QA on empty task (no deliverables produced at all)
        task_qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid})
        assert task_qa_res.status_code == 201, task_qa_res.text
        task_qa = task_qa_res.json()
        assert task_qa["status"] == "no_evidence"
        assert task_qa["task_verification_status"] == "qa_failed"
        assert task_qa["issues_opened_count"] >= 2

        verify_task_empty = client.post(f"/api/tasks/{tid}/verify", json={})
        assert verify_task_empty.status_code == 422

        # 3) Task-level QA with check_missing_deliverables=False on empty task MUST STILL NOT pass
        bypass_qa_res = client.post(
            f"/api/projects/{pid}/qa-reviews",
            json={"task_id": tid, "check_missing_deliverables": False},
        )
        assert bypass_qa_res.status_code == 201
        assert bypass_qa_res.json()["status"] == "no_evidence"
        assert bypass_qa_res.json()["task_verification_status"] == "qa_failed"
        assert client.post(f"/api/tasks/{tid}/verify", json={}).status_code == 422


def test_step12_issue_closure_requires_note_and_verify_requires_qa_rerun(tmp_path: Path) -> None:
    """Fix (2): Closing an issue requires >=10-char closure_note, keeps review non-passed, and /verify requires a QA re-run after closure."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Closure Gate Clinic", "code": "CLS-QA-12", "classification": "For Review"},
        ).json()
        pid = project["id"]

        clinic_model = build_synthetic_clinic_preset().model_dump()
        dwg_res = client.post(
            f"/api/projects/{pid}/parametric-drawings",
            json={
                "drawing_no": "A-101",
                "title": "Clean Plan",
                "scale_denominator": 100,
                "paper_size": "A3",
                "plan_model": clinic_model,
            },
        )
        assert dwg_res.status_code == 201
        dwg_id = dwg_res.json()["id"]

        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="Drawing Verification Task",
                prompt="Verify plan",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={"expected_deliverables": ["Parametric Drawing"]},
            )
            db.add(task)
            db.flush()
            tid = task.id
            dwg_row = db.get(ParametricDrawing, dwg_id)
            assert dwg_row is not None
            dwg_row.task_id = tid
            for d in db.query(Deliverable).filter(Deliverable.drawing_id == dwg_id).all():
                d.task_id = tid
            db.commit()

        # First QA run passes cleanly
        pass_qa_1 = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid})
        assert pass_qa_1.status_code == 201
        pass_rev_1 = pass_qa_1.json()
        assert pass_rev_1["status"] == "passed"

        # Log a manual issue on the task -> resets task to qa_failed
        man = client.post(
            f"/api/projects/{pid}/issues",
            json={
                "task_id": tid,
                "description": "Add egress exit sign notation on corridor wall.",
                "discipline": "fire_life_safety",
                "severity": "medium",
                "reference": "Sheet A-101",
                "corrective_action": "Add illuminated exit sign symbol at Corridor R-03.",
            },
        )
        assert man.status_code == 201
        issue_id = man.json()["id"]

        # Closing with missing or <10-char closure_note MUST fail with 422
        assert client.patch(f"/api/issues/{issue_id}", json={"status": "closed"}).status_code == 422
        assert client.patch(
            f"/api/issues/{issue_id}",
            json={"status": "closed", "closure_note": "   fixed  "},
        ).status_code == 422

        # Closing with >=10-char closure_note succeeds
        closed = client.patch(
            f"/api/issues/{issue_id}",
            json={"status": "closed", "closure_note": "Added exit sign symbol on sheet A-101 Rev 02."},
        )
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"

        # Trying /verify using the old pre-closure passing review MUST fail 422 requiring a re-run
        stale_verify = client.post(
            f"/api/tasks/{tid}/verify",
            json={"qa_review_id": pass_rev_1["id"]},
        )
        assert stale_verify.status_code == 422
        assert "re-run" in stale_verify.json()["detail"].lower()

        # Re-running QA after issue closure creates a new passing review and unlocks /verify
        pass_qa_2 = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid})
        assert pass_qa_2.status_code == 201
        pass_rev_2 = pass_qa_2.json()
        assert pass_rev_2["status"] == "passed"

        verify_ok = client.post(
            f"/api/tasks/{tid}/verify",
            json={"qa_review_id": pass_rev_2["id"], "verifier_note": "Verified after QA re-run"},
        )
        assert verify_ok.status_code == 200
        assert verify_ok.json()["verification_status"] == "verified"


def test_step12_corrupt_xlsx_raises_integrity_finding(tmp_path: Path) -> None:
    """Fix (3): Corrupt or unreadable exported XLSX must raise a high-severity 'integrity' QA finding instead of passing silently."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Corrupt XLSX QA Project", "code": "XLSX-QA-12", "classification": "For Review"},
        ).json()
        pid = project["id"]
        workspace_slug = project["workspace_slug"]

        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="BOQ Export QA Task",
                prompt="Prepare BOQ export",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={"expected_deliverables": ["Bill of Quantities"]},
            )
            db.add(task)
            db.commit()
            tid = task.id

        boq_res = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={"task_id": tid, "title": "Corrupt Test BOQ", "currency": "LYD", "language": "en"},
        )
        assert boq_res.status_code == 201
        boq_id = boq_res.json()["id"]

        add_res = client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={
                "item_no": "Q-01",
                "description": "Concrete slab finishing",
                "unit": "m2",
                "quantity": 50.0,
                "unit_rate": 120.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner quote",
            },
        )
        assert add_res.status_code == 201

        exp_res = client.post(f"/api/boq-sheets/{boq_id}/export", json={"language": "en"})
        assert exp_res.status_code == 201, exp_res.text

        # Corrupt the exported XLSX bytes on disk AND sync sha256 so arithmetic XLSX check is tested directly
        with app.state.session_factory() as db:
            xlsx_deliv = (
                db.query(Deliverable)
                .filter(Deliverable.boq_id == boq_id, Deliverable.format == "xlsx")
                .first()
            )
            assert xlsx_deliv is not None and xlsx_deliv.relative_path
            xlsx_path = resolve_project_file_path(settings.workspaces_dir, workspace_slug, xlsx_deliv.relative_path)
            xlsx_path.write_bytes(b"NOT_A_VALID_XLSX_ZIP_ARCHIVE_CORRUPT")
            xlsx_deliv.sha256 = sha256_file(xlsx_path)
            db.commit()

        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid})
        assert qa_res.status_code == 201, qa_res.text
        qa_out = qa_res.json()
        assert qa_out["status"] == "issues_found"
        assert qa_out["task_verification_status"] == "qa_failed"

        integrity_issues = [
            it for it in qa_out["issues"] if it["check_category"] == "integrity" and it["severity"] == "high"
        ]
        assert len(integrity_issues) == 1
        assert "unreadable or missing" in integrity_issues[0]["title"].lower()
        assert ".xlsx" in (integrity_issues[0]["reference"] or "").lower()

        # Verify gate blocks task with corrupt XLSX
        assert client.post(f"/api/tasks/{tid}/verify", json={}).status_code == 422
