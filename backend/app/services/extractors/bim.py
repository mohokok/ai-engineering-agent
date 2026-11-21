"""Deterministic BIM/IFC extractor using ifcopenshell (spaces, walls, doors, windows, properties, quantities)."""

from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element as ifc_element

from app.schemas.extraction import ExtractedItem
from app.services.extractors.office import ExtractedPayload


def _extract_ifc_units(ifc_file: Any) -> tuple[dict[str, str], list[str]]:
    """Read explicit unit assignments from IfcProject without inventing missing units."""
    units: dict[str, str] = {}
    warnings: list[str] = []
    projects = ifc_file.by_type("IfcProject")
    if not projects:
        warnings.append("No IfcProject entity found in IFC file; model units could not be verified.")
        return units, warnings

    unit_assignment = getattr(projects[0], "UnitsInContext", None)
    if unit_assignment is None:
        warnings.append("IfcProject.UnitsInContext is missing; IFC units are unspecified (not assumed).")
        return units, warnings

    for unit in getattr(unit_assignment, "Units", ()) or ():
        if unit.is_a("IfcSIUnit"):
            u_type = str(getattr(unit, "UnitType", "") or "")
            prefix = getattr(unit, "Prefix", None)
            name = getattr(unit, "Name", None)
            label = f"{prefix}_{name}".lower() if prefix else str(name or "").lower()
            if label == "milli_metre":
                units[u_type] = "mm"
            elif label == "centi_metre":
                units[u_type] = "cm"
            elif label == "metre":
                units[u_type] = "m"
            elif label == "square_metre":
                units[u_type] = "m2"
            elif label == "cubic_metre":
                units[u_type] = "m3"
            else:
                units[u_type] = label
        elif unit.is_a("IfcConversionBasedUnit"):
            u_type = str(getattr(unit, "UnitType", "") or "")
            u_name = str(getattr(unit, "Name", "") or "")
            units[u_type] = u_name
    return units, warnings


def _split_psets_and_quantities(raw_psets: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Separate Property Sets (Pset_*) and Quantity Sets (Qto_*) stripping internal STEP IDs."""
    properties: dict[str, dict[str, Any]] = {}
    quantities: dict[str, dict[str, Any]] = {}
    for set_name, entries in raw_psets.items():
        if not isinstance(entries, dict):
            continue
        cleaned = {k: v for k, v in entries.items() if k != "id"}
        if not cleaned:
            continue
        if set_name.startswith("Qto_") or "Quantit" in set_name:
            quantities[set_name] = cleaned
        else:
            properties[set_name] = cleaned
    return properties, quantities


def _find_explicit_area(quantities: dict[str, dict[str, Any]], properties: dict[str, dict[str, Any]]) -> tuple[float | None, str | None]:
    """Return explicitly authored IFC area value without fabricating geometry calculations."""
    preferred_keys = ("NetFloorArea", "GrossFloorArea", "Area", "NetArea", "GrossArea", "NetSideArea", "GrossSideArea")
    for bucket in (quantities, properties):
        for set_name, entries in bucket.items():
            for key in preferred_keys:
                val = entries.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    return float(val), f"{set_name}.{key}"
    return None, None


def _clean_container_name(element: Any) -> str | None:
    container = ifc_element.get_container(element)
    if container is not None:
        return getattr(container, "Name", None) or getattr(container, "LongName", None) or container.is_a()
    # IfcSpace often links to IfcBuildingStorey via IfcRelAggregates rather than ContainedInStructure
    parent = ifc_element.get_aggregate(element)
    if parent is not None:
        return getattr(parent, "Name", None) or getattr(parent, "LongName", None) or parent.is_a()
    return None


def extract_ifc(
    path: Path,
    *,
    source_file: str,
    file_id: str | None,
    version_number: int,
) -> tuple[ExtractedPayload, str | None, dict[str, Any]]:
    """Deterministically extract IFC schema, units, spaces, walls, doors, windows, properties, and quantities."""
    payload = ExtractedPayload()
    ifc_file = ifcopenshell.open(str(path))
    units_map, unit_warnings = _extract_ifc_units(ifc_file)
    payload.warnings.extend(unit_warnings)

    area_unit = units_map.get("AREAUNIT") or "unspecified_area_unit"
    length_unit = units_map.get("LENGTHUNIT") or "unspecified_length_unit"
    units_summary = f"length={length_unit}, area={area_unit}" if units_map else "unspecified"

    storeys = [
        {
            "name": getattr(st, "Name", None) or "",
            "long_name": getattr(st, "LongName", None),
            "elevation": getattr(st, "Elevation", None),
            "global_id": getattr(st, "GlobalId", None),
        }
        for st in ifc_file.by_type("IfcBuildingStorey")
    ]

    all_products = ifc_file.by_type("IfcProduct")
    product_counts: dict[str, int] = {}
    for prod in all_products:
        cls_name = prod.is_a()
        product_counts[cls_name] = product_counts.get(cls_name, 0) + 1

    spaces_list = list(ifc_file.by_type("IfcSpace"))
    walls_list = list(ifc_file.by_type("IfcWall"))
    doors_list = list(ifc_file.by_type("IfcDoor"))
    windows_list = list(ifc_file.by_type("IfcWindow"))

    payload.counts.ifc_spaces = len(spaces_list)
    payload.counts.ifc_walls = len(walls_list)
    payload.counts.ifc_doors = len(doors_list)
    payload.counts.ifc_windows = len(windows_list)
    payload.counts.entities = len(all_products)

    idx = 0
    spaces_without_area = 0
    space_inventory_rows: list[dict[str, Any]] = []
    element_inventory_rows: list[dict[str, Any]] = []

    for sp in spaces_list:
        raw_psets = ifc_element.get_psets(sp)
        props, qtos = _split_psets_and_quantities(raw_psets)
        area_val, area_source = _find_explicit_area(qtos, props)
        if area_val is None:
            spaces_without_area += 1
        storey_name = _clean_container_name(sp)
        name = getattr(sp, "Name", None) or ""
        long_name = getattr(sp, "LongName", None)
        gid = getattr(sp, "GlobalId", None) or str(sp.id())

        display_label = f"{name}" + (f" ({long_name})" if long_name and long_name != name else "")
        area_desc = f"{area_val} {area_unit} [{area_source}]" if area_val is not None else "not_provided_in_ifc"

        idx += 1
        payload.items.append(
            ExtractedItem(
                item_index=idx,
                item_type="bim_space",
                source_file=source_file,
                file_id=file_id,
                version_number=version_number,
                page_or_sheet=f"ifc:storey:{storey_name or 'unassigned'}",
                location=f"IfcSpace:{gid}",
                text=f"Space '{display_label or gid}' | Area={area_desc}",
                unit_or_format=area_unit if area_val is not None else None,
                area=area_val,
                properties=props or None,
                quantities=qtos or None,
                entity_handle=gid,
                extraction_method="native",
            )
        )
        space_inventory_rows.append(
            {
                "global_id": gid,
                "name": name,
                "long_name": long_name,
                "storey": storey_name,
                "area": area_val,
                "area_unit": area_unit if area_val is not None else None,
                "area_source": area_source or "not_provided_in_ifc",
            }
        )

    for el_group in (walls_list, doors_list, windows_list):
        for el in el_group:
            ifc_cls = el.is_a()
            raw_psets = ifc_element.get_psets(el)
            props, qtos = _split_psets_and_quantities(raw_psets)
            area_val, area_source = _find_explicit_area(qtos, props)
            storey_name = _clean_container_name(el)
            gid = getattr(el, "GlobalId", None) or str(el.id())
            el_name = getattr(el, "Name", None) or ""
            tag = getattr(el, "Tag", None)

            dims: dict[str, Any] = {}
            for attr in ("OverallWidth", "OverallHeight", "PredefinedType", "ObjectType"):
                val = getattr(el, attr, None)
                if val is not None:
                    dims[attr] = val
            if tag:
                dims["Tag"] = tag
            merged_props = dict(props)
            if dims:
                merged_props["IfcAttributes"] = dims

            idx += 1
            summary_parts = [f"{ifc_cls} '{el_name or gid}'"]
            if tag:
                summary_parts.append(f"Tag={tag}")
            if "OverallWidth" in dims or "OverallHeight" in dims:
                summary_parts.append(
                    f"W={dims.get('OverallWidth', '?')} x H={dims.get('OverallHeight', '?')} {length_unit}"
                )
            if area_val is not None:
                summary_parts.append(f"Area={area_val} {area_unit}")

            payload.items.append(
                ExtractedItem(
                    item_index=idx,
                    item_type="bim_element",
                    source_file=source_file,
                    file_id=file_id,
                    version_number=version_number,
                    page_or_sheet=f"ifc:{ifc_cls}",
                    location=f"{ifc_cls}:{gid}",
                    text=" | ".join(summary_parts),
                    unit_or_format=length_unit if units_map else None,
                    area=area_val,
                    properties=merged_props or None,
                    quantities=qtos or None,
                    entity_handle=gid,
                    extraction_method="native",
                )
            )
            element_inventory_rows.append(
                {
                    "ifc_type": ifc_cls,
                    "global_id": gid,
                    "name": el_name,
                    "tag": tag,
                    "storey": storey_name,
                    "area": area_val,
                    "area_source": area_source,
                    "quantities": qtos or None,
                    "attributes": dims,
                }
            )

    if spaces_without_area > 0:
        payload.warnings.append(
            f"{spaces_without_area} IfcSpace entity(ies) had no explicit Qto/property area in the IFC file; left null without geometric estimation."
        )
    other_products = {
        k: v
        for k, v in product_counts.items()
        if k not in {"IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace", "IfcWall", "IfcWallStandardCase", "IfcDoor", "IfcWindow"}
    }
    if other_products:
        payload.warnings.append(
            "Additional IFC product classes counted in summary only (full property/geometry extraction limited to spaces/walls/doors/windows): "
            + ", ".join(f"{k}={v}" for k, v in sorted(other_products.items()))
        )
    payload.warnings.append(
        "Known IFC limit: implicit 3D B-rep/extruded solid tessellation and spatial clash geometry are NOT computed from meshes; only authored Pset/Qto quantities and attributes are reported."
    )

    payload.counts.total_items = len(payload.items)
    inventory = {
        "kind": "bim_ifc",
        "schema": str(ifc_file.schema),
        "units": units_map,
        "storeys": storeys,
        "product_counts": dict(sorted(product_counts.items())),
        "spaces": space_inventory_rows,
        "elements": element_inventory_rows,
        "known_limits": [
            "Only authored Property Sets (Pset_*) and Quantity Sets (Qto_*) are extracted; unauthored areas stay null.",
            "3D B-rep / implicit mesh geometry calculation and visual 3D IFC rendering are not performed in Step 07.",
        ],
    }
    return payload, units_summary, inventory
