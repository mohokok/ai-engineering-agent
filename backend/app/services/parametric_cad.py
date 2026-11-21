"""Step 11 parametric drawing engine: room-model geometry -> AutoCAD mm DXF ($INSUNITS=4, TTF Arabic) + true-scale vector PDF + schedules + Step 07 round-trip verification."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import math
from pathlib import Path
import tempfile
from typing import Any

import ezdxf
from ezdxf.enums import TextEntityAlignment
import pymupdf

from app.schemas.drawings import (
    ComputedRoomMetric,
    DoorScheduleRow,
    DoorSpec,
    PaperSizeChoice,
    ParametricPlanModel,
    RoundTripCheckOut,
    RoomSpec,
    WallSpec,
    WindowScheduleRow,
    WindowSpec,
)
from app.services.extractors.cad import extract_dxf

_WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")
_PT_PER_MM = 72.0 / 25.4

PAPER_DIMENSIONS_MM: dict[PaperSizeChoice, tuple[float, float]] = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
}


@dataclass(frozen=True)
class WallRenderSegment:
    """One unbroken wall sub-segment after subtracting intersecting door and window openings."""

    wall_id: str
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]
    thickness_mm: float
    wall_type: str


def _polygon_area_and_perimeter(pts: list[tuple[float, float]]) -> tuple[float, float, tuple[float, float]]:
    """Compute exact 2D Shoelace area (mm2), perimeter (mm), and centroid (mm) deterministically in Python."""
    n = len(pts)
    twice_area = 0.0
    perim = 0.0
    cx_num = 0.0
    cy_num = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        cx_num += (x1 + x2) * cross
        cy_num += (y1 + y2) * cross
        perim += math.hypot(x2 - x1, y2 - y1)
    area = abs(0.5 * twice_area)
    if abs(twice_area) > 1e-6:
        signed_area = 0.5 * twice_area
        cx = cx_num / (6.0 * signed_area)
        cy = cy_num / (6.0 * signed_area)
    else:
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
    return area, perim, (round(cx, 3), round(cy, 3))


def compute_room_metrics(rooms: list[RoomSpec]) -> list[ComputedRoomMetric]:
    """Compute all room areas and perimeters strictly in code from coordinates (never user/AI numbers)."""
    results: list[ComputedRoomMetric] = []
    for rm in rooms:
        if rm.polygon_mm is not None:
            pts = [(float(p[0]), float(p[1])) for p in rm.polygon_mm]
        else:
            x0 = float(rm.x_mm or 0.0)
            y0 = float(rm.y_mm or 0.0)
            w = float(rm.width_mm or 0.0)
            h = float(rm.height_mm or 0.0)
            pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]

        area_mm2, perim_mm, centroid = _polygon_area_and_perimeter(pts)
        if area_mm2 <= 1.0:
            raise ValueError(f"Room '{rm.room_id}' has degenerate or zero area ({area_mm2} mm²).")

        results.append(
            ComputedRoomMetric(
                room_id=rm.room_id,
                name_ar=rm.name_ar,
                name_en=rm.name_en,
                polygon_mm=pts,
                area_mm2=round(area_mm2, 2),
                area_m2=round(area_mm2 / 1_000_000.0, 4),
                perimeter_mm=round(perim_mm, 2),
                perimeter_m=round(perim_mm / 1000.0, 4),
                centroid_mm=centroid,
                floor_finish=rm.floor_finish,
                wall_finish=rm.wall_finish,
                ceiling_finish=rm.ceiling_finish,
                skirting=rm.skirting,
            )
        )
    return results


def build_schedules_from_model(
    model: ParametricPlanModel,
) -> tuple[list[DoorScheduleRow], list[WindowScheduleRow]]:
    """Build aggregated door and window schedules deterministically from the exact same parametric model."""
    door_buckets: dict[tuple[str, float, float, str, str, str], dict[str, Any]] = {}
    for d in model.doors:
        key = (
            d.mark,
            round(float(d.width_mm), 2),
            round(float(d.height_mm), 2),
            d.material,
            d.fire_rating,
            d.hardware,
        )
        bucket = door_buckets.setdefault(
            key,
            {
                "mark": d.mark,
                "width_mm": round(float(d.width_mm), 2),
                "height_mm": round(float(d.height_mm), 2),
                "swings": [],
                "material": d.material,
                "fire_rating": d.fire_rating,
                "hardware": d.hardware,
                "count": 0,
                "door_ids": [],
                "room_refs": [],
            },
        )
        bucket["count"] += 1
        if d.swing not in bucket["swings"]:
            bucket["swings"].append(d.swing)
        bucket["door_ids"].append(d.door_id)
        if d.room_ref and d.room_ref not in bucket["room_refs"]:
            bucket["room_refs"].append(d.room_ref)

    win_buckets: dict[tuple[str, float, float, float, str], dict[str, Any]] = {}
    for w in model.windows:
        key_w = (
            w.mark,
            round(float(w.width_mm), 2),
            round(float(w.height_mm), 2),
            round(float(w.sill_mm), 2),
            w.glazing,
        )
        bucket_w = win_buckets.setdefault(
            key_w,
            {
                "mark": w.mark,
                "width_mm": round(float(w.width_mm), 2),
                "height_mm": round(float(w.height_mm), 2),
                "sill_mm": round(float(w.sill_mm), 2),
                "glazing": w.glazing,
                "count": 0,
                "window_ids": [],
                "room_refs": [],
            },
        )
        bucket_w["count"] += 1
        bucket_w["window_ids"].append(w.window_id)
        if w.room_ref and w.room_ref not in bucket_w["room_refs"]:
            bucket_w["room_refs"].append(w.room_ref)

    doors_out = [
        DoorScheduleRow(
            mark=b["mark"],
            width_mm=b["width_mm"],
            height_mm=b["height_mm"],
            swing=" / ".join(b["swings"]),
            material=b["material"],
            fire_rating=b["fire_rating"],
            hardware=b["hardware"],
            count=b["count"],
            door_ids=b["door_ids"],
            room_refs=b["room_refs"],
        )
        for _, b in sorted(door_buckets.items(), key=lambda kv: kv[0][0])
    ]
    wins_out = [WindowScheduleRow(**b) for _, b in sorted(win_buckets.items(), key=lambda kv: kv[0][0])]
    return doors_out, wins_out


def _split_walls_around_openings(
    walls: list[WallSpec],
    doors: list[DoorSpec],
    windows: list[WindowSpec],
) -> list[WallRenderSegment]:
    """Break solid wall spans around doors and windows placed onto each wall."""
    openings = [
        (float(d.position_mm[0]), float(d.position_mm[1]), float(d.width_mm), float(d.angle_deg))
        for d in doors
    ] + [
        (float(w.position_mm[0]), float(w.position_mm[1]), float(w.width_mm), float(w.angle_deg))
        for w in windows
    ]

    segments: list[WallRenderSegment] = []
    for wall in walls:
        x1, y1 = float(wall.start_mm[0]), float(wall.start_mm[1])
        x2, y2 = float(wall.end_mm[0]), float(wall.end_mm[1])
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length <= 1e-3:
            continue
        ux, uy = dx / length, dy / length
        wall_ang = math.degrees(math.atan2(dy, dx))

        gaps: list[tuple[float, float]] = []
        for ox, oy, ow, o_ang in openings:
            diff_deg = abs(((o_ang - wall_ang + 90.0) % 180.0) - 90.0)
            if diff_deg > 18.0:
                continue
            proj = (ox - x1) * ux + (oy - y1) * uy
            perp = abs(-(ox - x1) * uy + (oy - y1) * ux)
            if perp <= max(float(wall.thickness_mm) * 0.75, 160.0) and -ow * 0.2 <= proj <= length + ow * 0.2:
                g0 = max(0.0, proj - ow / 2.0)
                g1 = min(length, proj + ow / 2.0)
                if g1 - g0 > 1.0:
                    gaps.append((g0, g1))

        if not gaps:
            segments.append(
                WallRenderSegment(
                    wall_id=wall.wall_id,
                    start_mm=(x1, y1),
                    end_mm=(x2, y2),
                    thickness_mm=float(wall.thickness_mm),
                    wall_type=wall.wall_type,
                )
            )
            continue

        gaps.sort()
        merged: list[tuple[float, float]] = []
        for g0, g1 in gaps:
            if merged and g0 <= merged[-1][1] + 1.0:
                merged[-1] = (merged[-1][0], max(merged[-1][1], g1))
            else:
                merged.append((g0, g1))

        cursor = 0.0
        for g0, g1 in merged:
            if g0 - cursor > 2.0:
                segments.append(
                    WallRenderSegment(
                        wall_id=wall.wall_id,
                        start_mm=(x1 + ux * cursor, y1 + uy * cursor),
                        end_mm=(x1 + ux * g0, y1 + uy * g0),
                        thickness_mm=float(wall.thickness_mm),
                        wall_type=wall.wall_type,
                    )
                )
            cursor = max(cursor, g1)
        if length - cursor > 2.0:
            segments.append(
                WallRenderSegment(
                    wall_id=wall.wall_id,
                    start_mm=(x1 + ux * cursor, y1 + uy * cursor),
                    end_mm=(x2, y2),
                    thickness_mm=float(wall.thickness_mm),
                    wall_type=wall.wall_type,
                )
            )
    return segments


def _wall_face_quad(seg: WallRenderSegment) -> list[tuple[float, float]]:
    """Return the 4 corner coordinates of a thick 2D wall sub-segment."""
    x1, y1 = seg.start_mm
    x2, y2 = seg.end_mm
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    nx, ny = (-dy / length) * (seg.thickness_mm / 2.0), (dx / length) * (seg.thickness_mm / 2.0)
    return [
        (x1 + nx, y1 + ny),
        (x2 + nx, y2 + ny),
        (x2 - nx, y2 - ny),
        (x1 - nx, y1 - ny),
    ]


def _model_bounds_mm(
    rooms: list[ComputedRoomMetric],
    walls: list[WallSpec],
) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for rm in rooms:
        for px, py in rm.polygon_mm:
            xs.append(px)
            ys.append(py)
    for w in walls:
        pad = float(w.thickness_mm) / 2.0
        xs.extend([w.start_mm[0] - pad, w.start_mm[0] + pad, w.end_mm[0] - pad, w.end_mm[0] + pad])
        ys.extend([w.start_mm[1] - pad, w.start_mm[1] + pad, w.end_mm[1] - pad, w.end_mm[1] + pad])
    return min(xs), min(ys), max(xs), max(ys)


def generate_parametric_dxf(
    out_path: Path,
    *,
    model: ParametricPlanModel,
    rooms: list[ComputedRoomMetric],
    door_schedule: list[DoorScheduleRow],
    window_schedule: list[WindowScheduleRow],
    drawing_no: str,
    title: str,
    scale_denominator: int,
    paper_size: PaperSizeChoice,
    classification: str,
    revision: str,
    notes: str | None,
) -> None:
    """Compile the verified parametric model into an AutoCAD R2018 DXF in mm ($INSUNITS=4) with TrueType Arabic text."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing parametric DXF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 4  # Millimetres explicitly
    doc.header["$MEASUREMENT"] = 1  # Metric
    doc.header["$LUNITS"] = 2  # Decimal
    doc.header["$LUPREC"] = 0  # Whole millimetres cleanly readable

    # Mandatory TrueType font styles (Tahoma) for Arabic rendering in AutoCAD (never SHX)
    if "Standard" in doc.styles:
        std_style = doc.styles.get("Standard")
        std_style.dxf.font = "tahoma.ttf"
        std_style.dxf.bigfont = ""
    if "ARABIC_TTF" not in doc.styles:
        doc.styles.new("ARABIC_TTF", dxfattribs={"font": "tahoma.ttf", "bigfont": ""})

    dim_style = doc.dimstyles.get("EZDXF") if "EZDXF" in doc.dimstyles else doc.dimstyles.new("ARCH_MM")
    if "ARCH_MM" not in doc.dimstyles:
        dim_style = doc.dimstyles.new("ARCH_MM")
    else:
        dim_style = doc.dimstyles.get("ARCH_MM")
    dim_style.dxf.dimtxsty = "ARABIC_TTF"
    dim_style.dxf.dimtxt = 150.0
    dim_style.dxf.dimasz = 90.0
    dim_style.dxf.dimdec = 0
    dim_style.dxf.dimlfac = 1.0
    dim_style.dxf.dimtad = 1
    dim_style.dxf.dimgap = 60.0
    dim_style.dxf.dimexo = 90.0
    dim_style.dxf.dimexe = 120.0

    # Standard AIA/ISO-style architectural layers
    layer_defs = [
        ("A-WALL", 7),
        ("A-AREA", 3),
        ("A-DOOR", 30),
        ("A-WIND", 4),
        ("A-ANNO-TEXT", 7),
        ("A-ANNO-DIMS", 1),
        ("A-ANNO-SYMB", 2),
        ("A-ANNO-TTLB", 7),
    ]
    for lname, color in layer_defs:
        if lname not in doc.layers:
            doc.layers.add(lname, color=color)

    msp = doc.modelspace()
    min_x, min_y, max_x, max_y = _model_bounds_mm(rooms, model.walls)

    # 1. Room area boundaries (closed LWPOLYLINEs on A-AREA matching exact code-computed room areas!)
    for rm in rooms:
        msp.add_lwpolyline(
            rm.polygon_mm,
            close=True,
            dxfattribs={"layer": "A-AREA"},
        )
        cx, cy = rm.centroid_mm
        label_str = f"{rm.name_ar}\\P{rm.name_en}\\P{rm.area_m2:.2f} m2"
        mt = msp.add_mtext(
            label_str,
            dxfattribs={
                "layer": "A-ANNO-TEXT",
                "style": "ARABIC_TTF",
                "char_height": 170.0,
                "width": 2200.0,
                "attachment_point": 5,  # Middle Center
            },
        )
        mt.set_location((cx, cy))

    # 2. Split wall geometry with real wall thickness on A-WALL
    wall_segments = _split_walls_around_openings(model.walls, model.doors, model.windows)
    for seg in wall_segments:
        quad = _wall_face_quad(seg)
        msp.add_lwpolyline(quad, close=True, dxfattribs={"layer": "A-WALL"})

    # 3. Door symbols (BLOCK definitions + INSERTs on A-DOOR)
    door_block_cache: dict[tuple[str, int, str, str], str] = {}
    for d in model.doors:
        bkey = (d.mark, int(round(d.width_mm)), d.swing, d.swing_side)
        if bkey not in door_block_cache:
            bname = f"SYM_DOOR_{d.mark}_{int(round(d.width_mm))}_{d.swing[0].upper()}_{d.swing_side.upper()}"
            bname = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in bname)
            blk = doc.blocks.new(name=bname)
            w = float(d.width_mm)
            x_hinge = -w / 2.0 if d.swing == "left" else w / 2.0
            dir_y = 1.0 if d.swing_side == "in" else -1.0
            # Door jamb ticks
            blk.add_line((-w / 2.0, -100.0), (-w / 2.0, 100.0), dxfattribs={"layer": "A-DOOR"})
            blk.add_line((w / 2.0, -100.0), (w / 2.0, 100.0), dxfattribs={"layer": "A-DOOR"})
            # Door leaf line perpendicular to threshold
            blk.add_line((x_hinge, 0.0), (x_hinge, dir_y * w), dxfattribs={"layer": "A-DOOR"})
            # 90-degree swing arc
            if d.swing == "left" and dir_y > 0:
                s_a, e_a = 0.0, 90.0
            elif d.swing == "left" and dir_y < 0:
                s_a, e_a = 270.0, 360.0
            elif d.swing == "right" and dir_y > 0:
                s_a, e_a = 90.0, 180.0
            else:
                s_a, e_a = 180.0, 270.0
            blk.add_arc(
                center=(x_hinge, 0.0),
                radius=w,
                start_angle=s_a,
                end_angle=e_a,
                dxfattribs={"layer": "A-DOOR"},
            )
            txt = blk.add_text(
                d.mark,
                height=130.0,
                dxfattribs={"layer": "A-DOOR", "style": "ARABIC_TTF"},
            )
            txt.set_placement((0.0, dir_y * (w * 0.45)), align=TextEntityAlignment.MIDDLE_CENTER)
            door_block_cache[bkey] = bname

        msp.add_blockref(
            door_block_cache[bkey],
            insert=(float(d.position_mm[0]), float(d.position_mm[1])),
            dxfattribs={"layer": "A-DOOR", "rotation": float(d.angle_deg)},
        )

    # 4. Window symbols (BLOCK definitions + INSERTs on A-WIND)
    win_block_cache: dict[tuple[str, int], str] = {}
    for w_obj in model.windows:
        wkey = (w_obj.mark, int(round(w_obj.width_mm)))
        if wkey not in win_block_cache:
            bname = f"SYM_WIND_{w_obj.mark}_{int(round(w_obj.width_mm))}"
            bname = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in bname)
            blk = doc.blocks.new(name=bname)
            ww = float(w_obj.width_mm)
            # Outer sill & inner sill + center double glazing line
            for y_off in (-100.0, -25.0, 25.0, 100.0):
                blk.add_line((-ww / 2.0, y_off), (ww / 2.0, y_off), dxfattribs={"layer": "A-WIND"})
            blk.add_line((-ww / 2.0, -100.0), (-ww / 2.0, 100.0), dxfattribs={"layer": "A-WIND"})
            blk.add_line((ww / 2.0, -100.0), (ww / 2.0, 100.0), dxfattribs={"layer": "A-WIND"})
            txt = blk.add_text(
                w_obj.mark,
                height=130.0,
                dxfattribs={"layer": "A-WIND", "style": "ARABIC_TTF"},
            )
            txt.set_placement((0.0, 240.0), align=TextEntityAlignment.MIDDLE_CENTER)
            win_block_cache[wkey] = bname

        msp.add_blockref(
            win_block_cache[wkey],
            insert=(float(w_obj.position_mm[0]), float(w_obj.position_mm[1])),
            dxfattribs={"layer": "A-WIND", "rotation": float(w_obj.angle_deg)},
        )

    # 5. Linear dimensions (overall X/Y bounds + per-room extents) in exact millimetres
    overall_w_dim = msp.add_linear_dim(
        base=(min_x, min_y - 900.0),
        p1=(min_x, min_y),
        p2=(max_x, min_y),
        angle=0,
        dimstyle="ARCH_MM",
        dxfattribs={"layer": "A-ANNO-DIMS"},
    )
    overall_w_dim.render()

    overall_h_dim = msp.add_linear_dim(
        base=(min_x - 900.0, min_y),
        p1=(min_x, min_y),
        p2=(min_x, max_y),
        angle=90,
        dimstyle="ARCH_MM",
        dxfattribs={"layer": "A-ANNO-DIMS"},
    )
    overall_h_dim.render()

    for idx_r, rm in enumerate(rooms):
        xs_r = [p[0] for p in rm.polygon_mm]
        ys_r = [p[1] for p in rm.polygon_mm]
        rx0, rx1 = min(xs_r), max(xs_r)
        ry0, ry1 = min(ys_r), max(ys_r)
        if rx1 - rx0 > 500.0:
            d_rx = msp.add_linear_dim(
                base=(rx0, ry0 + 260.0),
                p1=(rx0, ry0),
                p2=(rx1, ry0),
                angle=0,
                dimstyle="ARCH_MM",
                dxfattribs={"layer": "A-ANNO-DIMS"},
            )
            d_rx.render()
        if idx_r < 2 and ry1 - ry0 > 500.0:
            d_ry = msp.add_linear_dim(
                base=(rx1 - 260.0, ry0),
                p1=(rx1, ry0),
                p2=(rx1, ry1),
                angle=90,
                dimstyle="ARCH_MM",
                dxfattribs={"layer": "A-ANNO-DIMS"},
            )
            d_ry.render()

    # 6. North Arrow & Legend + ModelSpace Schedules + Title Block Panel beside the plan
    panel_x = max_x + 1500.0
    na_cx = panel_x + 900.0
    na_cy = max_y - 700.0
    na_r = 450.0
    msp.add_circle((na_cx, na_cy), radius=na_r, dxfattribs={"layer": "A-ANNO-SYMB"})
    rad_n = math.radians(90.0 - float(model.north_angle_deg))
    tip_x = na_cx + math.cos(rad_n) * na_r
    tip_y = na_cy + math.sin(rad_n) * na_r
    left_x = na_cx + math.cos(rad_n + 2.5) * (na_r * 0.65)
    left_y = na_cy + math.sin(rad_n + 2.5) * (na_r * 0.65)
    right_x = na_cx + math.cos(rad_n - 2.5) * (na_r * 0.65)
    right_y = na_cy + math.sin(rad_n - 2.5) * (na_r * 0.65)
    msp.add_lwpolyline(
        [(left_x, left_y), (tip_x, tip_y), (right_x, right_y), (na_cx, na_cy)],
        close=True,
        dxfattribs={"layer": "A-ANNO-SYMB"},
    )
    na_lbl = msp.add_text(
        "N / شمال",
        height=170.0,
        dxfattribs={"layer": "A-ANNO-SYMB", "style": "ARABIC_TTF"},
    )
    na_lbl.set_placement((na_cx, na_cy - na_r - 220.0), align=TextEntityAlignment.MIDDLE_CENTER)

    # Legend & Title metadata in ModelSpace A-ANNO-TTLB / A-ANNO-SYMB
    legend_text = (
        "LEGEND / دليل الرموز:\\P"
        "A-WALL: Masonry & Partition Walls (mm)\\P"
        "A-AREA: Room Area Boundary (Net Polygons)\\P"
        "A-DOOR / A-WIND: Door & Window Symbols\\P"
        "A-ANNO-DIMS: True Scale Millimetre Dimensions"
    )
    mt_leg = msp.add_mtext(
        legend_text,
        dxfattribs={"layer": "A-ANNO-SYMB", "style": "ARABIC_TTF", "char_height": 140.0, "width": 4600.0},
    )
    mt_leg.set_location((panel_x, max_y - 1650.0))

    sched_lines = ["DOOR SCHEDULE / جدول الأبواب:"]
    for dr in door_schedule:
        sched_lines.append(f"{dr.mark}: {int(dr.width_mm)}x{int(dr.height_mm)}mm | Qty={dr.count} | {dr.material}")
    sched_lines.append("")
    sched_lines.append("WINDOW SCHEDULE / جدول النوافذ:")
    for wr in window_schedule:
        sched_lines.append(f"{wr.mark}: {int(wr.width_mm)}x{int(wr.height_mm)}mm Sill={int(wr.sill_mm)} | Qty={wr.count}")
    sched_lines.append("")
    sched_lines.append("FINISHES SCHEDULE / جدول التشطيبات:")
    for rm in rooms:
        sched_lines.append(f"{rm.room_id} ({rm.name_en}): {rm.area_m2:.2f} m2 | {rm.floor_finish}")

    mt_sched = msp.add_mtext(
        "\\P".join(sched_lines),
        dxfattribs={"layer": "A-ANNO-TTLB", "style": "ARABIC_TTF", "char_height": 125.0, "width": 5200.0},
    )
    mt_sched.set_location((panel_x, max_y - 3100.0))

    issued_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ttlb_str = (
        f"DWG NO: {drawing_no} | REV: {revision} | DATE: {issued_date}\\P"
        f"TITLE: {title}\\P"
        f"SCALE: 1:{scale_denominator} ({paper_size}) | UNITS: mm ($INSUNITS=4)\\P"
        f"CLASSIFICATION: {classification}\\P"
        f"NOTES: {notes or 'Verify all dimensions on site.'}"
    )
    msp.add_lwpolyline(
        [
            (panel_x - 100.0, min_y - 900.0),
            (panel_x + 5400.0, min_y - 900.0),
            (panel_x + 5400.0, min_y + 900.0),
            (panel_x - 100.0, min_y + 900.0),
        ],
        close=True,
        dxfattribs={"layer": "A-ANNO-TTLB"},
    )
    mt_ttlb = msp.add_mtext(
        ttlb_str,
        dxfattribs={"layer": "A-ANNO-TTLB", "style": "ARABIC_TTF", "char_height": 135.0, "width": 5200.0},
    )
    mt_ttlb.set_location((panel_x, min_y + 760.0))

    # 7. ISO PaperSpace Layout (true paper units mm + scaled viewport + Title Block)
    pw_mm, ph_mm = PAPER_DIMENSIONS_MM[paper_size]
    psp = doc.layouts.new("ISO_SHEET_PLAN")
    psp.page_setup(size=(pw_mm, ph_mm), margins=(10, 10, 10, 10), units="mm")
    psp.add_lwpolyline(
        [(10.0, 10.0), (pw_mm - 10.0, 10.0), (pw_mm - 10.0, ph_mm - 10.0), (10.0, ph_mm - 10.0)],
        close=True,
        dxfattribs={"layer": "A-ANNO-TTLB"},
    )
    plan_cx = (min_x + max_x) / 2.0
    plan_cy = (min_y + max_y) / 2.0
    vp_h_mm = ph_mm - 65.0
    psp.add_viewport(
        center=(pw_mm * 0.48, ph_mm * 0.56),
        size=(pw_mm - 35.0, vp_h_mm),
        view_center_point=(plan_cx, plan_cy),
        view_height=vp_h_mm * float(scale_denominator),
        dxfattribs={"layer": "A-ANNO-TTLB"},
    )
    psp_ttlb = psp.add_mtext(
        ttlb_str,
        dxfattribs={"layer": "A-ANNO-TTLB", "style": "ARABIC_TTF", "char_height": 3.2, "width": pw_mm - 30.0},
    )
    psp_ttlb.set_location((15.0, 38.0))

    doc.saveas(str(out_path))


def _esc(val: object) -> str:
    return html.escape(str(val if val is not None else ""), quote=True)


def _insert_bilingual_html_box(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    html_body: str,
    *,
    archive: pymupdf.Archive | None,
    css_extra: str = "",
) -> None:
    has_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    font_css = (
        "@font-face { font-family: 'DocFont'; src: url('tahoma.ttf'); font-weight: normal; }"
        if has_tahoma
        else ""
    )
    font_stack = "'DocFont', Tahoma, sans-serif" if has_tahoma else "sans-serif"
    full_html = (
        f"<html><head><meta charset='utf-8'><style>"
        f"{font_css} body {{ font-family: {font_stack}; margin: 0; padding: 0; color: #0f172a; }} {css_extra}"
        f"</style></head><body>{html_body}</body></html>"
    )
    page.insert_htmlbox(rect, full_html, archive=archive)


def generate_true_scale_parametric_pdf(
    out_path: Path,
    *,
    model: ParametricPlanModel,
    rooms: list[ComputedRoomMetric],
    door_schedule: list[DoorScheduleRow],
    window_schedule: list[WindowScheduleRow],
    drawing_no: str,
    title: str,
    project_code: str,
    project_name: str,
    scale_denominator: int,
    paper_size: PaperSizeChoice,
    classification: str,
    revision: str,
    notes: str | None,
) -> dict[str, float]:
    """Generate a 2-page true-scale vector architectural PDF (Page 1: 1:scale Plan; Page 2: Schedules) with embedded Arabic Tahoma."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing parametric PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pw_mm, ph_mm = PAPER_DIMENSIONS_MM[paper_size]
    pw_pt = pw_mm * _PT_PER_MM
    ph_pt = ph_mm * _PT_PER_MM

    # EXACT true paper scale transform: 1 mm on real building = (1 / scale_denominator) * (72 / 25.4) pt on PDF sheet!
    pt_per_model_mm = _PT_PER_MM / float(scale_denominator)

    min_x, min_y, max_x, max_y = _model_bounds_mm(rooms, model.walls)
    plan_w_pt = (max_x - min_x) * pt_per_model_mm
    plan_h_pt = (max_y - min_y) * pt_per_model_mm

    # Drawable sheet canvas left of Legend / Title Block margin
    margin_pt = 12.0 * _PT_PER_MM
    ttlb_h_pt = 42.0 * _PT_PER_MM
    sidebar_w_pt = 95.0 * _PT_PER_MM
    canvas_w = pw_pt - 2 * margin_pt - sidebar_w_pt
    canvas_h = ph_pt - 2 * margin_pt - ttlb_h_pt

    origin_x_pt = margin_pt + max(18.0, (canvas_w - plan_w_pt) * 0.5)
    # CAD +Y goes UP; PDF +Y goes DOWN
    plan_bottom_pt = margin_pt + canvas_h - max(18.0, (canvas_h - plan_h_pt) * 0.5)

    def to_pdf_pt(mx: float, my: float) -> pymupdf.Point:
        px = origin_x_pt + (mx - min_x) * pt_per_model_mm
        py = plan_bottom_pt - (my - min_y) * pt_per_model_mm
        return pymupdf.Point(px, py)

    archive = pymupdf.Archive(str(_WINDOWS_FONTS_DIR)) if (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file() else None
    doc = pymupdf.open()

    # ================= PAGE 1: TRUE-SCALE ARCHITECTURAL FLOOR PLAN =================
    page1 = doc.new_page(width=pw_pt, height=ph_pt)
    shape = page1.new_shape()

    # Outer sheet border & right sidebar + bottom Title Block frames
    outer_rect = pymupdf.Rect(margin_pt, margin_pt, pw_pt - margin_pt, ph_pt - margin_pt)
    shape.draw_rect(outer_rect)
    shape.finish(color=(0.12, 0.23, 0.37), width=1.4)

    sidebar_x = pw_pt - margin_pt - sidebar_w_pt
    ttlb_y = ph_pt - margin_pt - ttlb_h_pt
    shape.draw_line(pymupdf.Point(sidebar_x, margin_pt), pymupdf.Point(sidebar_x, ttlb_y))
    shape.finish(color=(0.3, 0.35, 0.45), width=0.8)
    shape.draw_line(pymupdf.Point(margin_pt, ttlb_y), pymupdf.Point(pw_pt - margin_pt, ttlb_y))
    shape.finish(color=(0.12, 0.23, 0.37), width=1.1)

    # 1. Room area boundaries (A-AREA)
    for rm in rooms:
        poly_pts = [to_pdf_pt(px, py) for px, py in rm.polygon_mm]
        shape.draw_polyline(poly_pts + [poly_pts[0]])
        shape.finish(color=(0.15, 0.55, 0.30), fill=(0.94, 0.99, 0.95), width=0.6)

    # 2. Split walls (A-WALL)
    wall_segments = _split_walls_around_openings(model.walls, model.doors, model.windows)
    for seg in wall_segments:
        quad = [to_pdf_pt(px, py) for px, py in _wall_face_quad(seg)]
        shape.draw_polyline(quad + [quad[0]])
        shape.finish(color=(0.06, 0.09, 0.16), fill=(0.82, 0.85, 0.89), width=0.9)

    # 3. Doors (leaf + 90 deg swing arc on A-DOOR)
    for d in model.doors:
        cx, cy = float(d.position_mm[0]), float(d.position_mm[1])
        ang = math.radians(float(d.angle_deg))
        w = float(d.width_mm)
        hx_local = -w / 2.0 if d.swing == "left" else w / 2.0
        dir_y = 1.0 if d.swing_side == "in" else -1.0

        def rot(lx: float, ly: float) -> pymupdf.Point:
            wx = cx + lx * math.cos(ang) - ly * math.sin(ang)
            wy = cy + lx * math.sin(ang) + ly * math.cos(ang)
            return to_pdf_pt(wx, wy)

        hinge_pt = rot(hx_local, 0.0)
        leaf_tip = rot(hx_local, dir_y * w)
        latch_pt = rot(-hx_local, 0.0)
        shape.draw_line(hinge_pt, leaf_tip)
        shape.finish(color=(0.78, 0.35, 0.05), width=0.9)
        # Approximate 90-degree arc smoothly as 16 vector chord segments at true radius!
        arc_pts: list[pymupdf.Point] = []
        sign_x = 1.0 if d.swing == "left" else -1.0
        for step_i in range(17):
            theta = (math.pi / 2.0) * (step_i / 16.0)
            ax = hx_local + sign_x * w * math.cos(theta)
            ay = dir_y * w * math.sin(theta)
            arc_pts.append(rot(ax, ay))
        shape.draw_polyline(arc_pts)
        shape.finish(color=(0.78, 0.35, 0.05), width=0.6, dashes="[2 2] 0")

    # 4. Windows (3 parallel glazing lines on A-WIND)
    for w_obj in model.windows:
        cx, cy = float(w_obj.position_mm[0]), float(w_obj.position_mm[1])
        ang = math.radians(float(w_obj.angle_deg))
        ww = float(w_obj.width_mm)

        def rot_w(lx: float, ly: float) -> pymupdf.Point:
            wx = cx + lx * math.cos(ang) - ly * math.sin(ang)
            wy = cy + lx * math.sin(ang) + ly * math.cos(ang)
            return to_pdf_pt(wx, wy)

        for y_off in (-85.0, 0.0, 85.0):
            shape.draw_line(rot_w(-ww / 2.0, y_off), rot_w(ww / 2.0, y_off))
            shape.finish(color=(0.0, 0.55, 0.72), width=0.75)

    # 5. Overall X & Y true-scale dimensions lines + labels (A-ANNO-DIMS)
    p_min = to_pdf_pt(min_x, min_y)
    p_xmax = to_pdf_pt(max_x, min_y)
    p_ymax = to_pdf_pt(min_x, max_y)
    dim_off_y = 22.0
    dim_off_x = -22.0
    shape.draw_line(pymupdf.Point(p_min.x, p_min.y + dim_off_y), pymupdf.Point(p_xmax.x, p_xmax.y + dim_off_y))
    shape.finish(color=(0.75, 0.1, 0.1), width=0.6)
    shape.draw_line(pymupdf.Point(p_min.x + dim_off_x, p_min.y), pymupdf.Point(p_ymax.x + dim_off_x, p_ymax.y))
    shape.finish(color=(0.75, 0.1, 0.1), width=0.6)

    # 6. North Arrow in Sidebar
    na_center = pymupdf.Point(sidebar_x + sidebar_w_pt * 0.5, margin_pt + 48.0)
    na_rad_pt = 20.0
    shape.draw_circle(na_center, na_rad_pt)
    shape.finish(color=(0.12, 0.23, 0.37), width=0.9)
    n_theta = math.radians(90.0 - float(model.north_angle_deg))
    n_tip = pymupdf.Point(na_center.x + math.cos(n_theta) * na_rad_pt, na_center.y - math.sin(n_theta) * na_rad_pt)
    n_l = pymupdf.Point(na_center.x + math.cos(n_theta + 2.5) * na_rad_pt * 0.6, na_center.y - math.sin(n_theta + 2.5) * na_rad_pt * 0.6)
    n_r = pymupdf.Point(na_center.x + math.cos(n_theta - 2.5) * na_rad_pt * 0.6, na_center.y - math.sin(n_theta - 2.5) * na_rad_pt * 0.6)
    shape.draw_polyline([n_l, n_tip, n_r, na_center])
    shape.finish(color=(0.12, 0.23, 0.37), fill=(0.12, 0.23, 0.37), width=0.8)

    # Graphic True-Scale Calibration Bar (shows exact 2000mm = 2.0m bar at 1:scale!)
    bar_mm = 2000.0
    bar_pt = bar_mm * pt_per_model_mm
    bx0 = sidebar_x + 22.0
    by0 = margin_pt + 98.0
    shape.draw_rect(pymupdf.Rect(bx0, by0, bx0 + bar_pt, by0 + 5.0))
    shape.finish(color=(0.1, 0.1, 0.1), fill=(0.15, 0.23, 0.35), width=0.6)
    shape.commit()

    # Room Labels (Arabic + English + Computed Code Area m2) + Overall Dimension Text
    _insert_bilingual_html_box(
        page1,
        pymupdf.Rect(p_min.x, p_min.y + 8.0, p_xmax.x, p_min.y + 24.0),
        f"<div style='text-align:center;font-size:7pt;color:#991b1b;'>{int(round(max_x - min_x))} mm</div>",
        archive=archive,
    )
    _insert_bilingual_html_box(
        page1,
        pymupdf.Rect(p_min.x - 75.0, p_ymax.y, p_min.x - 4.0, p_min.y),
        f"<div style='text-align:center;font-size:7pt;color:#991b1b;margin-top:45%;'>{int(round(max_y - min_y))} mm</div>",
        archive=archive,
    )

    for rm in rooms:
        rc = to_pdf_pt(*rm.centroid_mm)
        rm_box = pymupdf.Rect(rc.x - 52.0, rc.y - 26.0, rc.x + 52.0, rc.y + 26.0)
        _insert_bilingual_html_box(
            page1,
            rm_box,
            (
                f"<div style='text-align:center;font-size:6.5pt;line-height:1.25;'>"
                f"<div dir='rtl'><strong>{_esc(rm.name_ar)}</strong></div>"
                f"<div>{_esc(rm.name_en)}</div>"
                f"<div style='color:#166534;'><strong>{rm.area_m2:.2f} m²</strong></div>"
                f"</div>"
            ),
            archive=archive,
        )

    for d in model.doors:
        dp = to_pdf_pt(*d.position_mm)
        _insert_bilingual_html_box(
            page1,
            pymupdf.Rect(dp.x - 16.0, dp.y - 8.0, dp.x + 16.0, dp.y + 8.0),
            f"<div style='text-align:center;font-size:6pt;color:#9a3412;'><strong>{_esc(d.mark)}</strong></div>",
            archive=archive,
        )

    for w_obj in model.windows:
        wp = to_pdf_pt(*w_obj.position_mm)
        _insert_bilingual_html_box(
            page1,
            pymupdf.Rect(wp.x - 16.0, wp.y - 12.0, wp.x + 16.0, wp.y + 4.0),
            f"<div style='text-align:center;font-size:6pt;color:#0369a1;'><strong>{_esc(w_obj.mark)}</strong></div>",
            archive=archive,
        )

    # Sidebar Legend + Scale Bar Text
    total_area_m2 = round(sum(r.area_m2 for r in rooms), 4)
    sidebar_rect = pymupdf.Rect(sidebar_x + 8.0, margin_pt + 74.0, pw_pt - margin_pt - 8.0, ttlb_y - 8.0)
    sidebar_html = f"""
    <div style='font-size:7pt;line-height:1.35;'>
      <div style='text-align:center;font-weight:bold;color:#1e3a5f;'>N / شمال ({int(round(model.north_angle_deg))}°)</div>
      <div style='margin-top:26pt;font-size:6.5pt;'>Scale Calibration Bar: <strong>2000 mm = {bar_mm / scale_denominator:.1f} mm on {paper_size}</strong></div>
      <hr/>
      <div style='font-weight:bold;color:#1e3a5f;'>LEGEND / دليل الرموز</div>
      <div><span style='color:#0f172a;'>■</span> <strong>A-WALL</strong>: Walls (200 / 150 mm)</div>
      <div><span style='color:#16a34a;'>□</span> <strong>A-AREA</strong>: Room Net Polygons</div>
      <div><span style='color:#c2410c;'>⌒</span> <strong>A-DOOR</strong>: Door Swing Symbols ({len(model.doors)})</div>
      <div><span style='color:#0284c7;'>═</span> <strong>A-WIND</strong>: Window Glazing ({len(model.windows)})</div>
      <hr/>
      <div style='font-weight:bold;color:#1e3a5f;'>SUMMARY / ملخص المساحات</div>
      <div>Rooms Count: <strong>{len(rooms)}</strong></div>
      <div>Total Net Room Area: <strong>{total_area_m2:.2f} m²</strong></div>
      <div>Doors: <strong>{len(model.doors)}</strong> | Windows: <strong>{len(model.windows)}</strong></div>
      <div style='margin-top:6pt;font-size:6pt;color:#475569;'>True Scale Export: Print on {paper_size} at 100% (Actual Size) for 1:{scale_denominator} ruler check.</div>
    </div>
    """
    _insert_bilingual_html_box(page1, sidebar_rect, sidebar_html, archive=archive)

    # Title Block on Page 1
    issued_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ttlb_rect = pymupdf.Rect(margin_pt + 8.0, ttlb_y + 6.0, pw_pt - margin_pt - 8.0, ph_pt - margin_pt - 6.0)
    ttlb_html = f"""
    <table style='width:100%;border-collapse:collapse;font-size:7pt;'>
      <tr>
        <td style='width:24%;vertical-align:top;padding:3pt;border:1px solid #cbd5e1;'>
          <div style='color:#1e3a5f;font-weight:bold;'>PROJECT / المشروع</div>
          <div>[{_esc(project_code)}] {_esc(project_name)}</div>
          <div><span style='background:#fef3c7;border:1px solid #d97706;padding:1pt 4pt;font-weight:bold;'>Classification: {_esc(classification)}</span></div>
        </td>
        <td style='width:38%;vertical-align:top;padding:3pt;border:1px solid #cbd5e1;'>
          <div style='color:#1e3a5f;font-weight:bold;'>DRAWING TITLE / عنوان اللوحة</div>
          <div dir='auto' style='font-size:8pt;font-weight:bold;'>{_esc(title)}</div>
          <div style='color:#475569;font-size:6pt;'>Notes: {_esc(notes or "")}</div>
        </td>
        <td style='width:38%;vertical-align:top;padding:3pt;border:1px solid #cbd5e1;'>
          <div><strong>DWG NO:</strong> {_esc(drawing_no)} &nbsp;|&nbsp; <strong>REV:</strong> {_esc(revision)}</div>
          <div><strong>TRUE SCALE:</strong> 1:{scale_denominator} ({paper_size}) &nbsp;|&nbsp; <strong>UNITS:</strong> mm ($INSUNITS=4)</div>
          <div><strong>DATE:</strong> {_esc(issued_iso)}</div>
          <div style='font-size:6pt;color:#475569;'>Code-computed areas & schedules; advisory until licensed engineer sign-off.</div>
        </td>
      </tr>
    </table>
    """
    _insert_bilingual_html_box(page1, ttlb_rect, ttlb_html, archive=archive)

    # ================= PAGE 2: MODEL-MATCHED ARCHITECTURAL SCHEDULES =================
    page2 = doc.new_page(width=pw_pt, height=ph_pt)
    s2 = page2.new_shape()
    s2.draw_rect(outer_rect)
    s2.finish(color=(0.12, 0.23, 0.37), width=1.4)
    s2.commit()

    door_rows_html = "".join(
        f"<tr><td><strong>{_esc(r.mark)}</strong></td><td>{int(r.width_mm)}</td><td>{int(r.height_mm)}</td>"
        f"<td>{_esc(r.swing)}</td><td><strong>{r.count}</strong></td><td>{_esc(r.material)}</td>"
        f"<td>{_esc(r.fire_rating)}</td><td>{_esc(', '.join(r.door_ids))}</td></tr>"
        for r in door_schedule
    )
    win_rows_html = "".join(
        f"<tr><td><strong>{_esc(r.mark)}</strong></td><td>{int(r.width_mm)}</td><td>{int(r.height_mm)}</td>"
        f"<td>{int(r.sill_mm)}</td><td><strong>{r.count}</strong></td><td>{_esc(r.glazing)}</td>"
        f"<td>{_esc(', '.join(r.window_ids))}</td></tr>"
        for r in window_schedule
    )
    fin_rows_html = "".join(
        f"<tr><td><strong>{_esc(rm.room_id)}</strong></td><td dir='rtl'>{_esc(rm.name_ar)}</td><td>{_esc(rm.name_en)}</td>"
        f"<td><strong>{rm.area_m2:.2f}</strong></td><td>{rm.perimeter_m:.2f}</td>"
        f"<td>{_esc(rm.floor_finish)}</td><td>{_esc(rm.wall_finish)}</td><td>{_esc(rm.ceiling_finish)}</td></tr>"
        for rm in rooms
    )

    page2_html = f"""
    <div style='font-size:8pt;'>
      <div style='border-bottom:2px solid #1e3a5f;padding-bottom:4pt;margin-bottom:8pt;'>
        <strong style='font-size:11pt;color:#1e3a5f;'>ARCHITECTURAL SCHEDULES / جداول الأبواب والنوافذ والتشطيبات</strong>
        &nbsp;&nbsp;|&nbsp;&nbsp;
        <span>DWG NO: <strong>{_esc(drawing_no)}</strong></span>
        &nbsp;|&nbsp;
        <span>REV: <strong>{_esc(revision)}</strong></span>
        &nbsp;|&nbsp;
        <span>Classification: <strong>{_esc(classification)}</strong></span>
      </div>

      <h3 style='color:#1e3a5f;margin:6pt 0 3pt 0;'>1. Door Schedule / جدول الأبواب (Total = {sum(r.count for r in door_schedule)})</h3>
      <table style='width:100%;border-collapse:collapse;font-size:7pt;'>
        <tr style='background:#1e3a5f;color:#fff;'>
          <th>Mark</th><th>W (mm)</th><th>H (mm)</th><th>Swing</th><th>Qty</th><th>Material</th><th>Fire</th><th>IDs</th>
        </tr>
        {door_rows_html}
      </table>

      <h3 style='color:#1e3a5f;margin:10pt 0 3pt 0;'>2. Window Schedule / جدول النوافذ (Total = {sum(r.count for r in window_schedule)})</h3>
      <table style='width:100%;border-collapse:collapse;font-size:7pt;'>
        <tr style='background:#1e3a5f;color:#fff;'>
          <th>Mark</th><th>W (mm)</th><th>H (mm)</th><th>Sill (mm)</th><th>Qty</th><th>Glazing Specification</th><th>IDs</th>
        </tr>
        {win_rows_html}
      </table>

      <h3 style='color:#1e3a5f;margin:10pt 0 3pt 0;'>3. Room Areas &amp; Finishes Schedule / جدول الفراغات والتشطيبات (Total = {total_area_m2:.2f} m²)</h3>
      <table style='width:100%;border-collapse:collapse;font-size:7pt;'>
        <tr style='background:#1e3a5f;color:#fff;'>
          <th>Room ID</th><th>الاسم العربي</th><th>English Name</th><th>Area (m²)</th><th>Perim (m)</th><th>Floor Finish</th><th>Wall Finish</th><th>Ceiling Finish</th>
        </tr>
        {fin_rows_html}
      </table>
    </div>
    """
    _insert_bilingual_html_box(
        page2,
        pymupdf.Rect(margin_pt + 10.0, margin_pt + 10.0, pw_pt - margin_pt - 10.0, ph_pt - margin_pt - 10.0),
        page2_html,
        archive=archive,
        css_extra="td, th { border: 1px solid #cbd5e1; padding: 2.5pt 4pt; text-align: left; }",
    )

    doc.save(str(out_path))
    doc.close()
    return {
        "pt_per_model_mm": round(pt_per_model_mm, 8),
        "plan_width_pt": round(plan_w_pt, 4),
        "plan_height_pt": round(plan_h_pt, 4),
    }


def verify_dxf_round_trip(
    dxf_path: Path,
    *,
    rooms: list[ComputedRoomMetric],
    door_count: int,
    window_count: int,
) -> RoundTripCheckOut:
    """Re-read the generated DXF via the Step 07 extractor and verify $INSUNITS=4, TrueType fonts, room areas, and block counts."""
    with tempfile.TemporaryDirectory() as td:
        tmp_pages = Path(td) / "rt_pages"
        extracted_payload, _units_disp, inv = extract_dxf(
            dxf_path,
            output_pages_dir=tmp_pages,
            pages_relative_prefix="rt_pages",
            source_file=dxf_path.name,
            file_id=None,
            version_number=1,
        )

    # Check TrueType font enforcement directly on DXF style table
    dxf_check_doc = ezdxf.readfile(str(dxf_path))
    ttf_styles: list[str] = []
    uses_shx = False
    for st in dxf_check_doc.styles:
        font_name = str(getattr(st.dxf, "font", "") or "").lower()
        bigfont_name = str(getattr(st.dxf, "bigfont", "") or "").lower()
        if ".shx" in font_name or ".shx" in bigfont_name:
            uses_shx = True
        if ".ttf" in font_name:
            ttf_styles.append(f"{st.dxf.name}:{font_name}")

    insunits_code = int(inv.get("insunits_code") or 0)
    units_label = str(inv.get("declared_unit") or "unknown")
    units_doubtful = bool(inv.get("units_doubtful"))

    area_groups = [
        g for g in (inv.get("layer_area_groups") or []) if isinstance(g, dict) and str(g.get("layer")) == "A-AREA"
    ]
    extracted_contours = sum(int(g.get("count") or 0) for g in area_groups)
    extracted_area_m2 = round(sum(float(g.get("area_m2_sum") or 0.0) for g in area_groups), 4)
    expected_area_m2 = round(sum(r.area_m2 for r in rooms), 4)
    area_diff = round(abs(extracted_area_m2 - expected_area_m2), 4)

    blk_groups = [g for g in (inv.get("block_insert_groups") or []) if isinstance(g, dict)]
    extracted_doors = sum(int(g.get("count") or 0) for g in blk_groups if str(g.get("layer")) == "A-DOOR")
    extracted_windows = sum(int(g.get("count") or 0) for g in blk_groups if str(g.get("layer")) == "A-WIND")

    mismatches: list[str] = []
    if insunits_code != 4:
        mismatches.append(f"Expected $INSUNITS=4 (mm), got {insunits_code} ({units_label}).")
    if units_doubtful:
        mismatches.append("Step 07 extractor flagged drawing units as doubtful.")
    if uses_shx or not ttf_styles:
        mismatches.append("DXF must use TrueType (.ttf) text styles rather than SHX.")
    if extracted_contours != len(rooms):
        mismatches.append(f"Expected {len(rooms)} A-AREA room contours, extracted {extracted_contours}.")
    if area_diff > 0.01:
        mismatches.append(f"Total room area mismatch: model={expected_area_m2} m² vs DXF={extracted_area_m2} m².")
    if extracted_doors != door_count:
        mismatches.append(f"Door block count mismatch: model={door_count} vs DXF A-DOOR={extracted_doors}.")
    if extracted_windows != window_count:
        mismatches.append(f"Window block count mismatch: model={window_count} vs DXF A-WIND={extracted_windows}.")

    return RoundTripCheckOut(
        passed=len(mismatches) == 0,
        insunits_code=insunits_code,
        units=units_label,
        units_doubtful=units_doubtful,
        ttf_font_styles=ttf_styles,
        uses_shx=uses_shx,
        expected_room_count=len(rooms),
        extracted_area_contour_count=extracted_contours,
        expected_total_area_m2=expected_area_m2,
        extracted_total_area_m2=extracted_area_m2,
        area_diff_m2=area_diff,
        expected_doors_count=door_count,
        extracted_doors_count=extracted_doors,
        expected_windows_count=window_count,
        extracted_windows_count=extracted_windows,
        mismatches=mismatches,
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
