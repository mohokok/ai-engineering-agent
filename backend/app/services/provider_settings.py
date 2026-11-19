"""Non-secret DB settings, append-only usage tracking, keyring coordination, and runner."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

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
    MonthlyUsageOut,
    ProviderSettingsOut,
    ProviderSettingsUpdate,
    TokenUsageOut,
    UsageLimitsSchema,
)

PROVIDER_CONFIG_KEY = "provider.config"
PROVIDER_LAST_CHECK_KEY = "provider.last_check"
PROVIDER_DISCOVERED_MODELS_KEY = "provider.discovered_models"
USAGE_LEDGER_ENTITY_TYPE = "provider_usage"
logger = logging.getLogger(__name__)
CONSUMER_SUBSCRIPTION_NOTICE = (
    "Note: A consumer Gemini web subscription (Gemini Advanced / Google One) does NOT "
    "automatically include Gemini API access. Generate an authorized Gemini API key in "
    "Google AI Studio; it is stored only in Windows Credential Manager via keyring."
)


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _month_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


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


def _summarize_usage(
    db: Session,
    *,
    date_utc: str | None = None,
    month_utc: str | None = None,
) -> tuple[DailyUsageOut, MonthlyUsageOut]:
    """Sum append-only provider_usage AuditLog rows for daily and monthly totals."""
    target_day = date_utc or _today_utc()
    target_month = month_utc or _month_utc()
    month_start = datetime.strptime(f"{target_month}-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)

    rows = db.scalars(
        select(AuditLog).where(
            AuditLog.entity_type == USAGE_LEDGER_ENTITY_TYPE,
            AuditLog.created_at >= month_start - timedelta(days=1),
        )
    ).all()

    day_totals = {"requests": 0, "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    month_totals = {"requests": 0, "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    for row in rows:
        details = row.details_json or {}
        req_count = int(details.get("requests", 1) or 0)
        prompt_tokens = int(details.get("prompt_tokens", 0) or 0)
        output_tokens = int(details.get("output_tokens", 0) or 0)
        total_tokens = int(details.get("total_tokens", 0) or 0)

        if details.get("month_utc") == target_month:
            month_totals["requests"] += req_count
            month_totals["prompt_tokens"] += prompt_tokens
            month_totals["output_tokens"] += output_tokens
            month_totals["total_tokens"] += total_tokens

        if details.get("date_utc") == target_day:
            day_totals["requests"] += req_count
            day_totals["prompt_tokens"] += prompt_tokens
            day_totals["output_tokens"] += output_tokens
            day_totals["total_tokens"] += total_tokens

    return (
        DailyUsageOut(date_utc=target_day, **day_totals),
        MonthlyUsageOut(month_utc=target_month, **month_totals),
    )


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


def _load_discovered_models(db: Session, provider_id: str) -> tuple[list[dict[str, str]] | None, str | None]:
    row = db.get(Setting, PROVIDER_DISCOVERED_MODELS_KEY)
    if row is None or not isinstance(row.value_json, dict):
        return None, None
    data = row.value_json
    if data.get("provider") != provider_id:
        return None, None
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        return None, None
    return raw_models, data.get("refreshed_at")


def _build_available_providers(
    db: Session,
    cfg: ProviderSettingsUpdate,
) -> tuple[list[dict[str, Any]], str, str | None, str | None]:
    discovered, refreshed_at = _load_discovered_models(db, cfg.active_provider)
    providers = [dict(item) for item in PROVIDER_CATALOG]
    if discovered is None:
        return providers, "fallback_catalog", None, None

    for item in providers:
        if item.get("id") == cfg.active_provider:
            item["models"] = discovered

    live_ids = {str(m.get("id", "")) for m in discovered}
    missing = [
        m_id
        for m_id in (cfg.models.fast, cfg.models.deep)
        if m_id not in live_ids
    ]
    warning = None
    if missing:
        unique_missing = list(dict.fromkeys(missing))
        warning = (
            f"Configured model(s) ({', '.join(unique_missing)}) were not returned in the "
            "refreshed generateContent list for your API key. Pick an available model below or click Refresh models."
        )
    return providers, "live_api", refreshed_at, warning


def get_provider_settings(db: Session, secret_store: SecretStore) -> ProviderSettingsOut:
    """Return full non-secret provider settings along with boolean key status."""
    cfg = _load_provider_config(db)
    daily_usage, monthly_usage = _summarize_usage(db)
    last_check = _load_last_check(db)
    api_key_configured = secret_store.has_api_key(cfg.active_provider)
    providers, models_source, refreshed_at, model_warning = _build_available_providers(db, cfg)
    return ProviderSettingsOut(
        active_provider=cfg.active_provider,
        available_providers=providers,
        models=cfg.models,
        models_source=models_source,  # type: ignore[arg-type]
        models_refreshed_at=refreshed_at,
        model_warning=model_warning,
        usage_limits=cfg.usage_limits,
        daily_usage=daily_usage,
        monthly_usage=monthly_usage,
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
    """Remove stored API key from OS keyring and reset connection check and live model cache."""
    cfg = _load_provider_config(db)
    secret_store.delete_api_key(cfg.active_provider)
    cached_row = db.get(Setting, PROVIDER_DISCOVERED_MODELS_KEY)
    if cached_row is not None:
        db.delete(cached_row)
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


def _check_usage_budget(db: Session, limits: UsageLimitsSchema) -> tuple[DailyUsageOut, MonthlyUsageOut]:
    daily, monthly = _summarize_usage(db)
    if daily.requests >= limits.daily_request_limit:
        raise ProviderUsageLimitError(
            f"Daily request limit reached ({daily.requests}/{limits.daily_request_limit})."
        )
    if daily.total_tokens >= limits.daily_token_limit:
        raise ProviderUsageLimitError(
            f"Daily token limit reached ({daily.total_tokens}/{limits.daily_token_limit})."
        )
    if monthly.requests >= limits.monthly_request_limit:
        raise ProviderUsageLimitError(
            f"Monthly request limit reached ({monthly.requests}/{limits.monthly_request_limit})."
        )
    if monthly.total_tokens >= limits.monthly_token_limit:
        raise ProviderUsageLimitError(
            f"Monthly token limit reached ({monthly.total_tokens}/{limits.monthly_token_limit})."
        )
    return daily, monthly


def _append_usage_event(
    db: Session,
    *,
    provider: str,
    model: str,
    usage: TokenUsage,
    action: str,
    status_label: str,
    error_message: str | None = None,
) -> tuple[DailyUsageOut, MonthlyUsageOut]:
    """Append one immutable usage ledger entry and return updated daily/monthly sums."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    details: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "date_utc": today,
        "month_utc": month,
        "requests": 1,
        "prompt_tokens": usage.prompt_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "status": status_label,
    }
    if error_message is not None:
        details["error"] = error_message

    db.add(
        AuditLog(
            project_id=None,
            action=action,
            entity_type=USAGE_LEDGER_ENTITY_TYPE,
            entity_id=provider,
            actor="owner",
            details_json=details,
        )
    )
    db.flush()
    return _summarize_usage(db, date_utc=today, month_utc=month)


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
    """Enforce daily/monthly usage budgets, invoke LLMProvider, and log every attempt."""
    cfg = _load_provider_config(db)
    api_key = secret_store.get_api_key(cfg.active_provider)
    provider = create_provider(
        cfg.active_provider,
        api_key,
        fast_model=cfg.models.fast,
        deep_model=cfg.models.deep,
        client_factory=client_factory,
    )
    _check_usage_budget(db, cfg.usage_limits)
    if request.max_output_tokens is None:
        request.max_output_tokens = cfg.usage_limits.max_output_tokens

    resolved_model = (
        request.model_override.strip()
        if request.model_override and request.model_override.strip()
        else (cfg.models.deep if request.complexity == "deep" else cfg.models.fast)
    )
    try:
        response = provider.generate(request)
    except ProviderError as exc:
        safe_msg = sanitize_secret_text(str(exc), api_key)
        _append_usage_event(
            db,
            provider=cfg.active_provider,
            model=resolved_model,
            usage=exc.usage,
            action="provider.usage_failed",
            status_label="failed",
            error_message=safe_msg,
        )
        db.commit()
        raise

    _append_usage_event(
        db,
        provider=response.provider,
        model=response.model,
        usage=response.usage,
        action="provider.usage_recorded",
        status_label="ok",
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
    provider = create_provider(
        cfg.active_provider,
        api_key,
        fast_model=cfg.models.fast,
        deep_model=cfg.models.deep,
        client_factory=client_factory,
    )
    _check_usage_budget(db, cfg.usage_limits)

    try:
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
        _append_usage_event(
            db,
            provider=cfg.active_provider,
            model=selected_model,
            usage=exc.usage,
            action="provider.connection_failed",
            status_label="failed",
            error_message=safe_msg,
        )
        db.commit()
        raise

    daily_usage, monthly_usage = _append_usage_event(
        db,
        provider=result.provider,
        model=result.model,
        usage=result.usage,
        action="provider.connection_tested",
        status_label="ok",
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
        monthly_usage=monthly_usage,
        api_key_configured=True,
    )


def refresh_provider_models(
    db: Session,
    secret_store: SecretStore,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> ProviderSettingsOut:
    """Query active provider SDK for generateContent-capable models and cache non-secret metadata."""
    cfg = _load_provider_config(db)
    api_key = secret_store.get_api_key(cfg.active_provider)
    provider = create_provider(
        cfg.active_provider,
        api_key,
        fast_model=cfg.models.fast,
        deep_model=cfg.models.deep,
        client_factory=client_factory,
    )
    models = provider.list_models()
    serialized = [
        {"id": item.id, "label": item.label, "tier": item.tier}
        for item in models
    ]
    refreshed_at = datetime.now(timezone.utc).isoformat()
    _upsert_setting(
        db,
        key=PROVIDER_DISCOVERED_MODELS_KEY,
        value_json={
            "provider": cfg.active_provider,
            "refreshed_at": refreshed_at,
            "models": serialized,
        },
        category="ai_provider",
        description="Cached generateContent-capable models discovered for the active provider",
    )
    db.add(
        AuditLog(
            project_id=None,
            action="provider.models_refreshed",
            entity_type="provider",
            entity_id=cfg.active_provider,
            actor="owner",
            details_json={
                "provider": cfg.active_provider,
                "count": len(serialized),
                "model_ids": [item["id"] for item in serialized],
            },
        )
    )
    db.commit()
    return get_provider_settings(db, secret_store)


def refresh_models_on_startup(
    session_factory: sessionmaker[Session],
    secret_store: SecretStore,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> None:
    """Best-effort startup model discovery when an API key is already saved in keyring."""
    try:
        with session_factory() as db:
            cfg = _load_provider_config(db)
            if not secret_store.has_api_key(cfg.active_provider):
                return
            refresh_provider_models(db, secret_store, client_factory=client_factory)
    except Exception as exc:
        logger.warning(
            "Startup AI model list refresh skipped: %s",
            sanitize_secret_text(str(exc)),
        )
