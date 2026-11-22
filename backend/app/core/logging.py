"""Structured local JSONL rotating logging with secret and client-data redaction (no remote shipping)."""

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from app.core.security import redact_client_and_secrets_for_log, scrub_structured_mapping

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5
_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{4,64}$")

correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="-")

_AUDIT_LOGGER = logging.getLogger("app.audit")
_APP_LOGGER = logging.getLogger("app")


def get_logs_dir(workspaces_dir: Path) -> Path:
    """Return local logs root strictly under configured workspaces_dir."""
    return workspaces_dir.resolve()


def get_log_file_path(workspaces_dir: Path) -> Path:
    """Return the primary rotating structured log file path directly under workspaces_dir."""
    return get_logs_dir(workspaces_dir) / "agent.log"


def get_correlation_id() -> str:
    """Return active request correlation ID or '-' outside request scope."""
    return correlation_id_ctx.get()


def normalize_correlation_id(raw: str | None) -> str:
    """Accept clean caller correlation IDs or mint a fresh short hex identifier."""
    if raw:
        candidate = raw.strip()
        if _CORRELATION_ID_RE.match(candidate):
            return candidate
    return uuid4().hex[:16]


class SecretAndClientRedactionFilter(logging.Filter):
    """Logging filter that strips API keys, bearer tokens, emails, and raw client fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        safe_msg = redact_client_and_secrets_for_log(rendered)
        record.msg = safe_msg
        record.args = ()
        if hasattr(record, "structured_details"):
            record.structured_details = scrub_structured_mapping(getattr(record, "structured_details"))
        if hasattr(record, "exc_info") and record.exc_info:
            record.exc_text = redact_client_and_secrets_for_log(
                logging.Formatter().formatException(record.exc_info)
            )
            record.exc_info = None
        return True


class JsonLineFormatter(logging.Formatter):
    """Emit single-line UTF-8 JSON log objects containing correlation ID and safe metadata."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
            "event": getattr(record, "event_name", None) or "log",
            "message": redact_client_and_secrets_for_log(str(record.msg)),
        }
        details = getattr(record, "structured_details", None)
        if isinstance(details, dict) and details:
            payload["details"] = scrub_structured_mapping(details)
        if record.exc_text:
            payload["exception"] = redact_client_and_secrets_for_log(str(record.exc_text))
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class WorkspaceLogHandle:
    """Lifecycle handle owning the workspace RotatingFileHandler (closed cleanly on shutdown)."""

    log_path: Path
    handler: RotatingFileHandler
    max_bytes: int = LOG_MAX_BYTES
    backup_count: int = LOG_BACKUP_COUNT

    def close(self) -> None:
        if self.handler in _APP_LOGGER.handlers:
            _APP_LOGGER.removeHandler(self.handler)
        try:
            self.handler.flush()
            self.handler.close()
        except Exception:
            pass


def configure_workspace_logging(workspaces_dir: Path) -> WorkspaceLogHandle:
    """Attach a rotating UTF-8 JSONL handler under workspaces_dir/_logs/agent.log."""
    log_dir = get_logs_dir(workspaces_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = get_log_file_path(workspaces_dir)

    # Detach stale handlers targeting the exact same path so re-created apps don't duplicate entries.
    for existing in list(_APP_LOGGER.handlers):
        if getattr(existing, "_step20_log_path", None) == str(log_path):
            _APP_LOGGER.removeHandler(existing)
            try:
                existing.close()
            except Exception:
                pass

    handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, "_step20_log_path", str(log_path))
    handler.setLevel(logging.INFO)
    handler.addFilter(SecretAndClientRedactionFilter())
    handler.setFormatter(JsonLineFormatter())

    _APP_LOGGER.setLevel(logging.INFO)
    _APP_LOGGER.propagate = True
    _APP_LOGGER.addHandler(handler)
    return WorkspaceLogHandle(log_path=log_path, handler=handler)


def record_audit_log_event(
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    project_id: str | None = None,
    actor: str = "owner",
    details: dict[str, Any] | None = None,
) -> None:
    """Write a redacted structured audit line to the local rotating log file."""
    _AUDIT_LOGGER.info(
        f"Audit action={action} entity={entity_type}:{entity_id or '-'}",
        extra={
            "event_name": "audit_event",
            "correlation_id": get_correlation_id(),
            "structured_details": scrub_structured_mapping(
                {
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "project_id": project_id,
                    "actor": actor,
                    **(details or {}),
                }
            ),
        },
    )
