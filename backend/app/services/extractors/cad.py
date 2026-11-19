"""Deterministic CAD DXF reader (layers, blocks, text, dimensions, polylines, areas, units, PNG preview)."""

import math
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.pymupdf import PyMuPdfBackend
import ezdxf.math
from ezdxf.path import from_hatch, nesting

from app.schemas.extraction import ExtractedItem, ExtractionMethod
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

_THREE_D_ENTITY_TYPES = frozenset({"3DSOLID", "MESH", "SURFACE", "BODY", "3DFACE"})


def _polygon_perimeter(points: list[tuple[float, float]], *, closed: bool) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    for i in range(len(points) - 1):
        total += math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
    if closed and math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) > 1e-9:
        total += math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1])
    return total


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


def extract_dxf(
    path: Path,
    *,
    output_pages_dir: Path,
    pages_relative_prefix: str,
    source_file: str,
    file_id: str | None,
    version_number: int,
    extraction_method: ExtractionMethod = "native",
) -> tuple[ExtractedPayload, str | None, dict[str, Any]]:
    """Deterministically inventory DXF header units, layers, blocks, text, dimensions, and polyline areas."""
    payload = ExtractedPayload()
    output_pages_dir.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.readfile(str(path))
    insunits_raw = int(doc.header.get("$INSUNITS", 0) or 0)
    unit_label, scale_to_m, area_unit = _DXF_INSUNITS_MAP.get(
        insunits_raw, (f"insunits_{insunits_raw}", None, f"insunits_{insunits_raw}_sq")
    )
    units_display = f"{unit_label} ($INSUNITS={insunits_raw})"

    if insunits_raw == 0:
        payload.warnings.append(
            "$INSUNITS=0 (unitless): CAD areas and lengths are reported strictly in raw drawing units without assuming meters or millimeters."
        )

    msp = doc.modelspace()
    layout_records: list[tuple[str, str, Any]] = [("modelspace", "Model", msp)]
    for lay in doc.layouts:
        if lay.name.lower() != "model":
            layout_records.append(("paperspace", lay.name, lay))

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
            ent_layer = str(getattr(ent.dxf, "layer", "0") or "0")
            entity_type_counts[dxftype] = entity_type_counts.get(dxftype, 0) + 1
            counts_bucket = layer_entity_counts.setdefault(
                ent_layer, {"modelspace": 0, "paperspace": 0, "total": 0}
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
                blk_name = str(getattr(ent.dxf, "name", "") or "")
                block_insert_counts[blk_name] = block_insert_counts.get(blk_name, 0) + 1
            elif dxftype in _THREE_D_ENTITY_TYPES:
                three_d_count += 1
            elif dxftype == "ACAD_PROXY_ENTITY":
                proxy_count += 1

    # 1. Layers inventory
    idx = 0
    layer_inventory: list[dict[str, Any]] = []
    for layer in doc.layers:
        l_name = str(layer.dxf.name)
        l_counts = layer_entity_counts.get(l_name, {"modelspace": 0, "paperspace": 0, "total": 0})
        is_on = bool(layer.is_on())
        is_frozen = bool(layer.is_frozen())
        is_locked = bool(layer.is_locked())
        l_props = {
            "color": int(getattr(layer.dxf, "color", 7)),
            "linetype": str(getattr(layer.dxf, "linetype", "Continuous") or "Continuous"),
            "is_on": is_on,
            "is_frozen": is_frozen,
            "is_locked": is_locked,
            "modelspace_entities": l_counts["modelspace"],
            "paperspace_entities": l_counts["paperspace"],
            "total_entities": l_counts["total"],
        }
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
                layer=l_name,
                properties=l_props,
                extraction_method=extraction_method,
            )
        )
        layer_inventory.append({"name": l_name, **l_props})

    # 2. Blocks & XREF detection (skip internal anonymous *Model_Space / *Paper_Space blocks)
    block_inventory: list[dict[str, Any]] = []
    xref_names: list[str] = []
    for blk in doc.blocks:
        b_name = str(blk.name)
        if b_name.startswith("*"):
            continue
        block_entity = getattr(blk, "block", None)
        is_xref = bool(getattr(block_entity, "is_xref", False) or getattr(blk, "is_xref", False))
        xref_path = (
            str(getattr(getattr(block_entity, "dxf", None), "xref_path", "") or "")
            if is_xref
            else ""
        )
        if is_xref:
            xref_names.append(b_name)
        def_entities = sum(1 for _ in blk)
        ins_count = block_insert_counts.get(b_name, 0)
        b_props = {
            "definition_entities": def_entities,
            "insert_count": ins_count,
            "is_xref": is_xref,
            "xref_path": xref_path or None,
        }
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
                block_name=b_name,
                properties=b_props,
                extraction_method=extraction_method,
            )
        )
        block_inventory.append({"name": b_name, **b_props})

    if xref_names:
        payload.warnings.append(
            f"External XREF block(s) detected ({', '.join(xref_names)}); external referenced DWGs are NOT loaded or resolved."
        )

    # 3. Entities across ModelSpace and PaperSpace (TEXT, MTEXT, ATTRIB, DIMENSION, LWPOLYLINE, POLYLINE, CIRCLE, HATCH)
    area_inventory: list[dict[str, Any]] = []
    text_samples: list[dict[str, Any]] = []
    dimension_inventory: list[dict[str, Any]] = []

    for cad_space, lay_name, lay_obj in layout_records:
        page_label = f"dxf:{cad_space}:{lay_name}"
        for ent in lay_obj:
            dxftype = ent.dxftype()
            handle = str(getattr(ent.dxf, "handle", "") or "no_handle")
            ent_layer = str(getattr(ent.dxf, "layer", "0") or "0")

            if dxftype == "TEXT":
                raw_t = str(getattr(ent.dxf, "text", "") or "")
                cleaned_t, raw_orig, norm = _strip_with_raw(raw_t)
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
                            raw_text=raw_orig,
                            normalization_applied=norm,
                            layer=ent_layer,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )
                    payload.counts.text_items += 1
                    text_samples.append({"handle": handle, "layer": ent_layer, "space": cad_space, "type": "TEXT", "text": cleaned_t})

            elif dxftype == "MTEXT":
                raw_mt = str(getattr(ent, "text", "") or "")
                plain_mt = str(ent.plain_text() or "").strip()
                if plain_mt:
                    idx += 1
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
                            raw_text=raw_mt if raw_mt != plain_mt else None,
                            normalization_applied=(
                                "mtext_formatting_stripped" if raw_mt != plain_mt else "verbatim"
                            ),
                            layer=ent_layer,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )
                    payload.counts.text_items += 1
                    text_samples.append({"handle": handle, "layer": ent_layer, "space": cad_space, "type": "MTEXT", "text": plain_mt})

            elif dxftype == "INSERT":
                b_name = str(getattr(ent.dxf, "name", "") or "")
                for attrib in getattr(ent, "attribs", ()):
                    att_tag = str(getattr(attrib.dxf, "tag", "") or "")
                    att_val = str(getattr(attrib.dxf, "text", "") or "")
                    att_clean, att_raw, att_norm = _strip_with_raw(att_val)
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
                                raw_text=att_raw,
                                normalization_applied=att_norm,
                                layer=ent_layer,
                                block_name=b_name,
                                entity_handle=att_handle,
                                cad_space=cad_space,
                                extraction_method=extraction_method,
                            )
                        )
                        payload.counts.text_items += 1

            elif dxftype == "DIMENSION":
                payload.counts.dimensions += 1
                override_raw = str(getattr(ent.dxf, "text", "") or "")
                measured: float | None = None
                try:
                    val = ent.get_measurement()
                    if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val)):
                        measured = round(float(val), 6)
                except Exception:
                    measured = None

                override_note = (
                    f"override='{override_raw}'" if override_raw and override_raw != "<>" else "override='<auto>'"
                )
                meas_str = f"{measured} {unit_label}" if measured is not None else "unavailable"
                idx += 1
                dim_props = {
                    "dimtype": int(getattr(ent.dxf, "dimtype", 0)),
                    "measured_value": measured,
                    "override_text": override_raw,
                    "unit": unit_label,
                }
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
                        unit_or_format=unit_label,
                        perimeter_or_length=measured,
                        layer=ent_layer,
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
                    if getattr(ent, "has_arc", False):
                        pts = [(float(p.x), float(p.y)) for p in ent.flattening(distance=0.0005)]
                    else:
                        pts = [(float(p[0]), float(p[1])) for p in ent.get_points("xy")]
                except Exception:
                    pts = []
                is_closed = bool(getattr(ent, "closed", False)) or (
                    len(pts) >= 3 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 1e-5
                )
                perim = round(_polygon_perimeter(pts, closed=is_closed), 6) if len(pts) >= 2 else 0.0
                if is_closed and len(pts) >= 3:
                    native_area = round(float(ezdxf.math.area(pts)), 6)
                    area_m2 = round(native_area * (scale_to_m ** 2), 6) if scale_to_m is not None else None
                    payload.counts.closed_areas += 1
                    q_dict: dict[str, Any] = {
                        "area_native": native_area,
                        "area_native_unit": area_unit,
                        "perimeter_native": perim,
                        "perimeter_unit": unit_label,
                        "vertex_count": len(pts),
                    }
                    if area_m2 is not None:
                        q_dict["area_m2"] = area_m2
                    idx += 1
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="cad_polyline_area",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=page_label,
                            location=f"handle:{handle}|layer:{ent_layer}|LWPOLYLINE",
                            text=f"Closed LWPOLYLINE | Area={native_area} {area_unit}"
                            + (f" ({area_m2} m2)" if area_m2 is not None and area_unit != "m2" else "")
                            + f" | Perimeter={perim} {unit_label}",
                            unit_or_format=area_unit,
                            area=native_area,
                            perimeter_or_length=perim,
                            quantities=q_dict,
                            layer=ent_layer,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )
                    area_inventory.append({"handle": handle, "layer": ent_layer, "space": cad_space, "type": "LWPOLYLINE", **q_dict})
                else:
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
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )

            elif dxftype == "POLYLINE":
                payload.counts.polylines += 1
                if getattr(ent, "is_2d_polyline", False):
                    pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in ent.vertices]
                    is_closed = bool(ent.is_closed) or (
                        len(pts) >= 3 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) <= 1e-5
                    )
                    perim = round(_polygon_perimeter(pts, closed=is_closed), 6) if len(pts) >= 2 else 0.0
                    if is_closed and len(pts) >= 3:
                        native_area = round(float(ezdxf.math.area(pts)), 6)
                        area_m2 = round(native_area * (scale_to_m ** 2), 6) if scale_to_m is not None else None
                        payload.counts.closed_areas += 1
                        q_dict = {
                            "area_native": native_area,
                            "area_native_unit": area_unit,
                            "perimeter_native": perim,
                            "perimeter_unit": unit_label,
                            "vertex_count": len(pts),
                        }
                        if area_m2 is not None:
                            q_dict["area_m2"] = area_m2
                        idx += 1
                        payload.items.append(
                            ExtractedItem(
                                item_index=idx,
                                item_type="cad_polyline_area",
                                source_file=source_file,
                                file_id=file_id,
                                version_number=version_number,
                                page_or_sheet=page_label,
                                location=f"handle:{handle}|layer:{ent_layer}|POLYLINE",
                                text=f"Closed POLYLINE | Area={native_area} {area_unit} | Perimeter={perim} {unit_label}",
                                unit_or_format=area_unit,
                                area=native_area,
                                perimeter_or_length=perim,
                                quantities=q_dict,
                                layer=ent_layer,
                                entity_handle=handle,
                                cad_space=cad_space,
                                extraction_method=extraction_method,
                            )
                        )
                        area_inventory.append({"handle": handle, "layer": ent_layer, "space": cad_space, "type": "POLYLINE", **q_dict})
                elif getattr(ent, "is_3d_polyline", False):
                    three_d_count += 1

            elif dxftype == "CIRCLE":
                r = float(getattr(ent.dxf, "radius", 0.0) or 0.0)
                if r > 0:
                    native_area = round(math.pi * (r ** 2), 6)
                    circumf = round(2.0 * math.pi * r, 6)
                    area_m2 = round(native_area * (scale_to_m ** 2), 6) if scale_to_m is not None else None
                    payload.counts.closed_areas += 1
                    q_dict = {
                        "area_native": native_area,
                        "area_native_unit": area_unit,
                        "perimeter_native": circumf,
                        "perimeter_unit": unit_label,
                        "radius": round(r, 6),
                    }
                    if area_m2 is not None:
                        q_dict["area_m2"] = area_m2
                    idx += 1
                    payload.items.append(
                        ExtractedItem(
                            item_index=idx,
                            item_type="cad_polyline_area",
                            source_file=source_file,
                            file_id=file_id,
                            version_number=version_number,
                            page_or_sheet=page_label,
                            location=f"handle:{handle}|layer:{ent_layer}|CIRCLE",
                            text=f"CIRCLE r={round(r, 6)} {unit_label} | Area={native_area} {area_unit}",
                            unit_or_format=area_unit,
                            area=native_area,
                            perimeter_or_length=circumf,
                            quantities=q_dict,
                            layer=ent_layer,
                            entity_handle=handle,
                            cad_space=cad_space,
                            extraction_method=extraction_method,
                        )
                    )
                    area_inventory.append({"handle": handle, "layer": ent_layer, "space": cad_space, "type": "CIRCLE", **q_dict})

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
                            area_m2 = (
                                round(native_area * (scale_to_m ** 2), 6)
                                if scale_to_m is not None
                                else None
                            )
                            payload.counts.closed_areas += 1
                            area_basis = (
                                "net_outer_minus_islands"
                                if hole_count > 0
                                else "gross_outer_only_style_ignore"
                                if hatch_style == 2 and len(sub_paths) > 1
                                else "single_outer_loop"
                            )
                            q_dict = {
                                "area_native": native_area,
                                "area_native_unit": area_unit,
                                "gross_area_native": gross_area,
                                "island_hole_area_native": hole_area,
                                "island_count": hole_count,
                                "area_basis": area_basis,
                                "hatch_style": hatch_style,
                                "pattern_name": str(getattr(ent.dxf, "pattern_name", "") or ""),
                                "loop_count": len(sub_paths),
                            }
                            if area_m2 is not None:
                                q_dict["area_m2"] = area_m2
                            if hole_count > 0:
                                payload.warnings.append(
                                    f"HATCH entity handle={handle} on layer '{ent_layer}' contains {hole_count} island hole(s); net area={native_area} {area_unit} (gross={gross_area}, subtracted holes={hole_area})."
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
                                    location=f"handle:{handle}|layer:{ent_layer}|HATCH",
                                    text=f"HATCH Net Area={native_area} {area_unit} (gross={gross_area}, islands={hole_count})",
                                    unit_or_format=area_unit,
                                    area=native_area,
                                    quantities=q_dict,
                                    layer=ent_layer,
                                    entity_handle=handle,
                                    cad_space=cad_space,
                                    extraction_method=extraction_method,
                                )
                            )
                            area_inventory.append(
                                {
                                    "handle": handle,
                                    "layer": ent_layer,
                                    "space": cad_space,
                                    "type": "HATCH",
                                    **q_dict,
                                }
                            )
                except Exception:
                    payload.warnings.append(
                        f"HATCH entity handle={handle} on layer '{ent_layer}' has complex/island boundaries that could not be polygonized deterministically."
                    )

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

    payload.counts.layers = len(layer_inventory)
    payload.counts.blocks = len(block_inventory)
    payload.counts.block_inserts = sum(block_insert_counts.values())
    payload.counts.entities = modelspace_entity_count + paperspace_entity_count
    payload.counts.total_items = len(payload.items)

    inventory: dict[str, Any] = {
        "kind": "cad_dxf",
        "dxf_version": str(doc.dxfversion),
        "units": unit_label,
        "insunits_code": insunits_raw,
        "area_unit": area_unit,
        "modelspace_entities": modelspace_entity_count,
        "paperspace_entities": paperspace_entity_count,
        "entity_type_counts": dict(sorted(entity_type_counts.items())),
        "layers": layer_inventory,
        "blocks": block_inventory,
        "closed_areas": area_inventory,
        "dimensions": dimension_inventory,
        "text_items": text_samples,
        "xrefs_detected": xref_names,
    }
    return payload, units_display, inventory
