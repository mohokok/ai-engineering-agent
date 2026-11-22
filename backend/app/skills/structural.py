"""Step 19 pure deterministic Structural Assessment Support & Input/Output Checking library (0 AI tokens default; NEVER designs members or certifies safety)."""

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
from app.schemas.specialist import NOT_PROVIDED_LABEL, NO_VERIFIED_STANDARD_LABEL
from app.schemas.structural import (
    PRELIMINARY_STRUCTURAL_LABEL_EN,
    STRUCTURAL_SOFTWARE_RECOMMENDATION,
    StructuralAssessmentType,
    StructuralPresetOut,
)
from app.services.provider_settings import _load_provider_config, _summarize_usage, execute_provider_request
from app.services.research import estimate_prompt_tokens


class StructuralInputError(ValueError):
    """Raised when structural input structure or numeric field types are invalid."""


@dataclass(frozen=True)
class StructuralEvaluation:
    """Deterministic output of Step 19 structural takedown, combination & statics I/O checks."""

    assessment_type: StructuralAssessmentType
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


def _opt_nonneg(val: Any, name: str) -> float | None:
    if val is None or val == "" or (isinstance(val, str) and val.strip().lower() == NOT_PROVIDED_LABEL):
        return None
    try:
        num = float(val)
    except (TypeError, ValueError) as exc:
        raise StructuralInputError(f"Invalid numeric value for '{name}': {val!r}") from exc
    if num < 0:
        raise StructuralInputError(f"Field '{name}' cannot be negative (got {num}).")
    return num


def _opt_signed(val: Any, name: str) -> float | None:
    if val is None or val == "" or (isinstance(val, str) and val.strip().lower() == NOT_PROVIDED_LABEL):
        return None
    try:
        return float(val)
    except (TypeError, ValueError) as exc:
        raise StructuralInputError(f"Invalid signed numeric value for '{name}': {val!r}") from exc


def _disp(val: Any) -> Any:
    return NOT_PROVIDED_LABEL if val is None else val


def _evaluate_takedown(
    elements: list[Any],
    *,
    tol_pct: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int, int, float, bool]:
    prepared: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed = 0
    failed = 0
    sum_factored_kn = 0.0
    takedown_complete = True

    for idx, raw in enumerate(elements, start=1):
        if not isinstance(raw, dict):
            raise StructuralInputError(f"Takedown element #{idx} must be an object.")
        eid = str(raw.get("element_id") or f"C-{idx:02d}").strip()
        ename = str(raw.get("element_name") or f"Column / Wall {idx}").strip()

        area = _opt_nonneg(raw.get("tributary_area_m2"), f"{eid}.tributary_area_m2")
        floors_raw = _opt_nonneg(raw.get("floors_count"), f"{eid}.floors_count")
        floors = int(floors_raw) if floors_raw is not None else None
        dl_kpa = _opt_nonneg(raw.get("dead_load_kpa"), f"{eid}.dead_load_kpa")
        ll_kpa = _opt_nonneg(raw.get("live_load_kpa"), f"{eid}.live_load_kpa")
        d_fac = _opt_nonneg(raw.get("dead_factor"), f"{eid}.dead_factor")
        l_fac = _opt_nonneg(raw.get("live_factor"), f"{eid}.live_factor")
        self_wt = _opt_nonneg(raw.get("additional_dead_kn"), f"{eid}.additional_dead_kn") or 0.0
        rep_kn = _opt_nonneg(raw.get("reported_factored_axial_kn"), f"{eid}.reported_factored_axial_kn")
        cap_kn = _opt_nonneg(raw.get("owner_axial_capacity_kn"), f"{eid}.owner_axial_capacity_kn")

        missing: list[str] = []
        if area is None or area == 0:
            missing.append("tributary_area_m2")
        if floors is None or floors <= 0:
            missing.append("floors_count")
        if dl_kpa is None:
            missing.append("dead_load_kpa")
        if ll_kpa is None:
            missing.append("live_load_kpa")
        if d_fac is None:
            missing.append("dead_factor")
        if l_fac is None:
            missing.append("live_factor")

        unfactored_d: Any = NOT_PROVIDED_LABEL
        unfactored_l: Any = NOT_PROVIDED_LABEL
        factored_kn: Any = NOT_PROVIDED_LABEL
        util_ratio: Any = NOT_PROVIDED_LABEL

        if missing:
            takedown_complete = False
            msg = f"{eid}: missing owner takedown/factor field(s) {', '.join(missing)} -> '{NOT_PROVIDED_LABEL}'"
            blocked.append(msg)
            checks.append(
                {
                    "item_id": eid,
                    "label": f"{ename} — Load Takedown Readiness",
                    "expected": "tributary_area, floors, D/L kPa & owner factors",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": "kN",
                    "status": "blocked_missing_inputs",
                    "notes": msg,
                }
            )
        else:
            assert area is not None and floors is not None and dl_kpa is not None and ll_kpa is not None and d_fac is not None and l_fac is not None
            unfactored_d = round(floors * area * dl_kpa + self_wt, 4)
            unfactored_l = round(floors * area * ll_kpa, 4)
            factored_kn = round(d_fac * unfactored_d + l_fac * unfactored_l, 4)
            sum_factored_kn += factored_kn

            if rep_kn is not None:
                disc = 0.0 if factored_kn == 0 and rep_kn == 0 else (100.0 if factored_kn == 0 else round(abs(rep_kn - factored_kn) / factored_kn * 100.0, 4))
                match_ok = disc <= tol_pct
                passed += 1 if match_ok else 0
                failed += 0 if match_ok else 1
                checks.append(
                    {
                        "item_id": eid,
                        "label": f"{ename} — Software vs Hand Axial Takedown",
                        "expected": f"{factored_kn} kN (+/-{tol_pct}%)",
                        "actual": f"{rep_kn} kN (diff {disc}%)",
                        "unit": "kN",
                        "status": "PASS (PRELIMINARY)" if match_ok else "FAIL",
                        "notes": f"PRELIMINARY: {d_fac}*({unfactored_d}) + {l_fac}*({unfactored_l}).",
                    }
                )

            if cap_kn is None or cap_kn == 0:
                msg = f"{eid}: missing owner_axial_capacity_kn -> axial utilization check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked.append(msg)
                checks.append(
                    {
                        "item_id": eid,
                        "label": f"{ename} — Axial Demand / Owner Capacity Ratio",
                        "expected": "utilization <= 1.00",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "ratio",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                util_ratio = round(factored_kn / cap_kn, 4)
                cap_ok = util_ratio <= 1.0
                passed += 1 if cap_ok else 0
                failed += 0 if cap_ok else 1
                checks.append(
                    {
                        "item_id": eid,
                        "label": f"{ename} — Axial Demand / Owner Capacity Ratio",
                        "expected": "<= 1.00 (vs owner capacity)",
                        "actual": f"{util_ratio} ({factored_kn} / {cap_kn} kN)",
                        "unit": "ratio",
                        "status": "PASS (PRELIMINARY)" if cap_ok else "FAIL",
                        "notes": "Ratio vs owner capacity ONLY — does NOT size rebar/section or certify safety.",
                    }
                )

        prepared.append(
            {
                "kind": "takedown",
                "item_id": eid,
                "label": ename,
                "tributary_area_m2": _disp(area),
                "floors_count": _disp(floors),
                "dead_load_kpa": _disp(dl_kpa),
                "live_load_kpa": _disp(ll_kpa),
                "dead_factor": _disp(d_fac),
                "live_factor": _disp(l_fac),
                "unfactored_dead_kn": unfactored_d,
                "unfactored_live_kn": unfactored_l,
                "factored_axial_kn": factored_kn,
                "reported_factored_axial_kn": _disp(rep_kn),
                "owner_axial_capacity_kn": _disp(cap_kn),
                "axial_utilization_ratio": util_ratio,
            }
        )

    return prepared, checks, blocked, passed, failed, round(sum_factored_kn, 4), takedown_complete


def _evaluate_load_combinations(
    combos_payload: list[Any],
    *,
    tol_pct: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int, int]:
    prepared: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed = 0
    failed = 0

    for idx, entry in enumerate(combos_payload, start=1):
        if not isinstance(entry, dict):
            raise StructuralInputError(f"Load combination entry #{idx} must be an object.")
        cid = str(entry.get("member_id") or f"M-{idx:02d}").strip()
        cname = str(entry.get("member_name") or f"Member {idx}").strip()
        action_unit = str(entry.get("unit") or "kN").strip()
        actions = entry.get("unfactored_actions")
        combos = entry.get("combinations")
        rep_gov = _opt_signed(entry.get("reported_governing_value"), f"{cid}.reported_governing_value")
        owner_cap = _opt_nonneg(entry.get("owner_capacity"), f"{cid}.owner_capacity")

        if not isinstance(actions, dict) or not actions or not isinstance(combos, list) or not combos:
            msg = f"{cid}: missing unfactored_actions or owner combinations -> '{NOT_PROVIDED_LABEL}'"
            blocked.append(msg)
            checks.append(
                {
                    "item_id": cid,
                    "label": f"{cname} — Load Combination Envelope",
                    "expected": "owner factors & unfactored load cases",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": action_unit,
                    "status": "blocked_missing_inputs",
                    "notes": msg,
                }
            )
            prepared.append({"kind": "combination", "item_id": cid, "label": cname, "governing_value": NOT_PROVIDED_LABEL})
            continue

        parsed_actions: dict[str, float] = {}
        for k, v in actions.items():
            pv = _opt_signed(v, f"{cid}.unfactored_actions.{k}")
            if pv is None:
                msg = f"{cid}: load case '{k}' is '{NOT_PROVIDED_LABEL}'"
                blocked.append(msg)
            else:
                parsed_actions[str(k)] = pv

        gov_val: float | None = None
        gov_name: str = ""
        combo_results: list[dict[str, Any]] = []
        any_combo_blocked = False

        for c_i, cmb in enumerate(combos, start=1):
            if not isinstance(cmb, dict) or not isinstance(cmb.get("factors"), dict) or not cmb.get("factors"):
                raise StructuralInputError(f"{cid} combination #{c_i} must provide explicit owner 'factors' dict.")
            c_name = str(cmb.get("combo_name") or f"Combo-{c_i}").strip()
            factors: dict[str, Any] = cmb["factors"]
            total_c = 0.0
            c_missing: list[str] = []
            for lk, lf in factors.items():
                lf_val = _opt_signed(lf, f"{cid}.{c_name}.factors.{lk}")
                if lf_val is None:
                    c_missing.append(f"factor:{lk}")
                    continue
                if str(lk) not in parsed_actions:
                    c_missing.append(f"load_case:{lk}")
                    continue
                total_c += lf_val * parsed_actions[str(lk)]

            if c_missing:
                any_combo_blocked = True
                blocked.append(f"{cid}/{c_name}: missing {', '.join(c_missing)} -> '{NOT_PROVIDED_LABEL}'")
                combo_results.append({"combo_name": c_name, "value": NOT_PROVIDED_LABEL})
            else:
                r_tot = round(total_c, 4)
                combo_results.append({"combo_name": c_name, "value": r_tot})
                if gov_val is None or abs(r_tot) > abs(gov_val):
                    gov_val = r_tot
                    gov_name = c_name

        if any_combo_blocked or gov_val is None:
            checks.append(
                {
                    "item_id": cid,
                    "label": f"{cname} — Load Combination Governing Check",
                    "expected": "complete owner load factors",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": action_unit,
                    "status": "blocked_missing_inputs",
                    "notes": "Missing load case value or combination factor blocked combination envelope.",
                }
            )
            prepared.append(
                {
                    "kind": "combination",
                    "item_id": cid,
                    "label": cname,
                    "governing_combo": NOT_PROVIDED_LABEL,
                    "governing_value": NOT_PROVIDED_LABEL,
                    "combo_breakdown": combo_results,
                }
            )
        else:
            if rep_gov is not None:
                denom = abs(gov_val)
                disc = 0.0 if denom == 0 and rep_gov == 0 else (100.0 if denom == 0 else round(abs(rep_gov - gov_val) / denom * 100.0, 4))
                m_ok = disc <= tol_pct
                passed += 1 if m_ok else 0
                failed += 0 if m_ok else 1
                checks.append(
                    {
                        "item_id": cid,
                        "label": f"{cname} — Governing Combo Software Check ({gov_name})",
                        "expected": f"{gov_val} {action_unit} (+/-{tol_pct}%)",
                        "actual": f"{rep_gov} {action_unit} (diff {disc}%)",
                        "unit": action_unit,
                        "status": "PASS (PRELIMINARY)" if m_ok else "FAIL",
                        "notes": "Recomputed purely from owner-supplied load factors.",
                    }
                )
            else:
                passed += 1
                checks.append(
                    {
                        "item_id": cid,
                        "label": f"{cname} — Governing Owner Combination ({gov_name})",
                        "expected": "owner linear combinations evaluated",
                        "actual": f"{gov_val} {action_unit}",
                        "unit": action_unit,
                        "status": "PASS (PRELIMINARY)",
                        "notes": f"Owner combinations evaluated ({len(combo_results)} cases).",
                    }
                )

            if owner_cap is not None and owner_cap > 0:
                ratio = round(abs(gov_val) / owner_cap, 4)
                r_ok = ratio <= 1.0
                passed += 1 if r_ok else 0
                failed += 0 if r_ok else 1
                checks.append(
                    {
                        "item_id": cid,
                        "label": f"{cname} — Governing Action / Owner Capacity",
                        "expected": "<= 1.00",
                        "actual": f"{ratio} ({abs(gov_val)} / {owner_cap} {action_unit})",
                        "unit": "ratio",
                        "status": "PASS (PRELIMINARY)" if r_ok else "FAIL",
                        "notes": "Owner-supplied capacity ratio check only.",
                    }
                )

            prepared.append(
                {
                    "kind": "combination",
                    "item_id": cid,
                    "label": cname,
                    "governing_combo": gov_name,
                    "governing_value": gov_val,
                    "reported_governing_value": _disp(rep_gov),
                    "unit": action_unit,
                    "combo_breakdown": combo_results,
                }
            )

    return prepared, checks, blocked, passed, failed


def _evaluate_beams(
    beams: list[Any],
    *,
    tol_pct: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], int, int]:
    prepared: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    blocked: list[str] = []
    passed = 0
    failed = 0

    for idx, b in enumerate(beams, start=1):
        if not isinstance(b, dict):
            raise StructuralInputError(f"Beam entry #{idx} must be an object.")
        bid = str(b.get("beam_id") or f"B-{idx:02d}").strip()
        bname = str(b.get("beam_name") or f"Simple Span {idx}").strip()
        sup_cond = str(b.get("support_condition") or "simply_supported_udl").strip().lower()
        if sup_cond not in {"simply_supported_udl", "simply_supported_midspan_point", "cantilever_udl"}:
            raise StructuralInputError(f"Unsupported support_condition '{sup_cond}' on {bid}.")

        span_m = _opt_nonneg(b.get("span_m"), f"{bid}.span_m")
        factored_load = _opt_nonneg(b.get("factored_load_kn_or_knm"), f"{bid}.factored_load_kn_or_knm")
        service_load = _opt_nonneg(b.get("service_load_kn_or_knm"), f"{bid}.service_load_kn_or_knm")
        ei_kn_m2 = _opt_nonneg(b.get("ei_kn_m2"), f"{bid}.ei_kn_m2")
        if ei_kn_m2 is None:
            e_mpa = _opt_nonneg(b.get("e_mpa"), f"{bid}.e_mpa")
            i_mm4 = _opt_nonneg(b.get("i_mm4"), f"{bid}.i_mm4")
            if e_mpa is not None and i_mm4 is not None and e_mpa > 0 and i_mm4 > 0:
                ei_kn_m2 = round(e_mpa * i_mm4 * 1e-9, 4)

        rep_r = _opt_nonneg(b.get("reported_reaction_kn"), f"{bid}.reported_reaction_kn")
        rep_v = _opt_nonneg(b.get("reported_shear_kn"), f"{bid}.reported_shear_kn")
        rep_m = _opt_nonneg(b.get("reported_moment_kn_m"), f"{bid}.reported_moment_kn_m")
        rep_d = _opt_nonneg(b.get("reported_deflection_mm"), f"{bid}.reported_deflection_mm")

        cap_m = _opt_nonneg(b.get("owner_moment_capacity_kn_m"), f"{bid}.owner_moment_capacity_kn_m")
        cap_v = _opt_nonneg(b.get("owner_shear_capacity_kn"), f"{bid}.owner_shear_capacity_kn")
        lim_d = _opt_nonneg(b.get("owner_deflection_limit_mm"), f"{bid}.owner_deflection_limit_mm")

        missing_base: list[str] = []
        if span_m is None or span_m == 0:
            missing_base.append("span_m")
        if factored_load is None:
            missing_base.append("factored_load_kn_or_knm")

        r_kn: Any = NOT_PROVIDED_LABEL
        v_kn: Any = NOT_PROVIDED_LABEL
        m_knm: Any = NOT_PROVIDED_LABEL
        d_mm: Any = NOT_PROVIDED_LABEL

        if missing_base:
            msg = f"{bid}: missing {', '.join(missing_base)} -> beam statics blocked ('{NOT_PROVIDED_LABEL}')"
            blocked.append(msg)
            checks.append(
                {
                    "item_id": bid,
                    "label": f"{bname} — Simple Span Statics",
                    "expected": "span_m > 0 & factored_load",
                    "actual": NOT_PROVIDED_LABEL,
                    "unit": "kN / kN·m",
                    "status": "blocked_missing_inputs",
                    "notes": msg,
                }
            )
        else:
            assert span_m is not None and factored_load is not None
            if sup_cond == "simply_supported_udl":
                r_kn = round(factored_load * span_m / 2.0, 4)
                v_kn = r_kn
                m_knm = round(factored_load * (span_m**2) / 8.0, 4)
            elif sup_cond == "simply_supported_midspan_point":
                r_kn = round(factored_load / 2.0, 4)
                v_kn = r_kn
                m_knm = round(factored_load * span_m / 4.0, 4)
            else:
                r_kn = round(factored_load * span_m, 4)
                v_kn = r_kn
                m_knm = round(factored_load * (span_m**2) / 2.0, 4)

            def _cmp_soft(lbl: str, expected_v: float, rep_val: float | None, unit_s: str) -> None:
                nonlocal passed, failed
                if rep_val is None:
                    return
                disc = 0.0 if expected_v == 0 and rep_val == 0 else (100.0 if expected_v == 0 else round(abs(rep_val - expected_v) / expected_v * 100.0, 4))
                ok = disc <= tol_pct
                passed += 1 if ok else 0
                failed += 0 if ok else 1
                checks.append(
                    {
                        "item_id": bid,
                        "label": f"{bname} — {lbl}",
                        "expected": f"{expected_v} {unit_s} (+/-{tol_pct}%)",
                        "actual": f"{rep_val} {unit_s} (diff {disc}%)",
                        "unit": unit_s,
                        "status": "PASS (PRELIMINARY)" if ok else "FAIL",
                        "notes": f"Closed-form Euler-Bernoulli statics check ({sup_cond}).",
                    }
                )

            _cmp_soft("Reaction R vs Software", r_kn, rep_r, "kN")
            _cmp_soft("Max Shear V vs Software", v_kn, rep_v, "kN")
            _cmp_soft("Max Moment M vs Software", m_knm, rep_m, "kN·m")

            # Moment & shear ratios against owner-supplied capacities (missing blocks cleanly!)
            if cap_m is None or cap_m == 0:
                msg = f"{bid}: missing owner_moment_capacity_kn_m -> moment check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked.append(msg)
                checks.append(
                    {
                        "item_id": bid,
                        "label": f"{bname} — Moment / Owner Capacity Ratio",
                        "expected": "<= 1.00",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "ratio",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                m_ratio = round(m_knm / cap_m, 4)
                m_ok = m_ratio <= 1.0
                passed += 1 if m_ok else 0
                failed += 0 if m_ok else 1
                checks.append(
                    {
                        "item_id": bid,
                        "label": f"{bname} — Moment Demand / Owner Capacity",
                        "expected": "<= 1.00",
                        "actual": f"{m_ratio} ({m_knm} / {cap_m} kN·m)",
                        "unit": "ratio",
                        "status": "PASS (PRELIMINARY)" if m_ok else "FAIL",
                        "notes": "Does NOT select reinforcement/section; verifies demand <= owner capacity.",
                    }
                )

            if cap_v is None or cap_v == 0:
                msg = f"{bid}: missing owner_shear_capacity_kn -> shear check blocked ('{NOT_PROVIDED_LABEL}')"
                blocked.append(msg)
                checks.append(
                    {
                        "item_id": bid,
                        "label": f"{bname} — Shear Demand / Owner Capacity Ratio",
                        "expected": "<= 1.00",
                        "actual": NOT_PROVIDED_LABEL,
                        "unit": "ratio",
                        "status": "blocked_missing_inputs",
                        "notes": msg,
                    }
                )
            else:
                v_ratio = round(v_kn / cap_v, 4)
                v_ok = v_ratio <= 1.0
                passed += 1 if v_ok else 0
                failed += 0 if v_ok else 1
                checks.append(
                    {
                        "item_id": bid,
                        "label": f"{bname} — Shear Demand / Owner Capacity",
                        "expected": "<= 1.00",
                        "actual": f"{v_ratio} ({v_kn} / {cap_v} kN)",
                        "unit": "ratio",
                        "status": "PASS (PRELIMINARY)" if v_ok else "FAIL",
                        "notes": "Owner shear capacity ratio check only.",
                    }
                )

            # Deflection check if service load or limit or EI provided (if any deflection field given, all needed!)
            if any(v is not None for v in (service_load, ei_kn_m2, lim_d, rep_d)):
                miss_d: list[str] = []
                if service_load is None:
                    miss_d.append("service_load_kn_or_knm")
                if ei_kn_m2 is None or ei_kn_m2 == 0:
                    miss_d.append("ei_kn_m2 (or e_mpa & i_mm4)")
                if lim_d is None:
                    miss_d.append("owner_deflection_limit_mm")
                if miss_d:
                    msg = f"{bid}: incomplete deflection inputs ({', '.join(miss_d)}) -> '{NOT_PROVIDED_LABEL}'"
                    blocked.append(msg)
                    checks.append(
                        {
                            "item_id": bid,
                            "label": f"{bname} — Elastic Deflection Check",
                            "expected": "<= owner_deflection_limit_mm",
                            "actual": NOT_PROVIDED_LABEL,
                            "unit": "mm",
                            "status": "blocked_missing_inputs",
                            "notes": msg,
                        }
                    )
                else:
                    assert service_load is not None and ei_kn_m2 is not None and lim_d is not None
                    if sup_cond == "simply_supported_udl":
                        d_mm = round((5.0 * service_load * (span_m**4)) / (384.0 * ei_kn_m2) * 1000.0, 4)
                    elif sup_cond == "simply_supported_midspan_point":
                        d_mm = round((service_load * (span_m**3)) / (48.0 * ei_kn_m2) * 1000.0, 4)
                    else:
                        d_mm = round((service_load * (span_m**4)) / (8.0 * ei_kn_m2) * 1000.0, 4)
                    _cmp_soft("Deflection d vs Software", d_mm, rep_d, "mm")
                    d_ok = d_mm <= lim_d
                    passed += 1 if d_ok else 0
                    failed += 0 if d_ok else 1
                    checks.append(
                        {
                            "item_id": bid,
                            "label": f"{bname} — Elastic Deflection <= Owner Limit",
                            "expected": f"<= {lim_d} mm",
                            "actual": f"{d_mm} mm",
                            "unit": "mm",
                            "status": "PASS (PRELIMINARY)" if d_ok else "FAIL",
                            "notes": f"Elastic uncracked EI={ei_kn_m2} kN·m² (verify cracking/creep in software).",
                        }
                    )

        prepared.append(
            {
                "kind": "beam_statics",
                "item_id": bid,
                "label": bname,
                "support_condition": sup_cond,
                "span_m": _disp(span_m),
                "factored_load_kn_or_knm": _disp(factored_load),
                "reaction_kn": r_kn,
                "max_shear_kn": v_kn,
                "max_moment_kn_m": m_knm,
                "ei_kn_m2": _disp(ei_kn_m2),
                "elastic_deflection_mm": d_mm,
                "reported_moment_kn_m": _disp(rep_m),
                "owner_moment_capacity_kn_m": _disp(cap_m),
                "owner_shear_capacity_kn": _disp(cap_v),
                "owner_deflection_limit_mm": _disp(lim_d),
            }
        )

    return prepared, checks, blocked, passed, failed


def evaluate_structural_assessment(
    *,
    assessment_type: StructuralAssessmentType,
    inputs: dict[str, Any],
) -> StructuralEvaluation:
    """Execute deterministic Step 19 structural takedown, combination & statics checks (0 AI tokens)."""
    tol_pct = _opt_nonneg(inputs.get("discrepancy_tolerance_pct"), "discrepancy_tolerance_pct")
    if tol_pct is None:
        tol_pct = 2.0

    takedowns = inputs.get("takedown_elements") or []
    combos = inputs.get("load_combinations") or []
    beams = inputs.get("beams") or []

    if not isinstance(takedowns, list) or not isinstance(combos, list) or not isinstance(beams, list):
        raise StructuralInputError("'takedown_elements', 'load_combinations', and 'beams' must be lists.")

    if assessment_type == "takedown_check" and not takedowns:
        raise StructuralInputError("takedown_check requires a non-empty 'takedown_elements' list.")
    if assessment_type == "load_combinations" and not combos:
        raise StructuralInputError("load_combinations requires a non-empty 'load_combinations' list.")
    if assessment_type == "simple_statics_beam" and not beams:
        raise StructuralInputError("simple_statics_beam requires a non-empty 'beams' list.")
    if assessment_type == "full_structural_check" and not (takedowns or combos or beams):
        raise StructuralInputError("full_structural_check requires at least one takedown element, combination, or beam.")

    all_prepared: list[dict[str, Any]] = []
    all_checks: list[dict[str, Any]] = []
    all_blocked: list[str] = []
    passed = 0
    failed = 0
    total_factored_kn = 0.0
    takedown_ok = True

    if takedowns:
        p, c, b, pa, fa, skn, tk_ok = _evaluate_takedown(takedowns, tol_pct=tol_pct)
        all_prepared.extend(p)
        all_checks.extend(c)
        all_blocked.extend(b)
        passed += pa
        failed += fa
        total_factored_kn = skn
        takedown_ok = tk_ok
    if combos:
        p, c, b, pa, fa = _evaluate_load_combinations(combos, tol_pct=tol_pct)
        all_prepared.extend(p)
        all_checks.extend(c)
        all_blocked.extend(b)
        passed += pa
        failed += fa
    if beams:
        p, c, b, pa, fa = _evaluate_beams(beams, tol_pct=tol_pct)
        all_prepared.extend(p)
        all_checks.extend(c)
        all_blocked.extend(b)
        passed += pa
        failed += fa

    blocked_cnt = len(all_blocked)
    checks_passed = blocked_cnt == 0 and failed == 0 and passed > 0
    status = "blocked_missing_inputs" if blocked_cnt > 0 else "evaluated"
    return StructuralEvaluation(
        assessment_type=assessment_type,
        status=status,
        checks_passed=checks_passed,
        blocked_missing_count=blocked_cnt,
        failed_checks_count=failed,
        equations=[
            "Takedown: P_u = d_factor * (floors * area * D_kPa + P_add) + l_factor * (floors * area * L_kPa)  [kN]",
            "Combinations: E_u = sum(owner_factor_i * unfactored_action_i)",
            "Simply Supported UDL: R = V_max = w*L/2 | M_max = w*L^2/8 | delta_max = 5*w_s*L^4 / (384*EI) * 1000 [mm]",
            "Simply Supported Point: R = V_max = P/2 | M_max = P*L/4 | delta_max = P_s*L^3 / (48*EI) * 1000 [mm]",
            "Cantilever UDL: R = V_max = w*L | M_max = w*L^2/2 | delta_max = w_s*L^4 / (8*EI) * 1000 [mm]",
        ],
        methodology=(
            "ASSESSMENT SUPPORT & I/O CHECKING ONLY: evaluates owner-factored load takedowns, linear load combination "
            "envelopes, closed-form simple span statics, and software output discrepancy/capacity ratios without member design."
        ),
        preliminary_assumptions=[
            PRELIMINARY_STRUCTURAL_LABEL_EN,
            "Never designs reinforced concrete/steel members, reinforcement ratios, foundations, or connections and NEVER certifies structural safety.",
            "All load factors, load intensities (kPa), member capacities, and deflection limits are supplied strictly by owner / verified Standards Library (zero hardcoded ACI/Eurocode/AISC/Libyan code factors).",
            f"Software output comparison discrepancy band = +/-{tol_pct}% preliminary check threshold (non-code arithmetic sanity check); verify cracking, P-Delta & torsion in validated FEA software.",
        ],
        software_recommendation=STRUCTURAL_SOFTWARE_RECOMMENDATION,
        prepared_items=all_prepared,
        check_rows=all_checks,
        blocked_flags=all_blocked,
        metrics={
            "takedown_count": len(takedowns),
            "load_combinations_count": len(combos),
            "beams_count": len(beams),
            "total_takedown_factored_kn": total_factored_kn if (takedowns and takedown_ok) else NOT_PROVIDED_LABEL,
            "passed_checks_count": passed,
            "failed_checks_count": failed,
            "blocked_missing_count": blocked_cnt,
        },
    )


class _AiStructuralNarrativePayload(BaseModel):
    summary_prose: str = Field(..., min_length=10, max_length=2500)


def draft_structural_narrative_with_ai(
    db: Session,
    secret_store: SecretStore,
    *,
    assessment_type: StructuralAssessmentType,
    title: str,
    evaluation: StructuralEvaluation,
    standards_summary: str,
    complexity: TaskComplexity = "fast",
    project_id: str | None = None,
    client_factory: Callable[[str], Any] | None = None,
) -> tuple[str, TokenUsage]:
    """Optional Gemini summary prose ONLY (0 arithmetic changes, tagged UNVERIFIED AI DRAFT until owner/licensed-engineer sign-off)."""
    prompt = {
        "task": (
            "Write a brief non-binding assessment support summary of the deterministic structural checks below. "
            "Do NOT design members, invent ACI/EC/AISC/Libyan code factors or clauses, or change any numerical output. "
            "State clearly that final structural design requires validated commercial software and a licensed structural engineer."
        ),
        "assessment_type": assessment_type,
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
        raise ProviderUsageLimitError("Daily token limit would be exceeded by optional Step 19 AI summary.")
    if config.usage_limits.monthly_token_limit and (monthly_usage.total_tokens + est_tokens) > config.usage_limits.monthly_token_limit:
        raise ProviderUsageLimitError("Monthly token limit would be exceeded by optional Step 19 AI summary.")

    req = LLMRequest(
        prompt=prompt_json,
        system_instruction="Summarize deterministic structural check outputs concisely without designing members or inventing standard clauses.",
        complexity=complexity,
        temperature=0.0,
        response_schema=_AiStructuralNarrativePayload,
    )
    resp = execute_provider_request(
        db,
        secret_store,
        req,
        client_factory=client_factory,
        project_id=project_id,
    )
    try:
        parsed = _AiStructuralNarrativePayload.model_validate(resp.parsed_json)
    except ValidationError as exc:
        raise ProviderResponseError(
            f"Structural AI narrative validation failed: {exc.errors()[0].get('msg', 'invalid schema')}"
        ) from exc

    return sanitize_secret_text(parsed.summary_prose.strip()), resp.usage


def get_synthetic_structural_presets() -> list[StructuralPresetOut]:
    """Return synthetic Step 19 presets (SYNTHETIC values only, explicitly PRELIMINARY - for review by a licensed structural engineer)."""
    return [
        StructuralPresetOut(
            key="full_1",
            assessment_type="full_structural_check",
            label_en="Synthetic Column Takedown + Owner Combo + Simply Supported Beam Check (PRELIMINARY)",
            label_ar="نموذج فحص وتجهيز إنشائي تمثيلي شامل: أحمال عمود + تراكبات + كمرة بسيطة (أولي)",
            inputs={
                "discrepancy_tolerance_pct": 2.0,
                "takedown_elements": [
                    {
                        "element_id": "COL-A1",
                        "element_name": "Synthetic Grid A1 Column",
                        "tributary_area_m2": 25.0,
                        "floors_count": 3,
                        "dead_load_kpa": 8.0,
                        "live_load_kpa": 3.0,
                        "dead_factor": 1.2,
                        "live_factor": 1.6,
                        "reported_factored_axial_kn": 1080.0,
                        "owner_axial_capacity_kn": 1200.0,
                    }
                ],
                "load_combinations": [
                    {
                        "member_id": "FRAME-M1",
                        "member_name": "Synthetic Shear Check Action",
                        "unit": "kN",
                        "unfactored_actions": {"D": 100.0, "L": 50.0, "W": 30.0},
                        "combinations": [
                            {"combo_name": "Owner-C1", "factors": {"D": 1.4}},
                            {"combo_name": "Owner-C2", "factors": {"D": 1.2, "L": 1.6}},
                            {"combo_name": "Owner-C3", "factors": {"D": 1.2, "L": 0.5, "W": 1.0}},
                        ],
                        "reported_governing_value": 200.0,
                        "owner_capacity": 250.0,
                    }
                ],
                "beams": [
                    {
                        "beam_id": "BM-01",
                        "beam_name": "Synthetic Simply Supported UDL Girder",
                        "support_condition": "simply_supported_udl",
                        "span_m": 6.0,
                        "factored_load_kn_or_knm": 40.0,
                        "service_load_kn_or_knm": 28.0,
                        "e_mpa": 25000.0,
                        "i_mm4": 1600000000.0,
                        "reported_reaction_kn": 120.0,
                        "reported_shear_kn": 120.0,
                        "reported_moment_kn_m": 180.0,
                        "reported_deflection_mm": 11.8125,
                        "owner_moment_capacity_kn_m": 200.0,
                        "owner_shear_capacity_kn": 150.0,
                        "owner_deflection_limit_mm": 25.0,
                    }
                ],
            },
        ),
        StructuralPresetOut(
            key="beam_2",
            assessment_type="simple_statics_beam",
            label_en="Synthetic Cantilever UDL Statics Check (4 m, 15 kN/m — PRELIMINARY)",
            label_ar="نموذج فحص كابولي تمثيلي (4 م — أولي)",
            inputs={
                "discrepancy_tolerance_pct": 2.0,
                "beams": [
                    {
                        "beam_id": "CB-01",
                        "beam_name": "Synthetic Canopy Cantilever",
                        "support_condition": "cantilever_udl",
                        "span_m": 4.0,
                        "factored_load_kn_or_knm": 15.0,
                        "service_load_kn_or_knm": 10.0,
                        "ei_kn_m2": 32000.0,
                        "reported_reaction_kn": 60.0,
                        "reported_shear_kn": 60.0,
                        "reported_moment_kn_m": 120.0,
                        "reported_deflection_mm": 10.0,
                        "owner_moment_capacity_kn_m": 140.0,
                        "owner_shear_capacity_kn": 80.0,
                        "owner_deflection_limit_mm": 16.0,
                    }
                ],
            },
        ),
    ]
