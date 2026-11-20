"""Step 08 controlled internet research endpoints, source provenance queries, and optional keyring key config."""

from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.settings import _raise_provider_http_error
from app.core.config import Settings
from app.db.models import AuditLog
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.secrets import SecretStore
from app.schemas.research import (
    OptionalSearchKeyProvider,
    ResearchCapabilitiesOut,
    ResearchHistoryListResponse,
    ResearchRunDetailOut,
    ResearchRunRequest,
    ResearchSourceListResponse,
    SearchProviderKeySaveRequest,
)
from app.services.projects import ProjectNotFoundError
from app.services.research import (
    execute_research_query,
    get_research_capabilities,
    get_research_run_detail,
    list_research_runs,
    list_research_sources,
)
from app.services.research_fetch import search_key_account_name
from app.services.workspace import WorkspacePathError

router = APIRouter(prefix="/research", tags=["research"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


def _get_http_transport(request: Request) -> httpx.BaseTransport | None:
    return getattr(request.app.state, "research_http_transport", None)


@router.get("/capabilities", response_model=ResearchCapabilitiesOut)
def get_research_capabilities_endpoint(request: Request) -> ResearchCapabilitiesOut:
    """Return available search backends, keyring status, and reliability priority order."""
    return get_research_capabilities(_get_secret_store(request))


@router.put("/providers/{provider_id}/api-key", response_model=ResearchCapabilitiesOut)
def save_search_provider_key_endpoint(
    provider_id: OptionalSearchKeyProvider,
    payload: SearchProviderKeySaveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ResearchCapabilitiesOut:
    """Store an optional paid search API key strictly in OS keyring (never returned or logged)."""
    store = _get_secret_store(request)
    try:
        store.set_api_key(search_key_account_name(provider_id), payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    db.add(
        AuditLog(
            project_id=None,
            action="research.search_key_saved",
            entity_type="search_provider",
            entity_id=provider_id,
            actor="owner",
            details_json={"provider": provider_id, "backend": store.backend_name},
        )
    )
    db.commit()
    return get_research_capabilities(store)


@router.delete("/providers/{provider_id}/api-key", response_model=ResearchCapabilitiesOut)
def delete_search_provider_key_endpoint(
    provider_id: OptionalSearchKeyProvider,
    request: Request,
    db: Session = Depends(get_db),
) -> ResearchCapabilitiesOut:
    """Remove an optional search API key from OS keyring."""
    store = _get_secret_store(request)
    try:
        store.delete_api_key(search_key_account_name(provider_id))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    db.add(
        AuditLog(
            project_id=None,
            action="research.search_key_deleted",
            entity_type="search_provider",
            entity_id=provider_id,
            actor="owner",
            details_json={"provider": provider_id, "backend": store.backend_name},
        )
    )
    db.commit()
    return get_research_capabilities(store)


@router.post("/runs", response_model=ResearchRunDetailOut, status_code=status.HTTP_201_CREATED)
def run_research_endpoint(
    payload: ResearchRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ResearchRunDetailOut:
    """Execute controlled web search + direct page/PDF fetch and persist full source log."""
    try:
        return execute_research_query(
            db,
            _get_settings(request),
            _get_secret_store(request),
            payload,
            client_factory=_get_client_factory(request),
            http_transport=_get_http_transport(request),
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, WorkspacePathError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderError as exc:
        _raise_provider_http_error(exc)


@router.get("/runs", response_model=ResearchHistoryListResponse)
def list_research_runs_endpoint(
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> ResearchHistoryListResponse:
    """List persisted internet research runs ordered newest first."""
    runs = list_research_runs(db, project_id=project_id, status_filter=status_filter)
    return ResearchHistoryListResponse(runs=runs, total=len(runs))


@router.get("/runs/{run_id}", response_model=ResearchRunDetailOut)
def get_research_run_detail_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
) -> ResearchRunDetailOut:
    """Fetch complete details for one research run including every source citation."""
    try:
        return get_research_run_detail(db, run_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/sources", response_model=ResearchSourceListResponse)
def list_research_sources_endpoint(
    project_id: str | None = Query(default=None),
    reviewed_only: bool | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ResearchSourceListResponse:
    """List persisted research sources across runs ordered by priority rank and recency."""
    sources = list_research_sources(
        db, project_id=project_id, reviewed_only=reviewed_only
    )
    return ResearchSourceListResponse(sources=sources, total=len(sources))
