"""Step 11 persistence, versioning (05_Design_Drawings), synthetic clinic preset, and optional AI model drafting service."""

import json
import re
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import AuditLog, Deliverable, ParametricDrawing, Project, Task
from app.providers.base import LLMRequest, ProviderResponseError
from app.providers.secrets import SecretStore
from app.schemas.drawings import (
    ComputedRoomMetric,
    DoorScheduleRow,
    DoorSpec,
    ParametricDrawingDetailOut,
    ParametricDrawingGenerateRequest,
    ParametricDrawingListResponse,
    ParametricModelSuggestOut,
    ParametricModelSuggestRequest,
    ParametricPlanModel,
    RoomSpec,
    RoundTripCheckOut,
    WallSpec,
    WindowScheduleRow,
    WindowSpec,
)
from app.services.parametric_cad import (
    build_schedules_from_model,
    compute_room_metrics,
    generate_parametric_dxf,
    generate_true_scale_parametric_pdf,
    sha256_file,
    verify_dxf_round_trip,
)
from app.services.projects import ProjectNotFoundError
from app.services.provider_settings import execute_provider_request
from app.services.review_reports import _safe_filename_slug, _to_deliverable_out
from app.services.workspace import resolve_project_file_path


class DrawingNotFoundError(LookupError):
    """Raised when a requested parametric drawing ID does not exist."""


class DrawingValidationError(ValueError):
    """Raised when a parametric drawing request violates validation or owner-confirmation rules."""


def build_synthetic_clinic_preset() -> ParametricPlanModel:
    """Return a clean, conflict-free 5-room small clinic layout in millimetres (total area = 80.0 m2)."""
    return ParametricPlanModel(
        units="mm",
        north_angle_deg=0.0,
        rooms=[
            RoomSpec(
                room_id="R-01",
                name_ar="الاستقبال والانتظار",
                name_en="Reception & Waiting",
                x_mm=0.0,
                y_mm=0.0,
                width_mm=6000.0,
                height_mm=4000.0,
                floor_finish="Heavy-duty porcelain tile 600x600mm",
                wall_finish="Washable antibacterial acrylic paint",
                ceiling_finish="Acoustic mineral fiber suspended ceiling",
                skirting="100mm porcelain cove skirting",
            ),
            RoomSpec(
                room_id="R-02",
                name_ar="غرفة الكشف الأولى",
                name_en="Consultation Room 1",
                x_mm=6000.0,
                y_mm=0.0,
                width_mm=4000.0,
                height_mm=4000.0,
                floor_finish="Homogeneous medical vinyl sheet with welded seams",
                wall_finish="Washable antibacterial acrylic paint",
                ceiling_finish="Flush gypsum board ceiling",
                skirting="100mm coved vinyl skirting",
            ),
            RoomSpec(
                room_id="R-03",
                name_ar="الممر الطبي",
                name_en="Medical Corridor",
                x_mm=0.0,
                y_mm=4000.0,
                width_mm=10000.0,
                height_mm=1200.0,
                floor_finish="Heavy-duty slip-resistant porcelain tile",
                wall_finish="Washable antibacterial paint + corner guards",
                ceiling_finish="Flush moisture-resistant gypsum board",
                skirting="100mm porcelain skirting",
            ),
            RoomSpec(
                room_id="R-04",
                name_ar="غرفة الكشف الثانية",
                name_en="Consultation Room 2",
                x_mm=0.0,
                y_mm=5200.0,
                width_mm=5000.0,
                height_mm=2800.0,
                floor_finish="Homogeneous medical vinyl sheet with welded seams",
                wall_finish="Washable antibacterial acrylic paint",
                ceiling_finish="Flush gypsum board ceiling",
                skirting="100mm coved vinyl skirting",
            ),
            RoomSpec(
                room_id="R-05",
                name_ar="التعقيم ودورات المياه",
                name_en="Sterilization & WC",
                x_mm=5000.0,
                y_mm=5200.0,
                width_mm=5000.0,
                height_mm=2800.0,
                floor_finish="Anti-slip R11 ceramic floor tile",
                wall_finish="Full-height glazed ceramic wall tiles",
                ceiling_finish="Moisture-resistant green gypsum board",
                skirting="Integral ceramic tile base",
            ),
        ],
        walls=[
            WallSpec(wall_id="W-EXT-S", start_mm=(0.0, 0.0), end_mm=(10000.0, 0.0), thickness_mm=200.0, wall_type="exterior"),
            WallSpec(wall_id="W-EXT-E", start_mm=(10000.0, 0.0), end_mm=(10000.0, 8000.0), thickness_mm=200.0, wall_type="exterior"),
            WallSpec(wall_id="W-EXT-N", start_mm=(10000.0, 8000.0), end_mm=(0.0, 8000.0), thickness_mm=200.0, wall_type="exterior"),
            WallSpec(wall_id="W-EXT-W", start_mm=(0.0, 8000.0), end_mm=(0.0, 0.0), thickness_mm=200.0, wall_type="exterior"),
            WallSpec(wall_id="W-INT-H1", start_mm=(0.0, 4000.0), end_mm=(10000.0, 4000.0), thickness_mm=150.0, wall_type="interior"),
            WallSpec(wall_id="W-INT-H2", start_mm=(0.0, 5200.0), end_mm=(10000.0, 5200.0), thickness_mm=150.0, wall_type="interior"),
            WallSpec(wall_id="W-INT-V1", start_mm=(6000.0, 0.0), end_mm=(6000.0, 4000.0), thickness_mm=150.0, wall_type="interior"),
            WallSpec(wall_id="W-INT-V2", start_mm=(5000.0, 5200.0), end_mm=(5000.0, 8000.0), thickness_mm=150.0, wall_type="interior"),
        ],
        doors=[
            DoorSpec(
                door_id="DR-01",
                mark="D1",
                position_mm=(3000.0, 0.0),
                width_mm=1200.0,
                height_mm=2200.0,
                angle_deg=0.0,
                swing="right",
                swing_side="in",
                material="Tempered Double Glass Aluminum Frame",
                fire_rating="30 min",
                hardware="Heavy-duty pull handle + floor spring",
                room_ref="R-01",
            ),
            DoorSpec(
                door_id="DR-02",
                mark="D2",
                position_mm=(2000.0, 4000.0),
                width_mm=900.0,
                height_mm=2100.0,
                angle_deg=0.0,
                swing="left",
                swing_side="in",
                material="HPL Solid Core Flush Timber",
                fire_rating="30 min",
                hardware="Stainless lever set + overhead closer",
                room_ref="R-03",
            ),
            DoorSpec(
                door_id="DR-03",
                mark="D2",
                position_mm=(8000.0, 4000.0),
                width_mm=900.0,
                height_mm=2100.0,
                angle_deg=0.0,
                swing="right",
                swing_side="out",
                material="HPL Solid Core Flush Timber",
                fire_rating="30 min",
                hardware="Stainless lever set + overhead closer",
                room_ref="R-02",
            ),
            DoorSpec(
                door_id="DR-04",
                mark="D2",
                position_mm=(2500.0, 5200.0),
                width_mm=900.0,
                height_mm=2100.0,
                angle_deg=0.0,
                swing="left",
                swing_side="in",
                material="HPL Solid Core Flush Timber",
                fire_rating="30 min",
                hardware="Stainless lever set + overhead closer",
                room_ref="R-04",
            ),
            DoorSpec(
                door_id="DR-05",
                mark="D3",
                position_mm=(7500.0, 5200.0),
                width_mm=800.0,
                height_mm=2100.0,
                angle_deg=0.0,
                swing="right",
                swing_side="in",
                material="Moisture-resistant Compact Laminate (HPL)",
                fire_rating="Non-rated",
                hardware="Privacy thumbturn lock + stainless lever",
                room_ref="R-05",
            ),
        ],
        windows=[
            WindowSpec(
                window_id="WN-01",
                mark="W1",
                position_mm=(8000.0, 0.0),
                width_mm=1800.0,
                height_mm=1200.0,
                sill_mm=900.0,
                angle_deg=0.0,
                glazing="Double-glazed Low-E thermally broken aluminum",
                room_ref="R-02",
            ),
            WindowSpec(
                window_id="WN-02",
                mark="W1",
                position_mm=(2500.0, 8000.0),
                width_mm=1800.0,
                height_mm=1200.0,
                sill_mm=900.0,
                angle_deg=180.0,
                glazing="Double-glazed Low-E thermally broken aluminum",
                room_ref="R-04",
            ),
            WindowSpec(
                window_id="WN-03",
                mark="W2",
                position_mm=(7500.0, 8000.0),
                width_mm=800.0,
                height_mm=600.0,
                sill_mm=1600.0,
                angle_deg=180.0,
                glazing="Frosted double-glazed top-hung aluminum",
                room_ref="R-05",
            ),
            WindowSpec(
                window_id="WN-04",
                mark="W1",
                position_mm=(0.0, 2000.0),
                width_mm=1800.0,
                height_mm=1200.0,
                sill_mm=900.0,
                angle_deg=270.0,
                glazing="Double-glazed Low-E thermally broken aluminum",
                room_ref="R-01",
            ),
        ],
    )


def _strip_json_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _to_drawing_detail_out(row: ParametricDrawing) -> ParametricDrawingDetailOut:
    project = row.project
    metrics = row.computed_metrics_json if isinstance(row.computed_metrics_json, dict) else {}
    rooms = [ComputedRoomMetric.model_validate(item) for item in (metrics.get("rooms") or [])]
    doors = [DoorScheduleRow.model_validate(item) for item in (metrics.get("door_schedule") or [])]
    windows = [WindowScheduleRow.model_validate(item) for item in (metrics.get("window_schedule") or [])]
    rt_raw = metrics.get("round_trip_check") or {}
    rt_check = RoundTripCheckOut.model_validate(rt_raw)
    total_area_m2 = round(float(metrics.get("total_area_m2") or sum(r.area_m2 for r in rooms)), 4)

    deliverables_sorted = sorted(
        list(row.deliverables or []),
        key=lambda d: (d.format or "", d.filename or "", d.id),
    )
    return ParametricDrawingDetailOut(
        id=row.id,
        project_id=row.project_id,
        project_code=project.code if project else "",
        project_name=project.name if project else "",
        task_id=row.task_id,
        drawing_no=row.drawing_no,
        title=row.title,
        scale_denominator=row.scale_denominator,
        scale_label=f"1:{row.scale_denominator}",
        paper_size=row.paper_size,
        units=row.units,
        classification=row.classification,
        revision=row.revision,
        version=row.version,
        status=row.status,
        notes=row.notes,
        round_trip_passed=row.round_trip_passed,
        ai_suggested=row.ai_suggested,
        plan_model=ParametricPlanModel.model_validate(row.model_json),
        rooms_computed=rooms,
        total_area_m2=total_area_m2,
        door_schedule=doors,
        window_schedule=windows,
        round_trip_check=rt_check,
        deliverables=[_to_deliverable_out(d) for d in deliverables_sorted],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def generate_parametric_drawing(
    db: Session,
    settings: Settings,
    project_id: str,
    payload: ParametricDrawingGenerateRequest,
) -> ParametricDrawingDetailOut:
    """Compile a JSON room/wall/door/window model deterministically (0 AI tokens) into DXF + PDF + schedules in 05_Design_Drawings."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    if payload.ai_suggested and not payload.owner_confirmed_model:
        raise DrawingValidationError(
            "AI-suggested drawing model must be explicitly confirmed by the owner (owner_confirmed_model=true) before DXF/PDF generation."
        )

    if payload.task_id:
        task_row = db.get(Task, payload.task_id)
        if task_row is None or task_row.project_id != project_id:
            raise DrawingValidationError(f"Task '{payload.task_id}' does not belong to project '{project_id}'.")

    # Always compute room areas & perimeters strictly in code from coordinates, never user/AI text.
    computed_rooms = compute_room_metrics(payload.plan_model.rooms)
    total_area_m2 = round(sum(r.area_m2 for r in computed_rooms), 4)
    door_schedule, window_schedule = build_schedules_from_model(payload.plan_model)

    max_ver = db.scalar(
        select(func.max(ParametricDrawing.version)).where(ParametricDrawing.project_id == project_id)
    )
    next_version = int(max_ver or 0) + 1
    revision = f"Rev {next_version:02d}"
    drawing_id = new_uuid()
    short_id = drawing_id.replace("-", "")[:8]
    draw_slug = _safe_filename_slug(payload.drawing_no or payload.title, default="plan", max_len=28)

    rel_dxf = f"05_Design_Drawings/{draw_slug}_{short_id}_v{next_version}.dxf"
    rel_pdf = f"05_Design_Drawings/{draw_slug}_{short_id}_v{next_version}.pdf"
    path_dxf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_dxf)
    path_pdf = resolve_project_file_path(settings.workspaces_dir, project.workspace_slug, rel_pdf)

    for target in (path_dxf, path_pdf):
        if target.exists():
            raise FileExistsError(f"Drawing version path already exists (refusing overwrite): {target.name}")

    generate_parametric_dxf(
        path_dxf,
        model=payload.plan_model,
        rooms=computed_rooms,
        door_schedule=door_schedule,
        window_schedule=window_schedule,
        drawing_no=payload.drawing_no,
        title=payload.title,
        scale_denominator=payload.scale_denominator,
        paper_size=payload.paper_size,
        classification=payload.classification,
        revision=revision,
        notes=payload.notes,
    )
    generate_true_scale_parametric_pdf(
        path_pdf,
        model=payload.plan_model,
        rooms=computed_rooms,
        door_schedule=door_schedule,
        window_schedule=window_schedule,
        drawing_no=payload.drawing_no,
        title=payload.title,
        project_code=project.code,
        project_name=project.name,
        scale_denominator=payload.scale_denominator,
        paper_size=payload.paper_size,
        classification=payload.classification,
        revision=revision,
        notes=payload.notes,
    )

    round_trip = verify_dxf_round_trip(
        path_dxf,
        rooms=computed_rooms,
        door_count=len(payload.plan_model.doors),
        window_count=len(payload.plan_model.windows),
    )

    metrics_payload = {
        "rooms": [r.model_dump() for r in computed_rooms],
        "total_area_m2": total_area_m2,
        "door_schedule": [d.model_dump() for d in door_schedule],
        "window_schedule": [w.model_dump() for w in window_schedule],
        "round_trip_check": round_trip.model_dump(),
    }

    drawing_row = ParametricDrawing(
        id=drawing_id,
        project_id=project.id,
        task_id=payload.task_id,
        drawing_no=payload.drawing_no,
        title=payload.title,
        scale_denominator=payload.scale_denominator,
        paper_size=payload.paper_size,
        units=payload.plan_model.units,
        classification=payload.classification,
        revision=revision,
        version=next_version,
        status="verified" if round_trip.passed else "generated_with_warnings",
        notes=payload.notes,
        model_json=payload.plan_model.model_dump(),
        computed_metrics_json=metrics_payload,
        round_trip_passed=round_trip.passed,
        ai_suggested=payload.ai_suggested,
        token_usage_json={"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    )
    db.add(drawing_row)
    db.flush()

    summary_note = (
        f"Parametric drawing {payload.drawing_no} (1:{payload.scale_denominator} on {payload.paper_size}, {revision}), "
        f"{len(computed_rooms)} room(s) totaling {total_area_m2:.2f} m2, {len(payload.plan_model.doors)} door(s), "
        f"{len(payload.plan_model.windows)} window(s). Round-trip check: {'PASS' if round_trip.passed else 'WARNING'}."
    )

    specs = [
        ("05_Design_Drawings", "parametric_drawing_dxf", "dxf", "application/dxf", rel_dxf, path_dxf),
        ("05_Design_Drawings", "parametric_drawing_pdf", "pdf", "application/pdf", rel_pdf, path_pdf),
    ]
    for folder_name, deliv_type, fmt, mime, rel_path, disk_path in specs:
        db.add(
            Deliverable(
                project_id=project.id,
                task_id=payload.task_id,
                drawing_id=drawing_row.id,
                title=f"{payload.drawing_no} {payload.title} ({revision} — {fmt.upper()})",
                deliverable_type=deliv_type,
                discipline="architecture",
                format=fmt,
                classification=payload.classification,
                status="issued" if round_trip.passed else "draft",
                version=next_version,
                folder_name=folder_name,
                filename=disk_path.name,
                relative_path=rel_path,
                mime_type=mime,
                size_bytes=disk_path.stat().st_size,
                sha256=sha256_file(disk_path),
                summary=summary_note,
            )
        )

    db.add(
        AuditLog(
            project_id=project.id,
            action="parametric_drawing.generated",
            entity_type="parametric_drawing",
            entity_id=drawing_row.id,
            actor="owner",
            details_json={
                "drawing_no": payload.drawing_no,
                "version": next_version,
                "revision": revision,
                "scale_denominator": payload.scale_denominator,
                "paper_size": payload.paper_size,
                "total_area_m2": total_area_m2,
                "round_trip_passed": round_trip.passed,
                "ai_suggested": payload.ai_suggested,
                "tokens_used": 0,
            },
        )
    )
    db.commit()

    loaded = db.scalar(
        select(ParametricDrawing)
        .options(selectinload(ParametricDrawing.project), selectinload(ParametricDrawing.deliverables))
        .where(ParametricDrawing.id == drawing_row.id)
    )
    assert loaded is not None
    return _to_drawing_detail_out(loaded)


def list_project_parametric_drawings(
    db: Session,
    project_id: str,
) -> ParametricDrawingListResponse:
    """List parametric drawings belonging to a project ordered newest first."""
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")
    rows = db.scalars(
        select(ParametricDrawing)
        .options(selectinload(ParametricDrawing.project), selectinload(ParametricDrawing.deliverables))
        .where(ParametricDrawing.project_id == project_id)
        .order_by(ParametricDrawing.version.desc(), ParametricDrawing.created_at.desc())
    ).all()
    return ParametricDrawingListResponse(
        drawings=[_to_drawing_detail_out(r) for r in rows],
        total=len(rows),
        classification=project.classification,
    )


def get_parametric_drawing_detail(db: Session, drawing_id: str) -> ParametricDrawingDetailOut:
    """Retrieve a single parametric drawing with computed room metrics, schedules, and round-trip audit."""
    row = db.scalar(
        select(ParametricDrawing)
        .options(selectinload(ParametricDrawing.project), selectinload(ParametricDrawing.deliverables))
        .where(ParametricDrawing.id == drawing_id)
    )
    if row is None:
        raise DrawingNotFoundError(f"Parametric drawing '{drawing_id}' was not found.")
    return _to_drawing_detail_out(row)


def suggest_parametric_plan_model(
    db: Session,
    secret_store: SecretStore,
    project_id: str,
    payload: ParametricModelSuggestRequest,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> ParametricModelSuggestOut:
    """Ask the configured AI provider to draft an unconfirmed JSON room/wall/door/window model in millimetres.

    Any area numbers emitted by the AI are stripped by Pydantic (`extra="ignore"`) because deterministic
    code computes all areas strictly from coordinates upon owner confirmation.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError(f"Project '{project_id}' was not found.")

    system_prompt = (
        "You are an architectural CAD model assistant. Output ONLY valid JSON matching ParametricPlanModel "
        "with coordinates in millimetres (units='mm'). Include rooms (room_id, name_ar, name_en, x_mm, y_mm, "
        "width_mm, height_mm), walls (wall_id, start_mm, end_mm, thickness_mm, wall_type), doors, and windows. "
        "Do NOT write explanations or markdown outside JSON."
    )
    user_prompt = (
        f"Project: [{project.code}] {project.name} ({project.classification}).\n"
        f"Architectural brief: {payload.brief}\n"
        "Return a compact, valid ParametricPlanModel JSON object in millimetres."
    )
    llm_resp = execute_provider_request(
        db,
        secret_store,
        LLMRequest(
            prompt=user_prompt,
            system_instruction=system_prompt,
            complexity=payload.complexity,
            response_schema=ParametricPlanModel,
            temperature=0.1,
        ),
        client_factory=client_factory,
        project_id=project_id,
    )

    candidate_data: Any = llm_resp.parsed_json
    if candidate_data is None:
        cleaned = _strip_json_fences(llm_resp.text)
        try:
            candidate_data = json.loads(cleaned)
        except Exception as exc:
            raise ProviderResponseError(f"AI model suggestion did not return valid JSON: {exc}") from exc

    validated_model = ParametricPlanModel.model_validate(candidate_data)
    # Smoke-check coordinate computability before handing draft to owner review.
    compute_room_metrics(validated_model.rooms)

    tokens_used = int(llm_resp.usage.total_tokens or 0)
    db.add(
        AuditLog(
            project_id=project.id,
            action="parametric_drawing.model_suggested",
            entity_type="parametric_drawing",
            entity_id=project.id,
            actor="ai_provider",
            details_json={
                "model": llm_resp.model,
                "tokens_used": tokens_used,
                "rooms_count": len(validated_model.rooms),
                "requires_owner_confirmation": True,
            },
        )
    )
    db.commit()

    return ParametricModelSuggestOut(
        requires_owner_confirmation=True,
        message=(
            "Candidate floor plan model drafted by AI in millimetres. Any AI-supplied area text was stripped; "
            "review dimensions and confirm before DXF/PDF generation."
        ),
        plan_model=validated_model,
        tokens_used=tokens_used,
    )
