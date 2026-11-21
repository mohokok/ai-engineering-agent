"""Step 10 API endpoints for Bill of Quantities (BOQ), deterministic DXF/IFC/XLSX/PDF takeoffs, checks, and exports."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.schemas.boq import (
    BoqDetailOut,
    BoqExportOut,
    BoqExportRequest,
    BoqImportExtractionsRequest,
    BoqItemCreateRequest,
    BoqItemUpdateRequest,
    BoqListResponse,
    BoqSheetCreateRequest,
    BoqSheetUpdateRequest,
)
from app.services.boq import (
    BoqNotFoundError,
    BoqValidationError,
    add_boq_item,
    create_boq_sheet,
    delete_boq_item,
    export_boq_deliverables,
    get_boq_detail,
    import_extractions_into_boq,
    list_project_boq_sheets,
    rerun_boq_checks,
    update_boq_item,
    update_boq_sheet,
)
from app.services.projects import ProjectNotFoundError
from app.services.workspace import WorkspacePathError

router = APIRouter(tags=["boq-and-quantities"])


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post(
    "/projects/{project_id}/boq-sheets",
    response_model=BoqDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def create_boq_sheet_endpoint(
    project_id: str,
    payload: BoqSheetCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Create a BOQ sheet populated deterministically from DXF/IFC/XLSX/PDF extractions."""
    try:
        return create_boq_sheet(db, _get_settings(request), project_id, payload)
    except (ProjectNotFoundError, BoqNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoqValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/boq-sheets",
    response_model=BoqListResponse,
)
def list_project_boq_sheets_endpoint(
    project_id: str,
    db: Session = Depends(get_db),
) -> BoqListResponse:
    """List all BOQ sheets belonging to a project."""
    try:
        return list_project_boq_sheets(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/boq-sheets/{boq_id}",
    response_model=BoqDetailOut,
)
def get_boq_detail_endpoint(
    boq_id: str,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Retrieve a BOQ sheet with line items, audit checks, flagged items, and exports."""
    try:
        return get_boq_detail(db, boq_id)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/boq-sheets/{boq_id}",
    response_model=BoqDetailOut,
)
def update_boq_sheet_endpoint(
    boq_id: str,
    payload: BoqSheetUpdateRequest,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Update configurable currency, title, classification, or language on a BOQ sheet."""
    try:
        return update_boq_sheet(db, boq_id, payload)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/boq-sheets/{boq_id}/import-extractions",
    response_model=BoqDetailOut,
)
def import_boq_extractions_endpoint(
    boq_id: str,
    payload: BoqImportExtractionsRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Import/merge quantities from DXF/IFC extractions or existing BOQ schedules (XLSX/PDF)."""
    try:
        return import_extractions_into_boq(db, _get_settings(request), boq_id, payload)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoqValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/boq-sheets/{boq_id}/items",
    response_model=BoqDetailOut,
    status_code=status.HTTP_201_CREATED,
)
def add_boq_item_endpoint(
    boq_id: str,
    payload: BoqItemCreateRequest,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Add a manual BOQ line item (unsourced unit rates and unconfirmed-unit pricing strictly blocked)."""
    try:
        return add_boq_item(db, boq_id, payload)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoqValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.patch(
    "/boq-sheets/{boq_id}/items/{item_id}",
    response_model=BoqDetailOut,
)
def update_boq_item_endpoint(
    boq_id: str,
    item_id: str,
    payload: BoqItemUpdateRequest,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Update a BOQ line item cleanly with strict sourced-rate enforcement and Python arithmetic totals."""
    try:
        return update_boq_item(db, boq_id, item_id, payload)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoqValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.delete(
    "/boq-sheets/{boq_id}/items/{item_id}",
    response_model=BoqDetailOut,
)
def delete_boq_item_endpoint(
    boq_id: str,
    item_id: str,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Delete a BOQ line item and rerun checks."""
    try:
        return delete_boq_item(db, boq_id, item_id)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/boq-sheets/{boq_id}/checks",
    response_model=BoqDetailOut,
)
def rerun_boq_checks_endpoint(
    boq_id: str,
    db: Session = Depends(get_db),
) -> BoqDetailOut:
    """Re-run deterministic BOQ checks (duplicates, missing items, unit consistency, arithmetic)."""
    try:
        return rerun_boq_checks(db, boq_id)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/boq-sheets/{boq_id}/export",
    response_model=BoqExportOut,
    status_code=status.HTTP_201_CREATED,
)
def export_boq_deliverables_endpoint(
    boq_id: str,
    request: Request,
    payload: BoqExportRequest | None = None,
    db: Session = Depends(get_db),
) -> BoqExportOut:
    """Export versioned XLSX (with live Excel formulas) and UTF-8 CSV files into 06_BOQ."""
    try:
        return export_boq_deliverables(db, _get_settings(request), boq_id, payload)
    except BoqNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (WorkspacePathError, BoqValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
