"""Step 18 pure deterministic HVAC, Fire & Healthcare skills: PREPARE inputs & CHECK outputs only (0 AI tokens default)."""

from dataclasses import dataclass, field
import json
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.providers.base import (
    LLMRequest,
    ProviderResponseError,
    ProviderUsageLimitError,
    TaskComplexity,
    TokenUsage,
    sanitize_secret_text,
)
from app.providers.secrets import SecretStore
from app.schemas.specialist import (
    NOT_PROVIDED_LABEL,
    NO_VERIFIED_STANDARD_LABEL,
    PRELIMINARY_ENGINEER_LABEL_EN,
    SpecialistDomain,
    SpecialistPresetOut,
    SpecialistWorkflowMode,
)
from app.services.provider_settings import _load_provider_config, _summarize_usage, execute_provider_request
from app.services.research import estimate_prompt_tokens

SOFTWARE_RECOMMENDATIONS: dict[SpecialistDomain, str] = {
    "hvac": (
        "Input preparation & sanity check ONLY — validated commercial software recommended for final loads & ductwork "
        "(e.g., Carrier HAP, Trane TRACE 3D Plus, EnergyPlus) under licensed mechanical engineer review."
    ),
    "fire": (
        "Input preparation & sanity check ONLY — validated commercial software recommended for final hydraulic network calculations "
        "(e.g., Elite Fire, SprinkCALC, AutoSPRINK) under licensed fire protection engineer review."
    ),
    "healthcare": (
        "Input preparation & sanity check ONLY — validated commercial MEP/airflow software recommended for hospital pressure cascades & HEPA networks "
        "(e.g., Carrier HAP, CONTAM, Pipe-Flo) under licensed mechanical & clinical engineer review."
    ),
}


class SpecialistInputError(ValueError):
    """Raised when structural assessment inputs have invalid types or empty collections."""


@dataclass(frozen=True)
class SpecialistEvaluation:
    """Deterministic output of Step 18 input preparation and output verification (never replaces licensed engineer)."""

    domain: SpecialistDomain
    workflow_mode: SpecialistWorkflowMode
    status: str
    checks_passed: bool
    blocked_missing_count: int
    failed_checks_count: int
    equations: list[str]
    methodology: str
    preliminary_assumptions: list[str]
    software_recommendation: str
    prepared_items: list[dict[str, Any]]
    check_rows: list[dict[str, Any]]
    blocked_flags: list[str]
    metrics: dict[str, Any] = field(default_factory=dict)


def _opt_nonneg_float(val: Any, name: str) -> float | None:
    if val is None or val == "" or (isinstance(val, str) and val.strip().lower() == NOT_PROVIDED_LABEL):
        return None
    try:
        parsed = float(val)
    except (TypeError, ValueError) as exc:
        raise SpecialistInputError(f"Invalid numeric value for '{name}': {val!r}") from exc
    if parsed < 0:
        raise SpecialistInputError(f"Field '{name}' cannot be negative (got {parsed}).")
    return parsed


def _opt_signed_float(val: Any, name: str) -> float | None:
    if val is None or val == "" or (isinstance(val, str) and val.strip().lower() == NOT_PROVIDED_LABEL):
        return None
    try:
        return float(val)
    except (TypeError, ValueError) as exc:
        raise SpecialistInputError(f"Invalid signed numeric value for '{name}': {val!r}") from exc


def _disp(val: Any) -> Any:
    return NOT_PROVIDED_LABEL if val is None else val


def _evaluate_hvac(inputs: dict[str, Any], mode: SpecialistWorkflowMode) -> SpecialistEvaluation:
    """Prepare zone geometry/OA inputs and verify sensible heat vs reported supply airflow (Q = 1.21 * Vdot * dT)."""
    zones = inputs.get("zones")
    if not isinstance(zones, list) or len(zones) == 0:
        raise SpecialistInputError("HVAC inputs must include a non-empty 'zones' list.")

    air_factor = _opt_nonneg_float(inputs.get("air_heat_factor_kw_per_m3s"), "air_heat_factor_kw_per_m3s")
    if air_factor is None or air_factor == 0:
        air_factor = 1.21
    tol_pct = _opt_nonneg_float(inputs.get("airflow_tolerance_pct"), "airflow_tolerance_pct")
    if tol_pct is None:
        tol_pct = 5.0

    prepared_items: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    blocked_flags: list[str] = []
    passed_checks = 0
    failed_checks = 0

    total_area_m2 = 0.0
    total_volume_m3 = 0.0
    total_expected_supply_ls = 0.0
    total_reported_supply_ls = 0.0
    total_expected_oa_ls = 0.0
    volume_complete = True
    supply_complete = True

    for idx, z in enumerate(zones, start=1):
        if not isinstance(z, dict):
            raise SpecialistInputError(f"HVAC zone #{idx} must be an object.")
        zid = str(z.get("zone_id") or f"Z-{idx:02d}").strip()
        zname = str(z.get("zone_name") or f"Zone {idx}").strip()

        area = _opt_nonneg_float(z.get("floor_area_m2"), f"{zid}.floor_area_m2")
        height = _opt_nonneg_float(z.get("ceiling_height_m"), f"{zid}.ceiling_height_m")
        occ = _opt_nonneg_float(z.get("occupancy_count"), f"{zid}.occupancy_count")
        rp = _opt_nonneg_float(z.get("oa_ls_per_person"), f"{zid}.oa_ls_per_person")
        ra = _opt_nonneg_float(z.get("oa_ls_per_m2"), f"{zid}.oa_ls_per_m2")
        sens_w = _opt_nonneg_float(z.get("reported_sensible_load_w"), f"{zid}.reported_sensible_load_w")
        dt_k = _opt_nonneg_float(z.get("supply_delta_t_k"), f"{zid}.supply_delta_t_k")
        rep_ls = _opt_nonneg_float(z.get("reported_supply_airflow_ls"), f"{zid}.reported_supply_airflow_ls")
        rep_oa_ls = _opt_nonneg_float(z.get("reported_outdoor_airflow_ls"), f"{zid}.reported_outdoor_airflow_ls")

        missing_geom: list[str] = []
        if area is None or area == 0:
            missing_geom.append("floor_area_m2")
        if height is None or height == 0:
            missing_geom.append("ceiling_height_m")

        if missing_geom:
            vol_m3: Any = NOT_PROVIDED_LABEL
            volume_complete = False
            msg = f"{zid}: missing {', '.join(missing_geom)} -> volume blocked ('{NOT_PROVIDED_LABEL}')"
            blocked_flags.append(msg)
            check_rows.append(
                {
                    "item_id": zid,
                    "label": f"{zname} — Volume Preparation",
                    "expected": "area_m2 * ceiling_height_m > 0",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": "m³",
                    "status": "blocked_missing_inputs",
                    "notes": msg,
                }
            )
        else:
            vol_m3 = round(area * height, 4)
            total_area_m2 += area
            total_volume_m3 += vol_m3

        # Outdoor air preparation (only from owner-supplied Rp/Ra rates; never invent ASHRAE defaults)
        expected_oa_ls: Any = NOT_PROVIDED_LABEL
        if mode == "input_preparation" or any(v is not None for v in (occ, rp, ra, rep_oa_ls)):
            missing_oa: list[str] = []
            if area is None or area == 0:
                missing_oa.append("floor_area_m2")
            if occ is None:
                missing_oa.append("occupancy_count")
            if rp is None:
                missing_oa.append("oa_ls_per_person")
            if ra is None:
                missing_oa.append("oa_ls_per_m2")
            if missing_oa:
                msg = f"{zid}: missing {', '.join(missing_oa)} -> outdoor air target '{NOT_PROVIDED_LABEL}'"
                blocked_flags.append(msg)
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Outdoor Air Preparation",
                        "expected": "occ * oa_ls_per_person + area * oa_ls_per_m2",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "L/s",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                assert area is not None and occ is not None and rp is not None and ra is not None
                expected_oa_ls = round(occ * rp + area * ra, 4)
                total_expected_oa_ls += expected_oa_ls
                if mode in ("output_check", "full_preflight") and rep_oa_ls is not None:
                    oa_ok = rep_oa_ls >= expected_oa_ls
                    if oa_ok:
                        passed_checks += 1
                    else:
                        failed_checks += 1
                    check_rows.append(
                        {
                            "item_id": zid,
                            "label": f"{zname} — Reported OA Airflow >= Target",
                            "expected": f">= {expected_oa_ls} L/s",
                            "actual": f"{rep_oa_ls} L/s",
                            "unit": "L/s",
                            "status": "PASS (PRELIMINARY)" if oa_ok else "FAIL",
                            "notes": "Owner-supplied Rp/Ra rates; verify locally adopted ventilation code.",
                        }
                    )

        # Output check: sensible heat vs supply airflow balance
        expected_supply_ls: Any = NOT_PROVIDED_LABEL
        w_per_m2: Any = NOT_PROVIDED_LABEL
        supply_ach: Any = NOT_PROVIDED_LABEL
        diff_pct: Any = NOT_PROVIDED_LABEL

        if area and sens_w is not None:
            w_per_m2 = round(sens_w / area, 4)

        if mode in ("output_check", "full_preflight"):
            missing_bal: list[str] = []
            if sens_w is None:
                missing_bal.append("reported_sensible_load_w")
            if dt_k is None or dt_k == 0:
                missing_bal.append("supply_delta_t_k")
            if rep_ls is None:
                missing_bal.append("reported_supply_airflow_ls")
            if missing_bal:
                supply_complete = False
                msg = f"{zid}: missing {', '.join(missing_bal)} -> airflow output check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked_flags.append(msg)
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Sensible Load vs Airflow Check",
                        "expected": "sensible_w / (1.21 * dT)",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "L/s",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                assert sens_w is not None and dt_k is not None and rep_ls is not None
                expected_supply_ls = round(sens_w / (air_factor * dt_k), 4)
                total_expected_supply_ls += expected_supply_ls
                total_reported_supply_ls += rep_ls
                if isinstance(vol_m3, float) and vol_m3 > 0:
                    supply_ach = round((rep_ls * 3.6) / vol_m3, 4)
                if expected_supply_ls == 0:
                    diff_pct = 0.0 if rep_ls == 0 else 100.0
                else:
                    diff_pct = round(abs(rep_ls - expected_supply_ls) / expected_supply_ls * 100.0, 4)
                bal_ok = diff_pct <= tol_pct
                if bal_ok:
                    passed_checks += 1
                else:
                    failed_checks += 1
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Sensible Load vs Airflow Balance",
                        "expected": f"{expected_supply_ls} L/s (+/-{tol_pct}%)",
                        "actual": f"{rep_ls} L/s (diff {diff_pct}%)",
                        "unit": "L/s",
                        "status": "PASS (PRELIMINARY)" if bal_ok else "FAIL",
                        "notes": f"Q = {sens_w} W, dT = {dt_k} K, factor = {air_factor} kJ/(m³·K).",
                    }
                )
        elif not missing_geom:
            passed_checks += 1
            check_rows.append(
                {
                    "item_id": zid,
                    "label": f"{zname} — Envelope/Zone Input Package Ready",
                    "expected": "area > 0 & height > 0",
                    "actual": f"volume = {vol_m3} m³",
                    "unit": "m³",
                    "status": "INPUT_PREPARED_ONLY",
                    "notes": "Export prepared zone data to validated commercial HVAC load software.",
                }
            )

        prepared_items.append(
            {
                "zone_id": zid,
                "zone_name": zname,
                "floor_area_m2": _disp(area),
                "ceiling_height_m": _disp(height),
                "room_volume_m3": vol_m3,
                "occupancy_count": _disp(occ),
                "expected_oa_ls": expected_oa_ls,
                "reported_sensible_load_w": _disp(sens_w),
                "supply_delta_t_k": _disp(dt_k),
                "expected_supply_airflow_ls": expected_supply_ls,
                "reported_supply_airflow_ls": _disp(rep_ls),
                "airflow_discrepancy_pct": diff_pct,
                "sensible_w_per_m2": w_per_m2,
                "supply_ach": supply_ach,
            }
        )

    blocked_cnt = len(blocked_flags)
    checks_passed = blocked_cnt == 0 and failed_checks == 0 and passed_checks > 0
    status = "blocked_missing_inputs" if blocked_cnt > 0 else "evaluated"
    return SpecialistEvaluation(
        domain="hvac",
        workflow_mode=mode,
        status=status,
        checks_passed=checks_passed,
        blocked_missing_count=blocked_cnt,
        failed_checks_count=failed_checks,
        equations=[
            "Volume = floor_area_m2 * ceiling_height_m",
            "Expected OA (owner rates) = occupancy_count * oa_ls_per_person + floor_area_m2 * oa_ls_per_m2",
            "Expected Supply Airflow = reported_sensible_load_w / (air_heat_factor * supply_delta_t_k)  [L/s]",
            "Supply ACH = (reported_supply_airflow_ls * 3.6) / room_volume_m3",
        ],
        methodology=(
            "Prepares zone volume & owner-rate ventilation inputs for validated HVAC software and checks software-reported "
            "supply airflows against steady-state sensible heat balance."
        ),
        preliminary_assumptions=[
            PRELIMINARY_ENGINEER_LABEL_EN,
            f"Preliminary sea-level air heat capacity factor rho*cp = {air_factor} kJ/(m³·K); verify project altitude & moisture in HAP/TRACE.",
            f"Preliminary airflow vs sensible load balance tolerance threshold = +/-{tol_pct}% (verify design margin with licensed mechanical engineer).",
            "Outdoor air rates Rp/Ra are NEVER assumed from model memory — supplied strictly by owner / verified standard.",
        ],
        software_recommendation=SOFTWARE_RECOMMENDATIONS["hvac"],
        prepared_items=prepared_items,
        check_rows=check_rows,
        blocked_flags=blocked_flags,
        metrics={
            "zones_count": len(zones),
            "total_floor_area_m2": round(total_area_m2, 4) if volume_complete else NOT_PROVIDED_LABEL,
            "total_volume_m3": round(total_volume_m3, 4) if volume_complete else NOT_PROVIDED_LABEL,
            "total_expected_supply_ls": (
                round(total_expected_supply_ls, 4)
                if mode in ("output_check", "full_preflight") and supply_complete
                else NOT_PROVIDED_LABEL
            ),
            "total_reported_supply_ls": (
                round(total_reported_supply_ls, 4)
                if mode in ("output_check", "full_preflight") and supply_complete
                else NOT_PROVIDED_LABEL
            ),
            "total_expected_oa_ls": round(total_expected_oa_ls, 4) if total_expected_oa_ls > 0 else NOT_PROVIDED_LABEL,
            "passed_checks_count": passed_checks,
            "failed_checks_count": failed_checks,
            "blocked_missing_count": blocked_cnt,
        },
    )


def _evaluate_fire(inputs: dict[str, Any], mode: SpecialistWorkflowMode) -> SpecialistEvaluation:
    """Prepare hydraulic/tank inputs (from owner/verified code density & duration) and check pump/tank software outputs."""
    zones = inputs.get("zones")
    if not isinstance(zones, list) or len(zones) == 0:
        raise SpecialistInputError("Fire protection inputs must include a non-empty 'zones' list.")

    prepared_items: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    blocked_flags: list[str] = []
    passed_checks = 0
    failed_checks = 0

    max_flow_lpm = 0.0
    max_tank_m3 = 0.0
    all_hyd_complete = True

    for idx, z in enumerate(zones, start=1):
        if not isinstance(z, dict):
            raise SpecialistInputError(f"Fire zone #{idx} must be an object.")
        zid = str(z.get("zone_id") or f"F-{idx:02d}").strip()
        zname = str(z.get("zone_name") or f"Fire Zone {idx}").strip()

        area = _opt_nonneg_float(z.get("design_area_m2"), f"{zid}.design_area_m2")
        density = _opt_nonneg_float(z.get("design_density_mm_min"), f"{zid}.design_density_mm_min")
        hose = _opt_nonneg_float(z.get("hose_allowance_lpm"), f"{zid}.hose_allowance_lpm")
        dur = _opt_nonneg_float(z.get("duration_min"), f"{zid}.duration_min")

        pump_flow = _opt_nonneg_float(z.get("reported_pump_flow_lpm"), f"{zid}.reported_pump_flow_lpm")
        avail_bar = _opt_nonneg_float(z.get("reported_available_pressure_bar"), f"{zid}.reported_available_pressure_bar")
        req_bar = _opt_nonneg_float(z.get("required_system_pressure_bar"), f"{zid}.required_system_pressure_bar")
        tank_m3 = _opt_nonneg_float(z.get("reported_tank_volume_m3"), f"{zid}.reported_tank_volume_m3")

        missing_base: list[str] = []
        if area is None or area == 0:
            missing_base.append("design_area_m2")
        if density is None or density == 0:
            missing_base.append("design_density_mm_min")
        if hose is None:
            missing_base.append("hose_allowance_lpm")
        if dur is None or dur == 0:
            missing_base.append("duration_min")

        sprinkler_lpm: Any = NOT_PROVIDED_LABEL
        total_req_lpm: Any = NOT_PROVIDED_LABEL
        req_tank_m3: Any = NOT_PROVIDED_LABEL

        if missing_base:
            all_hyd_complete = False
            msg = f"{zid}: missing {', '.join(missing_base)} -> sprinkler/tank baseline blocked ('{NOT_PROVIDED_LABEL}')"
            blocked_flags.append(msg)
            check_rows.append(
                {
                    "item_id": zid,
                    "label": f"{zname} — Hydraulic Basis Preparation",
                    "expected": "design_area * density + hose & duration",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": "L/min",
                    "status": "blocked_missing_inputs",
                    "notes": msg,
                }
            )
        else:
            assert area is not None and density is not None and hose is not None and dur is not None
            sprinkler_lpm = round(area * density, 4)
            total_req_lpm = round(sprinkler_lpm + hose, 4)
            req_tank_m3 = round((total_req_lpm * dur) / 1000.0, 4)
            max_flow_lpm = max(max_flow_lpm, total_req_lpm)
            max_tank_m3 = max(max_tank_m3, req_tank_m3)
            if mode == "input_preparation":
                passed_checks += 1
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Hydraulic Demand Input Prepared",
                        "expected": f"{total_req_lpm} L/min for {dur} min",
                        "actual": f"Tank basis {req_tank_m3} m³",
                        "unit": "L/min / m³",
                        "status": "INPUT_PREPARED_ONLY",
                        "notes": "Submit area/density & piping model to validated hydraulic calculation software.",
                    }
                )

        if mode in ("output_check", "full_preflight") and not missing_base:
            assert isinstance(total_req_lpm, float) and isinstance(req_tank_m3, float)
            if pump_flow is None:
                msg = f"{zid}: missing reported_pump_flow_lpm -> pump capacity check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked_flags.append(msg)
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Pump Flow Capacity Check",
                        "expected": f">= {total_req_lpm} L/min",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "L/min",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                flow_ok = pump_flow >= total_req_lpm
                passed_checks += 1 if flow_ok else 0
                failed_checks += 0 if flow_ok else 1
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Pump Flow >= Demand (Sprinkler + Hose)",
                        "expected": f">= {total_req_lpm} L/min",
                        "actual": f"{pump_flow} L/min",
                        "unit": "L/min",
                        "status": "PASS (PRELIMINARY)" if flow_ok else "FAIL",
                        "notes": f"Sprinkler={sprinkler_lpm} + Hose={hose}.",
                    }
                )

            if avail_bar is None or req_bar is None:
                msg = f"{zid}: missing available/required pressure_bar -> pressure check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked_flags.append(msg)
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Hydraulic Pressure Margin Check",
                        "expected": "available_bar >= required_bar",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "bar",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                p_margin = round(avail_bar - req_bar, 4)
                p_ok = p_margin >= 0.0
                passed_checks += 1 if p_ok else 0
                failed_checks += 0 if p_ok else 1
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Available Pressure >= Required System Demand",
                        "expected": f">= {req_bar} bar",
                        "actual": f"{avail_bar} bar (margin {p_margin} bar)",
                        "unit": "bar",
                        "status": "PASS (PRELIMINARY)" if p_ok else "FAIL",
                        "notes": "From commercial hydraulic report; verify pump curve intersection.",
                    }
                )

            if tank_m3 is None:
                msg = f"{zid}: missing reported_tank_volume_m3 -> storage check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked_flags.append(msg)
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Fire Tank Usable Storage Check",
                        "expected": f">= {req_tank_m3} m³",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "m³",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                v_ok = tank_m3 >= req_tank_m3
                passed_checks += 1 if v_ok else 0
                failed_checks += 0 if v_ok else 1
                check_rows.append(
                    {
                        "item_id": zid,
                        "label": f"{zname} — Fire Tank Volume >= Required Duration",
                        "expected": f">= {req_tank_m3} m³",
                        "actual": f"{tank_m3} m³",
                        "unit": "m³",
                        "status": "PASS (PRELIMINARY)" if v_ok else "FAIL",
                        "notes": f"Duration = {dur} min.",
                    }
                )

        prepared_items.append(
            {
                "zone_id": zid,
                "zone_name": zname,
                "design_area_m2": _disp(area),
                "design_density_mm_min": _disp(density),
                "sprinkler_flow_lpm": sprinkler_lpm,
                "hose_allowance_lpm": _disp(hose),
                "total_required_flow_lpm": total_req_lpm,
                "duration_min": _disp(dur),
                "required_tank_volume_m3": req_tank_m3,
                "reported_pump_flow_lpm": _disp(pump_flow),
                "reported_available_pressure_bar": _disp(avail_bar),
                "required_system_pressure_bar": _disp(req_bar),
                "reported_tank_volume_m3": _disp(tank_m3),
            }
        )

    blocked_cnt = len(blocked_flags)
    checks_passed = blocked_cnt == 0 and failed_checks == 0 and passed_checks > 0
    status = "blocked_missing_inputs" if blocked_cnt > 0 else "evaluated"
    return SpecialistEvaluation(
        domain="fire",
        workflow_mode=mode,
        status=status,
        checks_passed=checks_passed,
        blocked_missing_count=blocked_cnt,
        failed_checks_count=failed_checks,
        equations=[
            "Sprinkler Flow (Q_spr) = design_area_m2 * design_density_mm_min  [L/min; 1 mm/min * 1 m² = 1 L/min]",
            "Total Demand Flow (Q_tot) = Q_spr + hose_allowance_lpm  [L/min]",
            "Required Tank Storage = (Q_tot * duration_min) / 1000  [m³]",
        ],
        methodology=(
            "Prepares owner-code design area/density/hose/duration demands and verifies commercial fire pump & tank outputs "
            "without performing unvalidated pipe network friction balancing."
        ),
        preliminary_assumptions=[
            PRELIMINARY_ENGINEER_LABEL_EN,
            "Sprinkler design density, remote area, hose allowance, and duration MUST come from owner's verified code / Standards Library (NEVER assumed from hazard titles).",
            "Preliminary sprinkler demand equals nominal area * density prior to hydraulic head balancing & sprinkler over-discharge in commercial software.",
        ],
        software_recommendation=SOFTWARE_RECOMMENDATIONS["fire"],
        prepared_items=prepared_items,
        check_rows=check_rows,
        blocked_flags=blocked_flags,
        metrics={
            "zones_count": len(zones),
            "governing_required_flow_lpm": round(max_flow_lpm, 4) if all_hyd_complete else NOT_PROVIDED_LABEL,
            "governing_required_tank_m3": round(max_tank_m3, 4) if all_hyd_complete else NOT_PROVIDED_LABEL,
            "passed_checks_count": passed_checks,
            "failed_checks_count": failed_checks,
            "blocked_missing_count": blocked_cnt,
        },
    )


def _evaluate_healthcare(inputs: dict[str, Any], mode: SpecialistWorkflowMode) -> SpecialistEvaluation:
    """Prepare hospital room ventilation/medical-gas inputs & check ACH + directional pressure against owner/verified limits ONLY."""
    spaces = inputs.get("spaces")
    if not isinstance(spaces, list) or len(spaces) == 0:
        raise SpecialistInputError("Healthcare inputs must include a non-empty 'spaces' list.")

    med_gases = inputs.get("medical_gas_outlets") or []
    if not isinstance(med_gases, list):
        raise SpecialistInputError("'medical_gas_outlets' must be a list when supplied.")

    prepared_items: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    blocked_flags: list[str] = []
    passed_checks = 0
    failed_checks = 0

    for idx, sp in enumerate(spaces, start=1):
        if not isinstance(sp, dict):
            raise SpecialistInputError(f"Healthcare space #{idx} must be an object.")
        sid = str(sp.get("space_id") or f"HC-{idx:02d}").strip()
        sname = str(sp.get("space_name") or f"Clinical Space {idx}").strip()

        area = _opt_nonneg_float(sp.get("floor_area_m2"), f"{sid}.floor_area_m2")
        height = _opt_nonneg_float(sp.get("ceiling_height_m"), f"{sid}.ceiling_height_m")
        sup_ls = _opt_nonneg_float(sp.get("supply_airflow_ls"), f"{sid}.supply_airflow_ls")
        exh_ls = _opt_nonneg_float(sp.get("exhaust_airflow_ls"), f"{sid}.exhaust_airflow_ls")
        oa_ls = _opt_nonneg_float(sp.get("outdoor_airflow_ls"), f"{sid}.outdoor_airflow_ls")
        req_tot_ach = _opt_nonneg_float(sp.get("required_total_ach"), f"{sid}.required_total_ach")
        req_oa_ach = _opt_nonneg_float(sp.get("required_oa_ach"), f"{sid}.required_oa_ach")
        raw_rel = str(sp.get("required_pressure_relationship") or "").strip().lower()
        req_rel = raw_rel if raw_rel in {"positive", "negative", "neutral"} else None
        meas_pa = _opt_signed_float(sp.get("measured_pressure_diff_pa"), f"{sid}.measured_pressure_diff_pa")
        min_pa = _opt_nonneg_float(sp.get("min_abs_pressure_diff_pa"), f"{sid}.min_abs_pressure_diff_pa")

        missing_geom: list[str] = []
        if area is None or area == 0:
            missing_geom.append("floor_area_m2")
        if height is None or height == 0:
            missing_geom.append("ceiling_height_m")

        vol_m3: Any = NOT_PROVIDED_LABEL
        supply_ach: Any = NOT_PROVIDED_LABEL
        exhaust_ach: Any = NOT_PROVIDED_LABEL
        effective_ach: Any = NOT_PROVIDED_LABEL
        oa_ach: Any = NOT_PROVIDED_LABEL
        air_bal: Any = NOT_PROVIDED_LABEL

        if missing_geom:
            msg = f"{sid}: missing {', '.join(missing_geom)} -> clinical room volume/ACH blocked ('{NOT_PROVIDED_LABEL}')"
            blocked_flags.append(msg)
            check_rows.append(
                {
                    "item_id": sid,
                    "label": f"{sname} — Room Geometry Preparation",
                    "expected": "floor_area_m2 * ceiling_height_m > 0",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": "m³",
                    "status": "blocked_missing_inputs",
                    "notes": msg,
                }
            )
        else:
            assert area is not None and height is not None
            vol_m3 = round(area * height, 4)
            if mode == "input_preparation":
                passed_checks += 1
                check_rows.append(
                    {
                        "item_id": sid,
                        "label": f"{sname} — Clinical Room Geometry Prepared",
                        "expected": "volume_m3 > 0",
                        "actual": f"{vol_m3} m³",
                        "unit": "m³",
                        "status": "INPUT_PREPARED_ONLY",
                        "notes": f"Owner targets: total_ach={_disp(req_tot_ach)}, pressure={req_rel or NOT_PROVIDED_LABEL}.",
                    }
                )

        if mode in ("output_check", "full_preflight") and isinstance(vol_m3, float):
            missing_flows: list[str] = []
            if sup_ls is None:
                missing_flows.append("supply_airflow_ls")
            if exh_ls is None:
                missing_flows.append("exhaust_airflow_ls")
            if oa_ls is None:
                missing_flows.append("outdoor_airflow_ls")
            if missing_flows:
                msg = f"{sid}: missing {', '.join(missing_flows)} -> ACH & balance checks blocked ('{NOT_PROVIDED_LABEL}')"
                blocked_flags.append(msg)
                check_rows.append(
                    {
                        "item_id": sid,
                        "label": f"{sname} — Clinical Airflows Availability",
                        "expected": "supply, exhaust & outdoor L/s",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "L/s",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                assert sup_ls is not None and exh_ls is not None and oa_ls is not None
                supply_ach = round((sup_ls * 3.6) / vol_m3, 4)
                exhaust_ach = round((exh_ls * 3.6) / vol_m3, 4)
                effective_ach = round(max(supply_ach, exhaust_ach), 4)
                oa_ach = round((oa_ls * 3.6) / vol_m3, 4)
                air_bal = round(sup_ls - exh_ls, 4)

                # Total ACH check against owner-supplied threshold (NEVER hardcoded from WHO/FGI memory)
                if req_tot_ach is None:
                    msg = f"{sid}: missing owner-supplied required_total_ach -> Total ACH check blocked ('{NOT_PROVIDED_LABEL}')"
                    blocked_flags.append(msg)
                    check_rows.append(
                        {
                            "item_id": sid,
                            "label": f"{sname} — Total ACH Check",
                            "expected": NOT_PROVIDED_LABEL,
                            "actual": f"{effective_ach} ACH",
                            "unit": "ACH",
                            "status": "blocked_missing_inputs",
                            "notes": msg,
                        }
                    )
                else:
                    tot_ok = effective_ach >= req_tot_ach
                    passed_checks += 1 if tot_ok else 0
                    failed_checks += 0 if tot_ok else 1
                    check_rows.append(
                        {
                            "item_id": sid,
                            "label": f"{sname} — Effective Total ACH >= Target",
                            "expected": f">= {req_tot_ach} ACH",
                            "actual": f"{effective_ach} ACH (Sup={supply_ach}, Exh={exhaust_ach})",
                            "unit": "ACH",
                            "status": "PASS (PRELIMINARY)" if tot_ok else "FAIL",
                            "notes": "Target threshold supplied explicitly by owner / verified standard.",
                        }
                    )

                # OA ACH check against owner-supplied threshold
                if req_oa_ach is None:
                    msg = f"{sid}: missing owner-supplied required_oa_ach -> Outdoor ACH check blocked ('{NOT_PROVIDED_LABEL}')"
                    blocked_flags.append(msg)
                    check_rows.append(
                        {
                            "item_id": sid,
                            "label": f"{sname} — Outdoor Air ACH Check",
                            "expected": NOT_PROVIDED_LABEL,
                            "actual": f"{oa_ach} ACH",
                            "unit": "ACH",
                            "status": "blocked_missing_inputs",
                            "notes": msg,
                        }
                    )
                else:
                    oa_ok = oa_ach >= req_oa_ach
                    passed_checks += 1 if oa_ok else 0
                    failed_checks += 0 if oa_ok else 1
                    check_rows.append(
                        {
                            "item_id": sid,
                            "label": f"{sname} — Outdoor Air ACH >= Target",
                            "expected": f">= {req_oa_ach} ACH",
                            "actual": f"{oa_ach} ACH",
                            "unit": "ACH",
                            "status": "PASS (PRELIMINARY)" if oa_ok else "FAIL",
                            "notes": "Target OA threshold supplied by owner / verified standard.",
                        }
                    )

                # Directional pressure airflow polarity check
                if req_rel is None:
                    msg = f"{sid}: missing required_pressure_relationship -> pressure check blocked ('{NOT_PROVIDED_LABEL}')"
                    blocked_flags.append(msg)
                    check_rows.append(
                        {
                            "item_id": sid,
                            "label": f"{sname} — Directional Pressure Offset",
                            "expected": NOT_PROVIDED_LABEL,
                            "actual": f"balance {air_bal} L/s",
                            "unit": "L/s",
                            "status": "blocked_missing_inputs",
                            "notes": msg,
                        }
                    )
                else:
                    if req_rel == "positive":
                        bal_ok = air_bal > 0
                        exp_txt = "supply > exhaust (+ L/s)"
                    elif req_rel == "negative":
                        bal_ok = air_bal < 0
                        exp_txt = "exhaust > supply (- L/s)"
                    else:
                        tol_bal = 0.05 * max(sup_ls, exh_ls, 1.0)
                        bal_ok = abs(air_bal) <= tol_bal
                        exp_txt = f"|balance| <= {round(tol_bal, 2)} L/s"
                    passed_checks += 1 if bal_ok else 0
                    failed_checks += 0 if bal_ok else 1
                    check_rows.append(
                        {
                            "item_id": sid,
                            "label": f"{sname} — Directional Airflow Balance ({req_rel})",
                            "expected": exp_txt,
                            "actual": f"{air_bal} L/s",
                            "unit": "L/s",
                            "status": "PASS (PRELIMINARY)" if bal_ok else "FAIL",
                            "notes": "Preliminary volumetric airflow offset; verify door cracks & envelope leakage.",
                        }
                    )

                    # Optional differential pressure check (if either Pa field provided, require both)
                    if meas_pa is not None or min_pa is not None:
                        if meas_pa is None or min_pa is None:
                            msg = f"{sid}: incomplete differential pressure fields -> Pa check blocked ('{NOT_PROVIDED_LABEL}')"
                            blocked_flags.append(msg)
                            check_rows.append(
                                {
                                    "item_id": sid,
                                    "label": f"{sname} — Differential Pressure (Pa)",
                                    "expected": _disp(min_pa),
                                    "actual": _disp(meas_pa),
                                    "unit": "Pa",
                                    "status": "blocked_missing_inputs",
                                    "notes": msg,
                                }
                            )
                        else:
                            if req_rel == "positive":
                                pa_ok = meas_pa >= min_pa
                                exp_pa_txt = f">= +{min_pa} Pa"
                            elif req_rel == "negative":
                                pa_ok = meas_pa <= -abs(min_pa)
                                exp_pa_txt = f"<= -{abs(min_pa)} Pa"
                            else:
                                pa_ok = abs(meas_pa) <= abs(min_pa)
                                exp_pa_txt = f"|dP| <= {abs(min_pa)} Pa"
                            passed_checks += 1 if pa_ok else 0
                            failed_checks += 0 if pa_ok else 1
                            check_rows.append(
                                {
                                    "item_id": sid,
                                    "label": f"{sname} — Measured Differential Pressure",
                                    "expected": exp_pa_txt,
                                    "actual": f"{meas_pa} Pa",
                                    "unit": "Pa",
                                    "status": "PASS (PRELIMINARY)" if pa_ok else "FAIL",
                                    "notes": "Owner/test-report Pa reading vs target.",
                                }
                            )

        prepared_items.append(
            {
                "space_id": sid,
                "space_name": sname,
                "floor_area_m2": _disp(area),
                "ceiling_height_m": _disp(height),
                "room_volume_m3": vol_m3,
                "supply_airflow_ls": _disp(sup_ls),
                "exhaust_airflow_ls": _disp(exh_ls),
                "outdoor_airflow_ls": _disp(oa_ls),
                "supply_ach": supply_ach,
                "exhaust_ach": exhaust_ach,
                "effective_ach": effective_ach,
                "oa_ach": oa_ach,
                "air_balance_ls": air_bal,
                "required_total_ach": _disp(req_tot_ach),
                "required_oa_ach": _disp(req_oa_ach),
                "required_pressure_relationship": req_rel or NOT_PROVIDED_LABEL,
                "measured_pressure_diff_pa": _disp(meas_pa),
            }
        )

    # Medical gas outlets diversity preparation (strictly owner-supplied flow_per_outlet & diversity_factor)
    total_med_gas_lpm = 0.0
    med_gas_summary: list[dict[str, Any]] = []
    for g_idx, g in enumerate(med_gases, start=1):
        if not isinstance(g, dict):
            raise SpecialistInputError(f"Medical gas item #{g_idx} must be an object.")
        gname = str(g.get("gas_name") or f"Gas-{g_idx}").strip()
        cnt = _opt_nonneg_float(g.get("outlet_count"), f"{gname}.outlet_count")
        rate = _opt_nonneg_float(g.get("flow_per_outlet_lpm"), f"{gname}.flow_per_outlet_lpm")
        div = _opt_nonneg_float(g.get("diversity_factor"), f"{gname}.diversity_factor")
        if cnt is None or rate is None or div is None:
            msg = f"Medical gas '{gname}': missing outlet_count/flow_per_outlet_lpm/diversity_factor -> '{NOT_PROVIDED_LABEL}'"
            blocked_flags.append(msg)
            med_gas_summary.append(
                {
                    "gas_name": gname,
                    "outlet_count": _disp(cnt),
                    "flow_per_outlet_lpm": _disp(rate),
                    "diversity_factor": _disp(div),
                    "diversified_flow_lpm": NOT_PROVIDED_LABEL,
                }
            )
        else:
            gflow = round(cnt * rate * div, 4)
            total_med_gas_lpm += gflow
            med_gas_summary.append(
                {
                    "gas_name": gname,
                    "outlet_count": cnt,
                    "flow_per_outlet_lpm": rate,
                    "diversity_factor": div,
                    "diversified_flow_lpm": gflow,
                }
            )

    blocked_cnt = len(blocked_flags)
    checks_passed = blocked_cnt == 0 and failed_checks == 0 and passed_checks > 0
    status = "blocked_missing_inputs" if blocked_cnt > 0 else "evaluated"
    return SpecialistEvaluation(
        domain="healthcare",
        workflow_mode=mode,
        status=status,
        checks_passed=checks_passed,
        blocked_missing_count=blocked_cnt,
        failed_checks_count=failed_checks,
        equations=[
            "Room Volume = floor_area_m2 * ceiling_height_m  [m³]",
            "Supply ACH = (supply_airflow_ls * 3.6) / room_volume_m3  |  Exhaust ACH = (exhaust_airflow_ls * 3.6) / room_volume_m3",
            "Effective Total ACH = max(Supply ACH, Exhaust ACH)  |  OA ACH = (outdoor_airflow_ls * 3.6) / room_volume_m3",
            "Volumetric Balance = supply_airflow_ls - exhaust_airflow_ls  [L/s]",
            "Medical Gas Flow = outlet_count * flow_per_outlet_lpm * diversity_factor  [L/min]",
        ],
        methodology=(
            "Prepares clinical space volumes, medical gas outlet demand inputs, and verifies ACH & room pressure offset polarity "
            "against owner-supplied / verified-standard targets ONLY (never inventing WHO/FGI limits from model memory)."
        ),
        preliminary_assumptions=[
            PRELIMINARY_ENGINEER_LABEL_EN,
            f"WHO / FGI / healthcare requirements apply ONLY when linked to owner Standards Library or reviewed ResearchSource; otherwise '{NO_VERIFIED_STANDARD_LABEL}'.",
            "Target ACH, pressure relationship (+/-/neutral), differential Pa limits, and medical-gas diversity factors MUST be supplied explicitly per clinical program.",
            "Preliminary volumetric neutral tolerance is +/-5% of peak room flow; confirm air balancing & HEPA pressure drops with clinical commissioning team.",
        ],
        software_recommendation=SOFTWARE_RECOMMENDATIONS["healthcare"],
        prepared_items=prepared_items,
        check_rows=check_rows,
        blocked_flags=blocked_flags,
        metrics={
            "spaces_count": len(spaces),
            "medical_gas_items": med_gas_summary,
            "total_diversified_medical_gas_lpm": round(total_med_gas_lpm, 4) if med_gases and blocked_cnt == 0 else NOT_PROVIDED_LABEL,
            "passed_checks_count": passed_checks,
            "failed_checks_count": failed_checks,
            "blocked_missing_count": blocked_cnt,
        },
    )


def evaluate_specialist_assessment(
    *,
    domain: SpecialistDomain,
    workflow_mode: SpecialistWorkflowMode,
    inputs: dict[str, Any],
) -> SpecialistEvaluation:
    """Dispatch deterministic Step 18 preparation & output checks across HVAC, Fire, and Healthcare (0 AI tokens)."""
    if domain == "hvac":
        return _evaluate_hvac(inputs, workflow_mode)
    if domain == "fire":
        return _evaluate_fire(inputs, workflow_mode)
    if domain == "healthcare":
        return _evaluate_healthcare(inputs, workflow_mode)
    raise SpecialistInputError(f"Unsupported specialist domain: {domain}")


class _AiNarrativePayload(BaseModel):
    summary_prose: str = Field(..., min_length=10, max_length=2500)


def draft_specialist_narrative_with_ai(
    db: Session,
    secret_store: SecretStore,
    *,
    domain: SpecialistDomain,
    title: str,
    evaluation: SpecialistEvaluation,
    standards_summary: str,
    complexity: TaskComplexity = "fast",
    project_id: str | None = None,
    client_factory: Callable[[str], Any] | None = None,
) -> tuple[str, TokenUsage]:
    """Optional Gemini prose summary ONLY (0 arithmetic changes, blocks unverified standard fabrications)."""
    prompt = {
        "task": (
            "Write a brief non-binding engineering review summary of the deterministic preflight check results below. "
            "Do NOT compute, change, or invent numbers, standard codes, clause numbers, or edition years. "
            "Remind the reader that final loads/hydraulics require validated commercial software and licensed engineer sign-off."
        ),
        "domain": domain,
        "title": title,
        "standards_context": standards_summary,
        "deterministic_metrics": evaluation.metrics,
        "blocked_flags": evaluation.blocked_flags[:10],
        "software_recommendation": evaluation.software_recommendation,
    }
    config = _load_provider_config(db)
    daily_usage, monthly_usage = _summarize_usage(db)
    prompt_json = json.dumps(prompt, ensure_ascii=False)
    est_tokens = estimate_prompt_tokens(prompt_json)
    if config.usage_limits.daily_token_limit and (daily_usage.total_tokens + est_tokens) > config.usage_limits.daily_token_limit:
        raise ProviderUsageLimitError("Daily token limit would be exceeded by optional Step 18 AI summary.")
    if config.usage_limits.monthly_token_limit and (monthly_usage.total_tokens + est_tokens) > config.usage_limits.monthly_token_limit:
        raise ProviderUsageLimitError("Monthly token limit would be exceeded by optional Step 18 AI summary.")

    req = LLMRequest(
        prompt=prompt_json,
        system_instruction="Summarize deterministic preflight metrics concisely in plain language without inventing codes or altering numbers.",
        complexity=complexity,
        temperature=0.0,
        response_schema=_AiNarrativePayload,
    )
    resp = execute_provider_request(
        db,
        secret_store,
        req,
        client_factory=client_factory,
        project_id=project_id,
    )
    try:
        parsed = _AiNarrativePayload.model_validate(resp.parsed_json)
    except ValidationError as exc:
        raise ProviderResponseError(
            f"Specialist AI narrative validation failed: {exc.errors()[0].get('msg', 'invalid schema')}"
        ) from exc

    return sanitize_secret_text(parsed.summary_prose.strip()), resp.usage


def get_synthetic_specialist_presets() -> list[SpecialistPresetOut]:
    """Return synthetic HVAC, Fire & Healthcare fixtures ONLY (all thresholds labelled preliminary; zero client data)."""
    return [
        SpecialistPresetOut(
            key="hvac_preflight_1",
            domain="hvac",
            workflow_mode="full_preflight",
            label_en="Synthetic HVAC Clinic Zone Check (60 m², 6.05 kW sensible, 500 L/s — Synthetic)",
            label_ar="نموذج فحص وتجهيز التكييف (60 م²، حمل محسوس 6.05 ك.واط — تمثيلي أولي)",
            inputs={
                "air_heat_factor_kw_per_m3s": 1.21,
                "airflow_tolerance_pct": 5.0,
                "zones": [
                    {
                        "zone_id": "Z-101",
                        "zone_name": "Synthetic Examination Suite A",
                        "floor_area_m2": 60.0,
                        "ceiling_height_m": 3.2,
                        "occupancy_count": 8,
                        "oa_ls_per_person": 7.5,
                        "oa_ls_per_m2": 0.6,
                        "reported_sensible_load_w": 6050.0,
                        "supply_delta_t_k": 10.0,
                        "reported_supply_airflow_ls": 500.0,
                        "reported_outdoor_airflow_ls": 100.0,
                    },
                    {
                        "zone_id": "Z-102",
                        "zone_name": "Synthetic Reception Waiting",
                        "floor_area_m2": 45.0,
                        "ceiling_height_m": 3.0,
                        "occupancy_count": 10,
                        "oa_ls_per_person": 3.8,
                        "oa_ls_per_m2": 0.3,
                        "reported_sensible_load_w": 3630.0,
                        "supply_delta_t_k": 10.0,
                        "reported_supply_airflow_ls": 300.0,
                        "reported_outdoor_airflow_ls": 55.0,
                    },
                ],
            },
        ),
        SpecialistPresetOut(
            key="fire_preflight_1",
            domain="fire",
            workflow_mode="full_preflight",
            label_en="Synthetic Fire Pump & Tank Demand Check (200 m², 4.1 mm/min, 60 min — Synthetic)",
            label_ar="نموذج فحص وتجهيز الحريق والمضخة والخزان (200 م²، 60 دقيقة — تمثيلي أولي)",
            inputs={
                "zones": [
                    {
                        "zone_id": "FZ-01",
                        "zone_name": "Synthetic Ground Wing Sprinkler Zone",
                        "design_area_m2": 200.0,
                        "design_density_mm_min": 4.1,
                        "hose_allowance_lpm": 380.0,
                        "duration_min": 60.0,
                        "reported_pump_flow_lpm": 1250.0,
                        "reported_available_pressure_bar": 6.2,
                        "required_system_pressure_bar": 5.5,
                        "reported_tank_volume_m3": 75.0,
                    }
                ],
            },
        ),
        SpecialistPresetOut(
            key="healthcare_preflight_1",
            domain="healthcare",
            workflow_mode="full_preflight",
            label_en="Synthetic Healthcare Room Airflow & Pressure Check (Negative Isolation + Positive Clean — Synthetic)",
            label_ar="نموذج فحص الغرف الصحية والضغط الموجب/السالب والغازات (تمثيلي أولي)",
            inputs={
                "spaces": [
                    {
                        "space_id": "HC-ISO-01",
                        "space_name": "Synthetic Negative Isolation Room",
                        "floor_area_m2": 20.0,
                        "ceiling_height_m": 3.0,
                        "supply_airflow_ls": 180.0,
                        "exhaust_airflow_ls": 220.0,
                        "outdoor_airflow_ls": 50.0,
                        "required_total_ach": 12.0,
                        "required_oa_ach": 2.0,
                        "required_pressure_relationship": "negative",
                        "measured_pressure_diff_pa": -5.0,
                        "min_abs_pressure_diff_pa": 2.5,
                    },
                    {
                        "space_id": "HC-CLN-02",
                        "space_name": "Synthetic Clean Procedure Room",
                        "floor_area_m2": 30.0,
                        "ceiling_height_m": 3.0,
                        "supply_airflow_ls": 210.0,
                        "exhaust_airflow_ls": 165.0,
                        "outdoor_airflow_ls": 75.0,
                        "required_total_ach": 6.0,
                        "required_oa_ach": 2.0,
                        "required_pressure_relationship": "positive",
                        "measured_pressure_diff_pa": 4.0,
                        "min_abs_pressure_diff_pa": 2.5,
                    },
                ],
                "medical_gas_outlets": [
                    {
                        "gas_name": "Synthetic O2",
                        "outlet_count": 4,
                        "flow_per_outlet_lpm": 20.0,
                        "diversity_factor": 0.75,
                    }
                ],
            },
        ),
    ]
