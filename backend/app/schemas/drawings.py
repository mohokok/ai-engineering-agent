"""Pydantic schemas for Step 11 parametric floor plan drawing model, schedules, and round-trip audit."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.projects import ProjectClassification
from app.schemas.reports import DeliverableOut

PaperSizeChoice = Literal["A3", "A4", "A2", "A1"]


class RoomSpec(BaseModel):
    """Parametric room definition in millimetres (any user/AI-supplied area field is ignored and computed strictly in code)."""

    model_config = ConfigDict(extra="ignore")

    room_id: str = Field(..., min_length=1, max_length=32)
    name_ar: str = Field(..., min_length=1, max_length=128)
    name_en: str = Field(..., min_length=1, max_length=128)
    x_mm: float | None = None
    y_mm: float | None = None
    width_mm: float | None = Field(default=None, gt=0)
    height_mm: float | None = Field(default=None, gt=0)
    polygon_mm: list[tuple[float, float]] | None = None
    floor_finish: str = Field(default="Porcelain non-slip tile 600x600mm", max_length=255)
    wall_finish: str = Field(default="Washable antibacterial acrylic paint", max_length=255)
    ceiling_finish: str = Field(default="Moisture-resistant gypsum board ceiling", max_length=255)
    skirting: str = Field(default="100mm matching porcelain skirting", max_length=255)

    @model_validator(mode="after")
    def validate_geometry(self) -> "RoomSpec":
        if self.polygon_mm is not None:
            if len(self.polygon_mm) < 3:
                raise ValueError(f"Room '{self.room_id}' polygon_mm must contain at least 3 vertices.")
        else:
            if (
                self.x_mm is None
                or self.y_mm is None
                or self.width_mm is None
                or self.height_mm is None
            ):
                raise ValueError(
                    f"Room '{self.room_id}' must supply either (x_mm, y_mm, width_mm, height_mm) or polygon_mm."
                )
        return self


class WallSpec(BaseModel):
    """Wall center/segment geometry in millimetres."""

    model_config = ConfigDict(extra="ignore")

    wall_id: str = Field(..., min_length=1, max_length=32)
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]
    thickness_mm: float = Field(default=200.0, gt=0, le=2000.0)
    wall_type: Literal["exterior", "interior"] = "exterior"

    @model_validator(mode="after")
    def validate_non_zero_length(self) -> "WallSpec":
        dx = self.end_mm[0] - self.start_mm[0]
        dy = self.end_mm[1] - self.start_mm[1]
        if (dx * dx + dy * dy) <= 1e-3:
            raise ValueError(f"Wall '{self.wall_id}' must have non-zero length in millimetres.")
        return self


class DoorSpec(BaseModel):
    """Door opening symbol metadata placed onto plan in millimetres."""

    model_config = ConfigDict(extra="ignore")

    door_id: str = Field(..., min_length=1, max_length=32)
    mark: str = Field(default="D1", min_length=1, max_length=32)
    position_mm: tuple[float, float]
    width_mm: float = Field(..., gt=0, le=10000.0)
    height_mm: float = Field(default=2100.0, gt=0, le=5000.0)
    angle_deg: float = Field(default=0.0)
    swing: Literal["left", "right"] = "left"
    swing_side: Literal["in", "out"] = "in"
    material: str = Field(default="HPL Solid Core Flush Timber", max_length=255)
    fire_rating: str = Field(default="Non-rated", max_length=64)
    hardware: str = Field(default="Stainless steel lever + hydraulic closer", max_length=255)
    room_ref: str = Field(default="", max_length=64)


class WindowSpec(BaseModel):
    """Window opening symbol metadata placed onto plan in millimetres."""

    model_config = ConfigDict(extra="ignore")

    window_id: str = Field(..., min_length=1, max_length=32)
    mark: str = Field(default="W1", min_length=1, max_length=32)
    position_mm: tuple[float, float]
    width_mm: float = Field(..., gt=0, le=20000.0)
    height_mm: float = Field(default=1200.0, gt=0, le=5000.0)
    sill_mm: float = Field(default=900.0, ge=0, le=3000.0)
    angle_deg: float = Field(default=0.0)
    glazing: str = Field(default="Double-glazed thermally broken aluminum", max_length=255)
    room_ref: str = Field(default="", max_length=64)


class ParametricPlanModel(BaseModel):
    """Canonical parametric floor plan model strictly expressed in millimetres ($INSUNITS=4)."""

    model_config = ConfigDict(extra="ignore")

    units: Literal["mm"] = "mm"
    north_angle_deg: float = Field(default=0.0, ge=-360.0, le=360.0)
    rooms: list[RoomSpec] = Field(..., min_length=1, max_length=100)
    walls: list[WallSpec] = Field(..., min_length=1, max_length=300)
    doors: list[DoorSpec] = Field(default_factory=list, max_length=200)
    windows: list[WindowSpec] = Field(default_factory=list, max_length=200)


class ComputedRoomMetric(BaseModel):
    """Code-computed room geometry & finishes metrics (never user-typed or AI-generated)."""

    room_id: str
    name_ar: str
    name_en: str
    polygon_mm: list[tuple[float, float]]
    area_mm2: float
    area_m2: float
    perimeter_mm: float
    perimeter_m: float
    centroid_mm: tuple[float, float]
    floor_finish: str
    wall_finish: str
    ceiling_finish: str
    skirting: str


class DoorScheduleRow(BaseModel):
    """Aggregated door schedule row derived from ParametricPlanModel.doors."""

    mark: str
    width_mm: float
    height_mm: float
    swing: str
    material: str
    fire_rating: str
    hardware: str
    count: int
    door_ids: list[str] = Field(default_factory=list)
    room_refs: list[str] = Field(default_factory=list)


class WindowScheduleRow(BaseModel):
    """Aggregated window schedule row derived from ParametricPlanModel.windows."""

    mark: str
    width_mm: float
    height_mm: float
    sill_mm: float
    glazing: str
    count: int
    window_ids: list[str] = Field(default_factory=list)
    room_refs: list[str] = Field(default_factory=list)


class RoundTripCheckOut(BaseModel):
    """Step 07 DXF re-read verification confirming $INSUNITS=4 (mm), TrueType Arabic fonts, room areas, and block counts."""

    passed: bool
    insunits_code: int
    units: str
    units_doubtful: bool
    ttf_font_styles: list[str] = Field(default_factory=list)
    uses_shx_font: bool = False
    expected_room_count: int
    extracted_area_contour_count: int
    expected_total_area_m2: float
    extracted_total_area_m2: float
    area_diff_m2: float
    expected_doors_count: int
    extracted_doors_count: int
    expected_windows_count: int
    extracted_windows_count: int
    mismatches: list[str] = Field(default_factory=list)


class ParametricDrawingGenerateRequest(BaseModel):
    """Request payload to compile a parametric JSON floor plan into DXF + true-scale PDF + schedules."""

    task_id: str | None = Field(default=None, max_length=64)
    drawing_no: str = Field(default="A-101", min_length=1, max_length=64)
    title: str = Field(default="مخطط الدور الأرضي لعيادة طبية / Clinic Ground Floor Plan", min_length=1, max_length=255)
    scale_denominator: int = Field(default=100, ge=10, le=500)
    paper_size: PaperSizeChoice = "A3"
    classification: ProjectClassification = "Preliminary"
    notes: str | None = Field(
        default="All dimensions in millimetres (mm). Do not scale directly from unverified prints; verify structural grids on site.",
        max_length=1500,
    )
    ai_suggested: bool = False
    owner_confirmed_model: bool = True
    plan_model: ParametricPlanModel


class ParametricModelSuggestRequest(BaseModel):
    """Optional natural-language brief for Gemini to draft a candidate JSON plan requiring owner confirmation."""

    brief: str = Field(..., min_length=3, max_length=1500)
    complexity: Literal["fast", "deep"] = "fast"


class ParametricModelSuggestOut(BaseModel):
    """Unconfirmed AI-drafted JSON plan model (requires explicit owner review & confirmation before drawing)."""

    requires_owner_confirmation: bool = True
    message: str
    plan_model: ParametricPlanModel
    tokens_used: int = 0


class ParametricDrawingDetailOut(BaseModel):
    """Complete persisted parametric drawing package with computed rooms, schedules, round-trip check, and 05_Design_Drawings files."""

    id: str
    project_id: str
    project_code: str
    project_name: str
    task_id: str | None = None
    drawing_no: str
    title: str
    scale_denominator: int
    scale_label: str
    paper_size: str
    units: str
    classification: ProjectClassification | str
    revision: str
    version: int
    status: str
    notes: str | None = None
    round_trip_passed: bool
    ai_suggested: bool
    plan_model: ParametricPlanModel
    rooms_computed: list[ComputedRoomMetric] = Field(default_factory=list)
    total_area_m2: float = 0.0
    door_schedule: list[DoorScheduleRow] = Field(default_factory=list)
    window_schedule: list[WindowScheduleRow] = Field(default_factory=list)
    round_trip_check: RoundTripCheckOut
    deliverables: list[DeliverableOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ParametricDrawingListResponse(BaseModel):
    """Project list of generated parametric drawings ordered newest first."""

    drawings: list[ParametricDrawingDetailOut] = Field(default_factory=list)
    total: int
    classification: ProjectClassification | str
