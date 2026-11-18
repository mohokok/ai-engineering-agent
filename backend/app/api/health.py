"""Health check endpoint for Step 01 verification."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Structured health status payload."""

    status: str
    service: str
    version: str
    environment: str
    classification: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return backend service health status."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="ai-engineering-agent",
        version=settings.app_version,
        environment=settings.app_env,
        classification="Preliminary",
    )
