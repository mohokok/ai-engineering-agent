"""Google Gemini LLM provider implementation using the official google-genai SDK."""

import json
import time
from typing import Any, Callable

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

from app.providers.base import (
    ConnectionCheckResult,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderQuotaError,
    ProviderResponseError,
    TaskComplexity,
    TokenUsage,
    ToolCallResult,
    sanitize_secret_text,
)

DEFAULT_GEMINI_FAST_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_DEEP_MODEL = "gemini-2.5-pro"

AVAILABLE_GEMINI_MODELS: tuple[dict[str, str], ...] = (
    {
        "id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash (Fast / General)",
        "tier": "fast",
    },
    {
        "id": "gemini-2.5-flash-lite",
        "label": "Gemini 2.5 Flash-Lite (Lightweight)",
        "tier": "fast",
    },
    {
        "id": "gemini-2.5-pro",
        "label": "Gemini 2.5 Pro (Deep Engineering Reasoning)",
        "tier": "deep",
    },
)


def _extract_usage(raw_usage: Any) -> TokenUsage:
    if raw_usage is None:
        return TokenUsage()
    prompt_tokens = int(getattr(raw_usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(raw_usage, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(raw_usage, "total_token_count", 0) or (prompt_tokens + output_tokens))
    thoughts_tokens = int(getattr(raw_usage, "thoughts_token_count", 0) or 0)
    cached_tokens = int(getattr(raw_usage, "cached_content_token_count", 0) or 0)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        thoughts_tokens=thoughts_tokens,
        cached_tokens=cached_tokens,
    )


class GeminiProvider(LLMProvider):
    """Swappable LLMProvider backed by the official Google GenAI SDK."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        fast_model: str = DEFAULT_GEMINI_FAST_MODEL,
        deep_model: str = DEFAULT_GEMINI_DEEP_MODEL,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        cleaned_key = api_key.strip()
        if not cleaned_key:
            raise ProviderConfigError("Gemini API key is not configured.")
        self._api_key = cleaned_key
        self._model_map: dict[TaskComplexity, str] = {
            "fast": fast_model.strip() or DEFAULT_GEMINI_FAST_MODEL,
            "deep": deep_model.strip() or DEFAULT_GEMINI_DEEP_MODEL,
        }
        self._client_factory = client_factory or (lambda key: genai.Client(api_key=key))

    def resolve_model(self, request: LLMRequest) -> str:
        """Select model based on explicit override or task complexity."""
        if request.model_override and request.model_override.strip():
            return request.model_override.strip()
        return self._model_map.get(request.complexity, DEFAULT_GEMINI_FAST_MODEL)

    def _build_client(self) -> Any:
        return self._client_factory(self._api_key)

    def _build_contents(self, request: LLMRequest) -> list[Any]:
        parts: list[Any] = [request.prompt]
        for media in request.media:
            parts.append(genai_types.Part.from_bytes(data=media.data, mime_type=media.mime_type))
        return parts

    def _build_config(self, request: LLMRequest) -> genai_types.GenerateContentConfig:
        config_kwargs: dict[str, Any] = {}
        if request.system_instruction:
            config_kwargs["system_instruction"] = request.system_instruction
        if request.temperature is not None:
            config_kwargs["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = request.response_schema
        if request.tools:
            declarations = [
                genai_types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=tool.parameters_schema,
                )
                for tool in request.tools
            ]
            config_kwargs["tools"] = [genai_types.Tool(function_declarations=declarations)]
        return genai_types.GenerateContentConfig(**config_kwargs)

    def _translate_api_error(self, exc: Exception) -> ProviderError:
        message = sanitize_secret_text(str(exc), self._api_key)
        status_code = getattr(exc, "code", None)
        lowered = message.lower()

        if status_code in (401, 403) or any(
            marker in lowered
            for marker in ("api_key_invalid", "invalid api key", "api key not valid", "permission_denied", "unauthorized")
        ):
            return ProviderAuthError(
                "Gemini API authentication failed. Verify your Gemini API key in Settings "
                "(note: a Gemini consumer subscription does not include Gemini API access)."
            )
        if status_code == 429 or any(
            marker in lowered for marker in ("resource_exhausted", "quota", "rate limit")
        ):
            return ProviderQuotaError(
                "Gemini API quota or rate limit exceeded. Wait and retry or check your Google AI Studio quota."
            )
        return ProviderError(f"Gemini API request failed: {message}")

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Call Gemini generate_content supporting text, JSON schema, media, and tools."""
        model_name = self.resolve_model(request)
        client = self._build_client()
        contents = self._build_contents(request)
        config = self._build_config(request)

        start = time.perf_counter()
        try:
            raw_resp = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except genai_errors.APIError as exc:
            raise self._translate_api_error(exc) from exc
        except ProviderError:
            raise
        except Exception as exc:
            raise self._translate_api_error(exc) from exc

        latency_ms = max(1, int((time.perf_counter() - start) * 1000))
        usage = _extract_usage(getattr(raw_resp, "usage_metadata", None))
        text = getattr(raw_resp, "text", None) or ""

        parsed_json: dict[str, Any] | list[Any] | None = None
        if request.response_schema is not None:
            parsed_attr = getattr(raw_resp, "parsed", None)
            if isinstance(parsed_attr, BaseModel):
                parsed_json = parsed_attr.model_dump()
            elif isinstance(parsed_attr, (dict, list)):
                parsed_json = parsed_attr
            else:
                if not text.strip():
                    raise ProviderResponseError("Gemini returned empty structured output.")
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ProviderResponseError(
                        f"Gemini returned invalid JSON for structured schema: {exc.msg}"
                    ) from exc
                if not isinstance(decoded, (dict, list)):
                    raise ProviderResponseError(
                        "Structured output must decode to a JSON object or array."
                    )
                parsed_json = decoded

        tool_calls: list[ToolCallResult] = []
        raw_calls = getattr(raw_resp, "function_calls", None) or []
        for fc in raw_calls:
            name = getattr(fc, "name", None)
            if name:
                raw_args = getattr(fc, "args", None) or {}
                tool_calls.append(ToolCallResult(name=str(name), arguments=dict(raw_args)))

        if not text and parsed_json is None and not tool_calls:
            raise ProviderResponseError("Gemini returned an empty response with no text or tool calls.")

        finish_reason = None
        candidates = getattr(raw_resp, "candidates", None) or []
        if candidates:
            raw_reason = getattr(candidates[0], "finish_reason", None)
            finish_reason = str(raw_reason) if raw_reason is not None else None

        return LLMResponse(
            provider=self.provider_name,
            model=model_name,
            text=text,
            parsed_json=parsed_json,
            tool_calls=tool_calls,
            usage=usage,
            latency_ms=latency_ms,
            raw_finish_reason=finish_reason,
        )

    def test_connection(self, model: str | None = None) -> ConnectionCheckResult:
        """Perform a minimal generate_content probe to verify key and quota access."""
        request = LLMRequest(
            prompt="Reply with the single word OK.",
            complexity="fast",
            model_override=model,
            temperature=0.0,
            max_output_tokens=16,
        )
        response = self.generate(request)
        return ConnectionCheckResult(
            provider=self.provider_name,
            model=response.model,
            connected=True,
            message=f"Connected cleanly to {response.model}.",
            usage=response.usage,
            latency_ms=response.latency_ms,
        )
