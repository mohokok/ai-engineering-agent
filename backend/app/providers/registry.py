"""Provider registry allowing AI backends to be swapped via configuration."""

from typing import Any, Callable

from app.providers.base import LLMProvider, ProviderConfigError
from app.providers.gemini import AVAILABLE_GEMINI_MODELS, GeminiProvider

PROVIDER_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "gemini",
        "name": "Google Gemini (Official google-genai SDK)",
        "models": list(AVAILABLE_GEMINI_MODELS),
    },
)


def create_provider(
    provider_name: str,
    api_key: str | None,
    *,
    fast_model: str,
    deep_model: str,
    client_factory: Callable[[str], Any] | None = None,
) -> LLMProvider:
    """Instantiate the configured LLMProvider implementation without rebuilding the app."""
    normalized = provider_name.strip().lower()
    if normalized == "gemini":
        if not api_key or not api_key.strip():
            raise ProviderConfigError(
                "No Gemini API key is saved in Windows Credential Manager. Enter your API key in Settings first."
            )
        return GeminiProvider(
            api_key=api_key,
            fast_model=fast_model,
            deep_model=deep_model,
            client_factory=client_factory,
        )
    raise ProviderConfigError(f"Unsupported AI provider: {provider_name!r}")
