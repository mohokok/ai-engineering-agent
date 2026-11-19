"""Tests for swappable LLMProvider, GeminiProvider, keyring storage, and settings API."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from keyring.errors import PasswordDeleteError
from pydantic import BaseModel
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AuditLog, Setting
from app.main import create_app
from app.providers import (
    GeminiProvider,
    KeyringSecretStore,
    LLMRequest,
    MediaInput,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderQuotaError,
    ProviderResponseError,
    ProviderServiceUnavailableError,
    ProviderUsageLimitError,
    SecretStore,
    ToolDefinition,
    create_provider,
)
from app.services.provider_settings import execute_provider_request


class _InMemorySecretStore(SecretStore):
    """Test double isolating tests from the owner's real Windows Credential Manager."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    @property
    def backend_name(self) -> str:
        return "InMemoryTestSecretStore"

    def get_api_key(self, provider_name: str) -> str | None:
        return self._data.get(provider_name.strip().lower())

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        cleaned = api_key.strip()
        if not cleaned:
            raise ValueError("API key must not be empty")
        self._data[provider_name.strip().lower()] = cleaned

    def delete_api_key(self, provider_name: str) -> None:
        self._data.pop(provider_name.strip().lower(), None)


class _DummyStructuredSchema(BaseModel):
    discipline: str
    summary: str
    item_count: int


def _fake_usage(prompt: int = 12, output: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=output,
        total_token_count=prompt + output,
        thoughts_token_count=0,
        cached_content_token_count=0,
    )


class _RecordingModels:
    def __init__(self, handler: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._handler = handler

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._handler(model, contents, config)


class _FakeGenAIClient:
    def __init__(self, handler: Any) -> None:
        self.models = _RecordingModels(handler)


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(workspaces_dir=tmp_path / "workspaces", database_url="")


def test_keyring_secret_store_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """KeyringSecretStore delegates CRUD cleanly to system keyring backend."""
    vault: dict[tuple[str, str], str] = {}

    def fake_get(service: str, user: str) -> str | None:
        return vault.get((service, user))

    def fake_set(service: str, user: str, val: str) -> None:
        vault[(service, user)] = val

    def fake_del(service: str, user: str) -> None:
        if (service, user) not in vault:
            raise PasswordDeleteError("missing")
        del vault[(service, user)]

    monkeypatch.setattr("app.providers.secrets.keyring.get_password", fake_get)
    monkeypatch.setattr("app.providers.secrets.keyring.set_password", fake_set)
    monkeypatch.setattr("app.providers.secrets.keyring.delete_password", fake_del)

    store = KeyringSecretStore()
    assert store.has_api_key("gemini") is False
    assert isinstance(store.backend_name, str) and len(store.backend_name) > 0

    with pytest.raises(ValueError):
        store.set_api_key("gemini", "   ")

    store.set_api_key("gemini", "mock-credential-value")
    assert store.has_api_key("gemini") is True
    assert store.get_api_key("gemini") == "mock-credential-value"

    store.delete_api_key("gemini")
    assert store.has_api_key("gemini") is False
    store.delete_api_key("gemini")  # idempotent when absent


def test_gemini_provider_text_structured_pdf_image_and_tools() -> None:
    """GeminiProvider handles text, structured JSON schema, PDF+image media, and tools."""
    recorder: list[_RecordingModels] = []

    def handler(model: str, contents: Any, config: Any) -> SimpleNamespace:
        if getattr(config, "response_mime_type", None) == "application/json":
            return SimpleNamespace(
                text='{"discipline":"Structural","summary":"Beam check OK","item_count":3}',
                parsed=_DummyStructuredSchema(
                    discipline="Structural", summary="Beam check OK", item_count=3
                ),
                function_calls=[],
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=_fake_usage(20, 15),
            )
        if getattr(config, "tools", None):
            return SimpleNamespace(
                text="",
                parsed=None,
                function_calls=[
                    SimpleNamespace(name="lookup_standard", args={"code": "ACI 318"})
                ],
                candidates=[SimpleNamespace(finish_reason="STOP")],
                usage_metadata=_fake_usage(18, 10),
            )
        return SimpleNamespace(
            text="تحليل هندسي مبدئي مكتمل",
            parsed=None,
            function_calls=[],
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=_fake_usage(30, 12),
        )

    def factory(_key: str) -> _FakeGenAIClient:
        client = _FakeGenAIClient(handler)
        recorder.append(client.models)
        return client

    provider = GeminiProvider("mock-credential-value", client_factory=factory)

    # 1. Text generation uses fast model by default
    text_resp = provider.generate_text("Explain load combinations")
    assert text_resp.model == "gemini-3.8-flash"
    assert text_resp.text == "تحليل هندسي مبدئي مكتمل"
    assert text_resp.usage.total_tokens == 42

    # 2. Structured JSON output via Pydantic schema
    struct_resp = provider.generate_structured(
        "Summarize findings", _DummyStructuredSchema, complexity="fast"
    )
    assert struct_resp.parsed_json == {
        "discipline": "Structural",
        "summary": "Beam check OK",
        "item_count": 3,
    }

    # 3. Multimodal small PDF page + PNG image uses deep model
    media_resp = provider.analyze_media(
        "Review attached plan and image",
        media=[
            MediaInput(data=b"%PDF-1.4\n1 0 obj\n%%EOF", mime_type="application/pdf", filename="page.pdf"),
            MediaInput(data=b"\x89PNG\r\n\x1a\nPNG", mime_type="image/png", filename="plan.png"),
        ],
        complexity="deep",
    )
    assert media_resp.model == "gemini-4-argon"
    media_call_contents = recorder[-1].calls[0]["contents"]
    assert len(media_call_contents) == 3
    assert isinstance(media_call_contents[1], genai_types.Part)
    assert isinstance(media_call_contents[2], genai_types.Part)

    # 4. Tool calling
    tools_resp = provider.generate_with_tools(
        "Verify ACI code edition",
        tools=[
            ToolDefinition(
                name="lookup_standard",
                description="Find code requirement",
                parameters_schema={"type": "object", "properties": {"code": {"type": "string"}}},
            )
        ],
    )
    assert len(tools_resp.tool_calls) == 1
    assert tools_resp.tool_calls[0].name == "lookup_standard"
    assert tools_resp.tool_calls[0].arguments == {"code": "ACI 318"}


def test_provider_errors_and_secret_scrubbing() -> None:
    """Invalid key, quota errors, bad JSON, and exceptions never leak key material."""
    fake_secret = "mock-super-secret-value"

    def auth_fail_factory(_key: str) -> Any:
        class _FailModels:
            def generate_content(self, **_kwargs: Any) -> Any:
                raise genai_errors.APIError(
                    401,
                    {"error": {"message": f"API key not valid for ?key={fake_secret}"}},
                )

        return SimpleNamespace(models=_FailModels())

    p_auth = GeminiProvider(fake_secret, client_factory=auth_fail_factory)
    with pytest.raises(ProviderAuthError) as auth_exc:
        p_auth.test_connection()
    assert fake_secret not in str(auth_exc.value)
    assert "consumer subscription" in str(auth_exc.value).lower()

    def quota_fail_factory(_key: str) -> Any:
        class _QuotaModels:
            def generate_content(self, **_kwargs: Any) -> Any:
                raise genai_errors.APIError(
                    429,
                    {"error": {"message": "RESOURCE_EXHAUSTED"}},
                )

        return SimpleNamespace(models=_QuotaModels())

    p_quota = GeminiProvider(fake_secret, client_factory=quota_fail_factory)
    with pytest.raises(ProviderQuotaError):
        p_quota.generate_text("hello")

    def generic_url_leak_factory(_key: str) -> Any:
        class _LeakModels:
            def generate_content(self, **_kwargs: Any) -> Any:
                raise RuntimeError(
                    f"Request https://example.invalid/v1?key={fake_secret}&alt=json failed"
                )

        return SimpleNamespace(models=_LeakModels())

    p_leak = GeminiProvider(fake_secret, client_factory=generic_url_leak_factory)
    with pytest.raises(ProviderError) as leak_exc:
        p_leak.generate_text("hello")
    assert fake_secret not in str(leak_exc.value)
    assert "[REDACTED]" in str(leak_exc.value)

    def bad_json_factory(_key: str) -> Any:
        class _BadJsonModels:
            def generate_content(self, **_kwargs: Any) -> Any:
                return SimpleNamespace(
                    text="{not valid json",
                    parsed=None,
                    function_calls=[],
                    candidates=[],
                    usage_metadata=_fake_usage(),
                )

        return SimpleNamespace(models=_BadJsonModels())

    p_bad_json = GeminiProvider(fake_secret, client_factory=bad_json_factory)
    with pytest.raises(ProviderResponseError):
        p_bad_json.generate_structured("return json", _DummyStructuredSchema)

    with pytest.raises(ProviderConfigError):
        create_provider("unsupported-provider", fake_secret, fast_model="x", deep_model="y")


def test_settings_api_keyring_swappability_usage_limits_and_zero_secret_leak(
    tmp_path: Path,
) -> None:
    """API endpoints store key only in SecretStore, never return it, and enforce usage caps."""
    fake_secret = "mock-nonkey-credential-value"
    secret_store = _InMemorySecretStore()
    mode = {"fail_auth": False}

    def client_factory(_key: str) -> Any:
        class _Models:
            def generate_content(self, *, model: str, **_kwargs: Any) -> Any:
                if mode["fail_auth"]:
                    raise genai_errors.APIError(
                        403, {"error": {"message": f"PERMISSION_DENIED for {fake_secret}"}}
                    )
                return SimpleNamespace(
                    text="OK",
                    parsed=None,
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=_fake_usage(10, 5),
                )

        return SimpleNamespace(models=_Models())

    app = create_app(
        _test_settings(tmp_path),
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        # 1. Initial state has no key stored
        r0 = client.get("/api/settings/provider")
        assert r0.status_code == 200
        d0 = r0.json()
        assert d0["api_key_configured"] is False
        assert d0["active_provider"] == "gemini"
        assert d0["models"]["fast"] == "gemini-3.8-flash"
        assert d0["models"]["deep"] == "gemini-4-argon"
        assert d0["models_source"] == "fallback_catalog"
        catalog_ids = [m["id"] for m in d0["available_providers"][0]["models"]]
        assert "gemini-3.8-flash" in catalog_ids
        assert "gemini-3.5-flash-lite" in catalog_ids
        assert "gemini-4-argon" in catalog_ids

        # 2. Test connection without key returns clear 400
        no_key_test = client.post("/api/settings/provider/test")
        assert no_key_test.status_code == 400

        # 3. Save API key -> stored ONLY in secret_store, never returned in JSON or stored in DB
        save_key_resp = client.put(
            "/api/settings/provider/api-key",
            json={"api_key": fake_secret},
        )
        assert save_key_resp.status_code == 200
        assert save_key_resp.json()["api_key_configured"] is True
        assert fake_secret not in save_key_resp.text
        assert secret_store.get_api_key("gemini") == fake_secret

        get_after = client.get("/api/settings/provider")
        assert get_after.status_code == 200
        assert fake_secret not in get_after.text

        # 4. Run Test Connection -> succeeds and increments daily usage
        ok_test = client.post("/api/settings/provider/test", json={"complexity": "fast"})
        assert ok_test.status_code == 200
        ok_data = ok_test.json()
        assert ok_data["connected"] is True
        assert ok_data["model"] == "gemini-3.8-flash"
        assert ok_data["usage"]["total_tokens"] == 15
        assert ok_data["daily_usage"]["requests"] == 1
        assert fake_secret not in ok_test.text

        # 5. Update provider models and enforce tight daily request cap (limit = 1 already reached)
        upd = client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.5-flash-lite", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 1,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 3000,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 4096,
                },
            },
        )
        assert upd.status_code == 200
        assert upd.json()["models"]["fast"] == "gemini-3.5-flash-lite"
        assert upd.json()["monthly_usage"]["requests"] == 1

        capped_test = client.post("/api/settings/provider/test")
        assert capped_test.status_code == 429

        # 6. Raise cap and test invalid key -> returns HTTP 401 without leaking key
        client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.8-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 100,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 3000,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 4096,
                },
            },
        )
        mode["fail_auth"] = True
        bad_test = client.post("/api/settings/provider/test")
        assert bad_test.status_code == 401
        assert fake_secret not in bad_test.text

        # 7. Also verify orchestrator entry execute_provider_request records usage cleanly
        mode["fail_auth"] = False
        with app.state.session_factory() as db:
            gen = execute_provider_request(
                db,
                secret_store,
                LLMRequest(prompt="Check structural span", complexity="deep"),
                client_factory=client_factory,
            )
            assert gen.model == "gemini-4-argon"

            # Verify ZERO occurrence of secret key across entire DB settings & audit_log
            all_settings = db.scalars(select(Setting)).all()
            all_audits = db.scalars(select(AuditLog)).all()
            serialized_db = repr([(s.key, s.value_json) for s in all_settings]) + repr(
                [(a.action, a.details_json) for a in all_audits]
            )
            assert fake_secret not in serialized_db

        # 8. Delete stored key cleanly
        del_resp = client.delete("/api/settings/provider/api-key")
        assert del_resp.status_code == 200
        assert del_resp.json()["api_key_configured"] is False
        assert del_resp.json()["last_connection_check"]["status"] == "untested"
        assert secret_store.has_api_key("gemini") is False


def test_monthly_usage_limits_and_failed_attempt_counting(tmp_path: Path) -> None:
    """Monthly caps block calls before Google; failed remote attempts count requests and tokens."""
    secret_store = _InMemorySecretStore()
    secret_store.set_api_key("gemini", "mock-monthly-test-key")
    calls = {"count": 0, "mode": "ok"}

    def client_factory(_key: str) -> Any:
        class _Models:
            def generate_content(self, **_kwargs: Any) -> Any:
                calls["count"] += 1
                if calls["mode"] == "auth_fail":
                    raise genai_errors.APIError(
                        401, {"error": {"message": "API_KEY_INVALID"}}
                    )
                if calls["mode"] == "bad_json_with_usage":
                    return SimpleNamespace(
                        text="{broken",
                        parsed=None,
                        function_calls=[],
                        candidates=[],
                        usage_metadata=_fake_usage(40, 20),
                    )
                return SimpleNamespace(
                    text="OK",
                    parsed=None,
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=_fake_usage(10, 5),
                )

        return SimpleNamespace(models=_Models())

    app = create_app(
        _test_settings(tmp_path),
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        # 1. Pre-populate a prior-day append-only row within the CURRENT UTC month
        #    so daily usage stays low while monthly usage triggers first.
        now = datetime.now(timezone.utc)
        month_str = now.strftime("%Y-%m")
        with app.state.session_factory() as db:
            db.add(
                AuditLog(
                    project_id=None,
                    action="provider.usage_recorded",
                    entity_type="provider_usage",
                    entity_id="gemini",
                    actor="owner",
                    details_json={
                        "provider": "gemini",
                        "model": "gemini-3.8-flash",
                        "date_utc": "1999-01-01",
                        "month_utc": month_str,
                        "requests": 2,
                        "prompt_tokens": 500,
                        "output_tokens": 200,
                        "total_tokens": 700,
                        "status": "ok",
                    },
                )
            )
            db.commit()

        # Set high daily caps (100 / 500k) and tight monthly request cap (2, already hit!)
        upd1 = client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.8-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 100,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 2,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 4096,
                },
            },
        )
        assert upd1.status_code == 200
        assert upd1.json()["daily_usage"]["requests"] == 0
        assert upd1.json()["monthly_usage"]["requests"] == 2

        calls_before = calls["count"]
        blocked_req = client.post("/api/settings/provider/test")
        assert blocked_req.status_code == 429
        assert "monthly request limit" in blocked_req.json()["detail"].lower()
        assert calls["count"] == calls_before  # blocked before calling Google SDK!

        # Locally blocked attempt must NOT increment counters
        after_blocked = client.get("/api/settings/provider").json()
        assert after_blocked["monthly_usage"]["requests"] == 2

        # 2. Allow monthly requests=100, test tight monthly token cap (limit=700 already hit!)
        client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.8-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 100,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 100,
                    "monthly_token_limit": 1000,
                    "max_output_tokens": 4096,
                },
            },
        )
        # Seed 300 more tokens in current month -> total 1000 == monthly_token_limit
        with app.state.session_factory() as db:
            db.add(
                AuditLog(
                    project_id=None,
                    action="provider.usage_recorded",
                    entity_type="provider_usage",
                    entity_id="gemini",
                    actor="owner",
                    details_json={
                        "provider": "gemini",
                        "model": "gemini-3.8-flash",
                        "date_utc": "1999-01-01",
                        "month_utc": month_str,
                        "requests": 1,
                        "prompt_tokens": 200,
                        "output_tokens": 100,
                        "total_tokens": 300,
                        "status": "ok",
                    },
                )
            )
            db.commit()

        calls_before = calls["count"]
        blocked_tok = client.post("/api/settings/provider/test")
        assert blocked_tok.status_code == 429
        assert "monthly token limit" in blocked_tok.json()["detail"].lower()
        with app.state.session_factory() as db:
            with pytest.raises(ProviderUsageLimitError):
                execute_provider_request(
                    db,
                    secret_store,
                    LLMRequest(prompt="Should be blocked by monthly token cap"),
                    client_factory=client_factory,
                )
        assert calls["count"] == calls_before

        # 3. Raise monthly caps and verify FAILED attempts reaching Google ARE counted
        client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.8-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 100,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 100,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 4096,
                },
            },
        )
        calls["mode"] = "auth_fail"
        fail_conn = client.post("/api/settings/provider/test")
        assert fail_conn.status_code == 401
        state_after_fail = client.get("/api/settings/provider").json()
        assert state_after_fail["daily_usage"]["requests"] == 1
        assert state_after_fail["monthly_usage"]["requests"] == 4  # 2 + 1 seeded + 1 failed

        # 4. Failed structured output with reported usage_metadata counts BOTH request and tokens
        calls["mode"] = "bad_json_with_usage"
        with app.state.session_factory() as db:
            with pytest.raises(ProviderResponseError):
                execute_provider_request(
                    db,
                    secret_store,
                    LLMRequest(prompt="return json", response_schema=_DummyStructuredSchema),
                    client_factory=client_factory,
                )
        state_after_bad_json = client.get("/api/settings/provider").json()
        assert state_after_bad_json["daily_usage"]["requests"] == 2
        assert state_after_bad_json["daily_usage"]["prompt_tokens"] == 40
        assert state_after_bad_json["daily_usage"]["output_tokens"] == 20
        assert state_after_bad_json["daily_usage"]["total_tokens"] == 60
        assert state_after_bad_json["monthly_usage"]["total_tokens"] == 1060


def test_debug_logging_never_leaks_api_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Capture DEBUG logs across root, httpx, httpx2, google_genai, uvicorn and assert key absent."""
    fake_secret = "mock-debug-log-guard-secret-9988"
    secret_store = _InMemorySecretStore()
    fail_mode = {"fail": False}

    def client_factory(_key: str) -> Any:
        logging.getLogger("google_genai").debug("google_genai synthetic debug call")
        logging.getLogger("httpx2").debug("httpx2 synthetic debug transport")

        class _Models:
            def generate_content(self, **_kwargs: Any) -> Any:
                if fail_mode["fail"]:
                    raise genai_errors.APIError(
                        401,
                        {"error": {"message": f"Invalid key at ?key={fake_secret}"}},
                    )
                return SimpleNamespace(
                    text="OK",
                    parsed=None,
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=_fake_usage(8, 2),
                )

        return SimpleNamespace(models=_Models())

    app = create_app(
        _test_settings(tmp_path),
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )

    watched_loggers = ("", "httpx", "httpx2", "google_genai", "uvicorn", "uvicorn.access", "uvicorn.error")
    saved_propagate: dict[str, bool] = {}
    for name in watched_loggers:
        if name:
            lg = logging.getLogger(name)
            saved_propagate[name] = lg.propagate
            lg.propagate = True

    try:
        with (
            caplog.at_level(logging.DEBUG),
            caplog.at_level(logging.DEBUG, logger="httpx"),
            caplog.at_level(logging.DEBUG, logger="httpx2"),
            caplog.at_level(logging.DEBUG, logger="google_genai"),
            caplog.at_level(logging.DEBUG, logger="uvicorn"),
            TestClient(app) as client,
        ):
            r_save = client.put("/api/settings/provider/api-key", json={"api_key": fake_secret})
            assert r_save.status_code == 200

            r_ok = client.post("/api/settings/provider/test")
            assert r_ok.status_code == 200

            fail_mode["fail"] = True
            r_fail = client.post("/api/settings/provider/test")
            assert r_fail.status_code == 401
    finally:
        for name, prop in saved_propagate.items():
            logging.getLogger(name).propagate = prop

    assert len(caplog.records) > 0
    assert fake_secret not in caplog.text
    for record in caplog.records:
        assert fake_secret not in record.getMessage()


def test_verify_gemini_live_script_with_mocked_provider(tmp_path: Path) -> None:
    """Owner verification script runs all 5 checks cleanly and emits zero secret strings."""
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import verify_gemini_live  # type: ignore[import-not-found]

    pdf_bytes = verify_gemini_live.build_minimal_valid_pdf()
    png_bytes = verify_gemini_live.build_minimal_valid_png()
    assert pdf_bytes.startswith(b"%PDF-1.4") and b"%%EOF" in pdf_bytes
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    owner_fake_key = "mock-owner-keyring-secret-777"
    store = _InMemorySecretStore()
    store.set_api_key("gemini", owner_fake_key)

    def mock_client_factory(key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                return [
                    SimpleNamespace(
                        name="models/gemini-3.8-flash",
                        display_name="Gemini 3.8 Flash",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/gemini-3.5-flash-lite",
                        display_name="Gemini 3.5 Flash-Lite",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/gemini-4-argon",
                        display_name="Gemini 4 Argon",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/text-embedding-004",
                        display_name="Text Embedding 004",
                        supported_actions=["embedContent"],
                    ),
                ]

            def generate_content(self, *, contents: Any, config: Any, **_kwargs: Any) -> Any:
                if key != owner_fake_key:
                    raise genai_errors.APIError(
                        400, {"error": {"message": f"API key not valid: ?key={key}"}}
                    )
                if getattr(config, "response_mime_type", None) == "application/json":
                    return SimpleNamespace(
                        text='{"discipline":"Civil","classification":"Preliminary","note":"OK"}',
                        parsed=verify_gemini_live.LiveStructuredCheckSchema(
                            discipline="Civil", classification="Preliminary", note="OK"
                        ),
                        function_calls=[],
                        candidates=[SimpleNamespace(finish_reason="STOP")],
                        usage_metadata=_fake_usage(20, 12),
                    )
                return SimpleNamespace(
                    text="Beam span 6.0m verified" if len(contents) > 1 else "OK",
                    parsed=None,
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=_fake_usage(15, 8),
                )

        return SimpleNamespace(models=_Models())

    db_url = f"sqlite:///{(tmp_path / 'live_verify.db').as_posix()}"
    summary = verify_gemini_live.run_live_checks(
        secret_store=store,
        client_factory=mock_client_factory,
        database_url=db_url,
    )
    assert summary["models_source"] == "live_api"
    assert summary["refreshed_generate_content_models_count"] == 3
    assert summary["check_1_test_connection"]["connected"] is True
    assert summary["check_2_invalid_key"]["rejected_cleanly"] is True
    assert set(summary["check_3_structured_json"]["parsed_keys"]) == {
        "classification",
        "discipline",
        "note",
    }
    assert summary["check_4_pdf_analysis"]["total_tokens"] == 23
    assert summary["check_5_image_analysis"]["total_tokens"] == 23
    serialized = repr(summary)
    assert owner_fake_key not in serialized
    assert "invalid-key-live-verification-probe" not in serialized



def test_provider_404_model_not_found_handling(tmp_path: Path) -> None:
    """HTTP 404 model-not-found names configured model, hints Refresh models, counts attempt, and hides key."""
    fake_secret = "mock-404-secret-value-555"

    def not_found_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                return []

            def generate_content(self, **_kwargs: Any) -> Any:
                raise genai_errors.APIError(
                    404,
                    {
                        "error": {
                            "code": 404,
                            "status": "NOT_FOUND",
                            "message": f"models/gemini-2.5-flash is not found for ?key={fake_secret}",
                        }
                    },
                )

        return SimpleNamespace(models=_Models())

    direct_provider = GeminiProvider(
        fake_secret,
        fast_model="gemini-2.5-flash",
        client_factory=not_found_factory,
    )
    with pytest.raises(ProviderModelNotFoundError) as exc_info:
        direct_provider.generate_text("hello")
    msg = str(exc_info.value)
    assert "gemini-2.5-flash" in msg
    assert "refresh" in msg.lower()
    assert fake_secret not in msg

    store = _InMemorySecretStore()
    store.set_api_key("gemini", fake_secret)
    app = create_app(
        _test_settings(tmp_path),
        secret_store=store,
        provider_client_factory=not_found_factory,
    )
    with TestClient(app) as client:
        client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-2.5-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 200,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 3000,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 8192,
                },
            },
        )
        res = client.post("/api/settings/provider/test", json={"complexity": "fast"})
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "gemini-2.5-flash" in detail
        assert "refresh" in detail.lower()
        assert fake_secret not in detail

        after = client.get("/api/settings/provider").json()
        assert after["daily_usage"]["requests"] == 1
        assert after["last_connection_check"]["status"] == "error"
        assert "gemini-2.5-flash" in after["last_connection_check"]["message"]


def test_refresh_models_filters_generate_content_and_startup_check(tmp_path: Path) -> None:
    """Refresh models calls SDK list, filters to generateContent, warns on missing saved model, and runs on startup."""
    secret_store = _InMemorySecretStore()
    calls = {"list": 0}

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                calls["list"] += 1
                return [
                    SimpleNamespace(
                        name="models/gemini-3.8-flash",
                        display_name="Gemini 3.8 Flash",
                        supported_actions=["generateContent", "countTokens"],
                    ),
                    SimpleNamespace(
                        name="models/gemini-3.5-flash-lite",
                        display_name="Gemini 3.5 Flash-Lite",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/gemini-4-argon",
                        display_name="Gemini 4 Argon",
                        supported_actions=["generateContent"],
                    ),
                    SimpleNamespace(
                        name="models/text-embedding-004",
                        display_name="Text Embedding 004",
                        supported_actions=["embedContent"],
                    ),
                    SimpleNamespace(
                        name="models/imagen-3.0-generate-002",
                        display_name="Imagen 3",
                        supported_actions=["predict"],
                    ),
                ]

        return SimpleNamespace(models=_Models())

    settings = _test_settings(tmp_path)
    app1 = create_app(
        settings,
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )
    with TestClient(app1) as client:
        # Refresh without stored key returns 400
        no_key = client.post("/api/settings/provider/models/refresh")
        assert no_key.status_code == 400

        client.put("/api/settings/provider/api-key", json={"api_key": "mock-refresh-key"})
        # Configure retired model ID manually to trigger model_warning after refresh
        client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-2.5-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 200,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 3000,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 8192,
                },
            },
        )

        refreshed = client.post("/api/settings/provider/models/refresh")
        assert refreshed.status_code == 200
        data = refreshed.json()
        assert data["models_source"] == "live_api"
        assert data["models_refreshed_at"] is not None
        ids = [m["id"] for m in data["available_providers"][0]["models"]]
        assert ids == ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-4-argon"]
        assert "text-embedding-004" not in ids
        assert "imagen-3.0-generate-002" not in ids
        assert data["model_warning"] is not None
        assert "gemini-2.5-flash" in data["model_warning"]

        # Switch to valid live model + verify manual model ID still permitted cleanly
        fixed = client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.8-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 200,
                    "daily_token_limit": 500000,
                    "monthly_request_limit": 3000,
                    "monthly_token_limit": 5000000,
                    "max_output_tokens": 8192,
                },
            },
        )
        assert fixed.status_code == 200
        assert fixed.json()["model_warning"] is None

        # Deleting API key clears cached discovered models back to fallback catalog
        deleted = client.delete("/api/settings/provider/api-key")
        assert deleted.status_code == 200
        assert deleted.json()["models_source"] == "fallback_catalog"
        assert deleted.json()["models_refreshed_at"] is None

        # Save key again so a restart triggers startup discovery automatically
        client.put("/api/settings/provider/api-key", json={"api_key": "mock-refresh-key"})

    calls_before_startup = calls["list"]
    app2 = create_app(
        settings,
        secret_store=secret_store,
        provider_client_factory=client_factory,
    )
    with TestClient(app2) as client2:
        assert calls["list"] == calls_before_startup + 1
        boot_state = client2.get("/api/settings/provider").json()
        assert boot_state["models_source"] == "live_api"
        assert [m["id"] for m in boot_state["available_providers"][0]["models"]] == [
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-4-argon",
        ]


def test_gemini_provider_503_exponential_backoff_retry_and_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 503 UNAVAILABLE retries up to max 3 tries with exponential backoff across generate & list_models."""
    fake_secret = "mock-503-secret-value-444"

    def _err_503() -> genai_errors.APIError:
        return genai_errors.APIError(
            503,
            {
                "error": {
                    "code": 503,
                    "status": "UNAVAILABLE",
                    "message": f"High demand on gemini-4-argon ?key={fake_secret}",
                }
            },
        )

    # 1. Fails twice with 503, succeeds on 3rd try -> exponential backoff [0.5, 1.0]
    sleeps_ok: list[float] = []
    calls_ok = {"generate": 0}

    def ok_on_third_factory(_key: str) -> Any:
        class _Models:
            def generate_content(self, **_kwargs: Any) -> Any:
                calls_ok["generate"] += 1
                if calls_ok["generate"] < 3:
                    raise _err_503()
                return SimpleNamespace(
                    text="Recovered on try 3",
                    parsed=None,
                    function_calls=[],
                    candidates=[SimpleNamespace(finish_reason="STOP")],
                    usage_metadata=_fake_usage(14, 6),
                )

        return SimpleNamespace(models=_Models())

    p_ok = GeminiProvider(
        fake_secret,
        deep_model="gemini-4-argon",
        client_factory=ok_on_third_factory,
        sleep_fn=sleeps_ok.append,
    )
    resp = p_ok.generate_text("check beam", complexity="deep")
    assert resp.text == "Recovered on try 3"
    assert resp.model == "gemini-4-argon"
    assert calls_ok["generate"] == 3
    assert sleeps_ok == [0.5, 1.0]

    # 2. list_models also retries transient 503 and succeeds on 2nd try
    sleeps_list: list[float] = []
    calls_list = {"list": 0}

    def list_ok_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                calls_list["list"] += 1
                if calls_list["list"] == 1:
                    raise _err_503()
                return [
                    SimpleNamespace(
                        name="models/gemini-4-argon",
                        display_name="Gemini 4 Argon",
                        supported_actions=["generateContent"],
                    )
                ]

        return SimpleNamespace(models=_Models())

    p_list = GeminiProvider(
        fake_secret,
        client_factory=list_ok_factory,
        sleep_fn=sleeps_list.append,
    )
    listed = p_list.list_models()
    assert [m.id for m in listed] == ["gemini-4-argon"]
    assert calls_list["list"] == 2
    assert sleeps_list == [0.5]

    # 3. Non-503 error (401) is NOT retried
    sleeps_401: list[float] = []
    calls_401 = {"count": 0}

    def fail_401_factory(_key: str) -> Any:
        class _Models:
            def generate_content(self, **_kwargs: Any) -> Any:
                calls_401["count"] += 1
                raise genai_errors.APIError(401, {"error": {"message": "API_KEY_INVALID"}})

        return SimpleNamespace(models=_Models())

    p_401 = GeminiProvider(
        fake_secret,
        client_factory=fail_401_factory,
        sleep_fn=sleeps_401.append,
    )
    with pytest.raises(ProviderAuthError):
        p_401.generate_text("hello")
    assert calls_401["count"] == 1
    assert sleeps_401 == []

    # 4. Exhausting all 3 attempts raises ProviderServiceUnavailableError, returns HTTP 503 via API,
    #    logs 1 logical failed remote attempt, and never leaks secrets
    sleeps_exhaust: list[float] = []
    calls_exhaust = {"generate": 0}
    monkeypatch.setattr("app.providers.gemini.time.sleep", sleeps_exhaust.append)

    def always_503_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[SimpleNamespace]:
                return []

            def generate_content(self, **_kwargs: Any) -> Any:
                calls_exhaust["generate"] += 1
                raise _err_503()

        return SimpleNamespace(models=_Models())

    p_exhaust = GeminiProvider(
        fake_secret,
        deep_model="gemini-4-argon",
        client_factory=always_503_factory,
    )
    with pytest.raises(ProviderServiceUnavailableError) as exc_info:
        p_exhaust.generate_text("check frame", complexity="deep")
    assert calls_exhaust["generate"] == 3
    assert sleeps_exhaust == [0.5, 1.0]
    assert "503" in str(exc_info.value)
    assert "3 attempts" in str(exc_info.value)
    assert fake_secret not in str(exc_info.value)

    calls_exhaust["generate"] = 0
    sleeps_exhaust.clear()
    store = _InMemorySecretStore()
    store.set_api_key("gemini", fake_secret)
    app = create_app(
        _test_settings(tmp_path),
        secret_store=store,
        provider_client_factory=always_503_factory,
    )
    with TestClient(app) as client:
        res = client.post("/api/settings/provider/test", json={"complexity": "deep"})
        assert res.status_code == 503
        detail = res.json()["detail"]
        assert "503" in detail
        assert "gemini-4-argon" in detail
        assert fake_secret not in detail
        assert calls_exhaust["generate"] == 3
        assert sleeps_exhaust == [0.5, 1.0]
        state = client.get("/api/settings/provider").json()
        assert state["daily_usage"]["requests"] == 1

