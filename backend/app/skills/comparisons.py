"""Step 15 deterministic Decimal technical comparison skill & optional Gemini narrative (default 0 tokens)."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re
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
from app.schemas.comparisons import (
    ADVISORY_NOTICE_AR,
    ADVISORY_NOTICE_EN,
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    ComparisonCellIn,
    ComparisonCriterionIn,
    ComparisonMatrixOut,
    ComparisonOptionIn,
    ComparisonPresetOut,
    EvaluatedCellOut,
    EvaluatedOptionOut,
    NOT_PROVIDED_LABEL,
)
from app.schemas.reports import ReportLanguage
from app.services.provider_settings import _load_provider_config, _summarize_usage, execute_provider_request
from app.services.research import estimate_prompt_tokens

_DEC_ZERO = Decimal("0")
_DEC_HUNDRED = Decimal("100")
_DEC_ONE = Decimal("1")
_Q4 = Decimal("0.0001")

_URL_RE = re.compile(r"(?:https?://|project-file://)[^\s,;\"')>\]]+", re.IGNORECASE)
_UNGROUNDED_STD_RE = re.compile(
    r"\b(?:ASTM|ACI|BS|EN|IEC|IEEE|ISO|ASHRAE|NFPA|ASME|ANSI|SBC|LBC)\s*[A-Z]?\s*\d[\w./-]*\b",
    re.IGNORECASE,
)


class ComparisonInputError(ValueError):
    """Raised when comparison criteria weights, values, units, or source inputs violate Step 15 rules."""


def _q4(value: Decimal) -> Decimal:
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def _dec(raw: float | int | str | Decimal, *, label: str) -> Decimal:
    try:
        d = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ComparisonInputError(f"Invalid decimal value for {label}: {raw!r}") from exc
    if not d.is_finite():
        raise ComparisonInputError(f"Non-finite value for {label}: {raw!r}")
    return d


# Canonical unit aliasing and explicit verified physical Decimal conversion factors.
# Currencies are tracked strictly so differing currencies are ALWAYS flagged rather than silently converted.
_UNIT_ALIASES: dict[str, str] = {
    "w": "W",
    "watt": "W",
    "watts": "W",
    "kw": "kW",
    "mw": "MW",
    "va": "VA",
    "kva": "kVA",
    "mva": "MVA",
    "l/s": "L/s",
    "lps": "L/s",
    "m3/h": "m3/h",
    "m³/h": "m3/h",
    "gpm": "GPM",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "pa": "Pa",
    "kpa": "kPa",
    "bar": "bar",
    "wh": "Wh",
    "kwh": "kWh",
    "mwh": "MWh",
    "g": "g",
    "kg": "kg",
    "ton": "ton",
    "t": "ton",
    "usd": "USD",
    "$": "USD",
    "lyd": "LYD",
    "eur": "EUR",
    "gbp": "GBP",
    "sar": "SAR",
    "aed": "AED",
    "%": "%",
    "pct": "%",
    "yr": "years",
    "yrs": "years",
    "year": "years",
    "years": "years",
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hours": "hours",
    "db": "dB",
    "dba": "dBA",
    "ip": "IP",
    "bool": "bool",
    "pass/fail": "bool",
    "score": "score_0_100",
    "score_0_100": "score_0_100",
}

_PHYSICAL_FAMILIES: dict[str, tuple[str, Decimal]] = {
    # Power (base: W)
    "W": ("power", Decimal("1")),
    "kW": ("power", Decimal("1000")),
    "MW": ("power", Decimal("1000000")),
    # Apparent Power (base: VA)
    "VA": ("apparent_power", Decimal("1")),
    "kVA": ("apparent_power", Decimal("1000")),
    "MVA": ("apparent_power", Decimal("1000000")),
    # Volumetric Flow (base: L/s; exact US GPM factor 0.0630902 L/s)
    "L/s": ("flow", Decimal("1")),
    "m3/h": ("flow", Decimal("1000") / Decimal("3600")),
    "GPM": ("flow", Decimal("0.0630902")),
    # Length (base: m)
    "mm": ("length", Decimal("0.001")),
    "cm": ("length", Decimal("0.01")),
    "m": ("length", Decimal("1")),
    # Pressure (base: Pa)
    "Pa": ("pressure", Decimal("1")),
    "kPa": ("pressure", Decimal("1000")),
    "bar": ("pressure", Decimal("100000")),
    # Energy (base: Wh)
    "Wh": ("energy", Decimal("1")),
    "kWh": ("energy", Decimal("1000")),
    "MWh": ("energy", Decimal("1000000")),
    # Mass (base: kg)
    "g": ("mass", Decimal("0.001")),
    "kg": ("mass", Decimal("1")),
    "ton": ("mass", Decimal("1000")),
    # Time (base: hours)
    "hours": ("time", Decimal("1")),
    "years": ("time", Decimal("8760")),
}

_CURRENCIES = {"USD", "LYD", "EUR", "GBP", "SAR", "AED"}


def canonicalize_unit(unit: str | None) -> str:
    """Normalize common case/symbol variations of units and currencies."""
    cleaned = (unit or "").strip()
    if not cleaned:
        return ""
    return _UNIT_ALIASES.get(cleaned.lower(), cleaned)


def convert_unit_decimal(
    value: Decimal,
    *,
    raw_unit: str,
    target_unit: str,
) -> tuple[Decimal | None, str, str | None]:
    """Convert raw Decimal metric explicitly into target_unit, or flag unit/currency mismatch."""
    src = canonicalize_unit(raw_unit)
    dst = canonicalize_unit(target_unit)
    if not src or not dst:
        if not src and dst in {"bool", "score_0_100"}:
            return value, "exact", None
        return None, "flagged_mismatch", f"Missing unit: expected '{dst or 'unspecified'}', got '{src or 'unspecified'}'."
    if src == dst:
        return _q4(value), "exact", None
    if src in _CURRENCIES or dst in _CURRENCIES:
        return (
            None,
            "flagged_mismatch",
            f"Currency mismatch ({src} vs {dst}): currencies are never silently converted without an owner-verified FX basis.",
        )
    src_info = _PHYSICAL_FAMILIES.get(src)
    dst_info = _PHYSICAL_FAMILIES.get(dst)
    if src_info and dst_info and src_info[0] == dst_info[0]:
        base_val = value * src_info[1]
        converted = _q4(base_val / dst_info[1])
        return converted, "converted_explicitly", f"Converted explicitly: {value} {src} -> {converted} {dst}"
    return (
        None,
        "flagged_mismatch",
        f"Unit mismatch ({src} vs {dst}): incompatible or unconvertible units flagged for engineer review.",
    )


def _is_missing_raw_value(raw_value: float | int | str | bool | None) -> bool:
    if raw_value is None:
        return True
    if isinstance(raw_value, str):
        token = raw_value.strip().lower()
        return token in {"", "not provided", "n/a", "na", "tbd", "none", "null", "-", "—"}
    return False


def _parse_bool_value(raw_value: float | int | str | bool) -> bool | None:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, (int, float)):
        if raw_value == 1:
            return True
        if raw_value == 0:
            return False
        return None
    token = str(raw_value).strip().lower()
    if token in {"true", "yes", "pass", "passed", "compliant", "ok", "1", "نعم", "مطابق", "ناجح"}:
        return True
    if token in {"false", "no", "fail", "failed", "non-compliant", "0", "لا", "غير مطابق", "راسب"}:
        return False
    return None


@dataclass
class _EvaluatedCellDraft:
    criterion: ComparisonCriterionIn
    weight_dec: Decimal
    raw_value: float | int | str | bool | None
    display_value: str
    raw_unit: str
    target_unit: str
    converted_dec: Decimal | None
    bool_val: bool | None
    unit_status: str
    conversion_note: str | None
    is_missing: bool
    mandatory_passed: bool | None
    source_kind: str
    source_ref: str
    boq_item_id: str | None
    specification_id: str | None
    calculation_id: str | None
    research_source_id: str | None
    notes: str | None


def _derive_lifecycle_cost_if_complete(
    *,
    criterion: ComparisonCriterionIn,
    option_cells_by_id: dict[str, ComparisonCellIn],
    criteria_by_id: dict[str, ComparisonCriterionIn],
    lifecycle_years: float | None,
) -> ComparisonCellIn | None:
    """Derive lifecycle_cost strictly when initial_cost, annual operating_cost & lifecycle_years are complete and currency-compatible."""
    if criterion.category != "lifecycle_cost" or lifecycle_years is None or lifecycle_years <= 0:
        return None
    init_crit = next((c for c in criteria_by_id.values() if c.category == "initial_cost"), None)
    oper_crit = next((c for c in criteria_by_id.values() if c.category == "operating_cost"), None)
    if not init_crit or not oper_crit:
        return None
    init_cell = option_cells_by_id.get(init_crit.criterion_id)
    oper_cell = option_cells_by_id.get(oper_crit.criterion_id)
    if not init_cell or not oper_cell:
        return None
    if _is_missing_raw_value(init_cell.value) or _is_missing_raw_value(oper_cell.value):
        return None
    if isinstance(init_cell.value, bool) or isinstance(oper_cell.value, bool):
        return None
    try:
        init_dec = _dec(init_cell.value, label=init_crit.criterion_id)  # type: ignore[arg-type]
        oper_dec = _dec(oper_cell.value, label=oper_crit.criterion_id)  # type: ignore[arg-type]
    except ComparisonInputError:
        return None

    target_unit = canonicalize_unit(criterion.target_unit)
    init_conv, init_status, _ = convert_unit_decimal(
        init_dec,
        raw_unit=init_cell.unit or init_crit.target_unit,
        target_unit=target_unit,
    )
    oper_conv, oper_status, _ = convert_unit_decimal(
        oper_dec,
        raw_unit=oper_cell.unit or oper_crit.target_unit,
        target_unit=target_unit,
    )
    if init_conv is None or oper_conv is None or init_status == "flagged_mismatch" or oper_status == "flagged_mismatch":
        return None

    years_dec = _dec(lifecycle_years, label="lifecycle_years")
    derived_total = _q4(init_conv + oper_conv * years_dec)
    return ComparisonCellIn(
        criterion_id=criterion.criterion_id,
        value=str(derived_total),
        unit=target_unit,
        source_kind="calculation",
        source_ref=(
            f"Derived deterministically: {init_conv} {target_unit} + "
            f"({oper_conv} {target_unit}/yr * {years_dec} yr) [from {init_crit.criterion_id} & {oper_crit.criterion_id}]"
        ),
        notes=f"Deterministic lifecycle calculation over {years_dec} years.",
    )


def evaluate_technical_comparison(
    *,
    criteria: list[ComparisonCriterionIn],
    options: list[ComparisonOptionIn],
    language: ReportLanguage = "en",
    lifecycle_years: float | None = None,
    enforce_weight_sum: bool = True,
) -> ComparisonMatrixOut:
    """Deterministically evaluate weighted Decimal scores, unit normalization/flags, mandatory gating, and advisory ranking."""
    if not criteria:
        raise ComparisonInputError("At least one comparison criterion is required.")
    if len(options) < 2:
        raise ComparisonInputError("At least two candidate options are required for comparison.")

    criteria_by_id: dict[str, ComparisonCriterionIn] = {}
    weights_by_id: dict[str, Decimal] = {}
    total_weight = _DEC_ZERO

    for crit in criteria:
        cid = crit.criterion_id.strip()
        if cid in criteria_by_id:
            raise ComparisonInputError(f"Duplicate criterion_id: '{cid}'.")
        w_dec = _dec(crit.weight, label=f"weight[{cid}]")
        if w_dec <= _DEC_ZERO:
            raise ComparisonInputError(f"Criterion '{cid}' weight must be > 0 (got {w_dec}).")
        criteria_by_id[cid] = crit
        weights_by_id[cid] = w_dec
        total_weight += w_dec

    total_weight_q = _q4(total_weight)
    weights_sum_valid = abs(total_weight_q - _DEC_HUNDRED) <= Decimal("0.0001")
    if enforce_weight_sum and not weights_sum_valid:
        raise ComparisonInputError(
            f"Criteria weights must sum strictly to 100.0 (current sum is {total_weight_q})."
        )

    seen_opt_ids: set[str] = set()
    for opt in options:
        oid = opt.option_id.strip()
        if oid in seen_opt_ids:
            raise ComparisonInputError(f"Duplicate option_id: '{oid}'.")
        seen_opt_ids.add(oid)

    unit_mismatch_flags: list[str] = []
    missing_mandatory_flags: list[str] = []

    # Step 1: Parse cells, derive lifecycle_cost ONLY if all inputs are present & unit-compatible, convert units.
    draft_grid: dict[str, dict[str, _EvaluatedCellDraft]] = {opt.option_id: {} for opt in options}

    for opt in options:
        opt_cells = {c.criterion_id: c for c in opt.cells}
        for crit in criteria:
            raw_cell = opt_cells.get(crit.criterion_id)
            if (raw_cell is None or _is_missing_raw_value(raw_cell.value)) and crit.category == "lifecycle_cost":
                derived = _derive_lifecycle_cost_if_complete(
                    criterion=crit,
                    option_cells_by_id=opt_cells,
                    criteria_by_id=criteria_by_id,
                    lifecycle_years=lifecycle_years,
                )
                if derived is not None:
                    raw_cell = derived

            target_u = canonicalize_unit(crit.target_unit)
            if raw_cell is None or _is_missing_raw_value(raw_cell.value):
                src_kind = raw_cell.source_kind if raw_cell else "owner_entered"
                src_ref = (raw_cell.source_ref or "").strip() if raw_cell else ""
                if not src_ref:
                    src_ref = NOT_PROVIDED_LABEL
                mand_ok: bool | None = False if crit.is_mandatory else None
                if crit.is_mandatory:
                    missing_mandatory_flags.append(f"{opt.name}: {crit.label} -> {NOT_PROVIDED_LABEL}")
                draft_grid[opt.option_id][crit.criterion_id] = _EvaluatedCellDraft(
                    criterion=crit,
                    weight_dec=weights_by_id[crit.criterion_id],
                    raw_value=None,
                    display_value=NOT_PROVIDED_LABEL,
                    raw_unit="",
                    target_unit=target_u,
                    converted_dec=None,
                    bool_val=None,
                    unit_status="not_applicable",
                    conversion_note=None,
                    is_missing=True,
                    mandatory_passed=mand_ok,
                    source_kind=src_kind,
                    source_ref=src_ref,
                    boq_item_id=raw_cell.boq_item_id if raw_cell else None,
                    specification_id=raw_cell.specification_id if raw_cell else None,
                    calculation_id=raw_cell.calculation_id if raw_cell else None,
                    research_source_id=raw_cell.research_source_id if raw_cell else None,
                    notes=raw_cell.notes if raw_cell else None,
                )
                continue

            src_ref_clean = (raw_cell.source_ref or "").strip()
            if not src_ref_clean:
                raise ComparisonInputError(
                    f"Option '{opt.option_id}', criterion '{crit.criterion_id}': non-missing value requires a source_ref."
                )

            if crit.direction == "boolean_pass":
                parsed_bool = _parse_bool_value(raw_cell.value)  # type: ignore[arg-type]
                if parsed_bool is None:
                    raise ComparisonInputError(
                        f"Option '{opt.option_id}', criterion '{crit.criterion_id}' expects boolean pass/fail, got {raw_cell.value!r}."
                    )
                expected_bool = True if crit.mandatory_expected_bool is None else bool(crit.mandatory_expected_bool)
                mand_ok = (parsed_bool == expected_bool) if crit.is_mandatory else None
                draft_grid[opt.option_id][crit.criterion_id] = _EvaluatedCellDraft(
                    criterion=crit,
                    weight_dec=weights_by_id[crit.criterion_id],
                    raw_value=parsed_bool,
                    display_value="PASS" if parsed_bool else "FAIL",
                    raw_unit=canonicalize_unit(raw_cell.unit or "bool"),
                    target_unit="bool",
                    converted_dec=None,
                    bool_val=parsed_bool,
                    unit_status="exact",
                    conversion_note=None,
                    is_missing=False,
                    mandatory_passed=mand_ok,
                    source_kind=raw_cell.source_kind,
                    source_ref=src_ref_clean,
                    boq_item_id=raw_cell.boq_item_id,
                    specification_id=raw_cell.specification_id,
                    calculation_id=raw_cell.calculation_id,
                    research_source_id=raw_cell.research_source_id,
                    notes=raw_cell.notes,
                )
                continue

            if isinstance(raw_cell.value, bool):
                raise ComparisonInputError(
                    f"Option '{opt.option_id}', criterion '{crit.criterion_id}' expects numeric value, got boolean."
                )
            num_dec = _dec(raw_cell.value, label=f"{opt.option_id}.{crit.criterion_id}")  # type: ignore[arg-type]
            if crit.direction in {"higher_better", "lower_better"} and num_dec < _DEC_ZERO:
                raise ComparisonInputError(
                    f"Option '{opt.option_id}', criterion '{crit.criterion_id}' requires non-negative numeric value for ratio scoring (got {num_dec})."
                )
            if crit.direction == "direct_score_0_100" and (num_dec < _DEC_ZERO or num_dec > _DEC_HUNDRED):
                raise ComparisonInputError(
                    f"Option '{opt.option_id}', criterion '{crit.criterion_id}' direct score must be within [0, 100] (got {num_dec})."
                )

            raw_u = canonicalize_unit(raw_cell.unit or crit.target_unit)
            conv_dec, u_status, conv_note = convert_unit_decimal(num_dec, raw_unit=raw_u, target_unit=target_u)
            if u_status == "flagged_mismatch":
                unit_mismatch_flags.append(f"{opt.name} / {crit.label}: {conv_note}")
                mand_ok = False if crit.is_mandatory else None
            elif crit.is_mandatory and conv_dec is not None:
                min_ok = True if crit.mandatory_min is None else (conv_dec >= _dec(crit.mandatory_min, label="mandatory_min"))
                max_ok = True if crit.mandatory_max is None else (conv_dec <= _dec(crit.mandatory_max, label="mandatory_max"))
                mand_ok = bool(min_ok and max_ok)
            else:
                mand_ok = None

            draft_grid[opt.option_id][crit.criterion_id] = _EvaluatedCellDraft(
                criterion=crit,
                weight_dec=weights_by_id[crit.criterion_id],
                raw_value=raw_cell.value,
                display_value=f"{num_dec:f}".rstrip("0").rstrip(".") if "." in f"{num_dec:f}" else f"{num_dec:f}",
                raw_unit=raw_u,
                target_unit=target_u,
                converted_dec=conv_dec,
                bool_val=None,
                unit_status=u_status,
                conversion_note=conv_note,
                is_missing=False,
                mandatory_passed=mand_ok,
                source_kind=raw_cell.source_kind,
                source_ref=src_ref_clean,
                boq_item_id=raw_cell.boq_item_id,
                specification_id=raw_cell.specification_id,
                calculation_id=raw_cell.calculation_id,
                research_source_id=raw_cell.research_source_id,
                notes=raw_cell.notes,
            )

    # Step 2: Deterministic Decimal normalization per criterion across valid (non-missing, non-mismatched) cells.
    norm_scores: dict[tuple[str, str], Decimal] = {}
    for crit in criteria:
        cid = crit.criterion_id
        valid_entries: list[tuple[str, _EvaluatedCellDraft]] = [
            (opt.option_id, draft_grid[opt.option_id][cid])
            for opt in options
            if not draft_grid[opt.option_id][cid].is_missing
            and draft_grid[opt.option_id][cid].unit_status != "flagged_mismatch"
        ]

        for opt in options:
            norm_scores[(opt.option_id, cid)] = _DEC_ZERO

        if crit.direction == "boolean_pass":
            expected_bool = True if crit.mandatory_expected_bool is None else bool(crit.mandatory_expected_bool)
            for oid, cell in valid_entries:
                norm_scores[(oid, cid)] = _q4(_DEC_HUNDRED) if (cell.bool_val == expected_bool) else _q4(_DEC_ZERO)
            continue

        numeric_vals = [(oid, cell.converted_dec) for oid, cell in valid_entries if cell.converted_dec is not None]
        if not numeric_vals:
            continue

        if crit.direction == "direct_score_0_100":
            for oid, dec_val in numeric_vals:
                norm_scores[(oid, cid)] = _q4(dec_val)
        elif crit.direction == "higher_better":
            max_v = max(v for _, v in numeric_vals)
            for oid, dec_val in numeric_vals:
                if max_v > _DEC_ZERO:
                    norm_scores[(oid, cid)] = _q4((dec_val / max_v) * _DEC_HUNDRED)
                else:
                    norm_scores[(oid, cid)] = _q4(_DEC_HUNDRED) if dec_val == _DEC_ZERO else _q4(_DEC_ZERO)
        elif crit.direction == "lower_better":
            min_v = min(v for _, v in numeric_vals)
            max_v = max(v for _, v in numeric_vals)
            for oid, dec_val in numeric_vals:
                if min_v > _DEC_ZERO:
                    norm_scores[(oid, cid)] = _q4((min_v / dec_val) * _DEC_HUNDRED)
                elif max_v > _DEC_ZERO:
                    norm_scores[(oid, cid)] = _q4(((max_v - dec_val) / max_v) * _DEC_HUNDRED)
                else:
                    norm_scores[(oid, cid)] = _q4(_DEC_HUNDRED)

    # Step 3: Build EvaluatedOptionOut rows and deterministic advisory ranking.
    evaluated_options_unsorted: list[tuple[Decimal, bool, str, EvaluatedOptionOut]] = []
    for opt in options:
        cells_out: list[EvaluatedCellOut] = []
        total_score = _DEC_ZERO
        failed_mandatory: list[str] = []
        missing_cnt = 0
        mismatch_cnt = 0

        for crit in criteria:
            draft = draft_grid[opt.option_id][crit.criterion_id]
            n_score = norm_scores[(opt.option_id, crit.criterion_id)]
            w_score = _q4((n_score * draft.weight_dec) / _DEC_HUNDRED)
            total_score = _q4(total_score + w_score)

            if draft.is_missing:
                missing_cnt += 1
            if draft.unit_status == "flagged_mismatch":
                mismatch_cnt += 1
            if draft.criterion.is_mandatory and draft.mandatory_passed is False:
                failed_mandatory.append(f"{crit.label} ({crit.criterion_id})")

            conv_str: str | None = None
            if draft.converted_dec is not None:
                conv_str = f"{draft.converted_dec:f}"

            cells_out.append(
                EvaluatedCellOut(
                    criterion_id=crit.criterion_id,
                    category=crit.category,
                    label=crit.label,
                    weight=float(draft.weight_dec),
                    is_mandatory=crit.is_mandatory,
                    raw_value=draft.raw_value,
                    display_value=draft.display_value,
                    raw_unit=draft.raw_unit,
                    target_unit=draft.target_unit,
                    converted_value=conv_str,
                    unit_status=draft.unit_status,
                    conversion_note=draft.conversion_note,
                    is_missing=draft.is_missing,
                    mandatory_passed=draft.mandatory_passed,
                    normalized_score=float(n_score),
                    weighted_score=float(w_score),
                    source_kind=draft.source_kind,
                    source_ref=draft.source_ref,
                    boq_item_id=draft.boq_item_id,
                    specification_id=draft.specification_id,
                    calculation_id=draft.calculation_id,
                    research_source_id=draft.research_source_id,
                    notes=draft.notes,
                )
            )

        mandatory_ok = len(failed_mandatory) == 0
        evaluated = EvaluatedOptionOut(
            option_id=opt.option_id,
            name=opt.name,
            vendor_or_source=opt.vendor_or_source.strip(),
            advisory_rank=0,
            total_weighted_score=float(total_score),
            mandatory_passed=mandatory_ok,
            failed_mandatory_criteria=failed_mandatory,
            missing_values_count=missing_cnt,
            unit_mismatch_count=mismatch_cnt,
            risks=[r.strip() for r in opt.risks if r.strip()],
            cells=cells_out,
        )
        evaluated_options_unsorted.append((total_score, mandatory_ok, opt.option_id, evaluated))

    ranked = sorted(
        evaluated_options_unsorted,
        key=lambda item: (not item[1], -item[0], item[2]),
    )
    ranked_options: list[EvaluatedOptionOut] = []
    for idx, (_, _, _, opt_out) in enumerate(ranked, start=1):
        opt_out.advisory_rank = idx
        ranked_options.append(opt_out)

    # Restore presentation order matching original option list? Keep deterministic advisory rank on each,
    # and sort matrix options by advisory_rank so matrix columns are intuitively ordered from rank 1 -> rank N.
    leader = ranked_options[0] if ranked_options and ranked_options[0].mandatory_passed else None

    return ComparisonMatrixOut(
        total_weight=float(total_weight_q),
        weights_sum_valid=weights_sum_valid,
        advisory_notice=ADVISORY_NOTICE_AR if language == "ar" else ADVISORY_NOTICE_EN,
        leading_option_id=leader.option_id if leader else None,
        leading_option_name=leader.name if leader else None,
        unit_mismatch_flags=unit_mismatch_flags,
        missing_mandatory_flags=missing_mandatory_flags,
        options=ranked_options,
    )


def recompute_comparison_matrix(
    *,
    criteria: list[ComparisonCriterionIn],
    options: list[ComparisonOptionIn],
    language: ReportLanguage = "en",
    lifecycle_years: float | None = None,
) -> ComparisonMatrixOut:
    """Recompute weighted Decimal matrix without raising on non-100 weights (used by QA arithmetic checker)."""
    return evaluate_technical_comparison(
        criteria=criteria,
        options=options,
        language=language,
        lifecycle_years=lifecycle_years,
        enforce_weight_sum=False,
    )


def _contains_ungrounded_standard(text: str, *, allowed_source_text: str) -> bool:
    for url_hit in _URL_RE.findall(text):
        if url_hit.lower() not in allowed_source_text:
            return True
    for std_hit in _UNGROUNDED_STD_RE.findall(text):
        if std_hit.lower() not in allowed_source_text:
            return True
    return False


class _AiComparisonNarrativePayload(BaseModel):
    executive_note: str = Field(..., min_length=10, max_length=2500)


def draft_comparison_narrative_with_ai(
    db: Session,
    secret_store: SecretStore,
    *,
    project_id: str,
    project_code: str,
    project_name: str,
    title: str,
    language: ReportLanguage,
    matrix: ComparisonMatrixOut,
    criteria: list[ComparisonCriterionIn],
    complexity: TaskComplexity = "fast",
    client_factory: Callable[[str], Any] | None = None,
    task_id: str | None = None,
) -> tuple[str, TokenUsage, int, int]:
    """Optional Gemini prose summary strictly grounded in evaluated numbers; NEVER alters scores or issues final selection."""
    summary_payload = {
        "project": f"[{project_code}] {project_name}",
        "comparison_title": title,
        "language": language,
        "rules": [
            "Summarize key technical & cost trade-offs ONLY from the verified numbers provided.",
            "NEVER compute scores, invent prices, invent vendor certifications, or invent standard numbers.",
            "Explicitly state that ranking is advisory and final selection belongs solely to the Owner / Licensed Engineer.",
        ],
        "advisory_leader": matrix.leading_option_name or "None (mandatory gate failures present)",
        "unit_mismatches": matrix.unit_mismatch_flags,
        "missing_mandatory": matrix.missing_mandatory_flags,
        "criteria": [
            {
                "criterion_id": c.criterion_id,
                "category": c.category,
                "label": c.label,
                "weight": str(c.weight),
                "mandatory": c.is_mandatory,
                "source_ref": c.source_ref,
            }
            for c in criteria
        ],
        "options": [
            {
                "option_id": o.option_id,
                "name": o.name,
                "advisory_rank": o.advisory_rank,
                "total_weighted_score": o.total_weighted_score,
                "mandatory_passed": o.mandatory_passed,
                "failed_mandatory": o.failed_mandatory_criteria,
                "risks": o.risks,
            }
            for o in matrix.options
        ],
    }
    prompt_text = json.dumps(summary_payload, ensure_ascii=False)
    prompt_chars = len(prompt_text)
    est_tokens = estimate_prompt_tokens(prompt_text)

    cfg = _load_provider_config(db)
    daily_usage, monthly_usage = _summarize_usage(db)
    if daily_usage.total_tokens + est_tokens > cfg.usage_limits.daily_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated comparison AI draft prompt ({est_tokens} tokens) plus daily usage "
            f"({daily_usage.total_tokens}) would exceed Step 04 daily limit ({cfg.usage_limits.daily_token_limit})."
        )
    if monthly_usage.total_tokens + est_tokens > cfg.usage_limits.monthly_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated comparison AI draft prompt ({est_tokens} tokens) plus monthly usage "
            f"({monthly_usage.total_tokens}) would exceed Step 04 monthly limit ({cfg.usage_limits.monthly_token_limit})."
        )

    sys_instr = (
        "You are an engineering consultancy technical evaluation editor. Write an objective executive trade-off "
        "summary ONLY from the provided matrix values in the requested language ('ar' or 'en'). Do not perform "
        "arithmetic, do not invent prices/standards/certifications, and make clear the Owner makes the final decision."
    )
    llm_req = LLMRequest(
        prompt=prompt_text,
        system_instruction=sys_instr,
        complexity=complexity,
        temperature=0.1,
        response_schema=_AiComparisonNarrativePayload,
    )
    llm_resp = execute_provider_request(
        db,
        secret_store,
        llm_req,
        client_factory=client_factory,
        project_id=project_id,
        task_id=task_id,
    )
    try:
        parsed = _AiComparisonNarrativePayload.model_validate(llm_resp.parsed_json)
    except ValidationError as exc:
        raise ProviderResponseError(
            f"Comparison AI narrative validation failed: {exc.errors()[0].get('msg', 'invalid schema')}"
        ) from exc

    allowed_text = " ".join(
        [title]
        + [c.label + " " + c.source_ref for c in criteria]
        + [o.name + " " + " ".join(o.risks) for o in matrix.options]
    ).lower()
    note = sanitize_secret_text(parsed.executive_note.strip())
    if _contains_ungrounded_standard(note, allowed_source_text=allowed_text):
        raise ProviderResponseError(
            "Comparison AI draft referenced an ungrounded standard clause or URL not present in verified inputs."
        )
    prefix = f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] " if language == "ar" else f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] "
    final_note = note if prefix.strip(" []") in note else f"{prefix}{note}"
    return final_note, llm_resp.usage, est_tokens, prompt_chars


def get_synthetic_comparison_presets() -> list[ComparisonPresetOut]:
    """Return synthetic clinic equipment comparison presets (0% client data, weights strictly sum to 100)."""
    return [
        ComparisonPresetOut(
            key="synthetic_clinic_backup_generator",
            title_en="Synthetic Clinic 150 kVA Standby Diesel Generator Evaluation (Example Data)",
            title_ar="مقارنة فنية تمثيلية لمولد ديزل احتياطي 150 ك.ف.أ لعيادة طبية (بيانات افتراضية)",
            comparison_scope="equipment",
            discipline="electrical",
            lifecycle_years=10.0,
            criteria=[
                ComparisonCriterionIn(
                    criterion_id="compliance",
                    category="compliance",
                    label="Emergency transfer compliance / المطابقة لمتطلبات التغذية الاحتياطية",
                    weight="15",
                    is_mandatory=True,
                    direction="boolean_pass",
                    target_unit="bool",
                    mandatory_expected_bool=True,
                    source_kind="owner_entered",
                    source_ref="Synthetic clinic preset — link to project Specification & verify against locally adopted code",
                ),
                ComparisonCriterionIn(
                    criterion_id="performance",
                    category="performance",
                    label="Continuous standby output / القدرة الاحتياطية المقننة",
                    weight="15",
                    is_mandatory=True,
                    direction="higher_better",
                    target_unit="kW",
                    mandatory_min=110.0,
                    source_kind="owner_entered",
                    source_ref="Synthetic clinic electrical demand baseline (preset)",
                ),
                ComparisonCriterionIn(
                    criterion_id="safety",
                    category="safety",
                    label="Acoustic enclosure & emergency shutdown interlocks / عزل الصوت وأقفال الطوارئ",
                    weight="10",
                    is_mandatory=True,
                    direction="direct_score_0_100",
                    target_unit="score_0_100",
                    mandatory_min=75.0,
                    source_kind="owner_entered",
                    source_ref="Synthetic HSE inspection checklist (preset)",
                ),
                ComparisonCriterionIn(
                    criterion_id="durability",
                    category="durability",
                    label="Rated overhaul interval / ساعات التشغيل قبل العمرة",
                    weight="10",
                    is_mandatory=False,
                    direction="higher_better",
                    target_unit="hours",
                    source_kind="owner_entered",
                    source_ref="Synthetic vendor brochure baseline (verify datasheet)",
                ),
                ComparisonCriterionIn(
                    criterion_id="energy",
                    category="energy",
                    label="Fuel efficiency at 75% load / استهلاك الوقود النوعي",
                    weight="10",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="g",
                    source_kind="owner_entered",
                    source_ref="Synthetic test bench allowance (g/kWh equivalent mass index)",
                ),
                ComparisonCriterionIn(
                    criterion_id="maintainability",
                    category="maintainability",
                    label="Local spare parts & service team availability / توافر قطع الغيار محلياً",
                    weight="10",
                    is_mandatory=False,
                    direction="direct_score_0_100",
                    target_unit="score_0_100",
                    source_kind="owner_entered",
                    source_ref="Synthetic local serviceability rubric (preset)",
                ),
                ComparisonCriterionIn(
                    criterion_id="constructability",
                    category="constructability",
                    label="Footprint & plinth fit score / ملاءمة الأبعاد والقاعدة الخرسانية",
                    weight="5",
                    is_mandatory=False,
                    direction="direct_score_0_100",
                    target_unit="score_0_100",
                    source_kind="owner_entered",
                    source_ref="Synthetic architectural pad coordination check",
                ),
                ComparisonCriterionIn(
                    criterion_id="initial_cost",
                    category="initial_cost",
                    label="Initial capital cost (Supply & Install) / التكلفة الرأسمالية التوريد والتركيب",
                    weight="10",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="USD",
                    source_kind="owner_entered",
                    source_ref="Synthetic sample offer A/B/C (NOT real market pricing)",
                ),
                ComparisonCriterionIn(
                    criterion_id="operating_cost",
                    category="operating_cost",
                    label="Annual maintenance & standby test cost / التكلفة التشغيلية السنوية",
                    weight="5",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="USD",
                    source_kind="owner_entered",
                    source_ref="Synthetic annual O&M estimate (NOT real pricing)",
                ),
                ComparisonCriterionIn(
                    criterion_id="lifecycle_cost",
                    category="lifecycle_cost",
                    label="10-Year Total Lifecycle Cost (Derived) / تكلفة دورة الحياة (10 سنوات)",
                    weight="5",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="USD",
                    source_kind="calculation",
                    source_ref="Derived deterministically: initial_cost + annual operating_cost * 10 years",
                ),
                ComparisonCriterionIn(
                    criterion_id="risks",
                    category="risks",
                    label="Supply-chain & commissioning risk resilience / مستوى أمان المخاطر والتشغيل",
                    weight="5",
                    is_mandatory=False,
                    direction="direct_score_0_100",
                    target_unit="score_0_100",
                    source_kind="owner_entered",
                    source_ref="Synthetic clinic risk scoring worksheet",
                ),
            ],
            options=[
                ComparisonOptionIn(
                    option_id="opt_a",
                    name="Synthetic Offer A — Heavy-Duty Industrial Enclosure",
                    vendor_or_source="Synthetic Vendor Alpha (Example Fixture)",
                    risks=["12-week sea freight lead time", "Requires 4.2m crane swing clearance"],
                    cells=[
                        ComparisonCellIn(criterion_id="compliance", value=True, unit="bool", source_kind="owner_entered", source_ref="Synthetic Offer A submittal sheet"),
                        ComparisonCellIn(criterion_id="performance", value=120, unit="kW", source_kind="owner_entered", source_ref="Synthetic Offer A prime/standby schedule"),
                        ComparisonCellIn(criterion_id="safety", value=90, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic Offer A acoustic enclosure data (68 dBA)"),
                        ComparisonCellIn(criterion_id="durability", value=25000, unit="hours", source_kind="owner_entered", source_ref="Synthetic Offer A engine overhaul spec"),
                        ComparisonCellIn(criterion_id="energy", value=210, unit="g", source_kind="owner_entered", source_ref="Synthetic Offer A fuel curve"),
                        ComparisonCellIn(criterion_id="maintainability", value=88, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic local stock declaration"),
                        ComparisonCellIn(criterion_id="constructability", value=82, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic pad layout review"),
                        ComparisonCellIn(criterion_id="initial_cost", value=42000, unit="USD", source_kind="owner_entered", source_ref="Synthetic commercial sheet A-01 (example only)"),
                        ComparisonCellIn(criterion_id="operating_cost", value=2400, unit="USD", source_kind="owner_entered", source_ref="Synthetic O&M schedule A-02 (example only)"),
                        ComparisonCellIn(criterion_id="risks", value=85, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic risk worksheet"),
                    ],
                ),
                ComparisonOptionIn(
                    option_id="opt_b",
                    name="Synthetic Offer B — Compact Quick-Delivery Unit",
                    vendor_or_source="Synthetic Vendor Beta (Example Fixture)",
                    risks=["Shorter warranty term", "Higher vibration isolation springs needed"],
                    cells=[
                        ComparisonCellIn(criterion_id="compliance", value=True, unit="bool", source_kind="owner_entered", source_ref="Synthetic Offer B submittal sheet"),
                        ComparisonCellIn(criterion_id="performance", value=115000, unit="W", source_kind="owner_entered", source_ref="Synthetic Offer B rating in Watts (demonstrates W->kW conversion)"),
                        ComparisonCellIn(criterion_id="safety", value=80, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic Offer B acoustic test"),
                        ComparisonCellIn(criterion_id="durability", value=18000, unit="hours", source_kind="owner_entered", source_ref="Synthetic Offer B overhaul manual"),
                        ComparisonCellIn(criterion_id="energy", value="0.225", unit="kg", source_kind="owner_entered", source_ref="Synthetic Offer B fuel curve in kg (demonstrates kg->g conversion)"),
                        ComparisonCellIn(criterion_id="maintainability", value=78, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic parts support note"),
                        ComparisonCellIn(criterion_id="constructability", value=92, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic compact footprint check"),
                        ComparisonCellIn(criterion_id="initial_cost", value=36500, unit="USD", source_kind="owner_entered", source_ref="Synthetic commercial sheet B-01 (example only)"),
                        ComparisonCellIn(criterion_id="operating_cost", value=3100, unit="USD", source_kind="owner_entered", source_ref="Synthetic O&M schedule B-02 (example only)"),
                        ComparisonCellIn(criterion_id="risks", value=74, unit="score_0_100", source_kind="owner_entered", source_ref="Synthetic risk worksheet"),
                    ],
                ),
            ],
        ),
        ComparisonPresetOut(
            key="synthetic_clinic_booster_pump_set",
            title_en="Synthetic Clinic Duplex Variable-Speed Water Booster Pump Comparison (Example)",
            title_ar="مقارنة فنية تمثيلية لمجموعة مضخات رفع المياه المزدوجة للعيادة (بيانات افتراضية)",
            comparison_scope="equipment",
            discipline="plumbing",
            lifecycle_years=10.0,
            criteria=[
                ComparisonCriterionIn(
                    criterion_id="compliance",
                    category="compliance",
                    label="Potable water contact compliance / مطابقة ملامسة مياه الشرب",
                    weight="20",
                    is_mandatory=True,
                    direction="boolean_pass",
                    target_unit="bool",
                    mandatory_expected_bool=True,
                    source_kind="owner_entered",
                    source_ref="Synthetic potable hygiene requirement (verify against locally adopted code)",
                ),
                ComparisonCriterionIn(
                    criterion_id="performance",
                    category="performance",
                    label="Duty flow capacity / تدفق التشغيل",
                    weight="25",
                    is_mandatory=True,
                    direction="higher_better",
                    target_unit="L/s",
                    mandatory_min=2.0,
                    source_kind="owner_entered",
                    source_ref="Synthetic clinic Hunter peak demand baseline",
                ),
                ComparisonCriterionIn(
                    criterion_id="energy",
                    category="energy",
                    label="Shaft power at duty point / القدرة الكهربائية المستهلكة",
                    weight="15",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="kW",
                    source_kind="owner_entered",
                    source_ref="Synthetic pump curve worksheet",
                ),
                ComparisonCriterionIn(
                    criterion_id="initial_cost",
                    category="initial_cost",
                    label="Package initial cost / التكلفة التأسيسية",
                    weight="20",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="USD",
                    source_kind="owner_entered",
                    source_ref="Synthetic sample offer (NOT real pricing)",
                ),
                ComparisonCriterionIn(
                    criterion_id="operating_cost",
                    category="operating_cost",
                    label="Annual maintenance & seal overhaul cost / تكلفة الصيانة السنوية",
                    weight="10",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="USD",
                    source_kind="owner_entered",
                    source_ref="Synthetic O&M schedule",
                ),
                ComparisonCriterionIn(
                    criterion_id="lifecycle_cost",
                    category="lifecycle_cost",
                    label="10-Year Total Lifecycle Cost / تكلفة دورة الحياة",
                    weight="10",
                    is_mandatory=False,
                    direction="lower_better",
                    target_unit="USD",
                    source_kind="calculation",
                    source_ref="Derived deterministically: initial_cost + operating_cost * 10 years",
                ),
            ],
            options=[
                ComparisonOptionIn(
                    option_id="pump_a",
                    name="Synthetic Duplex VFD SS316 Set",
                    vendor_or_source="Synthetic Hydraulic Systems A",
                    risks=["Requires surge tank pre-charge calibration at startup"],
                    cells=[
                        ComparisonCellIn(criterion_id="compliance", value=True, unit="bool", source_kind="owner_entered", source_ref="Synthetic SS316 wetted parts declaration"),
                        ComparisonCellIn(criterion_id="performance", value="2.5", unit="L/s", source_kind="owner_entered", source_ref="Synthetic curve point A"),
                        ComparisonCellIn(criterion_id="energy", value=2200, unit="W", source_kind="owner_entered", source_ref="Synthetic motor input in Watts (W->kW conversion)"),
                        ComparisonCellIn(criterion_id="initial_cost", value=6800, unit="USD", source_kind="owner_entered", source_ref="Synthetic offer P-A (example only)"),
                        ComparisonCellIn(criterion_id="operating_cost", value=450, unit="USD", source_kind="owner_entered", source_ref="Synthetic annual seal plan P-A"),
                    ],
                ),
                ComparisonOptionIn(
                    option_id="pump_b",
                    name="Synthetic Duplex VFD Cast-Iron/Bronze Set",
                    vendor_or_source="Synthetic Hydraulic Systems B",
                    risks=["Unverified VFD harmonics filter certificate"],
                    cells=[
                        ComparisonCellIn(criterion_id="compliance", value=True, unit="bool", source_kind="owner_entered", source_ref="Synthetic vendor declaration"),
                        ComparisonCellIn(criterion_id="performance", value="39.63", unit="GPM", source_kind="owner_entered", source_ref="Synthetic curve point B in GPM (GPM->L/s conversion)"),
                        ComparisonCellIn(criterion_id="energy", value=2.4, unit="kW", source_kind="owner_entered", source_ref="Synthetic motor input in kW"),
                        ComparisonCellIn(criterion_id="initial_cost", value=6100, unit="USD", source_kind="owner_entered", source_ref="Synthetic offer P-B (example only)"),
                        ComparisonCellIn(criterion_id="operating_cost", value=600, unit="USD", source_kind="owner_entered", source_ref="Synthetic annual maintenance P-B"),
                    ],
                ),
            ],
        ),
    ]
