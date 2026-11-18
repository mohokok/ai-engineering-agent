"""Non-secret DB settings, daily usage budgets, keyring coordination, and provider runner."""

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import AuditLog, Setting
from app.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderConfigError,
    ProviderError,
    ProviderUsageLimitError,
    TaskComplexity,
    TokenUsage,
    sanitize_secret_text,
)
from app.providers.gemini import DEFAULT_GEMINI_DEEP_MODEL, DEFAULT_GEMINI_FAST_MODEL
from app.providers.registry import PROVIDER_CATALOG, create_provider
from app.providers.secrets import SecretStore
from app.schemas.settings import (
    ConnectionCheckStatusOut,
    ConnectionTestOut,
    DailyUsageOut,
    ModelSelectionSchema,
    ProviderSettingsOut,
    ProviderSettingsUpdate,
    TokenUsageOut,
    UsageLimitsSchema,
)

PROVIDER_CONFIG_KEY = "provider.config"
PROVIDER_LAST_CHECK_KEY = "provider.last_check"
CONSUMER_SUBSCRIPTION_NOTICE = (
    "Note: A consumer Gemini web subscription (Gemini Advanced / Google One) does NOT "
    "automatically include Gemini API access. Generate an authorized Gemini API key in "
    "Google AI Studio; it is stored only in Windows Credential Manager via keyring."
)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _usage_key(date_utc: str) -> str:
    return f"provider.daily_usage.{date_utc}"


def _upsert_setting(
    db: Session,
    *,
    key: str,
    value_json: Any,
    category: str,
    description: str,
) -> None:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(
            key=key,
            value_json=value_json,
            category=category,
            description=description,
        )
        db.add(row)
    else:
        row.value_json = value_json
        row.category = category


def _load_provider_config(db: Session) -> ProviderSettingsUpdate:
    row = db.get(Setting, PROVIDER_CONFIG_KEY)
    if row is None or not isinstance(row.value_json, dict):
        return ProviderSettingsUpdate(
            active_provider="gemini",
            models=ModelSelectionSchema(
                fast=DEFAULT_GEMINI_FAST_MODEL,
                deep=DEFAULT_GEMINI_DEEP_MODEL,
            ),
            usage_limits=UsageLimitsSchema(),
        )
    return ProviderSettingsUpdate.model_validate(row.value_json)


def _load_daily_usage(db: Session, date_utc: str | None = None) -> DailyUsageOut:
    target_date = date_utc or _today_utc()
    row = db.get(Setting, _usage_key(target_date))
    if row is None or not isinstance(row.value_json, dict):
        return DailyUsageOut(date_utc=target_date)
    data = dict(row.value_json)
    data.setdefault("date_utc", target_date)
    return DailyUsageOut.model_validate(data)


def _load_last_check(db: Session) -> ConnectionCheckStatusOut:
    row = db.get(Setting, PROVIDER_LAST_CHECK_KEY)
    if row is None or not isinstance(row.value_json, dict):
        return ConnectionCheckStatusOut()
    return ConnectionCheckStatusOut.model_validate(row.value_json)


def _save_last_check(
    db: Session,
    *,
    status_value: str,
    model: str | None,
    message: str,
    latency_ms: int | None,
) -> None:
    payload = ConnectionCheckStatusOut(
        status=status_value,  # type: ignore[arg-type]
        checked_at=datetime.now(timezone.utc).isoformat(),
        model=model,
        message=message,
        latency_ms=latency_ms,
    ).model_dump()
    _upsert_setting(
        db,
        key=PROVIDER_LAST_CHECK_KEY,
        value_json=payload,
        category="ai_provider",
        description="Latest sanitized AI provider connection check result",
    )


def get_provider_settings(db: Session, secret_store: SecretStore) -> ProviderSettingsOut:
    """Return full non-secret provider settings along with boolean key status."""
    cfg = _load_provider_config(db)
    daily_usage = _load_daily_usage(db)
    last_check = _load_last_check(db)
    api_key_configured = secret_store.has_api_key(cfg.active_provider)
    return ProviderSettingsOut(
        active_provider=cfg.active_provider,
        available_providers=list(PROVIDER_CATALOG),
        models=cfg.models,
        usage_limits=cfg.usage_limits,
        daily_usage=daily_usage,
        api_key_configured=api_key_configured,
        credential_backend=secret_store.backend_name,
        last_connection_check=last_check,
        consumer_subscription_notice=CONSUMER_SUBSCRIPTION_NOTICE,
    )


def update_provider_settings(
    db: Session,
    secret_store: SecretStore,
    payload: ProviderSettingsUpdate,
) -> ProviderSettingsOut:
    """Validate and save non-secret provider preferences (never accepts secrets)."""
    supported_ids = {item["id"] for item in PROVIDER_CATALOG}
    if payload.active_provider not in supported_ids:
        raise ProviderConfigError(f"Unsupported AI provider: {payload.active_provider!r}")

    _upsert_setting(
        db,
        key=PROVIDER_CONFIG_KEY,
        value_json=payload.model_dump(),
        category="ai_provider",
        description="Non-secret AI provider model and usage limit preferences",
    )
    db.add(
        AuditLog(
            project_id=None,
            action="provider.settings_updated",
            entity_type="settings",
            entity_id=PROVIDER_CONFIG_KEY,
            actor="owner",
            details_json=payload.model_dump(),
        )
    )
    db.commit()
    return get_provider_settings(db, secret_store)


def save_provider_api_key(
    db: Session,
    secret_store: SecretStore,
    api_key: str,
) -> ProviderSettingsOut:
    """Store provider API key only in OS keyring and record a key-free audit event."""
    cfg = _load_provider_config(db)
    secret_store.set_api_key(cfg.active_provider, api_key)
    db.add(
        AuditLog(
            project_id=None,
            action="provider.api_key_updated",
            entity_type="credential",
            entity_id=cfg.active_provider,
            actor="owner",
            details_json={
                "provider": cfg.active_provider,
                "credential_backend": secret_store.backend_name,
            },
        )
    )
    db.commit()
    return get_provider_settings(db, secret_store)


def delete_provider_api_key(
    db: Session,
    secret_store: SecretStore,
) -> ProviderSettingsOut:
    """Remove stored API key from OS keyring and reset connection check state."""
    cfg = _load_provider_config(db)
    secret_store.delete_api_key(cfg.active_provider)
    _save_last_check(
        db,
        status_value="untested",
        model=None,
        message="API key removed from credential store.",
        latency_ms=None,
    )
    db.add(
        AuditLog(
            project_id=None,
            action="provider.api_key_deleted",
            entity_type="credential",
            entity_id=cfg.active_provider,
            actor="owner",
            details_json={"provider": cfg.active_provider},
        )
    )
    db.commit()
    return get_provider_settings(db, secret_store)


def _check_usage_budget(db: Session, limits: UsageLimitsSchema) -> DailyUsageOut:
    usage = _load_daily_usage(db)
    if usage.requests >= limits.daily_request_limit:
        raise ProviderUsageLimitError(
            f"Daily request limit reached ({usage.requests}/{limits.daily_request_limit})."
        )
    if usage.total_tokens >= limits.daily_token_limit:
        raise ProviderUsageLimitError(
            f"Daily token limit reached ({usage.total_tokens}/{limits.daily_token_limit})."
        )
    return usage


def _record_usage(
    db: Session,
    *,
    provider: str,
    model: str,
    usage: TokenUsage,
    action: str,
) -> DailyUsageOut:
    today = _today_utc()
    current = _load_daily_usage(db, today)
    updated = DailyUsageOut(
        date_utc=today,
        requests=current.requests + 1,
        prompt_tokens=current.prompt_tokens + usage.prompt_tokens,
        output_tokens=current.output_tokens + usage.output_tokens,
        total_tokens=current.total_tokens + usage.total_tokens,
    )
    _upsert_setting(
        db,
        key=_usage_key(today),
        value_json=updated.model_dump(),
        category="ai_usage",
        description=f"Daily AI usage totals for {today}",
    )
    db.add(
        AuditLog(
            project_id=None,
            action=action,
            entity_type="provider",
            entity_id=provider,
            actor="owner",
            details_json={
                "provider": provider,
                "model": model,
                "prompt_tokens": usage.prompt_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
            },
        )
    )
    return updated


def build_active_provider(
    db: Session,
    secret_store: SecretStore,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> tuple[LLMProvider, ProviderSettingsUpdate]:
    """Build the configured LLMProvider instance from non-secret config + keyring secret."""
    cfg = _load_provider_config(db)
    api_key = secret_store.get_api_key(cfg.active_provider)
    provider = create_provider(
        cfg.active_provider,
        api_key,
        fast_model=cfg.models.fast,
        deep_model=cfg.models.deep,
        client_factory=client_factory,
    )
    return provider, cfg


def execute_provider_request(
    db: Session,
    secret_store: SecretStore,
    request: LLMRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> LLMResponse:
    """Enforce daily usage budgets, invoke active LLMProvider, and persist token usage."""
    provider, cfg = build_active_provider(db, secret_store, client_factory=client_factory)
    _check_usage_budget(db, cfg.usage_limits)
    if request.max_output_tokens is None:
        request.max_output_tokens = cfg.usage_limits.max_output_tokens
    response = provider.generate(request)
    _record_usage(
        db,
        provider=response.provider,
        model=response.model,
        usage=response.usage,
        action="provider.usage_recorded",
    )
    db.commit()
    return response


def test_provider_connection(
    db: Session,
    secret_store: SecretStore,
    *,
    complexity: TaskComplexity = "fast",
    model_override: str | None = None,
    client_factory: Callable[[str], Any] | None = None,
) -> ConnectionTestOut:
    """Verify live connectivity for the active provider and persist non-secret check state."""
    cfg = _load_provider_config(db)
    selected_model = (
        model_override.strip()
        if model_override and model_override.strip()
        else (cfg.models.deep if complexity == "deep" else cfg.models.fast)
    )
    api_key = secret_store.get_api_key(cfg.active_provider)
    try:
        provider = create_provider(
            cfg.active_provider,
            api_key,
            fast_model=cfg.models.fast,
            deep_model=cfg.models.deep,
            client_factory=client_factory,
        )
        _check_usage_budget(db, cfg.usage_limits)
        result = provider.test_connection(model=selected_model)
    except ProviderError as exc:
        safe_msg = sanitize_secret_text(str(exc), api_key)
        _save_last_check(
            db,
            status_value="error",
            model=selected_model,
            message=safe_msg,
            latency_ms=None,
        )
        db.add(
            AuditLog(
                project_id=None,
                action="provider.connection_failed",
                entity_type="provider",
                entity_id=cfg.active_provider,
                actor="owner",
                details_json={"provider": cfg.active_provider, "model": selected_model, "error": safe_msg},
            )
        )
        db.commit()
        raise

    daily_usage = _record_usage(
        db,
        provider=result.provider,
        model=result.model,
        usage=result.usage,
        action="provider.connection_tested",
    )
    _save_last_check(
        db,
        status_value="connected",
        model=result.model,
        message=result.message,
        latency_ms=result.latency_ms,
    )
    db.commit()

    return ConnectionTestOut(
        connected=result.connected,
        provider=result.provider,
        model=result.model,
        message=result.message,
        latency_ms=result.latency_ms,
        usage=TokenUsageOut(
            prompt_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            thoughts_tokens=result.usage.thoughts_tokens,
            cached_tokens=result.usage.cached_tokens,
        ),
        daily_usage=daily_usage,
        api_key_configured=True,
    )
