"""Step 11 API endpoints for deterministic parametric CAD floor plan generation (DXF + true-scale PDF + schedules)."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.drawings import (
    ParametricDrawingDetailOut,
    ParametricDrawingGenerateRequest,
    ParametricDrawingListResponse,
    ParametricModelSuggestOut,
    ParametricModelSuggestRequest,
    ParametricPlanModel,
)
from app.services.parametric_drawings import (
    DrawingNotFoundError,
    DrawingValidationError,
    build_synthetic_clinic_preset,
    generate_parametric_drawing,
    get_parametric_drawing_detail,
    list_project_parametric_drawings,
    suggest_parametric_plan_model,
)
from app.services.projects import ProjectNotFoundError
from app.services.workspace import WorkspacePathError

router = APIRouter(tags=["parametric-drawings"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get(
    "/parametric-drawings/clinic-preset",
    response_model=ParametricPlanModel,
)
def get_clinic_preset_endpoint() -> ParametricPlanModel:
    """Return the built-in synthetic 5-room small clinic layout preset in millimetres (0 AI tokens)."""
    return build_synthetic_clinic_preset()


@router.post(
    "/projects/{project_id}/parametric-drawings/suggest-model",
    response_model=ParametricModelSuggestOut,
)
def suggest_parametric_model_endpoint(
    project_id: str,
    payload: ParametricModelSuggestRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ParametricModelSuggestOut:
    """Draft a candidate JSON floor plan model via the configured AI provider; always requires owner confirmation."""
    try:
        return suggest_parametric_plan_model(
            db,
            _get_secret_store(request),
            project_id,
            payload,
            client_factory=_get_client_factory(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (DrawingValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.post(
    "/projects/{project_id}/parametric-drawings",
    response_model=ParametricDrawingDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def generate_parametric_drawing_endpoint(
    project_id: str,
    payload: ParametricDrawingGenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ParametricDrawingDetailOut:
    """Compile a confirmed JSON room/wall/door/window model into DXF ($INSUNITS=4, TTF) + true-scale PDF in 05_Design_Drawings."""
    try:
        return generate_parametric_drawing(db, _get_settings(request), project_id, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (DrawingValidationError, ValueError, WorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/parametric-drawings",
    response_model=ParametricDrawingListResponse,
)
def list_project_parametric_drawings_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> ParametricDrawingListResponse:
    """List all parametric drawings generated for a project ordered newest first."""
    try:
        return list_project_parametric_drawings(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/parametric-drawings/{drawing_id}",
    response_model=ParametricDrawingDetailOut,
)
def get_parametric_drawing_detail_endpoint(
    drawing_id: str,
    db: Session = Depends(get_db),
) -> ParametricDrawingDetailOut:
    """Retrieve computed room areas, door/window/finishes schedules, round-trip audit, and 05_Design_Drawings links."""
    try:
        return get_parametric_drawing_detail(db, drawing_id)
    except DrawingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
