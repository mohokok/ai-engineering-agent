"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import re
from typing import Any, Callable

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.api.settings import router as settings_router
from app.core.config import Settings, get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory
from app.providers.secrets import KeyringSecretStore, SecretStore

_PROJECT_FILES_UPLOAD_PATH_RE = re.compile(r"^/api/projects/[^/]+/files/?$")


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
            and _PROJECT_FILES_UPLOAD_PATH_RE.match(scope.get("path", ""))
        ):
            for header_name, header_value in scope.get("headers", ()):
                if header_name.lower() == b"content-length":
                    try:
                        content_length = int(header_value.decode("ascii").strip())
                    except (UnicodeDecodeError, ValueError):
                        break
                    if content_length > self.max_request_bytes:
                        response = JSONResponse(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            content={
                                "detail": (
                                    f"Request Content-Length ({content_length} bytes) exceeds "
                                    f"maximum upload batch size ({self.max_request_bytes} bytes)."
                                )
                            },
                        )
                        await response(scope, receive, send)
                        return
                    break
        await self.app_asgi(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    *,
    secret_store: SecretStore | None = None,
    provider_client_factory: Callable[[str], Any] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings or get_settings()
    resolved_secret_store = secret_store or KeyringSecretStore()
    engine = create_db_engine(resolved_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
        upgrade_database(application.state.settings.database_url)
        try:
            yield
        finally:
            application.state.engine.dispose()

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

    application.add_middleware(
        UploadSizeLimitMiddleware,
        max_request_bytes=resolved_settings.max_files_per_upload * resolved_settings.max_upload_size_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router, prefix="/api")
    application.include_router(projects_router, prefix="/api")
    application.include_router(files_router, prefix="/api")
    application.include_router(settings_router, prefix="/api")
    return application


app = create_app()
