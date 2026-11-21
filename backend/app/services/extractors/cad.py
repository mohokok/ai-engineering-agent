"""Deterministic CAD DXF reader (layers, blocks, text, dimensions, polylines, areas, units, CP1256 decoding, PNG preview)."""

import math
import re
from pathlib import Path
from statistics import median
from typing import Any

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
import ezdxf.math
from ezdxf.path import from_hatch, nesting

from app.schemas.extraction import CadUnitChoice, ExtractedItem, ExtractionMethod
from app.services.extractors.office import ExtractedPayload, _strip_with_raw

# DXF header $INSUNITS code -> (unit_label, linear_scale_to_meters, native_area_unit)
_DXF_INSUNITS_MAP: dict[int, tuple[str, float | None, str | None]] = {
    0: ("unitless", None, "unitless_sq"),
    1: ("in", 0.0254, "sq_in"),
    2: ("ft", 0.3048, "sq_ft"),
    3: ("mi", 1609.344, "sq_mi"),
    4: ("mm", 0.001, "mm2"),
    5: ("cm", 0.01, "cm2"),
    6: ("m", 1.0, "m2"),
    7: ("km", 1000.0, "km2"),
    8: ("uin", 0.0000000254, "sq_uin"),
    9: ("mil", 0.0000254, "sq_mil"),
    10: ("yd", 0.9144, "sq_yd"),
    14: ("dm", 0.1, "dm2"),
}

CAD_UNIT_SCALE_MAP: dict[str, tuple[float | None, str]] = {
    label: (scale, area_u or f"{label}_sq")
    for label, scale, area_u in _DXF_INSUNITS_MAP.values()
}

_DISPLAY_UNIT_LABELS: dict[str, tuple[str, str]] = {
    "m": ("sq m", "m"),
    "cm": ("sq cm", "cm"),
    "mm": ("sq mm", "mm"),
    "dm": ("sq dm", "dm"),
    "km": ("sq km", "km"),
    "in": ("sq in", "in"),
    "ft": ("sq ft", "ft"),
    "yd": ("sq yd", "yd"),
    "mi": ("sq mi", "mi"),
    "uin": ("sq uin", "uin"),
    "mil": ("sq mil", "mil"),
    "unitless": ("unitless sq", "unitless"),
}


def clean_cad_unit_label(val: Any, *, is_ar: bool = False) -> str:
    """Normalize a CAD/BIM unit label, never returning literal 'None' or 'null'."""
    if val is None:
        return "غير محدد" if is_ar else "unspecified unit"
    text = str(val).strip()
    if text.lower() in {"", "none", "null", "unknown", "n/a"}:
        return "غير محدد" if is_ar else "unspecified unit"
    return text


def resolve_cad_unit_context(
    payload: dict[str, Any],
    cad_summary: dict[str, Any],
    *,
    is_ar: bool = False,
) -> dict[str, Any]:
    """Resolve active unit basis respecting owner confirmation and header $INSUNITS plausibility."""
    insunits_raw = cad_summary.get("insunits_code")
    insunits_code = int(insunits_raw) if isinstance(insunits_raw, (int, float)) else None
    raw_declared = clean_cad_unit_label(
        cad_summary.get("declared_unit") or cad_summary.get("units"),
        is_ar=is_ar,
    )
    confirmed_raw = payload.get("owner_confirmed_unit") or cad_summary.get("owner_confirmed_unit")
    confirmed_clean = (
        None
        if confirmed_raw is None or str(confirmed_raw).strip().lower() in {"", "none", "null", "unknown"}
        else str(confirmed_raw).strip()
    )

    if confirmed_clean == "unitless":
        is_doubtful = True
        active_unit = "unitless"
    elif confirmed_clean is not None:
        is_doubtful = False
        active_unit = clean_cad_unit_label(confirmed_clean, is_ar=is_ar)
    else:
        raw_doubtful = (
            payload.get("units_doubtful")
            if "units_doubtful" in payload
            else cad_summary.get("units_doubtful")
        )
        inferred_unitless = (
            insunits_code == 0
            or raw_declared in {"unitless", "unspecified unit", "غير محدد"}
            or (raw_declared.startswith("insunits_") and raw_declared not in CAD_UNIT_SCALE_MAP)
        )
        is_doubtful = bool(raw_doubtful) if raw_doubtful is not None else True
        if inferred_unitless:
            is_doubtful = True
        active_unit = (
            raw_declared
            if raw_declared not in {"unspecified unit", "غير محدد"}
            else clean_cad_unit_label(payload.get("cad_units"), is_ar=is_ar)
        )

    scale_to_m = CAD_UNIT_SCALE_MAP.get(active_unit, (None, ""))[0] if not is_doubtful else None
    if confirmed_clean and confirmed_clean != "unitless":
        basis_display = (
            f"{active_unit} (owner-confirmed; raw header $INSUNITS={insunits_code if insunits_code is not None else 'N/A'} {raw_declared})"
        )
    elif insunits_code is not None:
        basis_display = f"{active_unit} ($INSUNITS={insunits_code})"
    else:
        basis_display = active_unit

    return {
        "active_unit": active_unit,
        "raw_declared": raw_declared,
        "insunits_code": insunits_code,
        "confirmed": confirmed_clean,
        "is_doubtful": is_doubtful,
        "scale_to_m": scale_to_m,
        "basis_display": basis_display,
    }

UNITS_DOUBTFUL_WARNING = "units doubtful - owner must confirm drawing unit"

_THREE_D_ENTITY_TYPES = frozenset({"3DSOLID", "MESH", "SURFACE", "BODY", "3DFACE"})
_TOKEN_SPLIT_RE = re.compile(r"([\s_\-/\\|.,:;()\[\]{}+=]+)")
_ASCII_ALPHA_RE = re.compile(r"[A-Za-z]")
_ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_NUMBER_ONLY_RE = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:m|cm|mm|in|ft)?\s*$", re.IGNORECASE)

_NON_AREA_LAYER_KEYWORDS: tuple[str, ...] = (
    "defpoints",
    "grid",
    "axis",
    "axes",
    "dim",
    "dimension",
    "text",
    "txt",
    "anno",
    "annotation",
    "note",
    "title",
    "tblock",
    "border",
    "frame",
    "viewport",
    "vport",
    "furn",
    "furniture",
    "equip",
    "fixture",
    "sanitary",
    "elec",
    "light",
    "hvac",
    "duct",
    "pipe",
    "plumb",
    "fire",
    "hatch",
    "fill",
    "pattern",
    "sym",
    "symbol",
    "stair",
    "railing",
    "landscape",
    "tree",
    "park",
    "أبعاد",
    "محاور",
    "أثاث",
    "فرش",
    "مفروشات",
    "كتابة",
    "نصوص",
    "ملاحظات",
    "إطار",
    "تهشير",
    "كهرباء",
    "إضاءة",
    "تكييف",
    "صحية",
    "صرف",
    "حريق",
    "رموز",
)

_EXPLICIT_AREA_LAYER_KEYWORDS: tuple[str, ...] = (
    "area",
    "room",
    "space",
    "zone",
    "gross",
    "net",
    "boma",
    "gfa",
    "nfa",
    "boundary",
    "bnd",
    "footprint",
    "slab",
    "floor",
    "plan",
    "plot",
    "site",
    "parcel",
    "wall",
    "arch",
    "مساح",
    "غرف",
    "فراغ",
    "حدود",
    "أرضي",
    "بلاط",
    "جدران",
    "معمار",
    "موقع",
)


def classify_cad_area_bearing_layer(
    layer_name: str,
    *,
    has_closed_contours: bool = False,
    has_explicit_area_layers: bool = False,
) -> tuple[bool, str]:
    """Classify conservatively whether a CAD layer is area-bearing (never treating furniture/dims/grids as area)."""
    norm = layer_name.strip().lower()
    if any(tok in norm for tok in _NON_AREA_LAYER_KEYWORDS):
        return False, "excluded_non_area_layer"
    if any(tok in norm for tok in _EXPLICIT_AREA_LAYER_KEYWORDS):
        return True, "explicit_area_bearing_layer"
    if norm == "0" and has_closed_contours and not has_explicit_area_layers:
        return True, "default_layer_with_closed_contours"
    return False, "unclassified_non_area_layer"


def compute_layer_area_groups(
    closed_areas: list[dict[str, Any]],
    layer_inventory: list[dict[str, Any]],
    *,
    units_doubtful: bool,
) -> list[dict[str, Any]]:
    """Group closed contours per (layer, entity_type) with area_bearing flag and honest non-net-area label."""
    closed_layers = {str(e.get("layer") or "0") for e in closed_areas if isinstance(e, dict)}
    has_explicit_area_layers = any(
        any(tok in ln.strip().lower() for tok in _EXPLICIT_AREA_LAYER_KEYWORDS)
        and not any(tok in ln.strip().lower() for tok in _NON_AREA_LAYER_KEYWORDS)
        for ln in closed_layers
    )

    layer_meta: dict[str, tuple[bool, str]] = {}
    for layer_row in layer_inventory:
        if not isinstance(layer_row, dict):
            continue
        lname = str(layer_row.get("name") or "")
        if not lname:
            continue
        bearing, reason = classify_cad_area_bearing_layer(
            lname,
            has_closed_contours=(lname in closed_layers),
            has_explicit_area_layers=has_explicit_area_layers,
        )
        layer_row["area_bearing"] = bearing
        layer_row["area_bearing_reason"] = reason
        layer_meta[lname] = (bearing, reason)

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in closed_areas:
        if not isinstance(entry, dict):
            continue
        lname = str(entry.get("layer") or "0")
        etype = str(entry.get("type") or "LWPOLYLINE")
        buckets.setdefault((lname, etype), []).append(entry)

    groups: list[dict[str, Any]] = []
    for (lname, etype), entries in sorted(buckets.items()):
        if lname in layer_meta:
            bearing, reason = layer_meta[lname]
        else:
            bearing, reason = classify_cad_area_bearing_layer(
                lname,
                has_closed_contours=True,
                has_explicit_area_layers=has_explicit_area_layers,
            )
        native_sum = round(sum(float(e.get("area_native") or 0.0) for e in entries), 4)
        m2_values = [
            float(e["area_m2"])
            for e in entries
            if e.get("area_m2") is not None
        ]
        m2_sum = (
            round(sum(m2_values), 4)
            if (not units_doubtful and len(m2_values) == len(entries) and m2_values)
            else None
        )
        groups.append(
            {
                "layer": lname,
                "entity_type": etype,
                "area_bearing": bearing,
                "area_bearing_reason": reason,
                "count": len(entries),
                "area_native_sum": native_sum,
                "area_m2_sum": m2_sum,
                "label": "geometric sum, not net building area",
            }
        )
    return groups


def compute_layer_length_groups(
    linear_entries: list[dict[str, Any]],
    *,
    scale_to_m: float | None,
    units_doubtful: bool,
) -> list[dict[str, Any]]:
    """Aggregate ModelSpace linear lengths (LINE, ARC, open LWPOLYLINE/POLYLINE) per (layer, entity_type)."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in linear_entries:
        if not isinstance(entry, dict):
            continue
        lname = str(entry.get("layer") or "0")
        etype = str(entry.get("entity_type") or entry.get("type") or "LINE")
        length_val = float(entry.get("length_native") or entry.get("length_native_sum") or 0.0)
        count_val = int(entry.get("count") or 1)
        if length_val <= 0:
            continue
        bucket = buckets.setdefault(
            (lname, etype),
            {"layer": lname, "entity_type": etype, "count": 0, "length_native_sum": 0.0},
        )
        bucket["count"] += count_val
        bucket["length_native_sum"] += length_val

    groups: list[dict[str, Any]] = []
    for (lname, etype), bucket in sorted(buckets.items()):
        native_sum = round(float(bucket["length_native_sum"]), 4)
        norm = lname.strip().lower()
        is_anno = any(tok in norm for tok in _NON_AREA_LAYER_KEYWORDS)
        length_m_sum = (
            round(native_sum * float(scale_to_m), 4)
            if (not units_doubtful and scale_to_m is not None)
            else None
        )
        groups.append(
            {
                "layer": lname,
                "entity_type": etype,
                "count": int(bucket["count"]),
                "length_native_sum": native_sum,
                "length_m_sum": length_m_sum,
                "is_non_structural_layer": is_anno,
            }
        )
    return groups


def _to_legacy_8bit_bytes(segment: str) -> bytes | None:
    """Convert Latin-1 / CP1252-decoded legacy ANSI chars back into raw 8-bit bytes if possible."""
    out = bytearray()
    for ch in segment:
        code = ord(ch)
        if code <= 0xFF:
            out.append(code)
        else:
            try:
                encoded = ch.encode("cp1252")
            except UnicodeEncodeError:
                return None
            out.extend(encoded)
    return bytes(out)


def _is_cp1256_arabic_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x0621 <= code <= 0x064A
        or 0x064B <= code <= 0x0652
        or 0x0660 <= code <= 0x0669
        or ch in {"پ", "چ", "ژ", "گ", "ک", "ی", "،", "؛", "؟", "\u0640"}
    )


def _try_decode_cp1256_token(token: str) -> tuple[str | None, int, int]:
    """Return (decoded_token, high_byte_count, decoded_standard_arabic_count) for a non-ASCII token."""
    if not token or _ASCII_ALPHA_RE.search(token):
        return None, 0, 0
    high_count = sum(1 for ch in token if ord(ch) >= 0x80)
    if high_count == 0:
        return None, 0, 0
    raw_bytes = _to_legacy_8bit_bytes(token)
    if raw_bytes is None:
        return None, 0, 0
    try:
        candidate = raw_bytes.decode("cp1256", errors="strict")
    except UnicodeDecodeError:
        return None, 0, 0
    for c in candidate:
        oc = ord(c)
        if oc < 0x20 or (0x7F <= oc <= 0x9F):
            return None, 0, 0
    valid_high = sum(
        1 for orig, dec in zip(token, candidate) if ord(orig) < 0x80 or _is_cp1256_arabic_char(dec)
    )
    if valid_high != len(token):
        return None, 0, 0
    arabic_letters = sum(1 for c in candidate if 0x0621 <= ord(c) <= 0x064A)
    if arabic_letters == 0:
        return None, 0, 0
    return candidate, high_count, arabic_letters


def _decode_cad_text(raw: str, *, header_codepage: str = "") -> tuple[str, str | None, str | None]:
    """Decode DXF unicode escapes and legacy CP1256 Arabic mojibake while keeping raw strings."""
    if not raw:
        return "", None, None

    working = raw
    methods: list[str] = []
    if hasattr(ezdxf, "has_dxf_unicode") and ezdxf.has_dxf_unicode(working):
        decoded_u = ezdxf.decode_dxf_unicode(working)
        if decoded_u != working:
            working = decoded_u
            methods.append("dxf_unicode")

    # Never re-decode strings that already contain real Unicode Arabic script.
    if _ARABIC_SCRIPT_RE.search(working):
        return (
            working,
            raw if working != raw else None,
            "+".join(methods) if methods else None,
        )

    if not any(ord(ch) >= 0x80 for ch in working):
        return (
            working,
            raw if working != raw else None,
            "+".join(methods) if methods else None,
        )

    parts = _TOKEN_SPLIT_RE.split(working)
    token_candidates: list[tuple[str | None, int, int]] = []
    has_strong_arabic_mojibake = False
    for i, part in enumerate(parts):
        if i % 2 == 1:
            token_candidates.append((None, 0, 0))
            continue
        cand, high_cnt, arab_cnt = _try_decode_cp1256_token(part)
        token_candidates.append((cand, high_cnt, arab_cnt))
        if cand is not None and high_cnt >= 2 and arab_cnt >= 2:
            has_strong_arabic_mojibake = True

    explicit_1256 = "1256" in (header_codepage or "").upper()
    if not (has_strong_arabic_mojibake or explicit_1256):
        return (
            working,
            raw if working != raw else None,
            "+".join(methods) if methods else None,
        )

    out_parts: list[str] = []
    changed_cp1256 = False
    for i, part in enumerate(parts):
        cand, high_cnt, arab_cnt = token_candidates[i]
        if cand is None:
            out_parts.append(part)
            continue
        # Protect standalone Latin-1 diameter sign 'Ø' when no multi-char Arabic phrase exists
        if part == "\u00d8" and not has_strong_arabic_mojibake:
            out_parts.append(part)
            continue
        if high_cnt >= 2 or has_strong_arabic_mojibake or (explicit_1256 and arab_cnt >= 1):
            out_parts.append(cand)
            changed_cp1256 = True
        else:
            out_parts.append(part)

    final = "".join(out_parts)
    if changed_cp1256:
        methods.append("cp1256_mojibake_decoded")
    return (
        final,
        raw if final != raw else None,
        "+".join(methods) if methods else None,
    )


def _assess_cad_unit_plausibility(
    *,
    insunits_raw: int,
    declared_unit_label: str,
    declared_scale_to_m: float | None,
    dim_measurements: list[float],
    dim_override_numbers: list[float],
    dim_override_mismatches: int,
    closed_areas_native: list[tuple[float, float]],
    confirmed_unit: str | None = None,
) -> dict[str, Any]:
    """Assess whether declared CAD units are plausible against dimensions and closed areas."""
    reasons: list[str] = []

    if confirmed_unit is not None:
        if confirmed_unit == "unitless":
            return {
                "units_doubtful": True,
                "units_status": "unitless_owner_confirmed",
                "owner_confirmed_unit": "unitless",
                "effective_scale_to_m": None,
                "effective_unit_label": "unitless",
                "units_display": f"unitless (owner confirmed; file header {declared_unit_label}, $INSUNITS={insunits_raw})",
                "warnings": [
                    f"Owner confirmed drawing as unitless (header $INSUNITS={insunits_raw}); area_m2 kept null."
                ],
                "reasons": ["owner_confirmed_unitless"],
            }
        scale_to_m, _area_u = CAD_UNIT_SCALE_MAP[confirmed_unit]
        warn_list: list[str] = []
        if confirmed_unit != declared_unit_label:
            warn_list.append(
                f"Owner confirmed drawing unit '{confirmed_unit}' overriding file header "
                f"$INSUNITS={insunits_raw} ({declared_unit_label}); raw native values preserved untouched."
            )
        return {
            "units_doubtful": False,
            "units_status": "owner_confirmed",
            "owner_confirmed_unit": confirmed_unit,
            "effective_scale_to_m": scale_to_m,
            "effective_unit_label": confirmed_unit,
            "units_display": f"{confirmed_unit} (owner confirmed; file header {declared_unit_label}, $INSUNITS={insunits_raw})",
            "warnings": warn_list,
            "reasons": [],
        }

    # Unconfirmed: check unitless/unknown header first
    if insunits_raw == 0 or declared_scale_to_m is None:
        return {
            "units_doubtful": True,
            "units_status": "unitless",
            "owner_confirmed_unit": None,
            "effective_scale_to_m": None,
            "effective_unit_label": declared_unit_label,
            "units_display": f"{declared_unit_label} ($INSUNITS={insunits_raw})",
            "warnings": [
                f"$INSUNITS={insunits_raw} ({declared_unit_label}): {UNITS_DOUBTFUL_WARNING}; "
                "CAD areas and lengths are kept in raw native drawing units with area_m2 set to null."
            ],
            "reasons": ["missing_or_unitless_insunits"],
        }

    dims = [d for d in (dim_measurements + dim_override_numbers) if d > 1e-6]
    med_dim = median(dims) if dims else None
    med_dim_m = (med_dim * declared_scale_to_m) if med_dim is not None else None
    max_area_native = max((a for a, _ in closed_areas_native), default=None)
    max_perim_native = max((p for _, p in closed_areas_native if p > 0), default=None)
    max_area_m2 = (
        max_area_native * (declared_scale_to_m ** 2)
        if max_area_native is not None
        else None
    )

    if declared_unit_label in {"in", "ft", "yd", "uin", "mil"}:
        if med_dim_m is not None and med_dim_m < 0.45:
            reasons.append(
                f"median dimension {round(med_dim, 4)} {declared_unit_label} converts to "
                f"{round(med_dim_m, 4)} m (< 0.45 m), suggesting drawing may actually be in meters or cm"
            )
        if max_area_m2 is not None and max_area_native is not None:
            if (max_area_native >= 10.0 and max_area_m2 < 12.0) or (
                max_perim_native is not None and max_perim_native >= 40.0 and max_area_m2 < 12.0
            ):
                reasons.append(
                    f"largest closed area {round(max_area_native, 4)} converts to only "
                    f"{round(max_area_m2, 4)} m2 under {declared_unit_label} ($INSUNITS={insunits_raw})"
                )
    elif declared_unit_label == "mm":
        if med_dim is not None and med_dim < 50.0:
            reasons.append(
                f"median dimension {round(med_dim, 4)} mm ({round(med_dim_m or 0.0, 4)} m) looks meter/cm-scaled"
            )
        if max_area_m2 is not None and max_area_native is not None and max_area_native >= 1.0 and max_area_m2 < 0.25:
            reasons.append(
                f"largest closed area {round(max_area_native, 4)} mm2 converts to {round(max_area_m2, 6)} m2"
            )
    elif declared_unit_label == "cm":
        if med_dim is not None and med_dim < 15.0:
            reasons.append(
                f"median dimension {round(med_dim, 4)} cm ({round(med_dim_m or 0.0, 4)} m) looks meter-scaled"
            )
        if max_area_m2 is not None and max_area_native is not None and max_area_native >= 1.0 and max_area_m2 < 0.25:
            reasons.append(
                f"largest closed area {round(max_area_native, 4)} cm2 converts to {round(max_area_m2, 6)} m2"
            )
    elif declared_unit_label == "m":
        if med_dim is not None and med_dim >= 400.0:
            reasons.append(
                f"median dimension {round(med_dim, 4)} declared as meters (>= 400 m) looks mm/cm-scaled"
            )
        if max_area_native is not None and max_area_native > 50_000.0:
            reasons.append(
                f"largest closed area {round(max_area_native, 2)} declared as m2 (> 50,000) looks mm/cm-scaled"
            )

    if dim_override_mismatches > 0 and med_dim is not None:
        reasons.append(
            f"{dim_override_mismatches} DIMENSION entity override value(s) diverge from raw geometry measurement"
        )

    if reasons:
        detail = "; ".join(reasons)
        return {
            "units_doubtful": True,
            "units_status": "doubtful",
            "owner_confirmed_unit": None,
            "effective_scale_to_m": None,
            "effective_unit_label": declared_unit_label,
            "units_display": f"{declared_unit_label} ($INSUNITS={insunits_raw}; DOUBTFUL)",
            "warnings": [
                f"{UNITS_DOUBTFUL_WARNING} — file header declares $INSUNITS={insunits_raw} ({declared_unit_label}), "
                f"but geometry plausibility check flagged inconsistency: {detail}. "
                "area_m2 is set to null until confirmed by the owner."
            ],
            "reasons": reasons,
        }

    return {
        "units_doubtful": False,
        "units_status": "plausible",
        "owner_confirmed_unit": None,
        "effective_scale_to_m": declared_scale_to_m,
        "effective_unit_label": declared_unit_label,
        "units_display": f"{declared_unit_label} ($INSUNITS={insunits_raw})",
        "warnings": [],
        "reasons": [],
    }


def _apply_confirmed_unit_fields(
    entry: dict[str, Any],
    *,
    owner_confirmed_unit: str | None,
    declared_unit_label: str,
    declared_area_unit: str | None,
    scale_to_m: float | None,
) -> dict[str, Any]:
    """Attach confirmed area_m2 and display unit labels while preserving raw declared units and native values untouched."""
    native_area = entry.get("area_native")
    area_m2 = (
        round(float(native_area) * (scale_to_m ** 2), 6)
        if native_area is not None and scale_to_m is not None
        else None
    )
    entry["area_m2"] = area_m2
    if owner_confirmed_unit is not None:
        disp_area_unit, disp_perim_unit = _DISPLAY_UNIT_LABELS.get(
            owner_confirmed_unit, (f"sq {owner_confirmed_unit}", owner_confirmed_unit)
        )
        entry["confirmed_unit"] = owner_confirmed_unit
        entry["raw_declared_unit"] = declared_unit_label
        entry["raw_declared_area_unit"] = declared_area_unit
        if owner_confirmed_unit == "unitless" or scale_to_m is None:
            entry["display_area_unit"] = "unitless sq"
            entry["display_perimeter_unit"] = "unitless"
        else:
            entry["display_area"] = native_area
            entry["display_area_unit"] = disp_area_unit
            if entry.get("perimeter_native") is not None:
                entry["display_perimeter"] = entry["perimeter_native"]
                entry["display_perimeter_unit"] = disp_perim_unit
    return entry


def _format_closed_area_text(
    *,
    ent_kind: str,
    q_dict: dict[str, Any],
    unit_label: str,
    area_unit: str | None,
    owner_confirmed_unit: str | None,
) -> str:
    native_area = q_dict["area_native"]
    area_m2 = q_dict.get("area_m2")
    perim = q_dict.get("perimeter_native")
    if owner_confirmed_unit is not None and owner_confirmed_unit != "unitless":
        disp_area_unit = str(q_dict.get("display_area_unit") or "sq m")
        disp_perim_unit = str(q_dict.get("display_perimeter_unit") or owner_confirmed_unit)
        m2_note = f" ({area_m2} m2)" if area_m2 is not None and owner_confirmed_unit != "m" else ""
        if ent_kind == "HATCH":
            gross_area = q_dict.get("gross_area_native")
            hole_count = q_dict.get("island_count", 0)
            return (
                f"HATCH Confirmed Net Area={native_area} {disp_area_unit}{m2_note} "
                f"(gross={gross_area}, islands={hole_count}) [raw declared: {native_area} {area_unit}]"
            )
        if ent_kind == "CIRCLE":
            radius_val = q_dict.get("radius")
            return (
                f"CIRCLE r={radius_val} {disp_perim_unit} | Confirmed Area={native_area} {disp_area_unit}{m2_note} "
                f"[raw declared: {native_area} {area_unit}]"
            )
        return (
            f"Closed {ent_kind} | Confirmed Area={native_area} {disp_area_unit}{m2_note} | "
            f"Perimeter={perim} {disp_perim_unit} [raw declared: {native_area} {area_unit}, {perim} {unit_label}]"
        )

    if ent_kind == "HATCH":
        gross_area = q_dict.get("gross_area_native")
        hole_count = q_dict.get("island_count", 0)
        return f"HATCH Net Area={native_area} {area_unit} (gross={gross_area}, islands={hole_count})"
    if ent_kind == "CIRCLE":
        radius_val = q_dict.get("radius")
        m2_note = f" ({area_m2} m2)" if area_m2 is not None and area_unit != "m2" else ""
        return f"CIRCLE r={radius_val} {unit_label} | Area={native_area} {area_unit}{m2_note}"
    m2_note = f" ({area_m2} m2)" if area_m2 is not None and area_unit != "m2" else ""
    return f"Closed {ent_kind} | Area={native_area} {area_unit}{m2_note} | Perimeter={perim} {unit_label}"


def apply_confirmed_cad_unit(
    payload_data: dict[str, Any],
    *,
    confirmed_unit: CadUnitChoice,
) -> dict[str, Any]:
    """Return an updated CAD payload copy with area_m2 and confirmed display units without altering native values."""
    scale_to_m, _ = CAD_UNIT_SCALE_MAP[confirmed_unit]
    inv = dict(payload_data.get("drawing_inventory") or {})
    insunits_raw = int(inv.get("insunits_code", 0) or 0)
    declared_label = str(inv.get("declared_unit") or inv.get("units") or "unknown")
    declared_area_unit = str(inv.get("area_unit") or f"{declared_label}_sq")
    is_unitless = scale_to_m is None
    disp_area_unit, disp_linear_unit = _DISPLAY_UNIT_LABELS.get(
        confirmed_unit, (f"sq {confirmed_unit}", confirmed_unit)
    )

    updated = dict(payload_data)
    updated["owner_confirmed_unit"] = confirmed_unit
    updated["units_doubtful"] = is_unitless
    updated["units_status"] = "unitless_owner_confirmed" if is_unitless else "owner_confirmed"
    updated["cad_units"] = (
        f"{confirmed_unit} (owner confirmed; file header {declared_label}, $INSUNITS={insunits_raw})"
    )

    new_closed_areas: list[dict[str, Any]] = []
    for raw_entry in inv.get("closed_areas") or []:
        entry = _apply_confirmed_unit_fields(
            dict(raw_entry),
            owner_confirmed_unit=confirmed_unit,
            declared_unit_label=declared_label,
            declared_area_unit=str(raw_entry.get("area_native_unit") or declared_area_unit),
            scale_to_m=scale_to_m,
        )
        new_closed_areas.append(entry)

    new_dimensions: list[dict[str, Any]] = []
    for raw_dim in inv.get("dimensions") or []:
        d = dict(raw_dim)
        d["raw_declared_unit"] = str(d.get("raw_declared_unit") or d.get("unit") or declared_label)
        d["display_unit"] = disp_linear_unit
        d["confirmed_unit"] = confirmed_unit
        new_dimensions.append(d)

    layers_copy = [dict(layer_row) for layer_row in (inv.get("layers") or [])]
    inv["layers"] = layers_copy
    inv["closed_areas"] = new_closed_areas
    inv["layer_area_groups"] = compute_layer_area_groups(
        new_closed_areas,
        layers_copy,
        units_doubtful=is_unitless,
    )
    if inv.get("layer_length_groups"):
        inv["layer_length_groups"] = compute_layer_length_groups(
            list(inv.get("layer_length_groups") or []),
            scale_to_m=scale_to_m,
            units_doubtful=is_unitless,
        )
    if new_dimensions:
        inv["dimensions"] = new_dimensions
    inv["units_doubtful"] = is_unitless
    inv["units_status"] = updated["units_status"]
    inv["owner_confirmed_unit"] = confirmed_unit
    inv["display_area_unit"] = disp_area_unit
    inv["display_linear_unit"] = disp_linear_unit
    inv["confirmed_scale_to_m"] = scale_to_m
    updated["drawing_inventory"] = inv

    new_items: list[dict[str, Any]] = []
    for raw_item in payload_data.get("items") or []:
        item = dict(raw_item)
        if item.get("item_type") == "cad_polyline_area" and isinstance(item.get("quantities"), dict):
            q = _apply_confirmed_unit_fields(
                dict(item["quantities"]),
                owner_confirmed_unit=confirmed_unit,
                declared_unit_label=declared_label,
                declared_area_unit=str(item["quantities"].get("area_native_unit") or declared_area_unit),
                scale_to_m=scale_to_m,
            )
            item["quantities"] = q
            loc = str(item.get("location") or "")
            ent_kind = loc.rsplit("|", 1)[-1] if "|" in loc else "LWPOLYLINE"
            item["text"] = _format_closed_area_text(
                ent_kind=ent_kind,
                q_dict=q,
                unit_label=declared_label,
                area_unit=q.get("area_native_unit"),
                owner_confirmed_unit=confirmed_unit,
            )
        elif item.get("item_type") == "cad_dimension" and isinstance(item.get("properties"), dict):
            props = dict(item["properties"])
            props["raw_declared_unit"] = str(props.get("raw_declared_unit") or props.get("unit") or declared_label)
            props["display_unit"] = disp_linear_unit
            props["confirmed_unit"] = confirmed_unit
            item["properties"] = props
        new_items.append(item)
    updated["items"] = new_items

    kept_warnings = [
        w for w in (payload_data.get("warnings") or []) if UNITS_DOUBTFUL_WARNING not in w
    ]
    kept_warnings.append(
        f"Owner confirmed drawing unit '{confirmed_unit}' ({disp_area_unit} / {disp_linear_unit}; "
        f"header declared $INSUNITS={insunits_raw}, {declared_label}); raw native values preserved untouched."
    )
    updated["warnings"] = kept_warnings
    return updated


def _polyline_bulge_area_and_perimeter(
    points_xyb: list[tuple[float, float, float]],
    *,
    closed: bool,
) -> tuple[float, float]:
    """Compute exact 2D area and arc-aware perimeter for LWPOLYLINE/POLYLINE vertices (x, y, bulge)."""
    n = len(points_xyb)
    if n < 2:
        return 0.0, 0.0
    signed_poly_twice = 0.0
    arc_area_sum = 0.0
    perim = 0.0
    seg_count = n if closed else n - 1
    for i in range(seg_count):
        x1, y1, bulge = points_xyb[i]
        x2, y2, _ = points_xyb[(i + 1) % n]
        chord = math.hypot(x2 - x1, y2 - y1)
        if closed:
            signed_poly_twice += x1 * y2 - x2 * y1
        if abs(bulge) > 1e-12 and chord > 1e-12:
            theta = 4.0 * math.atan(bulge)
            radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
            perim += radius * abs(theta)
            if closed:
                seg_area = 0.5 * (radius * radius) * (abs(theta) - math.sin(abs(theta)))
                arc_area_sum += seg_area if bulge > 0 else -seg_area
        else:
            perim += chord
    total_area = abs(0.5 * signed_poly_twice + arc_area_sum) if closed else 0.0
    return total_area, perim


def _polygon_perimeter(points: list[tuple[float, float]], *, closed: bool) -> float:
    _, perim = _polyline_bulge_area_and_perimeter(
        [(x, y, 0.0) for x, y in points],
        closed=closed,
    )
    return perim


def _path_polygon_area(path_obj: Any) -> float:
    pts = [(float(p.x), float(p.y)) for p in path_obj.flattening(distance=0.001)]
    return float(ezdxf.math.area(pts)) if len(pts) >= 3 else 0.0


def _compute_hatch_areas(
    ent: Any,
    tree_nodes: list[Any],
    *,
    hatch_style: int,
    depth: int = 0,
) -> tuple[float, float, int]:
    """Return (net_area, gross_outer_area, island_hole_count) from nested hatch loops."""
    net = 0.0
    gross_outer = 0.0
    holes = 0
    for node in tree_nodes:
        if isinstance(node, list):
            if not node:
                continue
            outer_area = _path_polygon_area(node[0])
            if depth == 0:
                gross_outer += outer_area
                net += outer_area
            elif hatch_style == 2:
                # hatch_style=2 (IGNORE) fills entire outer region ignoring islands
                pass
            elif hatch_style == 1 and depth > 1:
                # hatch_style=1 (OUTER) ignores islands deeper than level 1
                pass
            else:
                sign = 1.0 if (depth % 2 == 0) else -1.0
                net += sign * outer_area
                if depth % 2 == 1:
                    holes += 1
            if len(node) > 1:
                child_net, _, child_holes = _compute_hatch_areas(
                    ent, node[1:], hatch_style=hatch_style, depth=depth + 1
                )
                net += child_net
                holes += child_holes
        else:
            area_val = _path_polygon_area(node)
            if depth == 0:
                gross_outer += area_val
                net += area_val
            elif hatch_style == 2:
                pass
            elif hatch_style == 1 and depth > 1:
                pass
            else:
                sign = 1.0 if (depth % 2 == 0) else -1.0
                net += sign * area_val
                if depth % 2 == 1:
                    holes += 1
    return net, gross_outer, holes


def _render_modelspace_preview(doc: Any, msp: Any, out_png_path: Path) -> bool:
    """Render ModelSpace vector geometry cleanly to A4 Landscape PNG without modifying source DXF."""
    backend = PyMuPdfBackend()
    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.COLOR,
    )
    Frontend(RenderContext(doc), backend, config=cfg).draw_layout(msp)
    page = layout.Page(297, 210, layout.Units.mm, margins=layout.Margins.all(10))
    png_bytes = backend.get_pixmap_bytes(page, fmt="png", dpi=150)
    if png_bytes:
        out_png_path.write_bytes(png_bytes)
        return True
    return False


def _append_closed_area_record(
    *,
    payload: ExtractedPayload,
    area_inventory: list[dict[str, Any]],
    pending: dict[str, Any],
    idx: int,
    source_file: str,
    file_id: str | None,
    version_number: int,
    extraction_method: ExtractionMethod,
    area_unit: str | None,
    unit_label: str,
    effective_scale_to_m: float | None,
    owner_confirmed_unit: str | None = None,
) -> int:
    """Finalize one closed geometry / HATCH record with verified or null area_m2 and confirmed display units."""
    native_area = float(pending["area_native"])
    q_dict = _apply_confirmed_unit_fields(
        dict(pending["quantities"]),
        owner_confirmed_unit=owner_confirmed_unit,
        declared_unit_label=unit_label,
        declared_area_unit=area_unit,
        scale_to_m=effective_scale_to_m,
    )

    ent_kind = str(pending["type"])
    handle = str(pending["handle"])
    ent_layer = str(pending["layer"])
    raw_layer = pending.get("raw_layer")
    cad_space = str(pending["space"])
    page_label = str(pending["page_label"])
    perim = pending.get("perimeter_native")

    if ent_kind == "HATCH":
        gross_area = float(q_dict["gross_area_native"])
        hole_count = int(q_dict["island_count"])
        hole_area = float(q_dict["net_subtracted_area_native"])
        if hole_count > 0:
            payload.warnings.append(
                f"HATCH entity handle={handle} on layer '{ent_layer}' contains {hole_count} island hole(s); "
                f"net area={native_area} {area_unit} (gross={gross_area}, net_subtracted={hole_area})."
            )
    text = _format_closed_area_text(
        ent_kind=ent_kind,
        q_dict=q_dict,
        unit_label=unit_label,
        area_unit=area_unit,
        owner_confirmed_unit=owner_confirmed_unit,
    )

    idx += 1
    payload.items.append(
        ExtractedItem(
            item_index=idx,
            item_type="cad_polyline_area",
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
            page_or_sheet=page_label,
            location=f"handle:{handle}|layer:{ent_layer}|{ent_kind}",
            text=text,
            unit_or_format=area_unit,
            area=native_area,
            perimeter_or_length=perim,
            quantities=q_dict,
            layer=ent_layer,
            raw_layer=raw_layer,
            entity_handle=handle,
            cad_space=cad_space,
            extraction_method=extraction_method,
        )
    )
    inv_entry: dict[str, Any] = {
        "handle": handle,
        "layer": ent_layer,
        "space": cad_space,
        "type": ent_kind,
        **q_dict,
    }
    if raw_layer:
        inv_entry["raw_layer"] = raw_layer
    area_inventory.append(inv_entry)
    return idx


def extract_dxf(
    path: Path,
    *,
    output_pages_dir: Path,
    pages_relative_prefix: str,
    source_file: str,
    file_id: str | None,
    version_number: int,
    extraction_method: ExtractionMethod = "native",
    confirmed_unit: CadUnitChoice | None = None,
) -> tuple[ExtractedPayload, str | None, dict[str, Any]]:
    """Deterministically inventory DXF header units, layers, blocks, text, dimensions, and polyline areas."""
    payload = ExtractedPayload()
    output_pages_dir.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.readfile(str(path))
    header_codepage = str(doc.header.get("$DWGCODEPAGE", "") or "")
    insunits_raw = int(doc.header.get("$INSUNITS", 0) or 0)
    unit_label, scale_to_m, area_unit = _DXF_INSUNITS_MAP.get(
        insunits_raw, (f"insunits_{insunits_raw}", None, f"insunits_{insunits_raw}_sq")
    )

    msp = doc.modelspace()
    layout_records: list[tuple[str, str, Any]] = [("modelspace", "Model", msp)]
    for lay in doc.layouts:
        if lay.name.lower() != "model":
            lay_dec, _, _ = _decode_cad_text(str(lay.name), header_codepage=header_codepage)
            layout_records.append(("paperspace", lay_dec or str(lay.name), lay))

    layer_entity_counts: dict[str, dict[str, int]] = {}
    block_insert_counts: dict[str, int] = {}
    entity_type_counts: dict[str, int] = {}
    three_d_count = 0
    proxy_count = 0
    paperspace_entity_count = 0
    paperspace_viewport_count = 0
    modelspace_entity_count = 0

    for cad_space, _lay_name, lay_obj in layout_records:
        for ent in lay_obj:
            dxftype = ent.dxftype()
            raw_ent_layer = str(getattr(ent.dxf, "layer", "0") or "0")
            entity_type_counts[dxftype] = entity_type_counts.get(dxftype, 0) + 1
            counts_bucket = layer_entity_counts.setdefault(
                raw_ent_layer, {"modelspace": 0, "paperspace": 0, "total": 0}
            )
            counts_bucket[cad_space] += 1
            counts_bucket["total"] += 1
            if cad_space == "modelspace":
                modelspace_entity_count += 1
            else:
                paperspace_entity_count += 1
                if dxftype == "VIEWPORT":
                    paperspace_viewport_count += 1
            if dxftype == "INSERT":
                blk_name_raw = str(getattr(ent.dxf, "name", "") or "")
                block_insert_counts[blk_name_raw] = block_insert_counts.get(blk_name_raw, 0) + 1
            elif dxftype in _THREE_D_ENTITY_TYPES:
                three_d_count += 1
            elif dxftype == "ACAD_PROXY_ENTITY":
                proxy_count += 1

    # 1. Layers inventory (with CP1256 Arabic decoding while preserving raw names)
    idx = 0
    layer_inventory: list[dict[str, Any]] = []
    encoding_recovered_count = 0
    for layer in doc.layers:
        raw_l_name = str(layer.dxf.name)
        l_name, l_raw_orig, l_enc_method = _decode_cad_text(
            raw_l_name, header_codepage=header_codepage
        )
        if l_raw_orig is not None:
            encoding_recovered_count += 1
        l_counts = layer_entity_counts.get(
            raw_l_name,
            layer_entity_counts.get(l_name, {"modelspace": 0, "paperspace": 0, "total": 0}),
        )
        is_on = bool(layer.is_on())
        is_frozen = bool(layer.is_frozen())
        is_locked = bool(layer.is_locked())
        l_props: dict[str, Any] = {
            "color": int(getattr(layer.dxf, "color", 7)),
            "linetype": str(getattr(layer.dxf, "linetype", "Continuous") or "Continuous"),
            "is_on": is_on,
            "is_frozen": is_frozen,
            "is_locked": is_locked,
            "modelspace_entities": l_counts["modelspace"],
            "paperspace_entities": l_counts["paperspace"],
            "total_entities": l_counts["total"],
        }
        if l_raw_orig is not None:
            l_props["raw_name"] = l_raw_orig
            l_props["encoding_recovered"] = l_enc_method
        idx += 1
        payload.items.append(
            ExtractedItem(
                item_index=idx,
                item_type="cad_layer",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="dxf:layers",
                location=f"layer:{l_name}",
                text=f"Layer '{l_name}' | entities={l_counts['total']} (model={l_counts['modelspace']}, paper={l_counts['paperspace']})",
                raw_text=l_raw_orig,
                normalization_applied=l_enc_method,
                layer=l_name,
                raw_layer=l_raw_orig,
                properties=l_props,
                extraction_method=extraction_method,
            )
        )
        layer_entry: dict[str, Any] = {"name": l_name, **l_props}
        layer_inventory.append(layer_entry)

    # 2. Blocks & XREF detection (skip internal anonymous *Model_Space / *Paper_Space blocks)
    block_inventory: list[dict[str, Any]] = []
    xref_names: list[str] = []
    for blk in doc.blocks:
        raw_b_name = str(blk.name)
        if raw_b_name.startswith("*"):
            continue
        b_name, b_raw_orig, b_enc_method = _decode_cad_text(
            raw_b_name, header_codepage=header_codepage
        )
        if b_raw_orig is not None:
            encoding_recovered_count += 1
        block_entity = getattr(blk, "block", None)
        is_xref = bool(getattr(block_entity, "is_xref", False) or getattr(blk, "is_xref", False))
        xref_path_raw = (
            str(getattr(getattr(block_entity, "dxf", None), "xref_path", "") or "")
            if is_xref
            else ""
        )
        xref_path, _, _ = _decode_cad_text(xref_path_raw, header_codepage=header_codepage)
        if is_xref:
            xref_names.append(b_name)
        def_entities = sum(1 for _ in blk)
        ins_count = block_insert_counts.get(raw_b_name, block_insert_counts.get(b_name, 0))
        b_props: dict[str, Any] = {
            "definition_entities": def_entities,
            "insert_count": ins_count,
            "is_xref": is_xref,
            "xref_path": xref_path or None,
        }
        if b_raw_orig is not None:
            b_props["raw_name"] = b_raw_orig
            b_props["encoding_recovered"] = b_enc_method
        idx += 1
        payload.items.append(
            ExtractedItem(
                item_index=idx,
                item_type="cad_block",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet="dxf:blocks",
                location=f"block:{b_name}",
                text=f"Block '{b_name}' | inserts={ins_count} | entities_in_def={def_entities}"
                + (" [EXTERNAL XREF]" if is_xref else ""),
                raw_text=b_raw_orig,
                normalization_applied=b_enc_method,
                block_name=b_name,
                raw_block_name=b_raw_orig,
                properties=b_props,
                extraction_method=extraction_method,
            )
        )
        block_inventory.append({"name": b_name, **b_props})

    if xref_names:
        payload.warnings.append(
            f"External XREF block(s) detected ({', '.join(xref_names)}); external referenced DWGs are NOT loaded or resolved."
        )

    # 3. Entities across ModelSpace and PaperSpace (TEXT, MTEXT, ATTRIB, DIMENSION, LINE, ARC, LWPOLYLINE, POLYLINE, CIRCLE, HATCH)
    area_inventory: list[dict[str, Any]] = []
    pending_areas: list[dict[str, Any]] = []
    pending_lengths: list[dict[str, Any]] = []
    layer_block_counts_map: dict[tuple[str, str], int] = {}
    text_samples: list[dict[str, Any]] = []
    dimension_inventory: list[dict[str, Any]] = []
    dim_measurements: list[float] = []
    dim_override_numbers: list[float] = []
    dim_override_mismatches = 0

    for cad_space, lay_name, lay_obj in layout_records:
        page_label = f"dxf:{cad_space}:{lay_name}"
        for ent in lay_obj:
            dxftype = ent.dxftype()
            handle = str(getattr(ent.dxf, "handle", "") or "no_handle")
            raw_ent_layer = str(getattr(ent.dxf, "layer", "0") or "0")
            ent_layer, ent_layer_raw, _ = _decode_cad_text(
                raw_ent_layer, header_codepage=header_codepage
            )

            if dxftype == "TEXT":
                raw_t = str(getattr(ent.dxf, "text", "") or "")
                dec_t, dec_raw_orig, enc_note = _decode_cad_text(raw_t, header_codepage=header_codepage)
                if dec_raw_orig is not None:
                    encoding_recovered_count += 1
                cleaned_t, strip_raw, strip_norm = _strip_with_raw(dec_t)
                raw_kept = raw_t if (dec_raw_orig is not None or strip_raw is not None) else None
                norm_label = (
                    f"{enc_note}+{strip_norm}" if enc_note and strip_norm != "verbatim" else (enc_note or strip_norm)
                )
                if cleaned_t:
                    idx += 1
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="text",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=page_label,
                            location=f"handle:{handle}|layer:{ent_layer}|TEXT",
                            text=cleaned_t,
                            raw_text=raw_kept,
                            normalization_applied=norm_label,
                            layer=ent_layer,
                            raw_layer=ent_layer_raw,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )
                    payload.counts.text_items += 1
                    sample_t: dict[str, Any] = {
                        "handle": handle,
                        "layer": ent_layer,
                        "space": cad_space,
                        "type": "TEXT",
                        "text": cleaned_t,
                    }
                    if raw_kept is not None:
                        sample_t["raw_text"] = raw_kept
                    text_samples.append(sample_t)

            elif dxftype == "MTEXT":
                raw_mt = str(getattr(ent, "text", "") or "")
                plain_mt_raw = str(ent.plain_text() or "").strip()
                plain_mt, mt_dec_raw, mt_enc = _decode_cad_text(
                    plain_mt_raw, header_codepage=header_codepage
                )
                if mt_dec_raw is not None:
                    encoding_recovered_count += 1
                if plain_mt:
                    idx += 1
                    norm_mt = (
                        f"{mt_enc}+mtext_formatting_stripped"
                        if mt_enc and raw_mt != plain_mt_raw
                        else (mt_enc or ("mtext_formatting_stripped" if raw_mt != plain_mt else "verbatim"))
                    )
                    raw_mt_kept = raw_mt if raw_mt != plain_mt else None
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="text",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=page_label,
                            location=f"handle:{handle}|layer:{ent_layer}|MTEXT",
                            text=plain_mt,
                            raw_text=raw_mt_kept,
                            normalization_applied=norm_mt,
                            layer=ent_layer,
                            raw_layer=ent_layer_raw,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )
                    payload.counts.text_items += 1
                    sample_mt: dict[str, Any] = {
                        "handle": handle,
                        "layer": ent_layer,
                        "space": cad_space,
                        "type": "MTEXT",
                        "text": plain_mt,
                    }
                    if raw_mt_kept is not None:
                        sample_mt["raw_text"] = raw_mt_kept
                    text_samples.append(sample_mt)

            elif dxftype == "INSERT":
                raw_ins_blk = str(getattr(ent.dxf, "name", "") or "")
                b_name, b_raw_orig, _ = _decode_cad_text(
                    raw_ins_blk, header_codepage=header_codepage
                )
                if cad_space == "modelspace" and b_name and not b_name.startswith("*"):
                    layer_block_counts_map[(ent_layer, b_name)] = (
                        layer_block_counts_map.get((ent_layer, b_name), 0) + 1
                    )
                for attrib in getattr(ent, "attribs", ()):
                    att_tag_raw = str(getattr(attrib.dxf, "tag", "") or "")
                    att_tag, _, _ = _decode_cad_text(att_tag_raw, header_codepage=header_codepage)
                    att_val_raw = str(getattr(attrib.dxf, "text", "") or "")
                    att_val_dec, att_dec_raw, att_enc = _decode_cad_text(
                        att_val_raw, header_codepage=header_codepage
                    )
                    if att_dec_raw is not None:
                        encoding_recovered_count += 1
                    att_clean, att_strip_raw, att_strip_norm = _strip_with_raw(att_val_dec)
                    raw_att_kept = (
                        att_val_raw
                        if (att_dec_raw is not None or att_strip_raw is not None)
                        else None
                    )
                    att_norm = (
                        f"{att_enc}+{att_strip_norm}"
                        if att_enc and att_strip_norm != "verbatim"
                        else (att_enc or att_strip_norm)
                    )
                    if att_clean:
                        idx += 1
                        att_handle = str(getattr(attrib.dxf, "handle", handle) or handle)
                        payload.items.append(
                            ExtractedItem(
                                item_index=idx,
                                item_type="text",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=page_label,
                                location=f"handle:{att_handle}|layer:{ent_layer}|ATTRIB:{att_tag}",
                                text=f"{att_tag}={att_clean}" if att_tag else att_clean,
                                raw_text=raw_att_kept,
                                normalization_applied=att_norm,
                                layer=ent_layer,
                                raw_layer=ent_layer_raw,
                                block_name=b_name,
                                raw_block_name=b_raw_orig,
                                entity_handle=att_handle,
                                cad_space=cad_space,
                                extraction_method=extraction_method,
                            )
                        )
                        payload.counts.text_items += 1

            elif dxftype == "DIMENSION":
                payload.counts.dimensions += 1
                override_raw = str(getattr(ent.dxf, "text", "") or "")
                override_dec, override_raw_orig, _ = _decode_cad_text(
                    override_raw, header_codepage=header_codepage
                )
                if override_raw_orig is not None:
                    encoding_recovered_count += 1
                measured: float | None = None
                try:
                    val = ent.get_measurement()
                    if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val)):
                        measured = round(float(val), 6)
                except Exception:
                    measured = None
                if measured is not None and measured > 0:
                    dim_measurements.append(measured)

                if override_dec and override_dec != "<>":
                    m_ov = _NUMBER_ONLY_RE.match(override_dec)
                    if m_ov:
                        try:
                            ov_num = float(m_ov.group(1).replace(",", "."))
                            if math.isfinite(ov_num) and ov_num > 0:
                                dim_override_numbers.append(ov_num)
                                if measured is not None and measured > 0:
                                    rel_diff = abs(ov_num - measured) / max(ov_num, measured)
                                    if rel_diff > 0.25:
                                        dim_override_mismatches += 1
                        except ValueError:
                            pass

                override_note = (
                    f"override='{override_dec}'" if override_dec and override_dec != "<>" else "override='<auto>'"
                )
                meas_str = f"{measured} {unit_label}" if measured is not None else "unavailable"
                idx += 1
                dim_props: dict[str, Any] = {
                    "dimtype": int(getattr(ent.dxf, "dimtype", 0)),
                    "measured_value": measured,
                    "override_text": override_dec,
                    "unit": unit_label,
                }
                if override_raw_orig is not None:
                    dim_props["raw_override_text"] = override_raw_orig
                payload.items.append(
                    ExtractedItem(
                        item_index=idx,
                        item_type="cad_dimension",
                        source_file=source_file,
                        file_id=file_id,
                        version_number=version_number,
                        page_or_sheet=page_label,
                        location=f"handle:{handle}|layer:{ent_layer}|DIMENSION",
                        text=f"Dimension measured={meas_str} | {override_note}",
                        raw_text=override_raw_orig,
                        unit_or_format=unit_label,
                        perimeter_or_length=measured,
                        layer=ent_layer,
                        raw_layer=ent_layer_raw,
                        entity_handle=handle,
                        cad_space=cad_space,
                        properties=dim_props,
                        extraction_method=extraction_method,
                    )
                )
                dimension_inventory.append({"handle": handle, "layer": ent_layer, "space": cad_space, **dim_props})

            elif dxftype == "LWPOLYLINE":
                payload.counts.polylines += 1
                try:
                    pts_xyb = [(float(p[0]), float(p[1]), float(p[2])) for p in ent.get_points("xyb")]
                except Exception:
                    pts_xyb = []
                has_arc = bool(getattr(ent, "has_arc", False)) or any(
                    abs(b) > 1e-12 for _, _, b in pts_xyb
                )
                is_closed = bool(getattr(ent, "closed", False)) or (
                    len(pts_xyb) >= 3
                    and math.hypot(pts_xyb[0][0] - pts_xyb[-1][0], pts_xyb[0][1] - pts_xyb[-1][1]) <= 1e-5
                )
                area_raw, perim_raw = _polyline_bulge_area_and_perimeter(pts_xyb, closed=is_closed)
                perim = round(perim_raw, 6)
                can_form_area = is_closed and (len(pts_xyb) >= 3 or (len(pts_xyb) == 2 and has_arc))
                if can_form_area and area_raw > 0:
                    native_area = round(area_raw, 6)
                    payload.counts.closed_areas += 1
                    pending_areas.append(
                        {
                            "handle": handle,
                            "layer": ent_layer,
                            "raw_layer": ent_layer_raw,
                            "space": cad_space,
                            "page_label": page_label,
                            "type": "LWPOLYLINE",
                            "area_native": native_area,
                            "perimeter_native": perim,
                            "quantities": {
                                "area_native": native_area,
                                "area_native_unit": area_unit,
                                "perimeter_native": perim,
                                "perimeter_unit": unit_label,
                                "vertex_count": len(pts_xyb),
                                "has_arc_bulge": has_arc,
                            },
                        }
                    )
                else:
                    if cad_space == "modelspace" and perim > 0:
                        pending_lengths.append(
                            {
                                "layer": ent_layer,
                                "entity_type": "LWPOLYLINE_OPEN",
                                "length_native": perim,
                            }
                        )
                    idx += 1
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="cad_entity",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=page_label,
                            location=f"handle:{handle}|layer:{ent_layer}|LWPOLYLINE(open)",
                            text=f"Open LWPOLYLINE | Length={perim} {unit_label}",
                            unit_or_format=unit_label,
                            perimeter_or_length=perim,
                            layer=ent_layer,
                            raw_layer=ent_layer_raw,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )

            elif dxftype == "LINE":
                try:
                    start = ent.dxf.start
                    end = ent.dxf.end
                    line_len = math.sqrt(
                        (float(end.x) - float(start.x)) ** 2
                        + (float(end.y) - float(start.y)) ** 2
                        + (float(end.z) - float(start.z)) ** 2
                    )
                    if cad_space == "modelspace" and math.isfinite(line_len) and line_len > 0:
                        pending_lengths.append(
                            {
                                "layer": ent_layer,
                                "entity_type": "LINE",
                                "length_native": round(line_len, 6),
                            }
                        )
                except Exception:
                    pass

            elif dxftype == "ARC":
                try:
                    arc_r = abs(float(getattr(ent.dxf, "radius", 0.0) or 0.0))
                    a1 = float(getattr(ent.dxf, "start_angle", 0.0) or 0.0)
                    a2 = float(getattr(ent.dxf, "end_angle", 0.0) or 0.0)
                    sweep_deg = (a2 - a1) % 360.0
                    if sweep_deg <= 0 and abs(a2 - a1) > 1e-9:
                        sweep_deg = 360.0
                    arc_len = arc_r * math.radians(sweep_deg)
                    if cad_space == "modelspace" and math.isfinite(arc_len) and arc_len > 0:
                        pending_lengths.append(
                            {
                                "layer": ent_layer,
                                "entity_type": "ARC",
                                "length_native": round(arc_len, 6),
                            }
                        )
                except Exception:
                    pass

            elif dxftype == "POLYLINE":
                payload.counts.polylines += 1
                if getattr(ent, "is_2d_polyline", False):
                    pts_xyb = [
                        (
                            float(v.dxf.location.x),
                            float(v.dxf.location.y),
                            float(getattr(v.dxf, "bulge", 0.0) or 0.0),
                        )
                        for v in ent.vertices
                    ]
                    has_arc = any(abs(b) > 1e-12 for _, _, b in pts_xyb)
                    is_closed = bool(ent.is_closed) or (
                        len(pts_xyb) >= 3
                        and math.hypot(pts_xyb[0][0] - pts_xyb[-1][0], pts_xyb[0][1] - pts_xyb[-1][1]) <= 1e-5
                    )
                    area_raw, perim_raw = _polyline_bulge_area_and_perimeter(pts_xyb, closed=is_closed)
                    perim = round(perim_raw, 6)
                    if is_closed and (len(pts_xyb) >= 3 or (len(pts_xyb) == 2 and has_arc)) and area_raw > 0:
                        native_area = round(area_raw, 6)
                        payload.counts.closed_areas += 1
                        pending_areas.append(
                            {
                                "handle": handle,
                                "layer": ent_layer,
                                "raw_layer": ent_layer_raw,
                                "space": cad_space,
                                "page_label": page_label,
                                "type": "POLYLINE",
                                "area_native": native_area,
                                "perimeter_native": perim,
                                "quantities": {
                                    "area_native": native_area,
                                    "area_native_unit": area_unit,
                                    "perimeter_native": perim,
                                    "perimeter_unit": unit_label,
                                    "vertex_count": len(pts_xyb),
                                    "has_arc_bulge": has_arc,
                                },
                            }
                        )
                    elif cad_space == "modelspace" and perim > 0:
                        pending_lengths.append(
                            {
                                "layer": ent_layer,
                                "entity_type": "POLYLINE_OPEN",
                                "length_native": perim,
                            }
                        )
                elif getattr(ent, "is_3d_polyline", False):
                    three_d_count += 1

            elif dxftype == "CIRCLE":
                r = float(getattr(ent.dxf, "radius", 0.0) or 0.0)
                if r > 0:
                    native_area = round(math.pi * (r ** 2), 6)
                    circumf = round(2.0 * math.pi * r, 6)
                    payload.counts.closed_areas += 1
                    pending_areas.append(
                        {
                            "handle": handle,
                            "layer": ent_layer,
                            "raw_layer": ent_layer_raw,
                            "space": cad_space,
                            "page_label": page_label,
                            "type": "CIRCLE",
                            "area_native": native_area,
                            "perimeter_native": circumf,
                            "quantities": {
                                "area_native": native_area,
                                "area_native_unit": area_unit,
                                "perimeter_native": circumf,
                                "perimeter_unit": unit_label,
                                "radius": round(r, 6),
                            },
                        }
                    )

            elif dxftype == "HATCH":
                try:
                    sub_paths = list(from_hatch(ent))
                    if sub_paths:
                        hatch_style = int(getattr(ent.dxf, "hatch_style", 0) or 0)
                        tree = nesting.make_polygon_structure(sub_paths)
                        net_raw, gross_raw, hole_count = _compute_hatch_areas(
                            ent, tree, hatch_style=hatch_style
                        )
                        native_area = round(max(0.0, net_raw), 6)
                        gross_area = round(max(0.0, gross_raw), 6)
                        hole_area = round(max(0.0, gross_area - native_area), 6)
                        if native_area > 0:
                            payload.counts.closed_areas += 1
                            area_basis = (
                                "net_outer_minus_islands"
                                if hole_count > 0
                                else "gross_outer_only_style_ignore"
                                if hatch_style == 2 and len(sub_paths) > 1
                                else "single_outer_loop"
                            )
                            pat_raw = str(getattr(ent.dxf, "pattern_name", "") or "")
                            pat_dec, _, _ = _decode_cad_text(pat_raw, header_codepage=header_codepage)
                            pending_areas.append(
                                {
                                    "handle": handle,
                                    "layer": ent_layer,
                                    "raw_layer": ent_layer_raw,
                                    "space": cad_space,
                                    "page_label": page_label,
                                    "type": "HATCH",
                                    "area_native": native_area,
                                    "perimeter_native": None,
                                    "quantities": {
                                        "area_native": native_area,
                                        "area_native_unit": area_unit,
                                        "gross_area_native": gross_area,
                                        "net_subtracted_area_native": hole_area,
                                        "island_count": hole_count,
                                        "area_basis": area_basis,
                                        "hatch_style": hatch_style,
                                        "pattern_name": pat_dec,
                                        "loop_count": len(sub_paths),
                                    },
                                }
                            )
                except Exception:
                    payload.warnings.append(
                        f"HATCH entity handle={handle} on layer '{ent_layer}' has complex/island boundaries that could not be polygonized deterministically."
                    )

    # 4. Assess drawing unit plausibility BEFORE emitting metric m2 conversions
    closed_pairs = [
        (float(p["area_native"]), float(p.get("perimeter_native") or 0.0))
        for p in pending_areas
    ]
    unit_assessment = _assess_cad_unit_plausibility(
        insunits_raw=insunits_raw,
        declared_unit_label=unit_label,
        declared_scale_to_m=scale_to_m,
        dim_measurements=dim_measurements,
        dim_override_numbers=dim_override_numbers,
        dim_override_mismatches=dim_override_mismatches,
        closed_areas_native=closed_pairs,
        confirmed_unit=confirmed_unit,
    )
    units_display = str(unit_assessment["units_display"])
    units_doubtful = bool(unit_assessment["units_doubtful"])
    units_status = str(unit_assessment["units_status"])
    owner_confirmed_unit = unit_assessment["owner_confirmed_unit"]
    effective_scale_to_m = unit_assessment["effective_scale_to_m"]
    payload.warnings.extend(unit_assessment["warnings"])

    if encoding_recovered_count > 0:
        payload.warnings.append(
            f"Recovered {encoding_recovered_count} legacy CP1256 Arabic string(s) into UTF-8 while keeping raw original values alongside."
        )

    for pending in pending_areas:
        idx = _append_closed_area_record(
            payload=payload,
            area_inventory=area_inventory,
            pending=pending,
            idx=idx,
            source_file=source_file,
            file_id=file_id,
            version_number=version_number,
            extraction_method=extraction_method,
            area_unit=area_unit,
            unit_label=unit_label,
            effective_scale_to_m=effective_scale_to_m,
            owner_confirmed_unit=owner_confirmed_unit,
        )

    if owner_confirmed_unit is not None:
        disp_area_u, disp_lin_u = _DISPLAY_UNIT_LABELS.get(
            owner_confirmed_unit, (f"sq {owner_confirmed_unit}", owner_confirmed_unit)
        )
        for dim_entry in dimension_inventory:
            dim_entry["raw_declared_unit"] = unit_label
            dim_entry["display_unit"] = disp_lin_u
            dim_entry["confirmed_unit"] = owner_confirmed_unit
        for item in payload.items:
            if item.item_type == "cad_dimension" and isinstance(item.properties, dict):
                item.properties["raw_declared_unit"] = unit_label
                item.properties["display_unit"] = disp_lin_u
                item.properties["confirmed_unit"] = owner_confirmed_unit

    # Render ModelSpace PNG preview cleanly
    preview_filename = "page_001.png"
    preview_path = output_pages_dir / preview_filename
    try:
        if _render_modelspace_preview(doc, msp, preview_path):
            rel_img_path = f"{pages_relative_prefix.rstrip('/')}/{preview_filename}"
            payload.rendered_page_images.append(rel_img_path)
            payload.counts.rendered_page_images = 1
    except Exception as exc:
        payload.warnings.append(f"DXF ModelSpace preview PNG rendering skipped ({exc.__class__.__name__}: {exc}).")

    if paperspace_entity_count > 0:
        payload.warnings.append(
            f"PaperSpace layouts contain {paperspace_entity_count} entities (including {paperspace_viewport_count} VIEWPORT object(s)); PNG preview renders ModelSpace only."
        )
    if three_d_count > 0:
        payload.warnings.append(
            f"Detected {three_d_count} 3D entity(ies) (3DSOLID/MESH/3DPOLYLINE); 3D volumes/meshes are NOT calculated deterministically in Step 07."
        )
    if proxy_count > 0:
        payload.warnings.append(
            f"Detected {proxy_count} ACAD_PROXY_ENTITY object(s) (custom Autodesk vertical/Civil/MEP objects not natively decomposed)."
        )

    layer_area_groups = compute_layer_area_groups(
        area_inventory,
        layer_inventory,
        units_doubtful=units_doubtful,
    )
    layer_length_groups = compute_layer_length_groups(
        pending_lengths,
        scale_to_m=effective_scale_to_m,
        units_doubtful=units_doubtful,
    )
    block_insert_groups = [
        {"layer": lname, "block_name": bname, "count": cnt}
        for (lname, bname), cnt in sorted(layer_block_counts_map.items())
    ]
    payload.counts.layers = len(layer_inventory)
    payload.counts.blocks = len(block_inventory)
    payload.counts.block_inserts = sum(block_insert_counts.values())
    payload.counts.entities = modelspace_entity_count + paperspace_entity_count
    payload.counts.total_items = len(payload.items)

    inventory: dict[str, Any] = {
        "kind": "cad_dxf",
        "dxf_version": str(doc.dxfversion),
        "dxf_codepage": header_codepage or None,
        "declared_unit": unit_label,
        "units": unit_label,
        "insunits_code": insunits_raw,
        "area_unit": area_unit,
        "units_doubtful": units_doubtful,
        "units_status": units_status,
        "owner_confirmed_unit": owner_confirmed_unit,
        "display_area_unit": (
            _DISPLAY_UNIT_LABELS.get(owner_confirmed_unit, (f"sq {owner_confirmed_unit}", owner_confirmed_unit))[0]
            if owner_confirmed_unit
            else None
        ),
        "display_linear_unit": (
            _DISPLAY_UNIT_LABELS.get(owner_confirmed_unit, (f"sq {owner_confirmed_unit}", owner_confirmed_unit))[1]
            if owner_confirmed_unit
            else None
        ),
        "unit_plausibility_reasons": unit_assessment["reasons"],
        "cp1256_strings_recovered": encoding_recovered_count,
        "modelspace_entities": modelspace_entity_count,
        "paperspace_entities": paperspace_entity_count,
        "entity_type_counts": dict(sorted(entity_type_counts.items())),
        "layers": layer_inventory,
        "blocks": block_inventory,
        "closed_areas": area_inventory,
        "layer_area_groups": layer_area_groups,
        "layer_length_groups": layer_length_groups,
        "block_insert_groups": block_insert_groups,
        "dimensions": dimension_inventory,
        "text_items": text_samples,
        "xrefs_detected": xref_names,
    }
    return payload, units_display, inventory
