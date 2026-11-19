"""Tests for Step 05 assignment intake, Orchestrator v0 structured JSON, Task History, and failure logging."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
import pytest

from app.core.config import Settings
from app.main import create_app
from app.providers import SecretStore


class _InMemorySecretStore(SecretStore):
    """Isolated test SecretStore so tests never read or alter Windows Credential Manager."""

    def __init__(self, initial_key: str | None = None) -> None:
        self._data: dict[str, str] = {}
        if initial_key:
            self._data["gemini"] = initial_key

    @property
    def backend_name(self) -> str:
        return "InMemoryTestSecretStore"

    def get_api_key(self, provider_name: str) -> str | None:
        return self._data.get(provider_name.strip().lower())

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        self._data[provider_name.strip().lower()] = api_key.strip()

    def delete_api_key(self, provider_name: str) -> None:
        self._data.pop(provider_name.strip().lower(), None)


def _fake_usage(prompt: int = 120, output: int = 65) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=output,
        total_token_count=prompt + output,
        thoughts_token_count=4,
        cached_content_token_count=0,
    )


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(workspaces_dir=tmp_path / "workspaces", database_url="")


def test_step05_arabic_english_mixed_assignments_orchestrator_v0_and_history(
    tmp_path: Path,
) -> None:
    """Three assignments (Arabic, English, mixed) persist structured understanding, files, steps, tokens, and history."""
    fake_key = "mock-step05-key-001"
    secret_store = _InMemorySecretStore(fake_key)
    captured_prompts: list[dict[str, Any]] = []

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                return [
                    SimpleNamespace(
                        name="models/gemini-3.8-flash",
                        display_name="Gemini 3.8 Flash",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/gemini-4-argon",
                        display_name="Gemini 4 Argon",
                        supported_actions=["generateContent"],
                    ),
                ]

            def generate_content(self, *, model: str, contents: Any, config: Any, **_kwargs: Any) -> Any:
                prompt_text = str(contents[0])
                captured_prompts.append(
                    {
                        "model": model,
                        "prompt": prompt_text,
                        "system": getattr(config, "system_instruction", ""),
                    }
                )
                if "مراجعة المخطط المعماري" in prompt_text:
                    payload = {
                        "language_detected": "ar",
                        "restated_assignment": "مراجعة المخطط المعماري للعيادة الطبية (مساحة 1200 م2) والتحقق من المتطلبات المبدئية مع الملف المرفق.",
                        "primary_discipline": "Architectural",
                        "secondary_disciplines": ["Fire & Life Safety", "Healthcare Engineering"],
                        "expected_deliverables": [
                            "تقرير ملاحظات المراجعة المعمارية",
                            "قائمة التحقق من الاشتراطات الصحية",
                        ],
                        "input_files": [
                            {
                                "filename": "clinic_plan.pdf",
                                "role": "المخطط المعماري المبدئي",
                                "status": "attached",
                            }
                        ],
                        "applicable_standards_to_verify": [
                            "Libyan Building & Municipality Requirements",
                            "NFPA 101 Life Safety Code",
                            "FGI Guidelines",
                        ],
                        "missing_information": ["عدد الأسرة أو السعة التصميمية للعيادة"],
                        "assumptions": ["الاستخدام المبدئي مركز رعاية نهارية من طابق واحد"],
                        "clarification_needed": True,
                        "clarifying_questions": [
                            "كم السعة التصميمية المتوقعة للمرضى وغرف الكشف؟"
                        ],
                        "recommended_next_steps": [
                            "استخراج النصوص والجداول من ملف clinic_plan.pdf في المرحلة التالية",
                        ],
                        "classification": "Preliminary",
                    }
                    return SimpleNamespace(
                        text="{}",
                        parsed=payload,
                        function_calls=[],
                        candidates=[SimpleNamespace(finish_reason="STOP")],
                        usage_metadata=_fake_usage(210, 95),
                    )

                if "Check primary concrete beam" in prompt_text:
                    payload = {
                        "language_detected": "en",
                        "restated_assignment": "Prepare an intake plan to verify a 6.0 m span reinforced concrete beam under preliminary dead and live loads.",
                        "primary_discipline": "Structural",
                        "secondary_disciplines": ["Engineering Quality Assurance"],
                        "expected_deliverables": ["Structural check plan and calculation outline"],
                        "input_files": [
                            {
                                "filename": "structural_framing.dxf",
                                "role": "Beam framing plan requested in prompt",
                                "status": "missing",
                            }
                        ],
                        "applicable_standards_to_verify": [
                            "ACI 318 Structural Concrete Code",
                            "ASCE 7 Minimum Design Loads",
                        ],
                        "missing_information": [],
                        "assumptions": ["Proceed on preliminary rectangular section assumption once loads are extracted"],
                        "clarification_needed": False,
                        "clarifying_questions": ["Should NOT be returned because clarification_needed is False"],
                        "recommended_next_steps": [
                            "Confirm beam section dimensions and concrete grade fc' before deterministic calculations",
                        ],
                        "classification": "Preliminary",
                    }
                    return SimpleNamespace(
                        text="{}",
                        parsed=payload,
                        function_calls=[],
                        candidates=[SimpleNamespace(finish_reason="STOP")],
                        usage_metadata=_fake_usage(180, 80),
                    )

                payload = {
                    "language_detected": "mixed",
                    "restated_assignment": "إعداد مسودة جدول الكميات المبدئي (BOQ) لمشروع Extension Building B بالاعتماد على المخطط والجداول المرفقة.",
                    "primary_discipline": "Quantity Surveying / BOQ",
                    "secondary_disciplines": ["Civil", "Structural"],
                    "expected_deliverables": [
                        "مسودة جدول كميات أولي (Draft BOQ)",
                        "قائمة البنود التي تحتاج تحققاً هندسياً",
                    ],
                    "input_files": [
                        {
                            "filename": "extension_schedule.xlsx",
                            "role": "Preliminary quantity breakdown table",
                            "status": "attached",
                        }
                    ],
                    "applicable_standards_to_verify": [
                        "POMI / CESMM Principles of Measurement",
                        "Libyan Tender & Specification Guidelines",
                    ],
                    "missing_information": ["تحديد العملة المعتمدة وأسعار الوحدة من المالك (LYD افتراضياً)"],
                    "assumptions": ["تُسجل الكميات كأولية بدون أسعار وحدة مخترعة"],
                    "clarification_needed": False,
                    "clarifying_questions": [],
                    "recommended_next_steps": [
                        "قراءة أوراق جدول البيانات extension_schedule.xlsx آلياً في الخطوة 06",
                    ],
                    "classification": "For Review",
                }
                return SimpleNamespace(
                    text="{}",
                    parsed=payload,
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=_fake_usage(240, 110),
                )

        return SimpleNamespace(models=_Models())

    app = create_app(
        _test_settings(tmp_path),
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        p1 = client.post(
            "/api/projects",
            json={"name": "عيادة طرابلس النموذجية", "code": "CLN-05", "location": "طرابلس"},
        )
        assert p1.status_code == 201
        project1_id = p1.json()["id"]

        p2 = client.post(
            "/api/projects",
            json={"name": "Extension Building B", "code": "EXT-B2"},
        )
        assert p2.status_code == 201
        project2_id = p2.json()["id"]

        # Upload sample input files to projects 1 and 2
        up1 = client.post(
            f"/api/projects/{project1_id}/files",
            files=[("files", ("clinic_plan.pdf", b"%PDF-1.4\n%MockPlan\n%%EOF", "application/pdf"))],
        )
        assert up1.status_code == 201
        clinic_file_id = up1.json()["items"][0]["file"]["id"]

        up2 = client.post(
            f"/api/projects/{project2_id}/files",
            files=[
                (
                    "files",
                    (
                        "extension_schedule.xlsx",
                        b"PK\x03\x04mock-xlsx-content",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )
            ],
        )
        assert up2.status_code == 201
        xlsx_file_id = up2.json()["items"][0]["file"]["id"]

        # Reject attaching project 2's file to project 1 task
        cross_err = client.post(
            "/api/tasks",
            json={
                "project_id": project1_id,
                "prompt": "Check schedule file",
                "attached_file_ids": [xlsx_file_id],
            },
        )
        assert cross_err.status_code == 400

        # Reject unknown project cleanly
        missing_proj = client.post(
            "/api/tasks",
            json={"project_id": "nonexistent-project-id", "prompt": "Check"},
        )
        assert missing_proj.status_code == 404

        # 1. Arabic assignment with attached PDF -> awaiting_clarification + clarifying question preserved
        t_ar = client.post(
            "/api/tasks",
            json={
                "project_id": project1_id,
                "prompt": "مراجعة المخطط المعماري للعيادة الطبية بمساحة 1200 م2 مع الملف المرفق.",
                "complexity": "fast",
                "attached_file_ids": [clinic_file_id],
            },
        )
        assert t_ar.status_code == 201
        d_ar = t_ar.json()
        assert d_ar["status"] == "awaiting_clarification"
        assert d_ar["classification"] == "Preliminary"
        assert d_ar["provider_name"] == "gemini"
        assert d_ar["model_name"] == "gemini-3.8-flash"
        assert d_ar["structured_output"]["language_detected"] == "ar"
        assert d_ar["structured_output"]["primary_discipline"] == "Architectural"
        assert d_ar["structured_output"]["clarification_needed"] is True
        assert len(d_ar["structured_output"]["clarifying_questions"]) == 1
        assert d_ar["token_usage"]["total_tokens"] == 305
        assert len(d_ar["attached_files"]) == 1
        assert d_ar["attached_files"][0]["filename"] == "clinic_plan.pdf"
        assert [s["module_name"] for s in d_ar["steps"]] == ["assignment_intake", "orchestrator_v0"]
        assert all(s["status"] == "completed" for s in d_ar["steps"])
        assert [log["action"] for log in d_ar["logs"]] == [
            "task.created",
            "provider.usage_recorded",
            "task.completed",
        ]

        # Confirm prompt wraps untrusted data in XML boundary tags
        assert "<UNTRUSTED_ASSIGNMENT_INPUT>" in captured_prompts[0]["prompt"]
        assert "<UNTRUSTED_ATTACHED_FILES>" in captured_prompts[0]["prompt"]
        assert "clinic_plan.pdf" in captured_prompts[0]["prompt"]

        # 2. English assignment without material missing clarification -> status completed + empty questions
        t_en = client.post(
            "/api/tasks",
            json={
                "project_id": project1_id,
                "title": "Beam Span 6.0m Intake",
                "prompt": "Check primary concrete beam for a 6.0m span against structural_framing.dxf.",
                "complexity": "deep",
            },
        )
        assert t_en.status_code == 201
        d_en = t_en.json()
        assert d_en["status"] == "completed"
        assert d_en["model_name"] == "gemini-4-argon"
        assert d_en["structured_output"]["language_detected"] == "en"
        assert d_en["structured_output"]["clarification_needed"] is False
        assert d_en["structured_output"]["clarifying_questions"] == []
        assert d_en["token_usage"]["total_tokens"] == 260

        # 3. Mixed Arabic+English assignment on project 2 -> status completed & attached xlsx
        t_mix = client.post(
            "/api/tasks",
            json={
                "project_id": project2_id,
                "prompt": "إعداد مسودة BOQ المبدئي لمشروع Extension Building B باستخدام جدول extension_schedule.xlsx.",
                "attached_file_ids": [xlsx_file_id],
                "classification": "For Review",
            },
        )
        assert t_mix.status_code == 201
        d_mix = t_mix.json()
        assert d_mix["status"] == "completed"
        assert d_mix["classification"] == "For Review"
        assert d_mix["structured_output"]["language_detected"] == "mixed"
        assert d_mix["structured_output"]["primary_discipline"] == "Quantity Surveying / BOQ"
        assert d_mix["token_usage"]["total_tokens"] == 350

        # Task History lists all 3 newest-first, supports filtering, and detail retrieval works
        hist_all = client.get("/api/tasks")
        assert hist_all.status_code == 200
        hist_data = hist_all.json()
        assert hist_data["total"] == 3
        assert [item["id"] for item in hist_data["tasks"]] == [d_mix["id"], d_en["id"], d_ar["id"]]

        hist_p1 = client.get(f"/api/tasks?project_id={project1_id}")
        assert hist_p1.status_code == 200
        assert hist_p1.json()["total"] == 2

        hist_clarify = client.get("/api/tasks?status=awaiting_clarification")
        assert hist_clarify.status_code == 200
        assert [item["id"] for item in hist_clarify.json()["tasks"]] == [d_ar["id"]]

        detail_fetch = client.get(f"/api/tasks/{d_ar['id']}")
        assert detail_fetch.status_code == 200
        assert detail_fetch.json()["structured_output"]["restated_assignment"].startswith("مراجعة المخطط")


def test_step05_failures_are_logged_not_hidden_without_secret_leaks(tmp_path: Path) -> None:
    """Missing keys, upstream provider failures, and usage caps persist as failed tasks with sanitized logs."""
    secret_store = _InMemorySecretStore()
    mode = {"fail_kind": "auth"}
    fake_secret = "mock-task-failure-secret-8899"

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                return []

            def generate_content(self, **_kwargs: Any) -> Any:
                if mode["fail_kind"] == "auth":
                    raise genai_errors.APIError(
                        401,
                        {"error": {"message": f"Invalid key at ?key={fake_secret}"}},
                    )
                if mode["fail_kind"] == "bad_json":
                    return SimpleNamespace(
                        text="{not valid json",
                        parsed=None,
                        function_calls=[],
                        candidates=[],
                        usage_metadata=_fake_usage(45, 15),
                    )
                raise AssertionError("Should not reach remote SDK when blocked by usage cap")

        return SimpleNamespace(models=_Models())

    app = create_app(
        _test_settings(tmp_path),
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        proj = client.post(
            "/api/projects",
            json={"name": "مشروع اختبار الفشل", "code": "FAIL-05"},
        )
        assert proj.status_code == 201
        project_id = proj.json()["id"]

        # 1. Missing API key -> task fails cleanly and is persisted in Task History
        res_no_key = client.post(
            "/api/tasks",
            json={"project_id": project_id, "prompt": "Analyze foundation layout"},
        )
        assert res_no_key.status_code == 201
        d1 = res_no_key.json()
        assert d1["status"] == "failed"
        assert "no gemini api key is saved" in d1["error_message"].lower()
        assert d1["steps"][1]["status"] == "failed"
        assert [log["action"] for log in d1["logs"]] == ["task.created", "task.failed"]

        # 2. Save key, trigger 401 auth failure containing secret -> scrubbed everywhere, task failed logged
        client.put("/api/settings/provider/api-key", json={"api_key": fake_secret})
        mode["fail_kind"] = "auth"
        res_auth = client.post(
            "/api/tasks",
            json={"project_id": project_id, "prompt": "Review MEP riser schematic"},
        )
        assert res_auth.status_code == 201
        d2 = res_auth.json()
        assert d2["status"] == "failed"
        assert fake_secret not in res_auth.text
        assert [log["action"] for log in d2["logs"]] == [
            "task.created",
            "provider.usage_failed",
            "task.failed",
        ]

        # 3. Bad structured JSON still logs reported remote tokens onto task and failed ledger
        mode["fail_kind"] = "bad_json"
        res_bad_json = client.post(
            "/api/tasks",
            json={"project_id": project_id, "prompt": "Inspect pump room"},
        )
        assert res_bad_json.status_code == 201
        d3 = res_bad_json.json()
        assert d3["status"] == "failed"
        assert d3["token_usage"]["total_tokens"] == 60

        # History contains all 3 failed tasks explicitly — failures are never hidden
        hist = client.get(f"/api/tasks?status=failed&project_id={project_id}")
        assert hist.status_code == 200
        assert hist.json()["total"] == 3
        assert fake_secret not in hist.text

        # Unknown task ID returns 404
        assert client.get("/api/tasks/missing-task-id").status_code == 404
