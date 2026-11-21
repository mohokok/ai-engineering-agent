"""Step 13 deterministic bilingual calculation report & live-formula spreadsheet exporter (DOCX / PDF / XLSX)."""

from dataclasses import dataclass
import hashlib
import html
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
import pymupdf

from app.schemas.calculations import CalculationLanguage, VERIFY_CODE_LABEL
from app.services.report_generator import (
    _configure_rtl_table,
    _set_element_tag,
    _shade_cell,
    _style_paragraph,
)

_WINDOWS_FONTS_DIR = Path("C:/Windows/Fonts")
_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class CalculationRenderData:
    """Symmetric calculation report payload rendered across DOCX, PDF, and XLSX."""

    project_code: str
    project_name: str
    title: str
    discipline: str
    calculation_type: str
    language: CalculationLanguage
    classification: str
    revision: str
    version: int
    export_version: int
    issued_at_iso: str
    inputs: dict[str, Any]
    units: dict[str, str]
    equations: str
    method: str
    assumptions: list[str]
    results: dict[str, Any]
    acceptance_criteria: list[str]
    acceptance_passed: bool
    references: list[dict[str, Any]]
    data_provenance: str = ""
    acceptance_outcome_label: str = ""


def _provenance_and_verdict_tokens(data: CalculationRenderData) -> tuple[str, str, str, str]:
    """Return (data_provenance, acceptance_outcome_label, pass_token, fail_token)."""
    prov = data.data_provenance or str(data.results.get("data_provenance") or "")
    if prov and prov != "owner_supplied":
        pass_tok = "PRELIMINARY PASS (built-in baseline data)"
        fail_tok = "PRELIMINARY FAIL (built-in baseline data)"
    else:
        pass_tok = "PASS"
        fail_tok = "FAIL"
    outcome_lbl = (
        data.acceptance_outcome_label
        or str(data.results.get("acceptance_outcome_label") or "")
        or (pass_tok if data.acceptance_passed else fail_tok)
    )
    return prov, outcome_lbl, pass_tok, fail_tok


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of an exported file."""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_xlsx_text(value: Any) -> str:
    text = str(value if value is not None else "")
    if text and text[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + text
    return text


def _esc(val: Any) -> str:
    return html.escape(str(val if val is not None else ""), quote=True)


def _esc_ltr(val: Any) -> str:
    return f"<span dir='ltr'>{_esc(val)}</span>"


_CALC_LABELS: dict[CalculationLanguage, dict[str, str]] = {
    "ar": {
        "classification_prefix": "التصنيف",
        "disclaimer": "تحذير مهني: هذه الحسابات الاستشارية أولية ومُنفَّذة برمجياً (0 توكن) — يجب التحقق من كافة المعاملات والاشتراطات وفق الكود المحلي المعتمد (verify against the locally adopted code) ومراجعة مهندس مرخص.",
        "project": "المشروع",
        "discipline": "التخصص",
        "calc_type": "نوع الحساب",
        "rev_ver": "الإصدار والمراجعة",
        "date": "تاريخ الإصدار (UTC)",
        "provenance": "مصدر البيانات (Data Provenance)",
        "outcome": "نتيجة معايير القبول",
        "pass": "مقبول (PASS)",
        "fail": "غير مقبول (FAIL)",
        "sec_inputs": "1. المدخلات والوحدات (Inputs & Units)",
        "sec_equations": "2. المعادلات الرياضية المستخدمة (Equations)",
        "sec_method": "3. منهجية الحساب (Methodology)",
        "sec_assumptions": "4. الافتراضات الهندسية (Assumptions)",
        "sec_results": "5. النتائج المحسوبة برمجياً (Deterministic Results)",
        "sec_breakdown": "5.1 جدول التفصيل (Breakdown Schedule)",
        "sec_acceptance": "6. معايير القبول والتحقق (Acceptance Criteria)",
        "sec_references": "7. المراجع المعتمدة (References — verify against the locally adopted code)",
        "col_param": "المعامل / البند",
        "col_val": "القيمة",
        "col_unit": "الوحدة",
        "col_src_kind": "نوع المصدر",
        "col_src_name": "اسم المصدر",
        "col_src_ref": "المرجع / الرابط",
        "col_src_date": "التاريخ",
        "col_src_lbl": "وسم التحقق",
    },
    "en": {
        "classification_prefix": "Classification",
        "disclaimer": "Engineering Notice: Deterministic calculation output (0 AI tokens) — verify all parameters and thresholds against the locally adopted code and obtain licensed engineer sign-off.",
        "project": "Project",
        "discipline": "Discipline",
        "calc_type": "Calculation Type",
        "rev_ver": "Version / Revision",
        "date": "Issue Date (UTC)",
        "provenance": "Data Provenance",
        "outcome": "Acceptance Outcome",
        "pass": "PASS",
        "fail": "FAIL",
        "sec_inputs": "1. Inputs & Units",
        "sec_equations": "2. Governing Equations",
        "sec_method": "3. Methodology",
        "sec_assumptions": "4. Engineering Assumptions",
        "sec_results": "5. Deterministic Results",
        "sec_breakdown": "5.1 Breakdown Schedule",
        "sec_acceptance": "6. Acceptance Criteria",
        "sec_references": "7. Standards & Owner References (verify against the locally adopted code)",
        "col_param": "Parameter",
        "col_val": "Value",
        "col_unit": "Unit",
        "col_src_kind": "Source Kind",
        "col_src_name": "Source Name",
        "col_src_ref": "Reference / URL",
        "col_src_date": "Date",
        "col_src_lbl": "Code Verification Label",
    },
}


def _flat_scalar_entries(mapping: dict[str, Any], units: dict[str, str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for k, v in mapping.items():
        if isinstance(v, (list, dict)):
            continue
        rows.append((k, "—" if v is None else str(v), units.get(k, "—")))
    return rows


def generate_calculation_xlsx(out_path: Path, data: CalculationRenderData) -> None:
    """Export deterministic calculation sheet with live Excel formulas plus Documentation & References sheet."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing calculation XLSX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _CALC_LABELS[data.language]
    prov_txt, outcome_txt, pass_tok, fail_tok = _provenance_and_verdict_tokens(data)
    wb = Workbook()
    ws = wb.active
    ws.title = "الحساب الهندسي" if is_ar else "Calculation Sheet"
    ws.views.sheetView[0].rightToLeft = is_ar

    navy_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    sub_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    ok_fill = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid")
    warn_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    hdr_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Calibri", size=11, bold=True)
    title_font = Font(name="Calibri", size=14, bold=True, color="1E3A5F")
    note_font = Font(name="Calibri", size=10, italic=True, color="475569")

    ws["A1"] = _safe_xlsx_text(data.title)
    ws["A1"].font = title_font
    ws.merge_cells("A1:H1")

    ws["A2"] = _safe_xlsx_text(
        f"[{data.project_code}] {data.project_name} | {data.discipline} / {data.calculation_type} | "
        f"{data.classification} | {data.revision} v{data.version} (Export v{data.export_version})"
    )
    ws["A2"].font = bold_font
    ws.merge_cells("A2:H2")

    ws["A3"] = _safe_xlsx_text(lbl["disclaimer"])
    ws["A3"].font = note_font
    ws.merge_cells("A3:H3")

    ws["A4"] = _safe_xlsx_text(f"{lbl['provenance']}: {prov_txt or '—'} | {lbl['outcome']}: {outcome_txt}")
    ws["A4"].font = bold_font
    ws["A4"].fill = warn_fill if (prov_txt and prov_txt != "owner_supplied") else ok_fill
    ws.merge_cells("A4:H4")

    row = 6
    # Inputs block with tracked cell coordinates for live Excel formulas
    ws.cell(row=row, column=1, value=_safe_xlsx_text(lbl["sec_inputs"])).font = bold_font
    row += 1
    for col_idx, header in enumerate((lbl["col_param"], lbl["col_val"], lbl["col_unit"]), start=1):
        c = ws.cell(row=row, column=col_idx, value=_safe_xlsx_text(header))
        c.fill = navy_fill
        c.font = hdr_font
    row += 1

    input_cell_map: dict[str, str] = {}
    for k, v in data.inputs.items():
        if isinstance(v, (list, dict)):
            continue
        ws.cell(row=row, column=1, value=_safe_xlsx_text(k))
        val_cell = ws.cell(row=row, column=2)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            val_cell.value = float(v)
        else:
            val_cell.value = _safe_xlsx_text(v)
        ws.cell(row=row, column=3, value=_safe_xlsx_text(data.units.get(k, "—")))
        input_cell_map[k] = f"B{row}"
        row += 1

    row += 1
    ws.cell(row=row, column=1, value=_safe_xlsx_text(lbl["sec_results"])).font = bold_font
    row += 1

    if data.calculation_type == "electrical_load_schedule":
        headers = [
            "Circuit ID",
            "Description",
            "Phase",
            "Connected Load (kW)",
            "Demand Factor",
            "Demand Load (kW)",
            "Power Factor",
            "Apparent Power (kVA)",
        ]
        for col_idx, h in enumerate(headers, start=1):
            c = ws.cell(row=row, column=col_idx, value=h)
            c.fill = navy_fill
            c.font = hdr_font
        row += 1
        start_r = row
        for c_item in data.results.get("circuits") or []:
            ws.cell(row=row, column=1, value=_safe_xlsx_text(c_item.get("circuit_id")))
            ws.cell(row=row, column=2, value=_safe_xlsx_text(c_item.get("description")))
            ws.cell(row=row, column=3, value=_safe_xlsx_text(c_item.get("phase")))
            ws.cell(row=row, column=4, value=float(c_item.get("connected_load_kw") or 0.0))
            ws.cell(row=row, column=5, value=float(c_item.get("demand_factor") or 0.0))
            ws.cell(row=row, column=6, value=f"=ROUND(D{row}*E{row},4)")
            ws.cell(row=row, column=7, value=float(c_item.get("power_factor") or 0.85))
            ws.cell(row=row, column=8, value=f"=ROUND(F{row}/G{row},4)")
            row += 1
        end_r = row - 1
        ws.cell(row=row, column=1, value="TOTAL").font = bold_font
        ws.cell(row=row, column=4, value=f"=ROUND(SUM(D{start_r}:D{end_r}),4)").font = bold_font
        ws.cell(row=row, column=6, value=f"=ROUND(SUM(F{start_r}:F{end_r}),4)").font = bold_font
        ws.cell(row=row, column=8, value=f"=ROUND(SUM(H{start_r}:H{end_r}),4)").font = bold_font
        for col_i in range(1, 9):
            ws.cell(row=row, column=col_i).fill = sub_fill
        tot_row = row
        row += 1

        spare_cell = input_cell_map["spare_capacity_pct"]
        v_cell = input_cell_map["system_voltage_v"]
        ph_cell = input_cell_map["phases"]
        max_unbal_cell = input_cell_map["max_phase_unbalance_pct"]

        summary_formulas = [
            ("Design Load (kW)", f"=ROUND(F{tot_row}*(1+{spare_cell}/100),4)", "kW"),
            ("Design Apparent Power (kVA)", f"=ROUND(H{tot_row}*(1+{spare_cell}/100),4)", "kVA"),
            ("Design Current (A)", f'=ROUND((B{row+1}*1000)/(IF({ph_cell}="3ph",SQRT(3),1)*{v_cell}),4)', "A"),
            ("Phase Unbalance (%)", float(data.results.get("phase_unbalance_pct") or 0.0), "%"),
            ("Acceptance Status", f'=IF(AND(F{tot_row}>0,B{row+3}<={max_unbal_cell}),"{pass_tok}","{fail_tok}")', "—"),
        ]
        for label_txt, formula_val, unit_txt in summary_formulas:
            ws.cell(row=row, column=1, value=label_txt).font = bold_font
            c_val = ws.cell(row=row, column=2, value=formula_val)
            c_val.font = bold_font
            ws.cell(row=row, column=3, value=unit_txt)
            if label_txt == "Acceptance Status":
                c_val.fill = ok_fill if data.acceptance_passed else warn_fill
            row += 1

    elif data.calculation_type == "plumbing_water_demand":
        headers = ["Fixture Type", "Label", "Count", "WSFU / Unit", "Subtotal WSFU"]
        for col_idx, h in enumerate(headers, start=1):
            c = ws.cell(row=row, column=col_idx, value=h)
            c.fill = navy_fill
            c.font = hdr_font
        row += 1
        start_r = row
        for fx in data.results.get("fixtures") or []:
            ws.cell(row=row, column=1, value=_safe_xlsx_text(fx.get("fixture_type")))
            ws.cell(row=row, column=2, value=_safe_xlsx_text(fx.get("label")))
            ws.cell(row=row, column=3, value=int(fx.get("count") or 0))
            ws.cell(row=row, column=4, value=float(fx.get("wsfu_per_unit") or 0.0))
            ws.cell(row=row, column=5, value=f"=ROUND(C{row}*D{row},4)")
            row += 1
        end_r = row - 1
        ws.cell(row=row, column=1, value="TOTAL WSFU").font = bold_font
        ws.cell(row=row, column=3, value=f"=SUM(C{start_r}:C{end_r})").font = bold_font
        ws.cell(row=row, column=5, value=f"=ROUND(SUM(E{start_r}:E{end_r}),4)").font = bold_font
        for col_i in range(1, 6):
            ws.cell(row=row, column=col_i).fill = sub_fill
        wsfu_tot_row = row
        row += 1

        occ_cell = input_cell_map["occupants_or_units"]
        lpd_cell = input_cell_map["daily_demand_l_per_person"]
        days_cell = input_cell_map["storage_autonomy_days"]
        stat_cell = input_cell_map["static_head_m"]
        fric_cell = input_cell_map["friction_and_residual_head_m"]
        eff_cell = input_cell_map["pump_efficiency"]

        gpm_row = row
        lps_row = row + 1
        daily_m3_row = row + 3
        tdh_row = row + 5
        hyd_row = row + 6
        summary_formulas = [
            ("Peak Flow (Hunter GPM)", float(data.results.get("peak_flow_gpm") or 0.0), "GPM"),
            ("Peak Flow (L/s)", f"=ROUND(B{gpm_row}*0.0630902,4)", "L/s"),
            ("Peak Flow (m3/h)", f"=ROUND(B{lps_row}*3.6,4)", "m3/h"),
            ("Daily Water Demand (m3/day)", f"=ROUND(({occ_cell}*{lpd_cell})/1000,4)", "m3/day"),
            ("Storage Tank Volume (m3)", f"=ROUND(B{daily_m3_row}*{days_cell},4)", "m3"),
            ("Total Dynamic Head (m)", f"=ROUND({stat_cell}+{fric_cell},4)", "m"),
            ("Hydraulic Power (kW)", f"=ROUND((9.80665*B{lps_row}*B{tdh_row})/1000,4)", "kW"),
            ("Pump Shaft Power (kW)", f"=ROUND(B{hyd_row}/{eff_cell},4)", "kW"),
            ("Acceptance Status", f'=IF(AND(E{wsfu_tot_row}>0,B{lps_row}>0),"{pass_tok}","{fail_tok}")', "—"),
        ]
        for label_txt, formula_val, unit_txt in summary_formulas:
            ws.cell(row=row, column=1, value=label_txt).font = bold_font
            c_val = ws.cell(row=row, column=2, value=formula_val)
            c_val.font = bold_font
            ws.cell(row=row, column=3, value=unit_txt)
            if label_txt == "Acceptance Status":
                c_val.fill = ok_fill if data.acceptance_passed else warn_fill
            row += 1

    else:
        for col_idx, header in enumerate((lbl["col_param"], lbl["col_val"], lbl["col_unit"]), start=1):
            c = ws.cell(row=row, column=col_idx, value=_safe_xlsx_text(header))
            c.fill = navy_fill
            c.font = hdr_font
        row += 1
        result_cell_map: dict[str, str] = {}
        for k, v_txt, u_txt in _flat_scalar_entries(data.results, data.units):
            ws.cell(row=row, column=1, value=_safe_xlsx_text(k))
            c_val = ws.cell(row=row, column=2)
            raw_v = data.results[k]
            if k == "acceptance_passed":
                c_val.value = _safe_xlsx_text(outcome_txt)
                c_val.fill = ok_fill if data.acceptance_passed else warn_fill
            elif isinstance(raw_v, (int, float)) and not isinstance(raw_v, bool):
                c_val.value = float(raw_v)
            else:
                c_val.value = _safe_xlsx_text(v_txt)
            ws.cell(row=row, column=3, value=_safe_xlsx_text(u_txt))
            result_cell_map[k] = f"B{row}"
            row += 1

        # Add live Excel formula cross-checks tied directly to input/result cells
        row += 1
        ws.cell(row=row, column=1, value="Live Excel Formula Check").font = bold_font
        row += 1
        if data.calculation_type == "electrical_cable_sizing":
            p_c = input_cell_map["design_power_kw"]
            v_c = input_cell_map["voltage_v"]
            pf_c = input_cell_map["power_factor"]
            ph_c = input_cell_map["phases"]
            ca_c = input_cell_map["ambient_temp_factor"]
            cg_c = input_cell_map["grouping_factor"]
            dv_max_c = input_cell_map["max_voltage_drop_pct"]
            in_r = result_cell_map["breaker_rating_a"]
            iz_r = result_cell_map["tabulated_ampacity_a"]
            dv_v_r = result_cell_map["voltage_drop_v"]

            live_rows = [
                ("Recomputed Design Current Ib (A)", f'=ROUND(({p_c}*1000)/(IF({ph_c}="3ph",SQRT(3),1)*{v_c}*{pf_c}),4)', "A"),
                ("Total Derating Factor Ct", f"=ROUND({ca_c}*{cg_c},4)", "—"),
                ("Derated Ampacity Iz_derated (A)", f"=ROUND({iz_r}*B{row+1},4)", "A"),
                ("Voltage Drop (%)", f"=ROUND(({dv_v_r}/{v_c})*100,4)", "%"),
                ("Live Acceptance Check", f'=IF(AND(B{row}<={in_r},{in_r}<=B{row+2},B{row+3}<={dv_max_c}),"{pass_tok}","{fail_tok}")', "—"),
            ]
        elif data.calculation_type == "electrical_voltage_drop":
            v_c = input_cell_map["voltage_v"]
            up_c = input_cell_map["upstream_drop_pct"]
            max_c = input_cell_map["max_total_drop_pct"]
            dv_v_r = result_cell_map["voltage_drop_v"]
            live_rows = [
                ("Circuit Voltage Drop (%)", f"=ROUND(({dv_v_r}/{v_c})*100,4)", "%"),
                ("Total Cumulative Drop (%)", f"=ROUND(B{row}+{up_c},4)", "%"),
                ("Receiving Voltage (V)", f"=ROUND({v_c}*(1-B{row+1}/100),4)", "V"),
                ("Live Acceptance Check", f'=IF(B{row+1}<={max_c},"{pass_tok}","{fail_tok}")', "—"),
            ]
        else:  # plumbing_pipe_sizing
            q_c = input_cell_map["flow_rate_lps"]
            len_c = input_cell_map["pipe_length_m"]
            min_c = input_cell_map["minor_loss_allowance_pct"]
            vmax_c = input_cell_map["max_velocity_mps"]
            hmax_c = input_cell_map["max_head_loss_m_per_100m"]
            id_r = result_cell_map["internal_diameter_mm"]
            hf100_r = result_cell_map["head_loss_m_per_100m"]
            live_rows = [
                ("Flow Q (m3/s)", f"=ROUND({q_c}/1000,6)", "m3/s"),
                ("Internal Pipe Area (m2)", f"=PI()*POWER({id_r}/1000,2)/4", "m2"),
                ("Flow Velocity (m/s)", f"=ROUND(B{row}/B{row+1},4)", "m/s"),
                ("Total Head Loss (m)", f"=ROUND({hf100_r}*({len_c}/100)*(1+{min_c}/100),4)", "m"),
                ("Pressure Drop (kPa)", f"=ROUND(998.2*9.80665*B{row+3}/1000,4)", "kPa"),
                ("Live Acceptance Check", f'=IF(AND(B{row+2}<={vmax_c},{hf100_r}<={hmax_c}),"{pass_tok}","{fail_tok}")', "—"),
            ]
        for label_txt, formula_val, unit_txt in live_rows:
            ws.cell(row=row, column=1, value=label_txt).font = bold_font
            c_val = ws.cell(row=row, column=2, value=formula_val)
            c_val.font = bold_font
            ws.cell(row=row, column=3, value=unit_txt)
            if "Acceptance" in label_txt:
                c_val.fill = ok_fill if data.acceptance_passed else warn_fill
            row += 1

        eval_sizes = data.results.get("evaluated_sizes") or []
        if isinstance(eval_sizes, list) and eval_sizes:
            row += 1
            ws.cell(row=row, column=1, value=_safe_xlsx_text(lbl["sec_breakdown"])).font = bold_font
            row += 1
            b_headers = [
                "Nominal DN (mm)",
                "Outer OD (mm)",
                "Wall (mm)",
                "Internal ID (mm)",
                "Velocity (m/s)",
                "Head Loss (m/100m)",
                "Total Loss (m)",
                "Status",
            ]
            for col_idx, h in enumerate(b_headers, start=1):
                c = ws.cell(row=row, column=col_idx, value=h)
                c.fill = navy_fill
                c.font = hdr_font
            row += 1
            for item in eval_sizes:
                ws.cell(row=row, column=1, value=float(item.get("nominal_diameter_mm") or 0.0))
                ws.cell(row=row, column=2, value=float(item["outer_diameter_mm"]) if item.get("outer_diameter_mm") is not None else "—")
                ws.cell(row=row, column=3, value=float(item["wall_thickness_mm"]) if item.get("wall_thickness_mm") is not None else "—")
                ws.cell(row=row, column=4, value=float(item.get("internal_diameter_mm") or 0.0))
                ws.cell(row=row, column=5, value=float(item.get("velocity_mps") or 0.0))
                ws.cell(row=row, column=6, value=float(item.get("head_loss_m_per_100m") or 0.0))
                ws.cell(row=row, column=7, value=float(item.get("total_head_loss_m") or 0.0))
                ws.cell(row=row, column=8, value=_safe_xlsx_text(item.get("status")))
                row += 1

    # Sheet 2: Documentation & References
    ws_doc = wb.create_sheet(title="المعادلات والمراجع" if is_ar else "Documentation & Refs")
    ws_doc.views.sheetView[0].rightToLeft = is_ar

    d_row = 1
    for heading, body in (
        (lbl["sec_equations"], data.equations),
        (lbl["sec_method"], data.method),
    ):
        ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(heading)).font = bold_font
        ws_doc.cell(row=d_row, column=2, value=_safe_xlsx_text(body)).alignment = Alignment(wrap_text=True)
        d_row += 1

    d_row += 1
    ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(lbl["sec_assumptions"])).font = bold_font
    d_row += 1
    for item in data.assumptions:
        ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(item))
        d_row += 1

    d_row += 1
    ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(lbl["sec_acceptance"])).font = bold_font
    d_row += 1
    for crit in data.acceptance_criteria:
        ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(crit))
        d_row += 1

    d_row += 1
    ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(lbl["sec_references"])).font = bold_font
    d_row += 1
    for col_idx, h in enumerate(
        (lbl["col_src_kind"], lbl["col_src_name"], lbl["col_src_ref"], lbl["col_src_date"], lbl["col_src_lbl"]),
        start=1,
    ):
        c = ws_doc.cell(row=d_row, column=col_idx, value=_safe_xlsx_text(h))
        c.fill = navy_fill
        c.font = hdr_font
    d_row += 1
    for ref in data.references:
        ws_doc.cell(row=d_row, column=1, value=_safe_xlsx_text(ref.get("source_kind")))
        ws_doc.cell(row=d_row, column=2, value=_safe_xlsx_text(ref.get("source_name")))
        ws_doc.cell(row=d_row, column=3, value=_safe_xlsx_text(ref.get("source_ref")))
        ws_doc.cell(row=d_row, column=4, value=_safe_xlsx_text(ref.get("publication_date") or "—"))
        ws_doc.cell(row=d_row, column=5, value=_safe_xlsx_text(ref.get("verification_label") or VERIFY_CODE_LABEL))
        d_row += 1

    for sheet_obj in (ws, ws_doc):
        for idx, width in ((1, 34), (2, 28), (3, 18), (4, 18), (5, 28), (6, 20), (7, 16), (8, 22)):
            col_letter = chr(ord("A") + idx - 1)
            sheet_obj.column_dimensions[col_letter].width = width

    wb.save(str(out_path))


def generate_calculation_docx(out_path: Path, data: CalculationRenderData) -> None:
    """Write a complete bilingual (Arabic RTL / English LTR) DOCX calculation report."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing calculation DOCX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    lbl = _CALC_LABELS[data.language]
    doc = Document()

    section = doc.sections[0]
    section.top_margin = Inches(0.6)
    section.bottom_margin = Inches(0.6)
    section.left_margin = Inches(0.6)
    section.right_margin = Inches(0.6)
    if is_ar:
        _set_element_tag(section._sectPr, "w:bidi")

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Tahoma" if is_ar else "Calibri"
    normal_style.font.size = Pt(10)

    h = doc.add_heading(f"{data.title} — [{lbl['classification_prefix']}: {data.classification}]", level=1)
    _style_paragraph(h, is_ar=is_ar, bold=True, font_size=15, color=RGBColor(0x1E, 0x3A, 0x5F))

    prov_txt, outcome_lbl, _, _ = _provenance_and_verdict_tokens(data)
    meta = (
        f"{lbl['project']}: [{data.project_code}] {data.project_name} | "
        f"{lbl['discipline']}: {data.discipline} ({data.calculation_type}) | "
        f"{lbl['rev_ver']}: v{data.version} ({data.revision}, Export v{data.export_version}) | "
        f"{lbl['outcome']}: {outcome_lbl} | {lbl['date']}: {data.issued_at_iso}"
    )
    p_meta = doc.add_paragraph(meta)
    _style_paragraph(p_meta, is_ar=is_ar, font_size=9, color=RGBColor(0x33, 0x41, 0x55))

    p_prov = doc.add_paragraph(f"{lbl['provenance']}: {prov_txt or '—'}")
    _style_paragraph(
        p_prov,
        is_ar=is_ar,
        bold=True,
        font_size=9,
        color=RGBColor(0x9A, 0x34, 0x12) if (prov_txt and prov_txt != "owner_supplied") else RGBColor(0x16, 0x65, 0x34),
    )

    p_disc = doc.add_paragraph(lbl["disclaimer"])
    _style_paragraph(p_disc, is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0x9A, 0x34, 0x12))

    def _add_kv_table(entries: list[tuple[str, str, str]]) -> None:
        tbl = doc.add_table(rows=1, cols=3)
        _configure_rtl_table(tbl, is_ar=is_ar)
        hdr_cells = tbl.rows[0].cells
        for i, htxt in enumerate((lbl["col_param"], lbl["col_val"], lbl["col_unit"])):
            hdr_cells[i].text = htxt
            _shade_cell(hdr_cells[i], "1E3A5F")
            _style_paragraph(hdr_cells[i].paragraphs[0], is_ar=is_ar, bold=True, font_size=9, color=RGBColor(0xFF, 0xFF, 0xFF))
        for k, v, u in entries:
            rc = tbl.add_row().cells
            rc[0].text = k
            rc[1].text = v
            rc[2].text = u
            for c_obj in rc:
                _style_paragraph(c_obj.paragraphs[0], is_ar=is_ar, font_size=9)

    # 1. Inputs & Units
    p_h1 = doc.add_heading(lbl["sec_inputs"], level=2)
    _style_paragraph(p_h1, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    _add_kv_table(_flat_scalar_entries(data.inputs, data.units))

    # 2. Equations
    p_h2 = doc.add_heading(lbl["sec_equations"], level=2)
    _style_paragraph(p_h2, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    p_eq = doc.add_paragraph(data.equations)
    _style_paragraph(p_eq, is_ar=False, font_size=9)

    # 3. Method
    p_h3 = doc.add_heading(lbl["sec_method"], level=2)
    _style_paragraph(p_h3, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    p_m = doc.add_paragraph(data.method)
    _style_paragraph(p_m, is_ar=is_ar, font_size=10)

    # 4. Assumptions
    p_h4 = doc.add_heading(lbl["sec_assumptions"], level=2)
    _style_paragraph(p_h4, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    for item in data.assumptions:
        pa = doc.add_paragraph(f"• {item}")
        _style_paragraph(pa, is_ar=is_ar, font_size=9)

    # 5. Results
    p_h5 = doc.add_heading(lbl["sec_results"], level=2)
    _style_paragraph(p_h5, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    _add_kv_table(_flat_scalar_entries(data.results, data.units))

    # Breakdown table for load schedule / fixtures / pipe sizes if present
    rows_list = data.results.get("circuits") or data.results.get("fixtures") or data.results.get("evaluated_sizes") or []
    if isinstance(rows_list, list) and rows_list:
        p_hb = doc.add_heading(lbl["sec_breakdown"], level=3)
        _style_paragraph(p_hb, is_ar=is_ar, bold=True, font_size=11, color=RGBColor(0x1E, 0x3A, 0x5F))
        cols = list(rows_list[0].keys())
        btbl = doc.add_table(rows=1, cols=len(cols))
        _configure_rtl_table(btbl, is_ar=is_ar)
        for i, col_name in enumerate(cols):
            btbl.rows[0].cells[i].text = str(col_name)
            _shade_cell(btbl.rows[0].cells[i], "1E3A5F")
            _style_paragraph(btbl.rows[0].cells[i].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
        for item_dict in rows_list:
            rc = btbl.add_row().cells
            for i, col_name in enumerate(cols):
                val = item_dict.get(col_name)
                rc[i].text = "—" if val is None else str(val)
                _style_paragraph(rc[i].paragraphs[0], is_ar=is_ar, font_size=8)

    # 6. Acceptance Criteria
    p_h6 = doc.add_heading(lbl["sec_acceptance"], level=2)
    _style_paragraph(p_h6, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    for crit in data.acceptance_criteria:
        pc = doc.add_paragraph(f"• {crit}")
        _style_paragraph(pc, is_ar=is_ar, bold=True, font_size=9)

    # 7. References
    p_h7 = doc.add_heading(lbl["sec_references"], level=2)
    _style_paragraph(p_h7, is_ar=is_ar, bold=True, font_size=12, color=RGBColor(0x1E, 0x3A, 0x5F))
    rtbl = doc.add_table(rows=1, cols=5)
    _configure_rtl_table(rtbl, is_ar=is_ar)
    for i, htxt in enumerate(
        (lbl["col_src_kind"], lbl["col_src_name"], lbl["col_src_ref"], lbl["col_src_date"], lbl["col_src_lbl"])
    ):
        rtbl.rows[0].cells[i].text = htxt
        _shade_cell(rtbl.rows[0].cells[i], "1E3A5F")
        _style_paragraph(rtbl.rows[0].cells[i].paragraphs[0], is_ar=is_ar, bold=True, font_size=8, color=RGBColor(0xFF, 0xFF, 0xFF))
    for ref in data.references:
        rc = rtbl.add_row().cells
        rc[0].text = str(ref.get("source_kind", ""))
        rc[1].text = str(ref.get("source_name", ""))
        rc[2].text = str(ref.get("source_ref", ""))
        rc[3].text = str(ref.get("publication_date") or "—")
        rc[4].text = str(ref.get("verification_label") or VERIFY_CODE_LABEL)
        for c_obj in rc:
            _style_paragraph(c_obj.paragraphs[0], is_ar=is_ar, font_size=8)

    doc.save(str(out_path))


def generate_calculation_pdf(out_path: Path, data: CalculationRenderData) -> None:
    """Render bilingual (Arabic RTL / English LTR) multi-page vector PDF calculation report via PyMuPDF Story."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing calculation PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _CALC_LABELS[data.language]

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    font_face_css = ""
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'CalcFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'CalcFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'CalcFont', Tahoma, sans-serif"
    else:
        font_stack = "sans-serif"

    def _kv_html(entries: list[tuple[str, str, str]]) -> str:
        rows = "".join(
            f"<tr><td>{_esc_ltr(k)}</td><td>{_esc_ltr(v)}</td><td>{_esc_ltr(u)}</td></tr>"
            for k, v, u in entries
        )
        return (
            f"<table><thead><tr><th>{_esc(lbl['col_param'])}</th><th>{_esc(lbl['col_val'])}</th>"
            f"<th>{_esc(lbl['col_unit'])}</th></tr></thead><tbody>{rows}</tbody></table>"
        )

    rows_list = data.results.get("circuits") or data.results.get("fixtures") or data.results.get("evaluated_sizes") or []
    breakdown_html = ""
    if isinstance(rows_list, list) and rows_list:
        cols = list(rows_list[0].keys())
        th_html = "".join(f"<th>{_esc_ltr(c)}</th>" for c in cols)
        tr_html = "".join(
            "<tr>" + "".join(f"<td>{_esc('—' if r.get(c) is None else r.get(c))}</td>" for c in cols) + "</tr>"
            for r in rows_list
        )
        breakdown_html = f"<h3>{_esc(lbl['sec_breakdown'])}</h3><table><thead><tr>{th_html}</tr></thead><tbody>{tr_html}</tbody></table>"

    assumptions_html = "<ul>" + "".join(f"<li>{_esc(a)}</li>" for a in data.assumptions) + "</ul>"
    criteria_html = "<ul>" + "".join(f"<li><strong>{_esc(c)}</strong></li>" for c in data.acceptance_criteria) + "</ul>"
    ref_rows_html = "".join(
        f"<tr><td>{_esc_ltr(r.get('source_kind'))}</td><td>{_esc(r.get('source_name'))}</td>"
        f"<td>{_esc_ltr(r.get('source_ref'))}</td><td>{_esc_ltr(r.get('publication_date') or '—')}</td>"
        f"<td><strong>{_esc_ltr(r.get('verification_label') or VERIFY_CODE_LABEL)}</strong></td></tr>"
        for r in data.references
    )
    prov_txt, outcome_txt, _, _ = _provenance_and_verdict_tokens(data)
    outcome_cls = "pass" if data.acceptance_passed else "fail"
    prov_cls = "disclaimer" if (prov_txt and prov_txt != "owner_supplied") else "prov-ok"

    html_doc = f"""<!DOCTYPE html>
<html lang="{data.language}" dir="{dir_attr}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 9.5pt; color: #0f172a; line-height: 1.4; }}
.banner {{ border: 1pt solid #1e3a5f; background-color: #f8fafc; padding: 8pt; margin-bottom: 10pt; }}
h1 {{ color: #1e3a5f; font-size: 13pt; margin: 0 0 4pt 0; }}
h2 {{ color: #1e3a5f; font-size: 11pt; margin: 10pt 0 4pt 0; border-bottom: 0.7pt solid #cbd5e1; padding-bottom: 2pt; }}
h3 {{ color: #1e3a5f; font-size: 10pt; margin: 8pt 0 3pt 0; }}
.badge {{ background-color: #1e3a5f; color: #ffffff; padding: 2pt 6pt; font-size: 8.5pt; font-weight: bold; }}
.pass {{ background-color: #15803d; color: #ffffff; padding: 2pt 6pt; font-size: 8.5pt; font-weight: bold; }}
.fail {{ background-color: #b91c1c; color: #ffffff; padding: 2pt 6pt; font-size: 8.5pt; font-weight: bold; }}
.disclaimer {{ color: #9a3412; font-weight: bold; font-size: 8.5pt; margin-top: 4pt; }}
.prov-ok {{ color: #166534; font-weight: bold; font-size: 8.5pt; margin-top: 4pt; }}
.eqbox {{ background-color: #f1f5f9; border: 0.7pt solid #cbd5e1; padding: 5pt; font-size: 8.5pt; direction: ltr; text-align: left; }}
table {{ width: 100%; border-collapse: collapse; margin: 4pt 0 8pt 0; font-size: 8.5pt; }}
th, td {{ border: 0.6pt solid #94a3b8; padding: 4pt; text-align: {align}; }}
th {{ background-color: #1e3a5f; color: #ffffff; font-weight: bold; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(data.title)} &nbsp; <span class="badge">{_esc(lbl['classification_prefix'])}: {_esc_ltr(data.classification)}</span> &nbsp; <span class="{outcome_cls}">{_esc(outcome_txt)}</span></h1>
    <div>{_esc(lbl['project'])}: {_esc_ltr('[' + data.project_code + ']')} {_esc(data.project_name)} | {_esc(lbl['discipline'])}: {_esc_ltr(data.discipline)} ({_esc_ltr(data.calculation_type)}) | {_esc(lbl['rev_ver'])}: {_esc_ltr(f'v{data.version} ({data.revision})')}</div>
    <div class="{prov_cls}">{_esc(lbl['provenance'])}: {_esc_ltr(prov_txt or '—')}</div>
    <div class="disclaimer">{_esc(lbl['disclaimer'])}</div>
  </div>
  <h2>{_esc(lbl['sec_inputs'])}</h2>
  {_kv_html(_flat_scalar_entries(data.inputs, data.units))}
  <h2>{_esc(lbl['sec_equations'])}</h2>
  <div class="eqbox">{_esc_ltr(data.equations)}</div>
  <h2>{_esc(lbl['sec_method'])}</h2>
  <p>{_esc(data.method)}</p>
  <h2>{_esc(lbl['sec_assumptions'])}</h2>
  {assumptions_html}
  <h2>{_esc(lbl['sec_results'])}</h2>
  {_kv_html(_flat_scalar_entries(data.results, data.units))}
  {breakdown_html}
  <h2>{_esc(lbl['sec_acceptance'])}</h2>
  {criteria_html}
  <h2>{_esc(lbl['sec_references'])}</h2>
  <table><thead><tr><th>{_esc(lbl['col_src_kind'])}</th><th>{_esc(lbl['col_src_name'])}</th><th>{_esc(lbl['col_src_ref'])}</th><th>{_esc(lbl['col_src_date'])}</th><th>{_esc(lbl['col_src_lbl'])}</th></tr></thead><tbody>{ref_rows_html}</tbody></table>
</body>
</html>"""

    archive = pymupdf.Archive(str(_WINDOWS_FONTS_DIR)) if has_win_tahoma else None
    story = pymupdf.Story(html=html_doc, archive=archive)
    writer = pymupdf.DocumentWriter(str(out_path))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    try:
        more = True
        guard = 0
        while more and guard < 100:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            guard += 1
    finally:
        writer.close()
