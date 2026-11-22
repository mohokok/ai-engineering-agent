"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import re
import time
from typing import Any, Callable

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.boq import router as boq_router
from app.api.calculations import router as calculations_router
from app.api.comparisons import router as comparisons_router
from app.api.drawings import router as drawings_router
from app.api.extraction import router as extraction_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.planning import router as planning_router
from app.api.projects import router as projects_router
from app.api.qa import router as qa_router
from app.api.reports import router as reports_router
from app.api.research import router as research_router
from app.api.settings import router as settings_router
from app.api.specialist import router as specialist_router
from app.api.specifications import router as specifications_router
from app.api.standards import router as standards_router
from app.api.structural import router as structural_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.core.config import Settings, get_settings
from app.core.errors import build_error_payload
from app.core.logging import (
    configure_workspace_logging,
    correlation_id_ctx,
    get_correlation_id,
    normalize_correlation_id,
)
from app.core.security import SECURITY_RESPONSE_HEADERS, sanitize_secret_text
from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory
from app.providers.secrets import KeyringSecretStore, SecretStore
from app.services.provider_settings import refresh_models_on_startup
from app.services.tasks import mark_stale_running_tasks_interrupted

_UPLOAD_SIZE_GUARD_RE = re.compile(r"^/api/(?:projects/[^/]+/files|standards/upload)/?$")
_HTTP_LOGGER = logging.getLogger("app.http")
_ERROR_LOGGER = logging.getLogger("app.errors")


class UploadSizeLimitMiddleware:
    """Reject oversized multipart uploads early on Content-Length before body parsing."""

    def __init__(self, app_asgi: Any, max_request_bytes: int) -> None:
        self.app_asgi = app_asgi
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Short-circuit HTTP 413 when upload Content-Length exceeds batch cap."""
        if (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and _UPLOAD_SIZE_GUARD_RE.match(scope.get("path", ""))
        ):
            for header_name, header_value in scope.get("headers", ()):
                if header_name.lower() == b"content-length":
                    try:
                        content_length = int(header_value.decode("ascii").strip())
                    except (UnicodeDecodeError, ValueError):
                        break
                    if content_length > self.max_request_bytes:
                        cid = get_correlation_id()
                        payload = build_error_payload(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=(
                                f"Request Content-Length ({content_length} bytes) exceeds "
                                f"maximum upload batch size ({self.max_request_bytes} bytes)."
                            ),
                            correlation_id=cid,
                        )
                        response = JSONResponse(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            content=payload,
                            headers={"X-Correlation-ID": cid},
                        )
                        await response(scope, receive, send)
                        return
                    break
        await self.app_asgi(scope, receive, send)


class HardeningAndLoggingMiddleware:
    """Outermost ASGI middleware: correlation IDs, security headers, and redacted local HTTP request logs."""

    def __init__(self, app_asgi: Any) -> None:
        self.app_asgi = app_asgi

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app_asgi(scope, receive, send)
            return

        incoming_cid: str | None = None
        for header_name, header_value in scope.get("headers", ()):
            if header_name.lower() == b"x-correlation-id":
                try:
                    incoming_cid = header_value.decode("ascii", errors="ignore")
                except Exception:
                    incoming_cid = None
                break

        cid = normalize_correlation_id(incoming_cid)
        scope["step20_correlation_id"] = cid
        token = correlation_id_ctx.set(cid)
        started = time.perf_counter()
        status_holder: list[int] = [500]
        method = str(scope.get("method") or "GET")
        path = str(scope.get("path") or "/")

        async def send_with_security_headers(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status_holder[0] = int(message.get("status", 500))
                raw_headers = list(message.get("headers") or [])
                existing_names = {h[0].lower() for h in raw_headers}
                if b"x-correlation-id" not in existing_names:
                    raw_headers.append((b"x-correlation-id", cid.encode("ascii")))
                for h_name, h_val in SECURITY_RESPONSE_HEADERS.items():
                    key_b = h_name.lower().encode("ascii")
                    if key_b not in existing_names:
                        raw_headers.append((key_b, h_val.encode("ascii")))
                message["headers"] = raw_headers
            await send(message)

        try:
            await self.app_asgi(scope, receive, send_with_security_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _HTTP_LOGGER.info(
                f"{method} {path} -> {status_holder[0]} ({duration_ms}ms)",
                extra={
                    "event_name": "http_request",
                    "correlation_id": cid,
                    "structured_details": {
                        "method": method,
                        "path": path,
                        "status_code": status_holder[0],
                        "duration_ms": duration_ms,
                    },
                },
            )
            correlation_id_ctx.reset(token)


def create_app(
    settings: Settings | None = None,
    *,
    secret_store: SecretStore | None = None,
    provider_client_factory: Callable[[str], Any] | None = None,
    research_http_transport: Any | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings or get_settings()
    resolved_secret_store = secret_store or KeyringSecretStore()
    engine = create_db_engine(resolved_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
        log_handle = configure_workspace_logging(application.state.settings.workspaces_dir)
        application.state.log_handle = log_handle
        try:
            upgrade_database(application.state.settings.database_url)
            mark_stale_running_tasks_interrupted(application.state.session_factory)
            refresh_models_on_startup(
                application.state.session_factory,
                application.state.secret_store,
                client_factory=application.state.provider_client_factory,
            )
            yield
        finally:
            application.state.engine.dispose()
            log_handle.close()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.secret_store = resolved_secret_store
    application.state.provider_client_factory = provider_client_factory
    application.state.research_http_transport = research_http_transport

    @application.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        cid = get_correlation_id()
        payload = build_error_payload(
            status_code=exc.status_code,
            detail=exc.detail,
            correlation_id=cid,
        )
        headers = dict(exc.headers or {})
        headers["X-Correlation-ID"] = cid
        return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)

    @application.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        cid = get_correlation_id()
        payload = build_error_payload(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
            correlation_id=cid,
            error_code="VALIDATION_ERROR",
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=payload,
            headers={"X-Correlation-ID": cid},
        )

    @application.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        cid = str(
            request.scope.get("step20_correlation_id")
            or normalize_correlation_id(request.headers.get("x-correlation-id"))
        )
        token = correlation_id_ctx.set(cid)
        try:
            _ERROR_LOGGER.error(
                f"Unhandled exception on {request.method} {request.url.path}: {sanitize_secret_text(exc.__class__.__name__)}",
                exc_info=exc,
                extra={
                    "event_name": "unhandled_exception",
                    "correlation_id": cid,
                    "structured_details": {
                        "method": request.method,
                        "path": request.url.path,
                        "error_type": exc.__class__.__name__,
                    },
                },
            )
            payload = build_error_payload(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error",
                correlation_id=cid,
                error_code="INTERNAL_ERROR",
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=payload,
                headers={**SECURITY_RESPONSE_HEADERS, "X-Correlation-ID": cid},
            )
        finally:
            correlation_id_ctx.reset(token)

    application.add_middleware(
        UploadSizeLimitMiddleware,
        max_request_bytes=resolved_settings.max_files_per_upload * resolved_settings.max_upload_size_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "X-Correlation-ID", "Authorization"],
        expose_headers=["X-Correlation-ID", "Content-Disposition"],
    )
    application.add_middleware(HardeningAndLoggingMiddleware)

    application.include_router(health_router, prefix="/api")
    application.include_router(projects_router, prefix="/api")
    application.include_router(files_router, prefix="/api")
    application.include_router(extraction_router, prefix="/api")
    application.include_router(tasks_router, prefix="/api")
    application.include_router(research_router, prefix="/api")
    application.include_router(reports_router, prefix="/api")
    application.include_router(boq_router, prefix="/api")
    application.include_router(calculations_router, prefix="/api")
    application.include_router(drawings_router, prefix="/api")
    application.include_router(specifications_router, prefix="/api")
    application.include_router(comparisons_router, prefix="/api")
    application.include_router(planning_router, prefix="/api")
    application.include_router(standards_router, prefix="/api")
    application.include_router(specialist_router, prefix="/api")
    application.include_router(structural_router, prefix="/api")
    application.include_router(qa_router, prefix="/api")
    application.include_router(settings_router, prefix="/api")
    application.include_router(system_router, prefix="/api")
    return application


app = create_app()
