"""Provider settings, credential management, and connection test endpoints."""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers.base import (
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderQuotaError,
    ProviderUsageLimitError,
)
from app.providers.secrets import SecretStore
from app.schemas.settings import (
    ApiKeySaveRequest,
    ConnectionTestOut,
    ConnectionTestRequest,
    ProviderSettingsOut,
    ProviderSettingsUpdate,
)
from app.services.provider_settings import (
    delete_provider_api_key,
    get_provider_settings,
    save_provider_api_key,
    test_provider_connection,
    update_provider_settings,
)

router = APIRouter(prefix="/settings/provider", tags=["settings"])


def _get_secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


def _get_client_factory(request: Request) -> Callable[[str], Any] | None:
    return getattr(request.app.state, "provider_client_factory", None)


@router.get("", response_model=ProviderSettingsOut)
def get_provider_settings_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> ProviderSettingsOut:
    """Return non-secret AI provider settings and boolean API key status."""
    return get_provider_settings(db, _get_secret_store(request))


@router.put("", response_model=ProviderSettingsOut)
def update_provider_settings_endpoint(
    payload: ProviderSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> ProviderSettingsOut:
    """Update non-secret provider preferences, complexity models, and usage limits."""
    try:
        return update_provider_settings(db, _get_secret_store(request), payload)
    except ProviderConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/api-key", response_model=ProviderSettingsOut)
def save_api_key_endpoint(
    payload: ApiKeySaveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ProviderSettingsOut:
    """Store provider API key securely in Windows Credential Manager (never returned)."""
    try:
        return save_provider_api_key(db, _get_secret_store(request), payload.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.delete("/api-key", response_model=ProviderSettingsOut)
def delete_api_key_endpoint(
    request: Request,
    db: Session = Depends(get_db),
) -> ProviderSettingsOut:
    """Remove stored provider API key from OS credential store."""
    try:
        return delete_provider_api_key(db, _get_secret_store(request))
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.post("/test", response_model=ConnectionTestOut)
def test_provider_connection_endpoint(
    request: Request,
    payload: ConnectionTestRequest | None = None,
    db: Session = Depends(get_db),
) -> ConnectionTestOut:
    """Verify configured provider credentials and model reachability."""
    body = payload or ConnectionTestRequest()
    try:
        return test_provider_connection(
            db,
            _get_secret_store(request),
            complexity=body.complexity,
            model_override=body.model_override,
            client_factory=_get_client_factory(request),
        )
    except ProviderAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except (ProviderQuotaError, ProviderUsageLimitError) as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except ProviderConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
