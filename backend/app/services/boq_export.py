"""Step 10 deterministic BOQ exporter: XLSX with live Excel formulas + UTF-8 CSV into 06_BOQ."""

import csv
import hashlib
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.schemas.boq import BoqChecksSummaryOut
from app.schemas.reports import ReportLanguage
from app.services.branding_exports import apply_xlsx_branding

_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_text_cell(value: str | None) -> str:
    """Neutralize leading spreadsheet formula triggers inside exported text cells in CSV."""
    text = str(value or "")
    if text and text[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + text
    return text


def _safe_xlsx_str(value: str | None) -> str:
    """Return stripped text for XLSX non-formula cells (always stored with explicit string data_type='s')."""
    return str(value or "")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_boq_xlsx(
    out_path: Path,
    *,
    title: str,
    project_code: str,
    project_name: str,
    classification: str,
    currency: str,
    revision: str,
    export_version: int,
    language: ReportLanguage,
    items: list[dict[str, Any]],
    checks: BoqChecksSummaryOut,
    include_checks_sheet: bool = True,
    omission_note: str | None = None,
) -> None:
    """Generate a versioned BOQ XLSX workbook with live row, status-subtotal, and grand-total Excel formulas."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing BOQ XLSX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = language == "ar"
    wb = Workbook()
    ws = wb.active
    ws.title = "جدول الكميات BOQ" if is_ar else "BOQ"
    ws.views.sheetView[0].rightToLeft = is_ar

    navy_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    sub_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    warn_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    ok_fill = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid")
    hdr_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    bold_font = Font(name="Calibri", size=11, bold=True)
    title_font = Font(name="Calibri", size=14, bold=True, color="1E3A5F")
    note_font = Font(name="Calibri", size=10, italic=True, color="475569")

    # Document control & scope block (rows 1-4)
    ws["A1"] = title
    ws["A1"].font = title_font
    ws.merge_cells("A1:K1")

    meta_text = (
        f"Project: [{project_code}] {project_name} | Classification: {classification} | "
        f"Currency: {currency} | {revision} (Export v{export_version})"
    )
    ws["A2"] = meta_text
    ws["A2"].font = bold_font
    ws.merge_cells("A2:K2")

    notice_text = (
        "Advisory BOQ — Unsourced unit rates are blocked; Extracted-Needs-Check rows and unconfirmed drawing units require licensed engineer & owner sign-off."
        if not is_ar
        else "جدول كميات استشاري — يُمنع تسعير أي بند بلا مصدر موثّق؛ البنود الموسومة Extracted-Needs-Check تتطلب تحققاً وموافقة هندسية."
    )
    ws["A3"] = notice_text
    ws["A3"].font = note_font
    ws.merge_cells("A3:K3")

    if omission_note:
        ws["A4"] = omission_note
        ws["A4"].font = note_font
        ws.merge_cells("A4:K4")

    headers = (
        [
            "رقم البند",
            "بيان الأعمال / الوصف",
            "الوحدة",
            "الكمية",
            f"سعر الوحدة ({currency})",
            f"الإجمالي ({currency})",
            "المرجع الفني",
            "مرجع المخطط",
            "مصدر السعر والتاريخ",
            "حالة التحقق",
            "ملاحظات",
        ]
        if is_ar
        else [
            "Item No.",
            "Description",
            "Unit",
            "Quantity",
            f"Unit Rate ({currency})",
            f"Total ({currency})",
            "Technical Reference",
            "Drawing Reference",
            "Rate Source / Date",
            "Verification Status",
            "Remarks",
        ]
    )

    header_row = 5
    for col_idx, h_label in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=h_label)
        cell.font = hdr_font
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    start_data_row = 6
    curr_row = start_data_row
    money_fmt = f'#,##0.00 "{currency}"'
    qty_fmt = "#,##0.####"

    for row_data in items:
        r = curr_row
        c_no = ws.cell(row=r, column=1, value=_safe_xlsx_str(row_data.get("item_no")))
        c_no.data_type = "s"
        c_desc = ws.cell(row=r, column=2, value=_safe_xlsx_str(row_data.get("description")))
        c_desc.data_type = "s"
        c_desc.alignment = Alignment(wrap_text=True, vertical="top")
        c_unit = ws.cell(row=r, column=3, value=_safe_xlsx_str(row_data.get("unit")))
        c_unit.data_type = "s"
        c_unit.alignment = Alignment(horizontal="center")

        c_qty = ws.cell(row=r, column=4, value=float(row_data.get("quantity") or 0.0))
        c_qty.number_format = qty_fmt

        raw_rate = row_data.get("unit_rate")
        c_rate = ws.cell(row=r, column=5, value=float(raw_rate) if raw_rate is not None else None)
        c_rate.number_format = money_fmt

        # Live Excel formula per line item so modifying D{r} or E{r} recalculates cleanly in Excel
        c_tot = ws.cell(row=r, column=6, value=f"=IF(ISNUMBER(E{r}),ROUND(D{r}*E{r},4),0)")
        c_tot.number_format = money_fmt

        c_tech = ws.cell(row=r, column=7, value=_safe_xlsx_str(row_data.get("technical_reference")))
        c_tech.data_type = "s"
        c_dwg = ws.cell(row=r, column=8, value=_safe_xlsx_str(row_data.get("drawing_reference")))
        c_dwg.data_type = "s"

        rate_src = ""
        if row_data.get("rate_source_kind"):
            kind_lbl = str(row_data.get("rate_source_kind"))
            ref_lbl = str(row_data.get("rate_source_ref") or "")
            date_lbl = str(row_data.get("rate_source_date") or "")
            rate_src = " | ".join(bit for bit in (kind_lbl, ref_lbl, date_lbl) if bit)
        c_src = ws.cell(row=r, column=9, value=rate_src)
        c_src.data_type = "s"

        ver_stat = str(row_data.get("verification_status") or "Extracted-Needs-Check")
        c_ver = ws.cell(row=r, column=10, value=ver_stat)
        c_ver.data_type = "s"
        c_ver.alignment = Alignment(horizontal="center")
        if ver_stat == "Extracted-Needs-Check":
            c_ver.fill = warn_fill
        elif ver_stat == "Extracted-Verified":
            c_ver.fill = ok_fill

        c_rem = ws.cell(row=r, column=11, value=_safe_xlsx_str(row_data.get("remarks")))
        c_rem.data_type = "s"
        c_rem.alignment = Alignment(wrap_text=True, vertical="top")
        curr_row += 1

    end_data_row = curr_row - 1
    if end_data_row < start_data_row:
        # Reserve one blank template row so live SUM/SUMIF/COUNTIF ranges stay valid on empty BOQs
        end_data_row = start_data_row
        ws.cell(row=start_data_row, column=4, value=0.0)
        ws.cell(row=start_data_row, column=6, value=f"=IF(ISNUMBER(E{start_data_row}),ROUND(D{start_data_row}*E{start_data_row},4),0)")
        curr_row = start_data_row + 1

    # Status subtotals & Grand Total with live Excel SUM / SUMIF formulas
    sub_rows = [
        ("Subtotal — Extracted-Verified", "Extracted-Verified"),
        ("Subtotal — Extracted-Needs-Check", "Extracted-Needs-Check"),
        ("Subtotal — Manual", "Manual"),
    ]
    for label_txt, status_key in sub_rows:
        r = curr_row
        ws.cell(row=r, column=2, value=label_txt).font = bold_font
        ws.cell(row=r, column=2).fill = sub_fill
        c_sub = ws.cell(
            row=r,
            column=6,
            value=f'=SUMIF(J{start_data_row}:J{end_data_row},"{status_key}",F{start_data_row}:F{end_data_row})',
        )
        c_sub.font = bold_font
        c_sub.fill = sub_fill
        c_sub.number_format = money_fmt
        curr_row += 1

    total_row = curr_row
    grand_lbl = "الإجمالي الكلي للمقايسة" if is_ar else "GRAND TOTAL"
    c_gt_lbl = ws.cell(row=total_row, column=2, value=f"{grand_lbl} ({currency})")
    c_gt_lbl.font = Font(name="Calibri", size=12, bold=True, color="1E3A5F")
    c_gt_lbl.fill = sub_fill
    c_gt_val = ws.cell(row=total_row, column=6, value=f"=SUM(F{start_data_row}:F{end_data_row})")
    c_gt_val.font = Font(name="Calibri", size=12, bold=True, color="1E3A5F")
    c_gt_val.fill = sub_fill
    c_gt_val.number_format = money_fmt

    col_widths = {
        "A": 13,
        "B": 42,
        "C": 16,
        "D": 14,
        "E": 18,
        "F": 20,
        "G": 26,
        "H": 30,
        "I": 28,
        "J": 22,
        "K": 36,
    }
    for col_letter, width in col_widths.items():
        ws.column_dimensions[col_letter].width = width

    if include_checks_sheet:
        ws_chk = wb.create_sheet(title="الفحص والتحقق Checks" if is_ar else "Checks & Flagged Items")
        ws_chk.views.sheetView[0].rightToLeft = is_ar
        boq_sheet_ref = f"'{ws.title}'"

        ws_chk["A1"] = "BOQ Quality & Arithmetic Checks Summary"
        ws_chk["A1"].font = title_font

        summary_rows = [
            ("Total Items", f"=COUNTA({boq_sheet_ref}!B{start_data_row}:B{end_data_row})"),
            (
                "Extracted-Verified Items",
                f'=COUNTIF({boq_sheet_ref}!J{start_data_row}:J{end_data_row},"Extracted-Verified")',
            ),
            (
                "Extracted-Needs-Check Items",
                f'=COUNTIF({boq_sheet_ref}!J{start_data_row}:J{end_data_row},"Extracted-Needs-Check")',
            ),
            (
                "Manual Items",
                f'=COUNTIF({boq_sheet_ref}!J{start_data_row}:J{end_data_row},"Manual")',
            ),
            ("Live Sheet Grand Total", f"={boq_sheet_ref}!F{total_row}"),
            ("High Severity Check Issues", checks.high_issues_count),
            ("Total Check Issues", checks.issues_count),
        ]
        for idx_s, (metric, formula_or_val) in enumerate(summary_rows, start=3):
            ws_chk.cell(row=idx_s, column=1, value=metric).font = bold_font
            val_cell = ws_chk.cell(row=idx_s, column=2, value=formula_or_val)
            if "Grand Total" in metric:
                val_cell.number_format = money_fmt

        chk_header_row = 12
        chk_headers = ["Issue ID", "Check Type", "Severity", "Item No.", "Message", "Recommended Action"]
        for c_i, h_txt in enumerate(chk_headers, start=1):
            hc = ws_chk.cell(row=chk_header_row, column=c_i, value=h_txt)
            hc.font = hdr_font
            hc.fill = navy_fill

        r_c = chk_header_row + 1
        for iss in checks.issues:
            ws_chk.cell(row=r_c, column=1, value=iss.issue_id)
            ws_chk.cell(row=r_c, column=2, value=iss.check_type)
            ws_chk.cell(row=r_c, column=3, value=iss.severity)
            c_ino = ws_chk.cell(row=r_c, column=4, value=_safe_xlsx_str(iss.item_no))
            c_ino.data_type = "s"
            c_msg = ws_chk.cell(row=r_c, column=5, value=_safe_xlsx_str(iss.message))
            c_msg.data_type = "s"
            c_act = ws_chk.cell(row=r_c, column=6, value=_safe_xlsx_str(iss.recommended_action))
            c_act.data_type = "s"
            r_c += 1

        r_c += 1
        ws_chk.cell(row=r_c, column=1, value="Items Flagged for Human Verification").font = bold_font
        r_c += 1
        flg_headers = ["Item No.", "Description", "Verification Status", "Reason"]
        for c_i, h_txt in enumerate(flg_headers, start=1):
            hc = ws_chk.cell(row=r_c, column=c_i, value=h_txt)
            hc.font = hdr_font
            hc.fill = navy_fill
        r_c += 1
        for flg in checks.flagged_items:
            ws_chk.cell(row=r_c, column=1, value=_safe_xlsx_str(flg.get("item_no"))).data_type = "s"
            ws_chk.cell(row=r_c, column=2, value=_safe_xlsx_str(flg.get("description"))).data_type = "s"
            ws_chk.cell(row=r_c, column=3, value=_safe_xlsx_str(flg.get("verification_status"))).data_type = "s"
            ws_chk.cell(row=r_c, column=4, value=_safe_xlsx_str(flg.get("reason"))).data_type = "s"
            r_c += 1

        for col_letter, width in {"A": 28, "B": 30, "C": 16, "D": 36, "E": 48, "F": 44}.items():
            ws_chk.column_dimensions[col_letter].width = width

    apply_xlsx_branding(
        wb,
        document_title=title,
        project_code=project_code,
        project_name=project_name,
        classification=classification,
        language=language,
    )
    wb.save(str(out_path))


def generate_boq_csv(
    out_path: Path,
    *,
    currency: str,
    items: list[dict[str, Any]],
    checks: BoqChecksSummaryOut,
) -> None:
    """Export UTF-8 (no BOM) CSV of BOQ lines and deterministic grand total."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing BOQ CSV: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Item No.",
                "Description",
                "Unit",
                "Quantity",
                f"Unit Rate ({currency})",
                f"Total ({currency})",
                "Technical Reference",
                "Drawing Reference",
                "Rate Source Kind",
                "Rate Source Ref",
                "Rate Source Date",
                "Verification Status",
                "Remarks",
            ]
        )
        for row_data in items:
            qty_val = float(row_data.get("quantity") or 0.0)
            rate_val = row_data.get("unit_rate")
            total_val = row_data.get("total")
            writer.writerow(
                [
                    _safe_text_cell(row_data.get("item_no")),
                    _safe_text_cell(row_data.get("description")),
                    _safe_text_cell(row_data.get("unit")),
                    qty_val,
                    float(rate_val) if rate_val is not None else "",
                    float(total_val) if total_val is not None else "",
                    _safe_text_cell(row_data.get("technical_reference")),
                    _safe_text_cell(row_data.get("drawing_reference")),
                    _safe_text_cell(row_data.get("rate_source_kind")),
                    _safe_text_cell(row_data.get("rate_source_ref")),
                    _safe_text_cell(row_data.get("rate_source_date")),
                    _safe_text_cell(row_data.get("verification_status")),
                    _safe_text_cell(row_data.get("remarks")),
                ]
            )
        writer.writerow(
            [
                "",
                f"GRAND TOTAL ({currency})",
                "",
                "",
                "",
                checks.grand_total,
                "",
                "",
                "",
                "",
                "",
                f"Issues={checks.issues_count} (High={checks.high_issues_count})",
                f"Flagged={len(checks.flagged_items)}",
            ]
        )
