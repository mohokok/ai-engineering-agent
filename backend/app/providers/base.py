"""Provider-agnostic LLM interfaces, request/response models, and exceptions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Literal

from pydantic import BaseModel

TaskComplexity = Literal["fast", "deep"]


class ProviderError(RuntimeError):
    """Base error raised by LLM provider adapters."""

    def __init__(self, message: str, *, usage: "TokenUsage | None" = None) -> None:
        super().__init__(message)
        self.usage = usage or TokenUsage()


class ProviderConfigError(ProviderError):
    """Raised when provider credentials or configuration are missing or invalid."""


class ProviderAuthError(ProviderError):
    """Raised when the provider rejects API authentication or authorization."""


class ProviderQuotaError(ProviderError):
    """Raised when the provider rate limit or billing quota is exceeded."""


class ProviderUsageLimitError(ProviderError):
    """Raised when configured local daily or monthly usage limits would be exceeded."""


class ProviderResponseError(ProviderError):
    """Raised when the provider returns empty or unparseable output."""


class ProviderModelNotFoundError(ProviderError):
    """Raised when the requested model ID is missing or retired (HTTP 404)."""


class ProviderServiceUnavailableError(ProviderError):
    """Raised when the provider remains temporarily unavailable (HTTP 503) after retries."""


@dataclass(frozen=True)
class MediaInput:
    """Binary image or PDF attachment for multimodal LLM requests."""

    data: bytes
    mime_type: str
    filename: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-agnostic function/tool declaration."""

    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCallResult:
    """Normalized function/tool call emitted by a provider."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class TokenUsage:
    """Normalized token accounting reported by an LLM provider."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMRequest:
    """Unified request contract supporting text, structured JSON, media, and tools."""

    prompt: str
    system_instruction: str | None = None
    complexity: TaskComplexity = "fast"
    model_override: str | None = None
    temperature: float | None = 0.2
    max_output_tokens: int | None = None
    response_schema: type[BaseModel] | dict[str, Any] | None = None
    media: list[MediaInput] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)


@dataclass
class LLMResponse:
    """Normalized response returned by any LLMProvider implementation."""

    provider: str
    model: str
    text: str = ""
    parsed_json: dict[str, Any] | list[Any] | None = None
    tool_calls: list[ToolCallResult] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: int = 0
    raw_finish_reason: str | None = None


@dataclass(frozen=True)
class ModelInfo:
    """Discovered model capability metadata returned by an LLM provider."""

    id: str
    label: str
    tier: TaskComplexity = "fast"
    supported_actions: tuple[str, ...] = ("generateContent",)


@dataclass(frozen=True)
class ConnectionCheckResult:
    """Result returned by LLMProvider.test_connection."""

    provider: str
    model: str
    connected: bool
    message: str
    usage: TokenUsage
    latency_ms: int


from app.core.security import sanitize_secret_text


class LLMProvider(ABC):
    """Abstract swappable interface for engineering AI model providers."""

    provider_name: str

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Execute a unified generation request against the configured provider."""

    @abstractmethod
    def test_connection(self, model: str | None = None) -> ConnectionCheckResult:
        """Verify live API credentials and model reachability with a minimal prompt."""

    def list_models(self) -> list[ModelInfo]:
        """Return available models capable of text/multimodal generation."""
        return []

    def generate_text(
        self,
        prompt: str,
        *,
        complexity: TaskComplexity = "fast",
        system_instruction: str | None = None,
        max_output_tokens: int | None = None,
    ) -> LLMResponse:
        """Convenience helper for plain text generation."""
        return self.generate(
            LLMRequest(
                prompt=prompt,
                complexity=complexity,
                system_instruction=system_instruction,
                max_output_tokens=max_output_tokens,
            )
        )

    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel] | dict[str, Any],
        *,
        complexity: TaskComplexity = "fast",
        system_instruction: str | None = None,
    ) -> LLMResponse:
        """Convenience helper for schema-constrained JSON output."""
        return self.generate(
            LLMRequest(
                prompt=prompt,
                complexity=complexity,
                system_instruction=system_instruction,
                response_schema=response_schema,
            )
        )

    def analyze_media(
        self,
        prompt: str,
        media: list[MediaInput],
        *,
        complexity: TaskComplexity = "deep",
        response_schema: type[BaseModel] | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Convenience helper for PDF and image multimodal analysis."""
        return self.generate(
            LLMRequest(
                prompt=prompt,
                complexity=complexity,
                media=media,
                response_schema=response_schema,
            )
        )

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        *,
        complexity: TaskComplexity = "fast",
        system_instruction: str | None = None,
    ) -> LLMResponse:
        """Convenience helper for tool/function calling."""
        return self.generate(
            LLMRequest(
                prompt=prompt,
                complexity=complexity,
                system_instruction=system_instruction,
                tools=tools,
            )
        )
