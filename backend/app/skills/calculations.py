"""Step 13 pure deterministic engineering calculation library (0 AI tokens): electrical & plumbing basics."""

from dataclasses import dataclass, field
import math
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.calculations import CalculationDiscipline, CalculationType

# Standard metric conductor sizes (mm^2)
STANDARD_CABLE_SIZES_MM2: tuple[float, ...] = (
    1.5,
    2.5,
    4.0,
    6.0,
    10.0,
    16.0,
    25.0,
    35.0,
    50.0,
    70.0,
    95.0,
    120.0,
    150.0,
    185.0,
    240.0,
)

# Standard molded-case / miniature circuit breaker frame ratings (A)
STANDARD_BREAKER_RATINGS_A: tuple[float, ...] = (
    6.0,
    10.0,
    16.0,
    20.0,
    25.0,
    32.0,
    40.0,
    50.0,
    63.0,
    80.0,
    100.0,
    125.0,
    160.0,
    200.0,
    250.0,
    315.0,
    400.0,
    500.0,
    630.0,
)

# Conservative preliminary baseline reference ampacities at 30C ambient (must verify against manufacturer datasheet & locally adopted code)
_BASELINE_AMPACITY_A: dict[tuple[str, str], dict[float, float]] = {
    ("copper", "XLPE_90C"): {
        1.5: 23.0,
        2.5: 31.0,
        4.0: 42.0,
        6.0: 54.0,
        10.0: 75.0,
        16.0: 100.0,
        25.0: 133.0,
        35.0: 164.0,
        50.0: 198.0,
        70.0: 253.0,
        95.0: 306.0,
        120.0: 354.0,
        150.0: 407.0,
        185.0: 464.0,
        240.0: 546.0,
    },
    ("copper", "PVC_70C"): {
        1.5: 17.5,
        2.5: 24.0,
        4.0: 32.0,
        6.0: 41.0,
        10.0: 57.0,
        16.0: 76.0,
        25.0: 101.0,
        35.0: 125.0,
        50.0: 151.0,
        70.0: 192.0,
        95.0: 232.0,
        120.0: 269.0,
        150.0: 309.0,
        185.0: 353.0,
        240.0: 415.0,
    },
    ("aluminum", "XLPE_90C"): {
        16.0: 77.0,
        25.0: 103.0,
        35.0: 127.0,
        50.0: 154.0,
        70.0: 196.0,
        95.0: 238.0,
        120.0: 276.0,
        150.0: 317.0,
        185.0: 362.0,
        240.0: 426.0,
    },
    ("aluminum", "PVC_70C"): {
        16.0: 59.0,
        25.0: 78.0,
        35.0: 96.0,
        50.0: 117.0,
        70.0: 149.0,
        95.0: 180.0,
        120.0: 208.0,
        150.0: 240.0,
        185.0: 274.0,
        240.0: 322.0,
    },
}

# Physical conductor constants: rho at 20C (ohm*mm^2/m) & temperature coefficient alpha (/degC)
_CONDUCTOR_PHYSICS: dict[str, tuple[float, float]] = {
    "copper": (0.017241, 0.00393),
    "aluminum": (0.028264, 0.00403),
}

# Preliminary Hunter's curve fixture unit baseline weights (verify against locally adopted plumbing code)
DEFAULT_WSFU_WEIGHTS: dict[str, float] = {
    "wc_flush_tank": 2.5,
    "wc_flush_valve": 6.0,
    "urinal_flush_valve": 4.0,
    "lavatory": 1.0,
    "kitchen_sink": 1.5,
    "service_sink": 2.5,
    "shower": 2.0,
    "hose_bibb": 2.5,
    "drinking_fountain": 0.5,
}

# Piecewise-linear Hunter's curve (WSFU -> US GPM) for flush-tank & flush-valve buildings
_HUNTER_CURVE_GPM: dict[str, tuple[tuple[float, float], ...]] = {
    "hunter_flush_tank": (
        (0.0, 0.0),
        (1.0, 3.0),
        (5.0, 7.0),
        (10.0, 11.5),
        (15.0, 14.5),
        (20.0, 17.0),
        (30.0, 21.5),
        (40.0, 25.0),
        (50.0, 28.5),
        (75.0, 36.5),
        (100.0, 43.5),
        (150.0, 55.0),
        (200.0, 65.0),
        (300.0, 84.0),
        (500.0, 118.0),
        (1000.0, 200.0),
    ),
    "hunter_flush_valve": (
        (0.0, 0.0),
        (5.0, 22.0),
        (10.0, 27.0),
        (15.0, 31.0),
        (20.0, 35.0),
        (30.0, 42.0),
        (40.0, 47.5),
        (50.0, 52.0),
        (75.0, 62.0),
        (100.0, 70.0),
        (150.0, 82.0),
        (200.0, 92.0),
        (300.0, 110.0),
        (500.0, 143.0),
        (1000.0, 212.0),
    ),
}

_GPM_TO_LPS = 0.0630902

# Standard nominal internal pipe bores (mm) & absolute surface roughness (mm)
STANDARD_PIPE_BORES_MM: tuple[float, ...] = (
    15.0,
    20.0,
    25.0,
    32.0,
    40.0,
    50.0,
    65.0,
    80.0,
    100.0,
    125.0,
    150.0,
    200.0,
)

_PIPE_ROUGHNESS_MM: dict[str, float] = {
    "PPR_PN20": 0.0015,
    "copper": 0.0015,
    "uPVC": 0.0015,
    "galvanized_steel": 0.15,
}

_WATER_KINEMATIC_VISCOSITY_M2_S = 1.004e-6  # 20 degC clean water
_WATER_DENSITY_KG_M3 = 998.2
_GRAVITY_M_S2 = 9.80665


class CalculationInputError(ValueError):
    """Raised when calculation inputs fail physical or engineering validation."""


class LoadCircuitInput(BaseModel):
    """Single feeder/branch circuit row in an electrical load schedule."""

    circuit_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=255)
    connected_load_kw: float = Field(..., ge=0.0, le=100000.0)
    demand_factor: float = Field(..., gt=0.0, le=1.0)
    power_factor: float | None = Field(default=None, gt=0.0, le=1.0)
    phase: Literal["L1", "L2", "L3", "3ph"] = "3ph"


class ElectricalLoadScheduleInput(BaseModel):
    """Deterministic input schema for an electrical panel load schedule."""

    panel_name: str = Field(..., min_length=1, max_length=128)
    system_voltage_v: float = Field(default=400.0, gt=0.0, le=35000.0)
    phases: Literal["3ph", "1ph"] = "3ph"
    power_factor: float = Field(default=0.85, gt=0.0, le=1.0)
    spare_capacity_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    max_phase_unbalance_pct: float = Field(default=15.0, gt=0.0, le=100.0)
    feeder_capacity_a: float | None = Field(default=None, gt=0.0, le=20000.0)
    circuits: list[LoadCircuitInput] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_phase_assignments(self) -> "ElectricalLoadScheduleInput":
        if self.phases == "1ph":
            for c in self.circuits:
                if c.phase == "3ph":
                    raise ValueError(
                        f"Circuit '{c.circuit_id}' cannot use phase='3ph' inside a 1ph single-phase panel."
                    )
        return self


class ElectricalCableSizingInput(BaseModel):
    """Deterministic input schema for electrical cable sizing and voltage-drop check."""

    circuit_name: str = Field(..., min_length=1, max_length=128)
    design_power_kw: float = Field(..., gt=0.0, le=50000.0)
    voltage_v: float = Field(default=400.0, gt=0.0, le=35000.0)
    phases: Literal["3ph", "1ph"] = "3ph"
    power_factor: float = Field(default=0.85, gt=0.0, le=1.0)
    length_m: float = Field(..., gt=0.0, le=5000.0)
    conductor_material: Literal["copper", "aluminum"] = "copper"
    insulation_type: Literal["XLPE_90C", "PVC_70C"] = "XLPE_90C"
    ambient_temp_factor: float = Field(default=0.87, gt=0.0, le=1.5)
    grouping_factor: float = Field(default=0.80, gt=0.0, le=1.0)
    max_voltage_drop_pct: float = Field(default=3.0, gt=0.0, le=20.0)
    breaker_rating_a: float | None = Field(default=None, gt=0.0, le=5000.0)
    selected_size_mm2: float | None = Field(default=None, gt=0.0, le=1000.0)
    custom_ampacity_a: float | None = Field(default=None, gt=0.0, le=5000.0)
    custom_r_ohm_per_km: float | None = Field(default=None, gt=0.0, le=100.0)
    custom_x_ohm_per_km: float = Field(default=0.08, ge=0.0, le=5.0)


class ElectricalVoltageDropInput(BaseModel):
    """Deterministic input schema for standalone electrical voltage-drop verification."""

    circuit_name: str = Field(..., min_length=1, max_length=128)
    load_current_a: float | None = Field(default=None, gt=0.0, le=10000.0)
    power_kw: float | None = Field(default=None, gt=0.0, le=50000.0)
    voltage_v: float = Field(default=400.0, gt=0.0, le=35000.0)
    phases: Literal["3ph", "1ph"] = "3ph"
    power_factor: float = Field(default=0.85, gt=0.0, le=1.0)
    length_m: float = Field(..., gt=0.0, le=5000.0)
    cable_size_mm2: float = Field(..., gt=0.0, le=1000.0)
    conductor_material: Literal["copper", "aluminum"] = "copper"
    conductor_temp_c: float = Field(default=70.0, ge=10.0, le=120.0)
    r_ohm_per_km: float | None = Field(default=None, gt=0.0, le=100.0)
    x_ohm_per_km: float = Field(default=0.08, ge=0.0, le=5.0)
    upstream_drop_pct: float = Field(default=0.0, ge=0.0, le=20.0)
    max_total_drop_pct: float = Field(default=5.0, gt=0.0, le=25.0)

    @model_validator(mode="after")
    def validate_load_present(self) -> "ElectricalVoltageDropInput":
        if self.load_current_a is None and self.power_kw is None:
            raise ValueError("Either 'load_current_a' or 'power_kw' must be supplied.")
        return self


class PlumbingFixtureInput(BaseModel):
    """Fixture count row for plumbing water demand (WSFU) calculations."""

    fixture_type: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=128)
    count: int = Field(..., ge=0, le=50000)
    wsfu_per_unit: float | None = Field(default=None, gt=0.0, le=100.0)


class PlumbingWaterDemandInput(BaseModel):
    """Deterministic input schema for building water demand, storage tank volume, and pump duty."""

    system_name: str = Field(..., min_length=1, max_length=128)
    building_type: Literal["residential", "clinic_office", "commercial", "custom"] = "clinic_office"
    conversion_method: Literal["hunter_flush_tank", "hunter_flush_valve"] = "hunter_flush_tank"
    fixtures: list[PlumbingFixtureInput] = Field(..., min_length=1)
    occupants_or_units: int = Field(default=0, ge=0, le=100000)
    daily_demand_l_per_person: float = Field(default=80.0, ge=0.0, le=5000.0)
    storage_autonomy_days: float = Field(default=1.0, ge=0.0, le=30.0)
    static_head_m: float = Field(default=12.0, ge=0.0, le=500.0)
    friction_and_residual_head_m: float = Field(default=18.0, ge=0.0, le=500.0)
    pump_efficiency: float = Field(default=0.65, gt=0.05, le=1.0)


class PlumbingPipeSizingInput(BaseModel):
    """Deterministic input schema for Darcy-Weisbach cold/hot water pipe sizing."""

    pipe_run_name: str = Field(..., min_length=1, max_length=128)
    flow_rate_lps: float = Field(..., gt=0.0, le=5000.0)
    pipe_length_m: float = Field(..., gt=0.0, le=10000.0)
    pipe_material: Literal["PPR_PN20", "copper", "uPVC", "galvanized_steel"] = "PPR_PN20"
    nominal_diameter_mm: float | None = Field(default=None, gt=0.0, le=1000.0)
    max_velocity_mps: float = Field(default=1.5, gt=0.1, le=10.0)
    max_head_loss_m_per_100m: float = Field(default=5.0, gt=0.1, le=100.0)
    minor_loss_allowance_pct: float = Field(default=15.0, ge=0.0, le=200.0)


@dataclass(frozen=True)
class CalculationEvaluation:
    """Complete deterministic Step 13 calculation output covering all mandatory fields."""

    discipline: CalculationDiscipline
    calculation_type: CalculationType
    inputs: dict[str, Any]
    units: dict[str, str]
    equations: str
    method: str
    assumptions: list[str]
    results: dict[str, Any]
    acceptance_criteria: list[str]
    acceptance_passed: bool
    breakdown_rows: list[dict[str, Any]] = field(default_factory=list)


def _r4(val: float) -> float:
    return round(float(val), 4)


def _conductor_resistance_ohm_per_km(
    *,
    material: str,
    size_mm2: float,
    temp_c: float,
) -> float:
    rho20, alpha = _CONDUCTOR_PHYSICS[material]
    return (rho20 * (1.0 + alpha * (temp_c - 20.0)) * 1000.0) / size_mm2


def _compute_voltage_drop_metrics(
    *,
    current_a: float,
    voltage_v: float,
    phases: str,
    power_factor: float,
    length_m: float,
    r_ohm_per_km: float,
    x_ohm_per_km: float,
) -> tuple[float, float]:
    sin_phi = math.sqrt(max(0.0, 1.0 - power_factor * power_factor))
    b_factor = math.sqrt(3.0) if phases == "3ph" else 2.0
    dv_v = b_factor * current_a * (length_m / 1000.0) * (r_ohm_per_km * power_factor + x_ohm_per_km * sin_phi)
    dv_pct = (dv_v / voltage_v) * 100.0
    return _r4(dv_v), _r4(dv_pct)


def _interpolate_hunter_gpm(wsfu: float, method: str) -> float:
    curve = _HUNTER_CURVE_GPM[method]
    if wsfu <= 0.0:
        return 0.0
    if wsfu >= curve[-1][0]:
        # Conservative linear extrapolation from final curve segment above 1000 WSFU
        x0, y0 = curve[-2]
        x1, y1 = curve[-1]
        slope = (y1 - y0) / (x1 - x0)
        return y1 + slope * (wsfu - x1)
    for idx in range(1, len(curve)):
        x0, y0 = curve[idx - 1]
        x1, y1 = curve[idx]
        if wsfu <= x1:
            frac = (wsfu - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return curve[-1][1]


def _darcy_friction_factor(*, reynolds: float, roughness_m: float, diameter_m: float) -> float:
    if reynolds <= 0.0:
        raise CalculationInputError("Reynolds number must be positive.")
    if reynolds < 2300.0:
        return 64.0 / reynolds
    rel_rough = roughness_m / diameter_m
    denom = math.log10((rel_rough / 3.7) + (5.74 / (reynolds ** 0.9)))
    return 0.25 / (denom * denom)


def calculate_electrical_load_schedule(raw_inputs: dict[str, Any]) -> CalculationEvaluation:
    """Deterministically compute an electrical panel load schedule, phase balance, and design current."""
    inp = ElectricalLoadScheduleInput.model_validate(raw_inputs)
    circuits_out: list[dict[str, Any]] = []
    phase_loads = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
    total_connected = 0.0
    total_demand = 0.0
    total_apparent = 0.0

    for c in inp.circuits:
        c_pf = c.power_factor if c.power_factor is not None else inp.power_factor
        demand_kw = _r4(c.connected_load_kw * c.demand_factor)
        apparent_kva = _r4(demand_kw / c_pf) if c_pf > 0 else 0.0
        total_connected += c.connected_load_kw
        total_demand += demand_kw
        total_apparent += apparent_kva
        if c.phase == "3ph":
            for ph in ("L1", "L2", "L3"):
                phase_loads[ph] += demand_kw / 3.0
        else:
            phase_loads[c.phase] += demand_kw
        circuits_out.append(
            {
                "circuit_id": c.circuit_id,
                "description": c.description,
                "phase": c.phase,
                "connected_load_kw": _r4(c.connected_load_kw),
                "demand_factor": _r4(c.demand_factor),
                "power_factor": _r4(c_pf),
                "demand_load_kw": demand_kw,
                "apparent_power_kva": apparent_kva,
            }
        )

    total_connected_r = _r4(total_connected)
    total_demand_r = _r4(total_demand)
    total_apparent_r = _r4(total_apparent)
    overall_df = _r4(total_demand_r / total_connected_r) if total_connected_r > 0 else 0.0
    eff_pf = _r4(total_demand_r / total_apparent_r) if total_apparent_r > 0 else inp.power_factor
    spare_mult = 1.0 + (inp.spare_capacity_pct / 100.0)
    design_load_kw = _r4(total_demand_r * spare_mult)
    design_apparent_kva = _r4(total_apparent_r * spare_mult)
    v_factor = math.sqrt(3.0) if inp.phases == "3ph" else 1.0
    design_current_a = _r4((design_apparent_kva * 1000.0) / (v_factor * inp.system_voltage_v))

    l1_r = _r4(phase_loads["L1"])
    l2_r = _r4(phase_loads["L2"])
    l3_r = _r4(phase_loads["L3"])
    if inp.phases == "3ph":
        avg_ph = (l1_r + l2_r + l3_r) / 3.0
        unbalance_pct = _r4(((max(l1_r, l2_r, l3_r) - min(l1_r, l2_r, l3_r)) / avg_ph) * 100.0) if avg_ph > 0 else 0.0
    else:
        unbalance_pct = 0.0

    unbalance_ok = (inp.phases == "1ph") or (unbalance_pct <= inp.max_phase_unbalance_pct)
    feeder_ok = True if inp.feeder_capacity_a is None else (design_current_a <= inp.feeder_capacity_a)
    nonzero_ok = total_demand_r > 0.0
    passed = bool(nonzero_ok and unbalance_ok and feeder_ok)

    criteria = [
        f"Total demand load > 0 kW: {total_demand_r} kW -> {'PASS' if nonzero_ok else 'FAIL'}",
    ]
    if inp.phases == "3ph":
        criteria.append(
            f"3-phase demand unbalance <= {inp.max_phase_unbalance_pct}%: {unbalance_pct}% -> {'PASS' if unbalance_ok else 'FAIL'} (verify against locally adopted code)"
        )
    if inp.feeder_capacity_a is not None:
        criteria.append(
            f"Design current <= feeder rating ({inp.feeder_capacity_a} A): {design_current_a} A -> {'PASS' if feeder_ok else 'FAIL'}"
        )

    equations = (
        "P_dem,i = P_conn,i * DF_i ; S_i = P_dem,i / PF_i ; "
        "P_des = sum(P_dem,i) * (1 + Spare%/100) ; S_des = sum(S_i) * (1 + Spare%/100) ; "
        f"I_des = (S_des * 1000) / ({'sqrt(3)' if inp.phases == '3ph' else '1'} * V_sys) ; "
        "Unbalance% = ((max(L1,L2,L3) - min(L1,L2,L3)) / avg(L1,L2,L3)) * 100"
    )
    method = (
        f"Deterministic panel load aggregation for '{inp.panel_name}' ({inp.phases}, {inp.system_voltage_v} V) "
        "using circuit-level demand factors, spare growth margin, phase-balancing summation, and rated line current."
    )
    assumptions = [
        f"Default panel power factor = {inp.power_factor} where individual circuit PF is omitted.",
        f"Future spare capacity allowance = {inp.spare_capacity_pct}% applied uniformly to connected demand.",
        "Circuit demand factors represent owner/designer planning diversity — verify against the locally adopted code and connected equipment nameplate data.",
    ]
    results = {
        "total_connected_kw": total_connected_r,
        "total_demand_kw": total_demand_r,
        "overall_demand_factor": overall_df,
        "effective_power_factor": eff_pf,
        "total_apparent_kva": total_apparent_r,
        "design_load_kw": design_load_kw,
        "design_apparent_kva": design_apparent_kva,
        "design_current_a": design_current_a,
        "phase_l1_kw": l1_r,
        "phase_l2_kw": l2_r,
        "phase_l3_kw": l3_r,
        "phase_unbalance_pct": unbalance_pct,
        "circuits": circuits_out,
        "acceptance_passed": passed,
    }
    units = {
        "system_voltage_v": "V",
        "spare_capacity_pct": "%",
        "max_phase_unbalance_pct": "%",
        "total_connected_kw": "kW",
        "total_demand_kw": "kW",
        "total_apparent_kva": "kVA",
        "design_load_kw": "kW",
        "design_apparent_kva": "kVA",
        "design_current_a": "A",
        "phase_l1_kw": "kW",
        "phase_l2_kw": "kW",
        "phase_l3_kw": "kW",
        "phase_unbalance_pct": "%",
    }
    return CalculationEvaluation(
        discipline="electrical",
        calculation_type="electrical_load_schedule",
        inputs=inp.model_dump(),
        units=units,
        equations=equations,
        method=method,
        assumptions=assumptions,
        results=results,
        acceptance_criteria=criteria,
        acceptance_passed=passed,
        breakdown_rows=circuits_out,
    )


def calculate_electrical_cable_sizing(raw_inputs: dict[str, Any]) -> CalculationEvaluation:
    """Deterministically size an electrical cable by ampacity derating and voltage-drop check."""
    inp = ElectricalCableSizingInput.model_validate(raw_inputs)
    v_factor = math.sqrt(3.0) if inp.phases == "3ph" else 1.0
    design_current_a = _r4((inp.design_power_kw * 1000.0) / (v_factor * inp.voltage_v * inp.power_factor))

    if inp.breaker_rating_a is not None:
        breaker_a = float(inp.breaker_rating_a)
        if breaker_a < design_current_a:
            raise CalculationInputError(
                f"Specified breaker_rating_a ({breaker_a} A) is lower than design current Ib ({design_current_a} A)."
            )
    else:
        matched_breakers = [r for r in STANDARD_BREAKER_RATINGS_A if r >= design_current_a]
        breaker_a = matched_breakers[0] if matched_breakers else math.ceil(design_current_a)

    derating = _r4(inp.ambient_temp_factor * inp.grouping_factor)
    required_tabulated_a = _r4(breaker_a / derating)
    temp_c = 90.0 if inp.insulation_type == "XLPE_90C" else 70.0
    table = _BASELINE_AMPACITY_A[(inp.conductor_material, inp.insulation_type)]

    chosen_size: float | None = None
    chosen_tab_amp: float = 0.0
    chosen_derated_amp: float = 0.0
    chosen_r: float = 0.0
    chosen_dv_v: float = 0.0
    chosen_dv_pct: float = 0.0
    governing = "ampacity"

    candidate_sizes = [inp.selected_size_mm2] if inp.selected_size_mm2 is not None else sorted(table.keys())
    for sz in candidate_sizes:
        assert sz is not None
        tab_amp = inp.custom_ampacity_a if inp.custom_ampacity_a is not None else table.get(sz)
        if tab_amp is None:
            raise CalculationInputError(
                f"No baseline ampacity available for {inp.conductor_material} {inp.insulation_type} {sz} mm^2; supply custom_ampacity_a."
            )
        derated_amp = _r4(tab_amp * derating)
        r_km = (
            inp.custom_r_ohm_per_km
            if inp.custom_r_ohm_per_km is not None
            else _r4(_conductor_resistance_ohm_per_km(material=inp.conductor_material, size_mm2=sz, temp_c=temp_c))
        )
        dv_v, dv_pct = _compute_voltage_drop_metrics(
            current_a=design_current_a,
            voltage_v=inp.voltage_v,
            phases=inp.phases,
            power_factor=inp.power_factor,
            length_m=inp.length_m,
            r_ohm_per_km=r_km,
            x_ohm_per_km=inp.custom_x_ohm_per_km,
        )
        chosen_size = sz
        chosen_tab_amp = tab_amp
        chosen_derated_amp = derated_amp
        chosen_r = r_km
        chosen_dv_v = dv_v
        chosen_dv_pct = dv_pct

        amp_ok_candidate = breaker_a <= derated_amp
        vd_ok_candidate = dv_pct <= inp.max_voltage_drop_pct
        if inp.selected_size_mm2 is not None:
            governing = "manual_selection"
            break
        if amp_ok_candidate and vd_ok_candidate:
            if sz > min(s for s, a in table.items() if a * derating >= breaker_a):
                governing = "voltage_drop"
            else:
                governing = "ampacity"
            break
    else:
        governing = "exceeds_single_core_range"

    assert chosen_size is not None
    ampacity_ok = design_current_a <= breaker_a <= chosen_derated_amp
    vd_ok = chosen_dv_pct <= inp.max_voltage_drop_pct
    passed = bool(ampacity_ok and vd_ok)
    margin_pct = _r4(((chosen_derated_amp - breaker_a) / breaker_a) * 100.0) if breaker_a > 0 else 0.0

    criteria = [
        f"Ib <= In <= Iz_derated ({design_current_a} A <= {breaker_a} A <= {chosen_derated_amp} A) -> {'PASS' if ampacity_ok else 'FAIL'}",
        f"Voltage drop <= {inp.max_voltage_drop_pct}%: {chosen_dv_pct}% -> {'PASS' if vd_ok else 'FAIL'} (verify against locally adopted code)",
    ]
    equations = (
        f"I_b = (P * 1000) / ({'sqrt(3)' if inp.phases == '3ph' else '1'} * V * PF) ; "
        "C_total = C_ambient * C_group ; I_z,req = I_n / C_total ; "
        "R(T) = rho_20 * [1 + alpha * (T - 20)] * 1000 / A ; "
        f"dV = {'sqrt(3)' if inp.phases == '3ph' else '2'} * I_b * (L / 1000) * (R * cos(phi) + X * sin(phi)) ; "
        "dV% = (dV / V) * 100"
    )
    method = (
        f"Deterministic feeder/branch cable selection for '{inp.circuit_name}' ({inp.conductor_material}, {inp.insulation_type}) "
        "enforcing protective-device coordination (Ib <= In <= Iz_derated) and voltage-drop compliance."
    )
    assumptions = [
        f"Operating conductor temperature assumed at maximum insulation rating ({temp_c} C) for resistance correction.",
        f"Preliminary baseline ampacity table used unless custom_ampacity_a is supplied; baseline reactance X = {inp.custom_x_ohm_per_km} ohm/km.",
        "Installation method, ambient derating, and grouping factors must be verified against the manufacturer datasheet and locally adopted wiring code.",
    ]
    results = {
        "design_current_a": design_current_a,
        "breaker_rating_a": _r4(breaker_a),
        "total_derating_factor": derating,
        "required_tabulated_ampacity_a": required_tabulated_a,
        "selected_cable_size_mm2": _r4(chosen_size),
        "tabulated_ampacity_a": _r4(chosen_tab_amp),
        "derated_ampacity_a": chosen_derated_amp,
        "ampacity_margin_pct": margin_pct,
        "resistance_ohm_per_km": chosen_r,
        "reactance_ohm_per_km": _r4(inp.custom_x_ohm_per_km),
        "voltage_drop_v": chosen_dv_v,
        "voltage_drop_pct": chosen_dv_pct,
        "governing_criterion": governing,
        "acceptance_passed": passed,
    }
    units = {
        "design_power_kw": "kW",
        "voltage_v": "V",
        "length_m": "m",
        "design_current_a": "A",
        "breaker_rating_a": "A",
        "required_tabulated_ampacity_a": "A",
        "selected_cable_size_mm2": "mm2",
        "tabulated_ampacity_a": "A",
        "derated_ampacity_a": "A",
        "ampacity_margin_pct": "%",
        "resistance_ohm_per_km": "ohm/km",
        "reactance_ohm_per_km": "ohm/km",
        "voltage_drop_v": "V",
        "voltage_drop_pct": "%",
        "max_voltage_drop_pct": "%",
    }
    return CalculationEvaluation(
        discipline="electrical",
        calculation_type="electrical_cable_sizing",
        inputs=inp.model_dump(),
        units=units,
        equations=equations,
        method=method,
        assumptions=assumptions,
        results=results,
        acceptance_criteria=criteria,
        acceptance_passed=passed,
    )


def calculate_electrical_voltage_drop(raw_inputs: dict[str, Any]) -> CalculationEvaluation:
    """Deterministically evaluate electrical circuit voltage drop in volts and percentage."""
    inp = ElectricalVoltageDropInput.model_validate(raw_inputs)
    v_factor = math.sqrt(3.0) if inp.phases == "3ph" else 1.0
    if inp.load_current_a is not None:
        current_a = _r4(inp.load_current_a)
    else:
        assert inp.power_kw is not None
        current_a = _r4((inp.power_kw * 1000.0) / (v_factor * inp.voltage_v * inp.power_factor))

    r_km = (
        _r4(inp.r_ohm_per_km)
        if inp.r_ohm_per_km is not None
        else _r4(
            _conductor_resistance_ohm_per_km(
                material=inp.conductor_material,
                size_mm2=inp.cable_size_mm2,
                temp_c=inp.conductor_temp_c,
            )
        )
    )
    dv_v, dv_pct = _compute_voltage_drop_metrics(
        current_a=current_a,
        voltage_v=inp.voltage_v,
        phases=inp.phases,
        power_factor=inp.power_factor,
        length_m=inp.length_m,
        r_ohm_per_km=r_km,
        x_ohm_per_km=inp.x_ohm_per_km,
    )
    total_drop_pct = _r4(dv_pct + inp.upstream_drop_pct)
    receiving_v = _r4(inp.voltage_v * (1.0 - total_drop_pct / 100.0))
    passed = total_drop_pct <= inp.max_total_drop_pct

    criteria = [
        f"Total cumulative voltage drop <= {inp.max_total_drop_pct}%: {total_drop_pct}% -> {'PASS' if passed else 'FAIL'} (verify against locally adopted code)",
    ]
    equations = (
        "R(T) = rho_20 * [1 + alpha * (T - 20)] * 1000 / A ; "
        f"dV = {'sqrt(3)' if inp.phases == '3ph' else '2'} * I * (L / 1000) * (R * cos(phi) + X * sin(phi)) ; "
        "dV% = (dV / V) * 100 ; Total_dV% = dV% + Upstream_dV% ; V_recv = V * (1 - Total_dV% / 100)"
    )
    method = (
        f"Steady-state AC voltage-drop calculation for '{inp.circuit_name}' ({inp.phases}, {inp.cable_size_mm2} mm^2 {inp.conductor_material}) "
        "using temperature-adjusted conductor resistance and inductive reactance."
    )
    assumptions = [
        f"Conductor temperature = {inp.conductor_temp_c} C (unless explicit r_ohm_per_km provided).",
        f"Inductive reactance X = {inp.x_ohm_per_km} ohm/km; upstream voltage drop = {inp.upstream_drop_pct}%.",
        "Confirm allowable branch/total voltage-drop limits against the locally adopted electrical code.",
    ]
    results = {
        "effective_current_a": current_a,
        "resistance_ohm_per_km": r_km,
        "reactance_ohm_per_km": _r4(inp.x_ohm_per_km),
        "voltage_drop_v": dv_v,
        "circuit_voltage_drop_pct": dv_pct,
        "upstream_drop_pct": _r4(inp.upstream_drop_pct),
        "total_voltage_drop_pct": total_drop_pct,
        "receiving_voltage_v": receiving_v,
        "acceptance_passed": passed,
    }
    units = {
        "voltage_v": "V",
        "length_m": "m",
        "cable_size_mm2": "mm2",
        "conductor_temp_c": "degC",
        "effective_current_a": "A",
        "resistance_ohm_per_km": "ohm/km",
        "reactance_ohm_per_km": "ohm/km",
        "voltage_drop_v": "V",
        "circuit_voltage_drop_pct": "%",
        "upstream_drop_pct": "%",
        "total_voltage_drop_pct": "%",
        "max_total_drop_pct": "%",
        "receiving_voltage_v": "V",
    }
    return CalculationEvaluation(
        discipline="electrical",
        calculation_type="electrical_voltage_drop",
        inputs=inp.model_dump(),
        units=units,
        equations=equations,
        method=method,
        assumptions=assumptions,
        results=results,
        acceptance_criteria=criteria,
        acceptance_passed=passed,
    )


def calculate_plumbing_water_demand(raw_inputs: dict[str, Any]) -> CalculationEvaluation:
    """Deterministically compute WSFU water demand, peak flow (L/s & m3/h), daily storage, and pump duty."""
    inp = PlumbingWaterDemandInput.model_validate(raw_inputs)
    fixtures_out: list[dict[str, Any]] = []
    total_wsfu = 0.0
    total_fixtures = 0

    for fx in inp.fixtures:
        weight = fx.wsfu_per_unit if fx.wsfu_per_unit is not None else DEFAULT_WSFU_WEIGHTS.get(fx.fixture_type)
        if weight is None:
            raise CalculationInputError(
                f"Unknown fixture_type '{fx.fixture_type}' requires an explicit 'wsfu_per_unit' weight."
            )
        subtotal = _r4(fx.count * weight)
        total_wsfu += subtotal
        total_fixtures += fx.count
        fixtures_out.append(
            {
                "fixture_type": fx.fixture_type,
                "label": fx.label or fx.fixture_type,
                "count": fx.count,
                "wsfu_per_unit": _r4(weight),
                "subtotal_wsfu": subtotal,
            }
        )

    total_wsfu_r = _r4(total_wsfu)
    peak_gpm = _r4(_interpolate_hunter_gpm(total_wsfu_r, inp.conversion_method))
    peak_lps = _r4(peak_gpm * _GPM_TO_LPS)
    peak_m3_h = _r4(peak_lps * 3.6)

    daily_l = _r4(inp.occupants_or_units * inp.daily_demand_l_per_person)
    daily_m3 = _r4(daily_l / 1000.0)
    storage_m3 = _r4(daily_m3 * inp.storage_autonomy_days)
    tdh_m = _r4(inp.static_head_m + inp.friction_and_residual_head_m)
    hyd_kw = _r4((_GRAVITY_M_S2 * peak_lps * tdh_m) / 1000.0)
    pump_kw = _r4(hyd_kw / inp.pump_efficiency) if inp.pump_efficiency > 0 else 0.0

    demand_ok = total_wsfu_r > 0.0 and peak_lps > 0.0
    storage_ok = True if inp.occupants_or_units == 0 else (storage_m3 >= daily_m3)
    passed = bool(demand_ok and storage_ok)

    criteria = [
        f"Total WSFU > 0 and peak flow > 0 L/s: {total_wsfu_r} WSFU / {peak_lps} L/s -> {'PASS' if demand_ok else 'FAIL'}",
        f"Reserve storage >= daily demand ({storage_m3} m3 >= {daily_m3} m3) -> {'PASS' if storage_ok else 'FAIL'} (verify against locally adopted code)",
    ]
    equations = (
        "Total_WSFU = sum(Count_i * WSFU_i) ; Q_peak(GPM) = Hunter_Interp(Total_WSFU) ; "
        "Q_peak(L/s) = Q_peak(GPM) * 0.0630902 ; Q_peak(m3/h) = Q_peak(L/s) * 3.6 ; "
        "V_daily = Occupants * L_per_person / 1000 ; V_tank = V_daily * Autonomy_days ; "
        "TDH = H_static + H_fric_resid ; P_hyd = (9.80665 * Q_peak(L/s) * TDH) / 1000 ; P_shaft = P_hyd / eta"
    )
    method = (
        f"Hunter's-curve Water Supply Fixture Unit (WSFU) peak demand method ({inp.conversion_method}) "
        f"for '{inp.system_name}' ({inp.building_type}), paired with daily tank autonomy sizing and hydraulic pump duty."
    )
    assumptions = [
        "WSFU weights and Hunter probability curve represent preliminary planning baselines — verify against the locally adopted plumbing code.",
        f"Daily per-capita water consumption = {inp.daily_demand_l_per_person} L/day with {inp.storage_autonomy_days} day(s) storage autonomy.",
        f"Booster pump combined hydraulic/mechanical efficiency assumed at {inp.pump_efficiency * 100:.1f}%.",
    ]
    results = {
        "total_fixture_count": total_fixtures,
        "total_wsfu": total_wsfu_r,
        "peak_flow_gpm": peak_gpm,
        "peak_flow_lps": peak_lps,
        "peak_flow_m3_h": peak_m3_h,
        "daily_demand_l": daily_l,
        "daily_demand_m3": daily_m3,
        "storage_tank_m3": storage_m3,
        "total_dynamic_head_m": tdh_m,
        "hydraulic_power_kw": hyd_kw,
        "pump_shaft_power_kw": pump_kw,
        "fixtures": fixtures_out,
        "acceptance_passed": passed,
    }
    units = {
        "total_wsfu": "WSFU",
        "peak_flow_gpm": "GPM",
        "peak_flow_lps": "L/s",
        "peak_flow_m3_h": "m3/h",
        "daily_demand_l": "L/day",
        "daily_demand_m3": "m3/day",
        "storage_tank_m3": "m3",
        "static_head_m": "m",
        "friction_and_residual_head_m": "m",
        "total_dynamic_head_m": "m",
        "hydraulic_power_kw": "kW",
        "pump_shaft_power_kw": "kW",
    }
    return CalculationEvaluation(
        discipline="plumbing",
        calculation_type="plumbing_water_demand",
        inputs=inp.model_dump(),
        units=units,
        equations=equations,
        method=method,
        assumptions=assumptions,
        results=results,
        acceptance_criteria=criteria,
        acceptance_passed=passed,
        breakdown_rows=fixtures_out,
    )


def calculate_plumbing_pipe_sizing(raw_inputs: dict[str, Any]) -> CalculationEvaluation:
    """Deterministically size a water supply pipe using Darcy-Weisbach + Swamee-Jain friction loss."""
    inp = PlumbingPipeSizingInput.model_validate(raw_inputs)
    flow_m3_s = inp.flow_rate_lps / 1000.0
    roughness_mm = _PIPE_ROUGHNESS_MM[inp.pipe_material]
    roughness_m = roughness_mm / 1000.0

    candidates = [inp.nominal_diameter_mm] if inp.nominal_diameter_mm is not None else list(STANDARD_PIPE_BORES_MM)
    chosen_dn = float(candidates[-1])  # type: ignore[arg-type]
    chosen_vel = 0.0
    chosen_re = 0.0
    chosen_f = 0.0
    chosen_hf100 = 0.0
    chosen_hf_total = 0.0
    chosen_dp_kpa = 0.0

    for dn_mm in candidates:
        assert dn_mm is not None
        d_m = dn_mm / 1000.0
        area_m2 = math.pi * (d_m * d_m) / 4.0
        vel_mps = flow_m3_s / area_m2
        reynolds = (vel_mps * d_m) / _WATER_KINEMATIC_VISCOSITY_M2_S
        f_factor = _darcy_friction_factor(reynolds=reynolds, roughness_m=roughness_m, diameter_m=d_m)
        hf_per_100m = f_factor * (100.0 / d_m) * ((vel_mps * vel_mps) / (2.0 * _GRAVITY_M_S2))
        hf_total_m = hf_per_100m * (inp.pipe_length_m / 100.0) * (1.0 + inp.minor_loss_allowance_pct / 100.0)
        dp_kpa = (_WATER_DENSITY_KG_M3 * _GRAVITY_M_S2 * hf_total_m) / 1000.0

        chosen_dn = dn_mm
        chosen_vel = _r4(vel_mps)
        chosen_re = _r4(reynolds)
        chosen_f = round(f_factor, 6)
        chosen_hf100 = _r4(hf_per_100m)
        chosen_hf_total = _r4(hf_total_m)
        chosen_dp_kpa = _r4(dp_kpa)

        if inp.nominal_diameter_mm is not None:
            break
        if chosen_vel <= inp.max_velocity_mps and chosen_hf100 <= inp.max_head_loss_m_per_100m:
            break

    vel_ok = chosen_vel <= inp.max_velocity_mps
    hf_ok = chosen_hf100 <= inp.max_head_loss_m_per_100m
    passed = bool(vel_ok and hf_ok)

    criteria = [
        f"Flow velocity <= {inp.max_velocity_mps} m/s: {chosen_vel} m/s -> {'PASS' if vel_ok else 'FAIL'}",
        f"Friction gradient <= {inp.max_head_loss_m_per_100m} m/100m: {chosen_hf100} m/100m -> {'PASS' if hf_ok else 'FAIL'} (verify against locally adopted code)",
    ]
    equations = (
        "Q = Q_lps / 1000 ; A = pi * D^2 / 4 ; v = Q / A ; Re = v * D / nu ; "
        "f = 64/Re (Re<2300) else 0.25 / [log10((eps/D)/3.7 + 5.74/Re^0.9)]^2 ; "
        "hf_100 = f * (100/D) * (v^2 / (2*g)) ; "
        "hf_total = hf_100 * (L/100) * (1 + minor%/100) ; dP_kPa = rho * g * hf_total / 1000"
    )
    method = (
        f"Darcy-Weisbach hydraulic pipe sizing for '{inp.pipe_run_name}' ({inp.pipe_material}) "
        "using explicit Swamee-Jain friction factor correlation and velocity/gradient bounds."
    )
    assumptions = [
        f"Clean water properties at 20 C: kinematic viscosity nu = 1.004e-6 m^2/s, density = 998.2 kg/m^3.",
        f"Absolute internal pipe roughness epsilon = {roughness_mm} mm for {inp.pipe_material}; minor fittings allowance = {inp.minor_loss_allowance_pct}%.",
        "Selected nominal bore represents internal hydraulic diameter — verify SDR wall thickness and allowable velocity against locally adopted plumbing code.",
    ]
    results = {
        "flow_rate_m3_s": round(flow_m3_s, 6),
        "selected_nominal_diameter_mm": _r4(chosen_dn),
        "velocity_mps": chosen_vel,
        "reynolds_number": chosen_re,
        "darcy_friction_factor": chosen_f,
        "head_loss_m_per_100m": chosen_hf100,
        "total_head_loss_m": chosen_hf_total,
        "pressure_drop_kpa": chosen_dp_kpa,
        "acceptance_passed": passed,
    }
    units = {
        "flow_rate_lps": "L/s",
        "flow_rate_m3_s": "m3/s",
        "pipe_length_m": "m",
        "selected_nominal_diameter_mm": "mm",
        "velocity_mps": "m/s",
        "max_velocity_mps": "m/s",
        "head_loss_m_per_100m": "m/100m",
        "max_head_loss_m_per_100m": "m/100m",
        "total_head_loss_m": "m",
        "pressure_drop_kpa": "kPa",
    }
    return CalculationEvaluation(
        discipline="plumbing",
        calculation_type="plumbing_pipe_sizing",
        inputs=inp.model_dump(),
        units=units,
        equations=equations,
        method=method,
        assumptions=assumptions,
        results=results,
        acceptance_criteria=criteria,
        acceptance_passed=passed,
    )


_DISPATCH: dict[CalculationType, Any] = {
    "electrical_load_schedule": calculate_electrical_load_schedule,
    "electrical_cable_sizing": calculate_electrical_cable_sizing,
    "electrical_voltage_drop": calculate_electrical_voltage_drop,
    "plumbing_water_demand": calculate_plumbing_water_demand,
    "plumbing_pipe_sizing": calculate_plumbing_pipe_sizing,
}


def evaluate_calculation(
    calculation_type: CalculationType | str,
    raw_inputs: dict[str, Any],
) -> CalculationEvaluation:
    """Dispatch and deterministically execute one of the Step 13 engineering calculators."""
    fn = _DISPATCH.get(calculation_type)  # type: ignore[arg-type]
    if fn is None:
        raise CalculationInputError(
            f"Unsupported calculation_type '{calculation_type}'. Supported: {', '.join(sorted(_DISPATCH))}."
        )
    return fn(raw_inputs)


def get_synthetic_calculation_presets() -> list[dict[str, Any]]:
    """Return synthetic clinic/office examples (zero client data) for all 5 Step 13 calculators."""
    return [
        {
            "calculation_type": "electrical_load_schedule",
            "discipline": "electrical",
            "title_en": "Synthetic Clinic Panel Load Schedule (MDB-CLINIC-01)",
            "title_ar": "جدول أحمال كهربائية نموذجي للعيادة (MDB-CLINIC-01)",
            "inputs": {
                "panel_name": "MDB-CLINIC-01",
                "system_voltage_v": 400.0,
                "phases": "3ph",
                "power_factor": 0.85,
                "spare_capacity_pct": 20.0,
                "max_phase_unbalance_pct": 15.0,
                "feeder_capacity_a": 100.0,
                "circuits": [
                    {"circuit_id": "C-01", "description": "Ground Floor LED Lighting", "connected_load_kw": 6.0, "demand_factor": 0.9, "phase": "L1"},
                    {"circuit_id": "C-02", "description": "Reception & Exam Small Power", "connected_load_kw": 8.0, "demand_factor": 0.7, "phase": "L2"},
                    {"circuit_id": "C-03", "description": "Lab & Diagnostic Receptacles", "connected_load_kw": 7.5, "demand_factor": 0.8, "phase": "L3"},
                    {"circuit_id": "C-04", "description": "Split HVAC & Fresh Air Package", "connected_load_kw": 18.0, "demand_factor": 0.85, "phase": "3ph"},
                ],
            },
            "default_reference": {
                "source_kind": "owner_supplied",
                "source_name": "Synthetic Clinic Design Basis Brief",
                "source_ref": "Owner Synthetic Design Basis Rev 01 (0% client data)",
            },
        },
        {
            "calculation_type": "electrical_cable_sizing",
            "discipline": "electrical",
            "title_en": "Synthetic HVAC Chiller Feeder Cable Sizing (FEEDER-HVAC-01)",
            "title_ar": "حساب مقاس كابل مغذي التكييف النموذجي (FEEDER-HVAC-01)",
            "inputs": {
                "circuit_name": "FEEDER-HVAC-01",
                "design_power_kw": 18.0,
                "voltage_v": 400.0,
                "phases": "3ph",
                "power_factor": 0.85,
                "length_m": 45.0,
                "conductor_material": "copper",
                "insulation_type": "XLPE_90C",
                "ambient_temp_factor": 0.87,
                "grouping_factor": 0.80,
                "max_voltage_drop_pct": 3.0,
            },
            "default_reference": {
                "source_kind": "owner_supplied",
                "source_name": "Synthetic Electrical Feeder Schedule Brief",
                "source_ref": "Owner Feeder Basis Rev 01",
            },
        },
        {
            "calculation_type": "electrical_voltage_drop",
            "discipline": "electrical",
            "title_en": "Synthetic Sub-Main Voltage Drop Check (SUBMAIN-LAB-01)",
            "title_ar": "فحص هبوط الجهد للمغذي الفرعي النموذجي (SUBMAIN-LAB-01)",
            "inputs": {
                "circuit_name": "SUBMAIN-LAB-01",
                "load_current_a": 45.0,
                "voltage_v": 400.0,
                "phases": "3ph",
                "power_factor": 0.85,
                "length_m": 80.0,
                "cable_size_mm2": 16.0,
                "conductor_material": "copper",
                "conductor_temp_c": 70.0,
                "x_ohm_per_km": 0.08,
                "upstream_drop_pct": 1.0,
                "max_total_drop_pct": 5.0,
            },
            "default_reference": {
                "source_kind": "owner_supplied",
                "source_name": "Synthetic Sub-Main Schedule Brief",
                "source_ref": "Owner Sub-Main Voltage Drop Input Rev 01",
            },
        },
        {
            "calculation_type": "plumbing_water_demand",
            "discipline": "plumbing",
            "title_en": "Synthetic Clinic Cold Water Demand & Storage (CWS-CLINIC-01)",
            "title_ar": "حساب استهلاك وخزان المياه النموذجي للعيادة (CWS-CLINIC-01)",
            "inputs": {
                "system_name": "CWS-CLINIC-01",
                "building_type": "clinic_office",
                "conversion_method": "hunter_flush_tank",
                "fixtures": [
                    {"fixture_type": "wc_flush_tank", "label": "Water Closet (Flush Tank)", "count": 4},
                    {"fixture_type": "lavatory", "label": "Examination Lavatory", "count": 6},
                    {"fixture_type": "service_sink", "label": "Janitor Service Sink", "count": 1},
                    {"fixture_type": "kitchen_sink", "label": "Sterilization/Prep Sink", "count": 2},
                ],
                "occupants_or_units": 45,
                "daily_demand_l_per_person": 80.0,
                "storage_autonomy_days": 1.0,
                "static_head_m": 12.0,
                "friction_and_residual_head_m": 18.0,
                "pump_efficiency": 0.65,
            },
            "default_reference": {
                "source_kind": "owner_supplied",
                "source_name": "Synthetic Clinic Plumbing Basis",
                "source_ref": "Owner Plumbing Fixture Count Schedule Rev 01",
            },
        },
        {
            "calculation_type": "plumbing_pipe_sizing",
            "discipline": "plumbing",
            "title_en": "Synthetic Cold Water Main Riser Sizing (RISER-CWS-MAIN)",
            "title_ar": "حساب قطر صاعد التغذية الرئيسي النموذجي (RISER-CWS-MAIN)",
            "inputs": {
                "pipe_run_name": "RISER-CWS-MAIN",
                "flow_rate_lps": 1.5,
                "pipe_length_m": 35.0,
                "pipe_material": "PPR_PN20",
                "max_velocity_mps": 1.5,
                "max_head_loss_m_per_100m": 5.0,
                "minor_loss_allowance_pct": 15.0,
            },
            "default_reference": {
                "source_kind": "owner_supplied",
                "source_name": "Synthetic Riser Hydraulic Basis",
                "source_ref": "Owner PPR Riser Routing Input Rev 01",
            },
        },
    ]
