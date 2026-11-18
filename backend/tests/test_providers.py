"""Tests for swappable LLMProvider, GeminiProvider, keyring storage, and settings API."""

from pathlib import Path
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
    ProviderQuotaError,
    ProviderResponseError,
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
    assert text_resp.model == "gemini-2.5-flash"
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
    assert media_resp.model == "gemini-2.5-pro"
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
        assert d0["models"]["fast"] == "gemini-2.5-flash"
        assert d0["models"]["deep"] == "gemini-2.5-pro"

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
        assert ok_data["model"] == "gemini-2.5-flash"
        assert ok_data["usage"]["total_tokens"] == 15
        assert ok_data["daily_usage"]["requests"] == 1
        assert fake_secret not in ok_test.text

        # 5. Update provider models and enforce tight daily request cap (limit = 1 already reached)
        upd = client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-2.5-flash-lite", "deep": "gemini-2.5-pro"},
                "usage_limits": {
                    "daily_request_limit": 1,
                    "daily_token_limit": 500000,
                    "max_output_tokens": 4096,
                },
            },
        )
        assert upd.status_code == 200
        assert upd.json()["models"]["fast"] == "gemini-2.5-flash-lite"

        capped_test = client.post("/api/settings/provider/test")
        assert capped_test.status_code == 429

        # 6. Raise cap and test invalid key -> returns HTTP 401 without leaking key
        client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-2.5-flash", "deep": "gemini-2.5-pro"},
                "usage_limits": {
                    "daily_request_limit": 100,
                    "daily_token_limit": 500000,
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
            assert gen.model == "gemini-2.5-pro"

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
