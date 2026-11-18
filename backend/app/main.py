"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.projects import router as projects_router
from app.core.config import Settings, get_settings
from app.db.migrations import upgrade_database
from app.db.session import create_db_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings or get_settings()
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
    return application


app = create_app()
