"""Step 21 end-to-end synthetic smoke test covering all 15 UI tabs & 17 SPEC.md acceptance criteria without real client data or secrets."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import ezdxf
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.providers.secrets import SecretStore


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


def _fake_orchestrator_factory() -> Any:
    def _factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, *, model: str, contents: Any, config: Any, **_kwargs: Any) -> Any:
                payload = {
                    "language_detected": "mixed",
                    "restated_assignment": "Synthesize multidisciplinary review package for Synthetic E2E Clinic (0% client data).",
                    "primary_discipline": "multidisciplinary",
                    "secondary_disciplines": ["architectural", "electrical", "structural"],
                    "expected_deliverables": ["Review Report", "BOQ", "Specs", "Schedule", "Calculation"],
                    "input_files": [
                        {"filename": "clinic_brief.txt", "role": "Design basis", "status": "attached"}
                    ],
                    "applicable_standards_to_verify": ["SYN-1000-2024"],
                    "missing_information": [],
                    "assumptions": ["PRELIMINARY synthetic smoke test assumption - confirm with owner."],
                    "clarification_needed": False,
                    "clarifying_questions": [],
                    "recommended_next_steps": ["Extract files", "Run deterministic checks", "Run QA review"],
                    "suggested_classification": "Preliminary",
                }
                return SimpleNamespace(
                    text=json.dumps(payload),
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=90,
                        candidates_token_count=45,
                        total_token_count=135,
                        thoughts_token_count=0,
                        cached_content_token_count=0,
                    ),
                )

        return SimpleNamespace(models=_Models())

    return _factory


def _build_synthetic_dxf_bytes() -> bytes:
    import io

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # metres
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (5, 0), (5, 4), (0, 4)], close=True, dxfattribs={"layer": "A-AREA"})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def test_step21_end_to_end_all_15_tabs_and_17_acceptance_criteria_synthetic_only(tmp_path: Path) -> None:
    """Exercise all 15 application tabs and 17 acceptance criteria end-to-end using strictly synthetic fixtures."""
    settings = Settings(workspaces_dir=tmp_path / "workspaces", database_url="")
    store = _InMemorySecretStore({"gemini": "nonkey-mock-orchestrator-smoke"})
    app = create_app(
        settings,
        secret_store=store,
        provider_client_factory=_fake_orchestrator_factory(),
    )

    with TestClient(app) as client:
        # [Tab 15: Settings & System] Health + Provider Settings + System Hardening info
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/settings/provider").json()["api_key_configured"] is True
        sys_info = client.get("/api/system/info").json()
        assert sys_info["backend_host"] == "127.0.0.1"
        assert sys_info["log_viewer_enabled"] is False
        assert sys_info["backup_excludes_keyring"] is True

        # [Tab 1: Projects & Files] Create Arabic+English synthetic clinic project & upload read-only files + extract
        proj = client.post(
            "/api/projects",
            json={
                "name": "عيادة طبية تمثيلية — Step 21 Synthetic Smoke",
                "code": "SYN-E2E-21",
                "project_type": "healthcare_clinic",
                "location": "Tripoli (Synthetic Fixture)",
                "language": "ar",
                "classification": "Preliminary",
            },
        )
        assert proj.status_code == 201
        pid = proj.json()["id"]

        up = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("clinic_brief.txt", b"Synthetic clinic area 20 m2 lighting 6 kW water 12 L/min.", "text/plain")),
                ("files", ("clinic_plan.dxf", _build_synthetic_dxf_bytes(), "application/dxf")),
            ],
        )
        assert up.status_code == 201
        file_ids = [item["file"]["id"] for item in up.json()["items"]]
        txt_file_id, dxf_file_id = file_ids[0], file_ids[1]

        ext_txt = client.post(f"/api/files/{txt_file_id}/extract")
        assert ext_txt.status_code == 201
        ext_dxf = client.post(f"/api/files/{dxf_file_id}/extract")
        assert ext_dxf.status_code == 201
        assert client.post(
            f"/api/extractions/{ext_dxf.json()['id']}/confirm-unit",
            json={"confirmed_unit": "m"},
        ).status_code == 200

        # [Tab 2: Assignments] Natural-language assignment understood by Orchestrator v0 + history
        task_res = client.post(
            "/api/tasks",
            json={
                "project_id": pid,
                "prompt": "Prepare preliminary multidisciplinary package for synthetic clinic using attached brief.",
                "attached_file_ids": [txt_file_id],
                "classification": "Preliminary",
            },
        )
        assert task_res.status_code == 201
        tid = task_res.json()["id"]
        assert client.get(f"/api/tasks/{tid}").status_code == 200

        # [Tab 3: Research] Controlled owner-provided source log run (0 web leakage, 0 AI synthesis tokens)
        res_run = client.post(
            "/api/research/runs",
            json={
                "project_id": pid,
                "task_id": tid,
                "query": "Synthetic clinic reference log",
                "owner_files": [{"file_id": txt_file_id, "priority_tier": "official_regulations"}],
                "synthesize_with_ai": False,
            },
        )
        assert res_run.status_code == 201
        rs_id = res_run.json()["sources"][0]["id"]

        # [Tab 4: Standards Library] Owner-created synthetic standard SYN-1000-2024 confirmed current + exported
        std_preset = client.get("/api/standards/presets").json()["presets"][0]["standard"]
        std_preset["project_id"] = pid
        std_res = client.post("/api/standards", json=std_preset)
        assert std_res.status_code == 201
        std_id = std_res.json()["id"]
        assert client.post(f"/api/standards/{std_id}/confirm", json={"confirmed_by": "Owner"}).status_code == 200
        assert client.post("/api/standards/export-register", json={"project_id": pid, "language": "ar"}).status_code == 201

        # [Tab 8: BOQ] Sheet + sourced line item + live XLSX/CSV export
        boq_sheet = client.post(
            f"/api/projects/{pid}/boq-sheets",
            json={"task_id": tid, "title": "Synthetic E2E BOQ", "language": "en", "currency": "USD"},
        )
        assert boq_sheet.status_code == 201
        boq_id = boq_sheet.json()["id"]
        assert client.post(
            f"/api/boq-sheets/{boq_id}/items",
            json={
                "item_no": "E2E-1",
                "description": "Synthetic Distribution Panel Board",
                "unit": "nos",
                "quantity": 1.0,
                "unit_rate": 1500.0,
                "rate_source_kind": "owner_input",
                "rate_source_ref": "Owner Synthetic Baseline Quote",
            },
        ).status_code == 201
        assert client.post(f"/api/boq-sheets/{boq_id}/export", json={"language": "en"}).status_code == 201

        # [Tab 9: Drawings] Parametric CAD DXF + scaled PDF + schedules + round-trip check
        clinic_model = client.get("/api/parametric-drawings/clinic-preset").json()
        drw_res = client.post(
            f"/api/projects/{pid}/parametric-drawings",
            json={
                "task_id": tid,
                "drawing_no": "A-101",
                "title": "Synthetic E2E Clinic Plan",
                "plan_model": clinic_model,
                "owner_confirmed_model": True,
            },
        )
        assert drw_res.status_code == 201
        drw_id = drw_res.json()["id"]
        assert drw_res.json()["round_trip_passed"] is True

        # [Tab 10: Calculations (MEP)] Deterministic electrical load schedule + DOCX/PDF/XLSX export
        calc_preset = client.get("/api/calculations/presets").json()["presets"][0]
        calc_res = client.post(
            f"/api/projects/{pid}/calculations",
            json={
                "task_id": tid,
                "title": calc_preset["title_en"],
                "calculation_type": calc_preset["calculation_type"],
                "language": "en",
                "inputs": calc_preset["inputs"],
                "references": [
                    {
                        "source_kind": "verified_source_log",
                        "source_name": "clinic_brief.txt",
                        "source_ref": "Owner-supplied clinic design brief",
                        "research_source_id": rs_id,
                    }
                ],
            },
        )
        assert calc_res.status_code == 201
        calc_id = calc_res.json()["id"]
        assert client.post(f"/api/calculations/{calc_id}/export", json={"language": "en"}).status_code == 201

        # [Tab 5: Specialist HVAC/Fire/Healthcare] Deterministic check linked to verified SYN-1000-2024 + export
        spec_preset = client.get("/api/specialist-assessments/presets").json()["presets"][0]
        spc_res = client.post(
            f"/api/projects/{pid}/specialist-assessments",
            json={
                "task_id": tid,
                "domain": spec_preset["domain"],
                "workflow_mode": spec_preset["workflow_mode"],
                "title": "Synthetic E2E Specialist Check",
                "language": "en",
                "inputs": spec_preset["inputs"],
                "references": [{"source_kind": "standard_library", "standard_library_id": std_id}],
            },
        )
        assert spc_res.status_code == 201
        spc_id = spc_res.json()["id"]
        assert client.post(f"/api/specialist-assessments/{spc_id}/export", json={"language": "en"}).status_code == 201

        # [Tab 6: Structural Support] Deterministic takedown/combos/statics I/O check linked to SYN-1000-2024 + export
        str_preset = client.get("/api/structural-assessments/presets").json()["presets"][0]
        str_res = client.post(
            f"/api/projects/{pid}/structural-assessments",
            json={
                "task_id": tid,
                "assessment_type": str_preset["assessment_type"],
                "title": "Synthetic E2E Structural I/O Check",
                "language": "en",
                "inputs": str_preset["inputs"],
                "references": [{"source_kind": "standard_library", "standard_library_id": std_id}],
            },
        )
        assert str_res.status_code == 201
        str_id = str_res.json()["id"]
        assert client.post(f"/api/structural-assessments/{str_id}/export", json={"language": "en"}).status_code == 201

        # [Tab 11: Specifications] Traceable spec from BOQ + drawing + research log + DOCX/PDF export
        spec_doc = client.post(
            f"/api/projects/{pid}/specifications",
            json={
                "task_id": tid,
                "title": "Synthetic E2E Specification Package",
                "language": "en",
                "boq_sheet_ids": [boq_id],
                "drawing_ids": [drw_id],
                "research_source_ids": [rs_id],
            },
        )
        assert spec_doc.status_code == 201
        assert client.post(f"/api/specifications/{spec_doc.json()['id']}/export", json={"language": "en"}).status_code == 201

        # [Tab 12: Comparisons] Decimal comparison + owner decision + export
        cmp_preset = client.get("/api/comparisons/presets").json()["presets"][0]
        cmp_res = client.post(
            f"/api/projects/{pid}/comparisons",
            json={
                "task_id": tid,
                "title": cmp_preset["title_en"],
                "comparison_scope": cmp_preset["comparison_scope"],
                "discipline": cmp_preset["discipline"],
                "language": "en",
                "lifecycle_years": cmp_preset["lifecycle_years"],
                "criteria": cmp_preset["criteria"],
                "options": cmp_preset["options"],
            },
        )
        assert cmp_res.status_code == 201
        cmp_id = cmp_res.json()["id"]
        selected_opt = cmp_res.json()["matrix"]["options"][0]["option_id"]
        assert (
            client.post(
                f"/api/comparisons/{cmp_id}/decide",
                json={"selected_option_id": selected_opt, "decided_by": "Owner", "decision_note": "Selected for Step 21 E2E synthetic smoke test."},
            ).status_code
            == 200
        )

        # [Tab 13: Planning] Deterministic WBS + CPM schedule + baseline + Gantt PDF/XLSX export
        pln_preset = client.get("/api/planning/presets").json()["presets"][0]
        pln_res = client.post(
            f"/api/projects/{pid}/schedules",
            json={
                "task_id": tid,
                "title": pln_preset["title_en"],
                "discipline": pln_preset["discipline"],
                "language": "en",
                "start_date": pln_preset["start_date"],
                "calendar": pln_preset["calendar"],
                "wbs_items": pln_preset["wbs_items"],
                "activities": pln_preset["activities"],
            },
        )
        assert pln_res.status_code == 201
        sch_id = pln_res.json()["id"]
        assert client.post(f"/api/schedules/{sch_id}/set-baseline").status_code == 200
        assert client.post(f"/api/schedules/{sch_id}/export", json={"language": "en"}).status_code == 201

        # [Tab 7: Review Reports & Deliverables] Generate report + retrieve & download deliverable
        rep_res = client.post(
            f"/api/projects/{pid}/review-reports",
            json={"task_id": tid, "file_ids": [txt_file_id, dxf_file_id], "research_run_ids": [res_run.json()["id"]], "language": "ar"},
        )
        assert rep_res.status_code == 201
        delivs = client.get(f"/api/projects/{pid}/deliverables").json()
        assert delivs["total"] >= 10
        dl = client.get(f"/api/deliverables/{delivs['deliverables'][0]['id']}/download")
        assert dl.status_code == 200
        assert len(dl.content) > 0

        # [Tab 14: QA] Independent QA inspection across ALL modules -> passes cleanly + verify task
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid})
        assert qa_res.status_code == 201
        qa_body = qa_res.json()
        assert qa_body["status"] == "passed", f"Unexpected QA issues in E2E smoke test: {qa_body.get('issues')}"
        verify_res = client.post(
            f"/api/tasks/{tid}/verify",
            json={"qa_review_id": qa_body["id"], "verifier_note": "E2E smoke verification passed."},
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["verification_status"] == "verified"

        # [Tab 15: System Backup & Dry-Run Restore] Create backup + verify SHA-256 dry-run
        bak = client.post("/api/system/backup", json={"label": "e2e_smoke"})
        assert bak.status_code == 201
        dry = client.post(
            "/api/system/restore",
            json={"backup_filename": bak.json()["backup"]["filename"], "dry_run": True},
        )
        assert dry.status_code == 200
        assert dry.json()["valid"] is True
        assert dry.json()["excludes_keyring"] is True
