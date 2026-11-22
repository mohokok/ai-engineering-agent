"""Central Step 20 secret redaction, client-data log scrubbing, and HTTP security header utilities."""

import re
from typing import Any

# Common secret / API key shapes across providers and VCS tokens (never hardcode real keys).
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:key|api_key|apikey|token|access_token|secret|auth)=)[^&\s\"'<>]+",
    re.IGNORECASE,
)
_HEADER_SECRET_RE = re.compile(
    r"\b(authorization|x-goog-api-key|x-api-key)\s*([:=])\s*(?:Bearer\s+)?[^\s,;'\"}\]]+",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(r"\b(Bearer\s+)[A-Za-z0-9._\-]{12,}\b", re.IGNORECASE)
_AI_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z\-_]{16,}\b")
_SK_KEY_RE = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9\-_]{16,}\b")
_TVLY_KEY_RE = re.compile(r"\btvly-[A-Za-z0-9\-_]{12,}\b", re.IGNORECASE)
_GH_TOKEN_RE = re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)

# Client/PII patterns redacted before structured local logging (never in raw log lines).
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_SENSITIVE_KEY_EXACT = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "token",
        "access_token",
        "password",
        "authorization",
        "x_goog_api_key",
        "x_api_key",
    }
)
_CLIENT_TEXT_KEY_EXACT = frozenset(
    {
        "prompt",
        "raw_text",
        "extracted_text",
        "content",
        "file_bytes",
        "summary_prose",
        "owner_notes",
        "description",
        "brief",
        "client_name",
        "project_name",
        "query",
    }
)

SECURITY_RESPONSE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
}

_KEY_DETECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", _AI_KEY_RE),
    ("sk_prefixed_key", _SK_KEY_RE),
    ("tavily_key", _TVLY_KEY_RE),
    ("github_token", _GH_TOKEN_RE),
    ("pem_private_key", _PEM_PRIVATE_KEY_RE),
)


def sanitize_secret_text(text: str, secret: str | None = None) -> str:
    """Scrub secret strings, provider API key shapes, headers, and query params."""
    if not text:
        return ""
    cleaned = str(text)
    if secret:
        cleaned = cleaned.replace(secret, "[REDACTED]")
    cleaned = _PEM_PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", cleaned)
    cleaned = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", cleaned)
    cleaned = _HEADER_SECRET_RE.sub(r"\1\2 [REDACTED]", cleaned)
    cleaned = _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", cleaned)
    cleaned = _AI_KEY_RE.sub("[REDACTED_KEY]", cleaned)
    cleaned = _SK_KEY_RE.sub("[REDACTED_KEY]", cleaned)
    cleaned = _TVLY_KEY_RE.sub("[REDACTED_KEY]", cleaned)
    cleaned = _GH_TOKEN_RE.sub("[REDACTED_KEY]", cleaned)
    return cleaned


def redact_client_and_secrets_for_log(text: str, extra_secrets: tuple[str, ...] = ()) -> str:
    """Scrub secrets and common PII (emails) before writing operational log lines."""
    cleaned = sanitize_secret_text(text)
    for sec in extra_secrets:
        if sec:
            cleaned = cleaned.replace(sec, "[REDACTED]")
    cleaned = _EMAIL_RE.sub("[REDACTED_EMAIL]", cleaned)
    return cleaned


def scrub_structured_mapping(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys and raw client-content fields for local JSON logs."""
    if _depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            norm = str(k).strip().lower().replace("-", "_")
            if norm in _SENSITIVE_KEY_EXACT:
                out[str(k)] = "[REDACTED]"
            elif norm in _CLIENT_TEXT_KEY_EXACT:
                out[str(k)] = "[REDACTED_CLIENT_DATA]"
            else:
                out[str(k)] = scrub_structured_mapping(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub_structured_mapping(item, _depth=_depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return redact_client_and_secrets_for_log(value)
    return value


def find_key_like_strings(text: str) -> list[str]:
    """Return matching rule names if any key-like secret material is present in text."""
    hits: list[str] = []
    if not text:
        return hits
    for rule_name, pattern in _KEY_DETECTION_PATTERNS:
        if pattern.search(text):
            hits.append(rule_name)
    return hits
