"""Pydantic schemas for AI provider settings, credentials status, and connection checks."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.providers.base import TaskComplexity
from app.providers.gemini import DEFAULT_GEMINI_DEEP_MODEL, DEFAULT_GEMINI_FAST_MODEL


class ModelSelectionSchema(BaseModel):
    """Configured model identifiers per task complexity tier."""

    fast: str = Field(default=DEFAULT_GEMINI_FAST_MODEL, min_length=1, max_length=128)
    deep: str = Field(default=DEFAULT_GEMINI_DEEP_MODEL, min_length=1, max_length=128)

    @field_validator("fast", "deep")
    @classmethod
    def strip_model_id(cls, value: str) -> str:
        """Ensure configured model names are trimmed and non-blank."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Model identifier must not be empty")
        return cleaned


class UsageLimitsSchema(BaseModel):
    """Daily and monthly cost/rate safety caps enforced before external LLM calls."""

    daily_request_limit: int = Field(default=200, ge=1, le=100_000)
    daily_token_limit: int = Field(default=500_000, ge=1_000, le=100_000_000)
    monthly_request_limit: int = Field(default=3_000, ge=1, le=5_000_000)
    monthly_token_limit: int = Field(default=5_000_000, ge=1_000, le=5_000_000_000)
    max_output_tokens: int = Field(default=8192, ge=64, le=65_536)


class ProviderSettingsUpdate(BaseModel):
    """Non-secret provider configuration payload."""

    active_provider: str = Field(default="gemini", min_length=1, max_length=64)
    models: ModelSelectionSchema = Field(default_factory=ModelSelectionSchema)
    usage_limits: UsageLimitsSchema = Field(default_factory=UsageLimitsSchema)

    @field_validator("active_provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize active provider identifier."""
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("active_provider must not be empty")
        return cleaned


class ApiKeySaveRequest(BaseModel):
    """Sensitive API key write-only payload stored directly into OS keyring."""

    api_key: str = Field(..., min_length=1, max_length=512)

    @field_validator("api_key")
    @classmethod
    def validate_non_blank_key(cls, value: str) -> str:
        """Reject whitespace-only API key submissions."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("API key must not be empty")
        return cleaned


class _UsageTotalsBase(BaseModel):
    requests: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class DailyUsageOut(_UsageTotalsBase):
    """Tracked daily token and request usage counters summed from append-only logs."""

    date_utc: str


class MonthlyUsageOut(_UsageTotalsBase):
    """Tracked monthly token and request usage counters summed from append-only logs."""

    month_utc: str


class ConnectionCheckStatusOut(BaseModel):
    """Sanitized summary of the most recent connection check (never holds secrets)."""

    status: Literal["untested", "connected", "error"] = "untested"
    checked_at: str | None = None
    model: str | None = None
    message: str | None = None
    latency_ms: int | None = None


class ProviderSettingsOut(BaseModel):
    """Read-only view of AI provider settings; never contains API key material."""

    active_provider: str
    available_providers: list[dict[str, Any]]
    models: ModelSelectionSchema
    usage_limits: UsageLimitsSchema
    daily_usage: DailyUsageOut
    monthly_usage: MonthlyUsageOut
    api_key_configured: bool
    credential_backend: str
    last_connection_check: ConnectionCheckStatusOut
    consumer_subscription_notice: str
    classification: str = "Preliminary"


class ConnectionTestRequest(BaseModel):
    """Optional overrides when running a live connection test from Settings."""

    complexity: TaskComplexity = "fast"
    model_override: str | None = Field(default=None, max_length=128)


class TokenUsageOut(BaseModel):
    """Serialized token usage metrics from a provider call."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0


class ConnectionTestOut(BaseModel):
    """Connection test outcome returned to the Settings UI."""

    connected: bool
    provider: str
    model: str
    message: str
    latency_ms: int
    usage: TokenUsageOut
    daily_usage: DailyUsageOut
    monthly_usage: MonthlyUsageOut
    api_key_configured: bool
    classification: str = "Preliminary"
