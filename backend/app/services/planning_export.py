"""Step 16 bilingual Arabic RTL / English LTR vector PDF (with Gantt chart) & live-formula XLSX project planning exporter."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
import pymupdf

from app.schemas.planning import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NOT_PROVIDED_LABEL,
    ScheduleResultOut,
    WbsItemIn,
)
from app.schemas.reports import ReportLanguage
from app.services.calc_export import _safe_xlsx_text
from app.services.report_generator import (
    _WINDOWS_FONTS_DIR,
    _esc,
    _esc_ltr,
    _esc_rtl_cell,
)


@dataclass(frozen=True)
class ScheduleRenderData:
    """Normalized immutable Step 16 planning schedule payload rendered cleanly to PDF Gantt and XLSX."""

    project_code: str
    project_name: str
    title: str
    discipline: str
    language: ReportLanguage
    classification: str
    revision: str
    version: int
    export_version: int
    is_baseline: bool
    issued_at_iso: str
    use_ai: bool
    ai_draft_status: str
    owner_approved_by: str | None
    owner_approved_at_iso: str | None
    summary: str | None
    wbs_items: list[WbsItemIn] = field(default_factory=list)
    result: ScheduleResultOut = field(default_factory=lambda: ScheduleResultOut(
        project_start_date="",
        effective_start_date="",
        calendar_preset="libya_sun_thu",
        calendar_summary="",
        critical_path_complete=False,
    ))


_SCHED_LABELS: dict[ReportLanguage, dict[str, str]] = {
    "ar": {
        "classification_prefix": "التصنيف",
        "project": "المشروع",
        "discipline": "التخصص",
        "rev_ver": "الإصدار / المراجعة",
        "date": "تاريخ التصدير (UTC)",
        "calendar": "التقويم المعتمد (Calendar)",
        "baseline_tag": "الجدول المرجعي الأساسي (BASELINE)",
        "baseline_cmp": "مقارنة بالجدول المرجعي",
        "start_finish": "البداية الفعالة / النهاية المتوقعة",
        "critical_path": "المسار الحرج (Critical Path)",
        "ai_det": "المسار الحتمي: حساب المسار الحرج وتواريخ التقويم برمجياً (0 توكن ذكاء اصطناعي).",
        "ai_unverified": AI_UNVERIFIED_DRAFT_LABEL_AR,
        "ai_approved": "ملخص الذكاء الاصطناعي — مُعتمَد من المالك",
        "gantt_heading": "1. مخطط جانت الزمني (Gantt Chart & Critical Path)",
        "wbs_heading": "2. جدول الأنشطة وتفاصيل CPM ومقارنة المرجع والمصادر",
        "flags_heading": "3. تنبيهات المدد المفقودة والفروع المتوقفة (Blocked Branches)",
        "milestones_heading": "4. المعالم الرئيسية للمشروع (Milestones)",
        "summary_heading": "الملخص التنفيذي للجدول الزمني",
        "no_flags": "جميع الأنشطة مكتملة المدد وتم احتساب المسار الحرج بالكامل.",
        "critical_badge": "حرج",
        "blocked_badge": "متوقف — مدة غير مزودة",
    },
    "en": {
        "classification_prefix": "Classification",
        "project": "Project",
        "discipline": "Discipline",
        "rev_ver": "Version / Revision",
        "date": "Export Date (UTC)",
        "calendar": "Working Calendar",
        "baseline_tag": "LOCKED BASELINE SCHEDULE",
        "baseline_cmp": "Baseline Variance Basis",
        "start_finish": "Effective Start / Projected Finish",
        "critical_path": "Critical Path Activities",
        "ai_det": "Deterministic CPM Path: Forward/Backward pass, float & calendar dates computed in Python (0 AI tokens).",
        "ai_unverified": AI_UNVERIFIED_DRAFT_LABEL_EN,
        "ai_approved": "AI Schedule Summary — Owner Approved",
        "gantt_heading": "1. Visual Gantt Chart & Critical Path Timeline",
        "wbs_heading": "2. WBS Activity Schedule, Float, Baseline Variance & Provenance",
        "flags_heading": "3. Missing Duration ('not provided') & Blocked Branch Warnings",
        "milestones_heading": "4. Key Project Milestones",
        "summary_heading": "Schedule Executive Summary",
        "no_flags": "All activities include owner-supplied durations; critical path computed cleanly.",
        "critical_badge": "CRITICAL",
        "blocked_badge": "BLOCKED — not provided",
    },
}


def _ai_banner(data: ScheduleRenderData, lbl: dict[str, str]) -> str:
    if data.ai_draft_status == "unverified_ai_draft":
        return f"[{lbl['ai_unverified']}] — Narrative awaits Owner approval."
    if data.ai_draft_status == "owner_approved":
        return f"{lbl['ai_approved']} ({data.owner_approved_by or 'Owner'})"
    return lbl["ai_det"]


def generate_schedule_pdf(out_path: Path, data: ScheduleRenderData) -> None:
    """Render immutable bilingual Arabic RTL / English LTR vector PDF with drawn Gantt chart via PyMuPDF Story."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing schedule PDF: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    dir_attr = "rtl" if is_ar else "ltr"
    align = "right" if is_ar else "left"
    lbl = _SCHED_LABELS[data.language]
    res = data.result

    has_win_tahoma = (_WINDOWS_FONTS_DIR / "tahoma.ttf").is_file()
    if has_win_tahoma:
        bold_rule = (
            "@font-face { font-family: 'PlanFont'; src: url('tahomabd.ttf'); font-weight: bold; }"
            if (_WINDOWS_FONTS_DIR / "tahomabd.ttf").is_file()
            else ""
        )
        font_face_css = (
            "@font-face { font-family: 'PlanFont'; src: url('tahoma.ttf'); font-weight: normal; }"
            + bold_rule
        )
        font_stack = "'PlanFont', Tahoma, sans-serif"
    else:
        font_face_css = ""
        font_stack = "sans-serif"

    # Compute Gantt horizontal horizon span (at least 1 working day)
    max_ef = max([1] + [a.early_finish_wd or 0 for a in res.activities if a.early_finish_wd is not None])
    mid_wd = max_ef // 2

    gantt_rows_html = ""
    for act in res.activities:
        if act.cpm_status != "computed" or act.early_start_wd is None or act.early_finish_wd is None:
            bar_html = (
                f"<div style='background:#fef3c7;color:#92400e;border:0.5pt solid #f59e0b;"
                f"padding:2pt 4pt;font-size:6.8pt;font-weight:bold;'>"
                f"{_esc_ltr(NOT_PROVIDED_LABEL)} — {_esc(lbl['blocked_badge'])}</div>"
            )
        else:
            es = act.early_start_wd
            ef = act.early_finish_wd
            pre_pct = round((es / max_ef) * 100.0, 2)
            dur_span = max(0.5 if act.is_milestone else 1.0, float(ef - es))
            bar_pct = min(round(100.0 - pre_pct, 2), max(2.2, round((dur_span / max_ef) * 100.0, 2)))
            float_wd = act.total_float_wd or 0
            float_pct = 0.0
            if float_wd > 0 and (pre_pct + bar_pct) < 99.0:
                float_pct = min(round(100.0 - pre_pct - bar_pct, 2), round((float_wd / max_ef) * 100.0, 2))
            rem_pct = max(0.0, round(100.0 - pre_pct - bar_pct - float_pct, 2))

            if act.is_milestone:
                bar_color = "#7c3aed"
                bar_label = "◆"
            elif act.is_critical:
                bar_color = "#dc2626"
                bar_label = f"{act.duration_days}d CRIT"
            else:
                bar_color = "#2563eb"
                bar_label = f"{act.duration_days}d"

            pre_td = f"<td style='width:{pre_pct}%;border:none;padding:0;'></td>" if pre_pct > 0 else ""
            bar_td = (
                f"<td style='width:{bar_pct}%;background:{bar_color};color:#ffffff;"
                f"border:0.4pt solid #0f172a;padding:1.5pt 2pt;font-size:6.3pt;font-weight:bold;text-align:center;'>"
                f"{_esc_ltr(bar_label)}</td>"
            )
            fl_td = (
                f"<td style='width:{float_pct}%;background:#bfdbfe;border:0.4pt dashed #60a5fa;padding:0;' title='Float {float_wd}d'></td>"
                if float_pct > 0
                else ""
            )
            rem_td = f"<td style='width:{rem_pct}%;border:none;padding:0;'></td>" if rem_pct > 0 else ""
            bar_html = (
                f"<table dir='ltr' style='width:100%;table-layout:fixed;border-collapse:collapse;margin:0;'>"
                f"<tr>{pre_td}{bar_td}{fl_td}{rem_td}</tr></table>"
            )

        status_badge = ""
        if act.is_critical:
            status_badge = f"<span class='crit'>{_esc(lbl['critical_badge'])}</span>"
        elif act.cpm_status != "computed":
            status_badge = f"<span class='blk'>{_esc_ltr(NOT_PROVIDED_LABEL)}</span>"

        gantt_rows_html += (
            f"<tr>"
            f"<td style='width:7%;'>{_esc_ltr(act.activity_id)}</td>"
            f"<td style='width:22%;'>{_esc_rtl_cell(act.name, is_ar=is_ar)} {status_badge}</td>"
            f"<td style='width:9%;'>{_esc_ltr(act.display_duration + (' wd' if act.duration_days is not None else ''))}</td>"
            f"<td style='width:14%;font-size:6.8pt;'>{_esc_ltr((act.planned_start or NOT_PROVIDED_LABEL) + ' -> ' + (act.planned_finish or NOT_PROVIDED_LABEL))}</td>"
            f"<td style='width:48%;padding:2pt 3pt;background:#f8fafc;'>{bar_html}</td>"
            f"</tr>"
        )

    detail_rows_html = ""
    for act in res.activities:
        pred_str = ", ".join(
            f"{d.predecessor_id}({d.dep_type}{'+' + str(d.lag_days) if d.lag_days > 0 else (str(d.lag_days) if d.lag_days < 0 else '')})"
            for d in act.predecessors
        ) or "—"
        qty_str = f"{act.quantity:g} {act.unit}".strip() if act.quantity is not None else "—"
        es_ef = f"{act.early_start_wd} / {act.early_finish_wd}" if act.early_start_wd is not None else NOT_PROVIDED_LABEL
        ls_lf = f"{act.late_start_wd} / {act.late_finish_wd}" if act.late_start_wd is not None else "blocked"
        tf_txt = f"{act.total_float_wd} wd" if act.total_float_wd is not None else "blocked"
        b_var = (
            f"{act.finish_variance_wd:+d} wd ({act.variance_status})"
            if act.finish_variance_wd is not None
            else act.variance_status
        )
        row_cls = " class='critrow'" if act.is_critical else (" class='warnrow'" if act.cpm_status != "computed" else "")
        detail_rows_html += (
            f"<tr{row_cls}>"
            f"<td>{_esc_ltr(act.activity_id)}</td>"
            f"<td>{_esc_ltr(act.wbs_code)}</td>"
            f"<td>{_esc_rtl_cell(act.name, is_ar=is_ar)}</td>"
            f"<td>{_esc_ltr(act.display_duration)}</td>"
            f"<td>{_esc_ltr(qty_str)}</td>"
            f"<td>{_esc_ltr(pred_str)}</td>"
            f"<td>{_esc_ltr(es_ef)}</td>"
            f"<td>{_esc_ltr(ls_lf)}</td>"
            f"<td>{_esc_ltr(tf_txt)}</td>"
            f"<td>{_esc_ltr((act.planned_start or NOT_PROVIDED_LABEL) + ' -> ' + (act.planned_finish or NOT_PROVIDED_LABEL))}</td>"
            f"<td>{_esc_ltr(b_var)}</td>"
            f"<td>[{_esc_ltr(act.source_kind)}] {_esc_rtl_cell(act.source_ref, is_ar=is_ar)}</td>"
            f"</tr>"
        )

    flags_list = list(res.missing_duration_flags) + list(res.blocked_branch_flags)
    flags_html = (
        f"<p>{_esc(lbl['no_flags'])}</p>"
        if not flags_list
        else "<ul>" + "".join(f"<li class='badtxt'>{_esc(fl)}</li>" for fl in flags_list) + "</ul>"
    )
    milestone_html = (
        "<ul>"
        + "".join(
            f"<li><strong>{_esc_ltr(m['activity_id'])}</strong> — {_esc(m['name'])}: {_esc_ltr(m['target_date'])} "
            f"{'(CRITICAL)' if m.get('is_critical') else ''}</li>"
            for m in res.milestone_summary
        )
        + "</ul>"
        if res.milestone_summary
        else f"<p>{_esc_ltr('—')}</p>"
    )
    summary_html = f"<h2>{_esc(lbl['summary_heading'])}</h2><p>{_esc(data.summary)}</p>" if data.summary else ""
    base_badge = f" &nbsp; <span class='base'>{_esc(lbl['baseline_tag'])}</span>" if data.is_baseline else ""
    base_cmp_line = (
        f"<div>{_esc(lbl['baseline_cmp'])}: {_esc(res.baseline_title or res.baseline_schedule_id or '')} | "
        f"Project Finish Variance: {_esc_ltr(f'{res.project_finish_variance_wd:+d} wd' if res.project_finish_variance_wd is not None else 'blocked')}</div>"
        if res.baseline_schedule_id
        else ""
    )

    html_doc = f"""<!DOCTYPE html>
<html dir="{dir_attr}">
<head>
<meta charset="utf-8" />
<style>
{font_face_css}
body {{ font-family: {font_stack}; direction: {dir_attr}; text-align: {align}; font-size: 8.2pt; color: #0f172a; margin: 0; }}
.banner {{ border-bottom: 2px solid #1e3a5f; padding-bottom: 5pt; margin-bottom: 7pt; }}
h1 {{ color: #1e3a5f; font-size: 12.5pt; margin: 0 0 3pt 0; }}
h2 {{ color: #1e3a5f; font-size: 10pt; margin: 8pt 0 3pt 0; }}
.badge {{ background-color: #1e3a5f; color: #ffffff; padding: 1pt 4pt; font-size: 7.5pt; font-weight: bold; }}
.base {{ background-color: #15803d; color: #ffffff; padding: 1pt 4pt; font-size: 7.5pt; font-weight: bold; }}
.crit {{ background-color: #dc2626; color: #ffffff; padding: 0.5pt 3pt; font-size: 6.5pt; font-weight: bold; }}
.blk {{ background-color: #f59e0b; color: #0f172a; padding: 0.5pt 3pt; font-size: 6.5pt; font-weight: bold; }}
table {{ width: 100%; border-collapse: collapse; margin: 3pt 0 7pt 0; font-size: 7.4pt; }}
th, td {{ border: 0.5pt solid #94a3b8; padding: 3pt; text-align: {align}; vertical-align: middle; }}
th {{ background-color: #1e3a5f; color: #ffffff; font-weight: bold; }}
tr.critrow td {{ background-color: #fef2f2; }}
tr.warnrow td {{ background-color: #fffbeb; }}
.badtxt {{ color: #b91c1c; font-weight: bold; }}
</style>
</head>
<body>
  <div class="banner">
    <h1>{_esc(data.title)} &nbsp; <span class="badge">{_esc(lbl['classification_prefix'])}: {_esc_ltr(data.classification)}</span>{base_badge}</h1>
    <div>{_esc(lbl['project'])}: {_esc_ltr('[' + data.project_code + ']')} {_esc(data.project_name)} | {_esc(lbl['discipline'])}: {_esc_ltr(data.discipline)} | {_esc(lbl['rev_ver'])}: {_esc_ltr(f'v{data.version} (Export v{data.export_version}, {data.revision})')}</div>
    <div>{_esc(lbl['calendar'])}: {_esc_ltr(res.calendar_summary)}</div>
    <div>{_esc(lbl['start_finish'])}: {_esc_ltr(res.effective_start_date)} -> {_esc_ltr(res.project_finish_date or NOT_PROVIDED_LABEL)} ({_esc_ltr(f'{res.total_duration_wd} wd' if res.total_duration_wd is not None else NOT_PROVIDED_LABEL)})</div>
    <div>{_esc(lbl['critical_path'])}: {_esc_ltr(', '.join(res.critical_path_ids) if res.critical_path_ids else 'BLOCKED / NONE')}</div>
    {base_cmp_line}
    <div>{_esc(_ai_banner(data, lbl))}</div>
  </div>
  {summary_html}
  <h2>{_esc(lbl['gantt_heading'])}</h2>
  <table>
    <thead>
      <tr>
        <th style="width:7%;">ID</th>
        <th style="width:22%;">Activity</th>
        <th style="width:9%;">Dur</th>
        <th style="width:14%;">Dates</th>
        <th style="width:48%;">Timeline (Day {_esc_ltr('0')} .. Day {_esc_ltr(str(mid_wd))} .. Day {_esc_ltr(str(max_ef))} wd | Red=Critical, Blue=Float Bar, Purple=Milestone)</th>
      </tr>
    </thead>
    <tbody>{gantt_rows_html}</tbody>
  </table>
  <h2>{_esc(lbl['wbs_heading'])}</h2>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>WBS</th><th>Activity</th><th>Dur (wd)</th><th>Qty</th><th>Pred (FS)</th>
        <th>ES/EF</th><th>LS/LF</th><th>Float</th><th>Start -> Finish</th><th>Base Var</th><th>Source Ref</th>
      </tr>
    </thead>
    <tbody>{detail_rows_html}</tbody>
  </table>
  <h2>{_esc(lbl['flags_heading'])}</h2>
  {flags_html}
  <h2>{_esc(lbl['milestones_heading'])}</h2>
  {milestone_html}
</body>
</html>"""

    archive = pymupdf.Archive(str(_WINDOWS_FONTS_DIR)) if has_win_tahoma else None
    story = pymupdf.Story(html=html_doc, archive=archive)
    writer = pymupdf.DocumentWriter(str(out_path))
    mediabox = pymupdf.Rect(0, 0, 842, 595)  # A4 Landscape
    where = mediabox + (26, 26, -26, -26)
    try:
        more = True
        guard = 0
        while more and guard < 120:
            dev = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(dev)
            writer.end_page()
            guard += 1
    finally:
        writer.close()


def generate_schedule_xlsx(out_path: Path, data: ScheduleRenderData) -> None:
    """Export immutable bilingual live-formula XLSX workbook (CPM Schedule, WBS & Baseline, Provenance)."""
    if out_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing schedule XLSX: {out_path.name}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    is_ar = data.language == "ar"
    res = data.result
    wb = Workbook()
    ws = wb.active
    ws.title = "الجدول والمسار الحرج" if is_ar else "Schedule & CPM"
    ws.views.sheetView[0].rightToLeft = is_ar

    navy_fill = PatternFill("solid", fgColor="1E3A5F")
    crit_fill = PatternFill("solid", fgColor="FEE2E2")
    warn_fill = PatternFill("solid", fgColor="FEF3C7")
    sub_fill = PatternFill("solid", fgColor="E2E8F0")
    hdr_font = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    bold_font = Font(name="Tahoma", size=10, bold=True)
    reg_font = Font(name="Tahoma", size=10)
    align = Alignment(horizontal="right" if is_ar else "left", vertical="center", wrap_text=True)

    meta = [
        ("Project", f"[{data.project_code}] {data.project_name}"),
        ("Title", data.title),
        ("Classification", f"{data.classification} | v{data.version} ({data.revision})"),
        ("Calendar Basis", res.calendar_summary),
        ("Effective Start -> Finish", f"{res.effective_start_date} -> {res.project_finish_date or NOT_PROVIDED_LABEL}"),
        ("Critical Path IDs", ", ".join(res.critical_path_ids) if res.critical_path_ids else "BLOCKED"),
        ("Exported UTC", data.issued_at_iso),
    ]
    for r_i, (k, v) in enumerate(meta, start=1):
        c1 = ws.cell(row=r_i, column=1, value=_safe_xlsx_text(k))
        c2 = ws.cell(row=r_i, column=2, value=_safe_xlsx_text(v))
        c1.font = bold_font
        c2.font = reg_font
        c1.alignment = align
        c2.alignment = align

    hdr_row = 9
    headers = [
        "Activity ID",
        "WBS Code",
        "Activity Name",
        "Milestone?",
        "Duration (wd)",
        "Predecessors (FS+lag)",
        "Early Start (wd)",
        "Early Finish (wd)",
        "Late Start (wd)",
        "Late Finish (wd)",
        "Total Float (wd)",
        "Critical Path?",
        "Planned Start",
        "Planned Finish",
        "Baseline EF (wd)",
        "Finish Variance (wd)",
    ]
    for col_i, h_txt in enumerate(headers, start=1):
        c = ws.cell(row=hdr_row, column=col_i, value=_safe_xlsx_text(h_txt))
        c.fill = navy_fill
        c.font = hdr_font
        c.alignment = align

    first_row = hdr_row + 1
    row = first_row
    for act in res.activities:
        pred_txt = ", ".join(
            f"{d.predecessor_id}({d.dep_type}{'+' + str(d.lag_days) if d.lag_days > 0 else (str(d.lag_days) if d.lag_days < 0 else '')})"
            for d in act.predecessors
        ) or "—"
        ws.cell(row=row, column=1, value=_safe_xlsx_text(act.activity_id)).font = reg_font
        ws.cell(row=row, column=2, value=_safe_xlsx_text(act.wbs_code)).font = reg_font
        ws.cell(row=row, column=3, value=_safe_xlsx_text(act.name)).font = bold_font if act.is_critical else reg_font
        ws.cell(row=row, column=4, value="YES" if act.is_milestone else "NO").font = reg_font
        dur_cell = ws.cell(row=row, column=5, value=act.duration_days if act.duration_days is not None else NOT_PROVIDED_LABEL)
        if act.duration_days is None:
            dur_cell.fill = warn_fill
        ws.cell(row=row, column=6, value=_safe_xlsx_text(pred_txt)).font = reg_font
        ws.cell(row=row, column=7, value=act.early_start_wd if act.early_start_wd is not None else "blocked").font = reg_font
        ws.cell(row=row, column=8, value=f'=IF(AND(ISNUMBER(E{row}),ISNUMBER(G{row})),G{row}+E{row},"not provided")')
        ws.cell(row=row, column=9, value=act.late_start_wd if act.late_start_wd is not None else "blocked").font = reg_font
        ws.cell(row=row, column=10, value=f'=IF(AND(ISNUMBER(E{row}),ISNUMBER(I{row})),I{row}+E{row},"blocked")')
        ws.cell(row=row, column=11, value=f'=IF(AND(ISNUMBER(I{row}),ISNUMBER(G{row})),I{row}-G{row},"blocked")')
        c_crit = ws.cell(row=row, column=12, value=f'=IF(ISNUMBER(K{row}),IF(K{row}=0,"CRITICAL","No"),"BLOCKED")')
        if act.is_critical:
            c_crit.fill = crit_fill
            c_crit.font = bold_font
        elif act.cpm_status != "computed":
            c_crit.fill = warn_fill
        ws.cell(row=row, column=13, value=_safe_xlsx_text(act.planned_start or NOT_PROVIDED_LABEL)).font = reg_font
        ws.cell(row=row, column=14, value=_safe_xlsx_text(act.planned_finish or NOT_PROVIDED_LABEL)).font = reg_font

        # Baseline Early Finish = ES_var check anchor if baseline present
        b_ef = None
        if act.baseline_start and act.finish_variance_wd is not None and act.early_finish_wd is not None:
            b_ef = act.early_finish_wd - act.finish_variance_wd
        ws.cell(row=row, column=15, value=b_ef if b_ef is not None else "—")
        ws.cell(row=row, column=16, value=f'=IF(AND(ISNUMBER(H{row}),ISNUMBER(O{row})),H{row}-O{row},"—")')
        row += 1

    last_row = row - 1
    tot_row = row
    ws.cell(row=tot_row, column=1, value="TOTAL").font = bold_font
    ws.cell(row=tot_row, column=3, value="Project Schedule Summary").font = bold_font
    ws.cell(
        row=tot_row,
        column=8,
        value=f'=IF(COUNTIF(L{first_row}:L{last_row},"BLOCKED")>0,"BLOCKED",MAX(H{first_row}:H{last_row}))',
    ).font = bold_font
    ws.cell(row=tot_row, column=12, value=f'=COUNTIF(L{first_row}:L{last_row},"CRITICAL")').font = bold_font
    for col_i in range(1, len(headers) + 1):
        ws.cell(row=tot_row, column=col_i).fill = sub_fill
        ws.column_dimensions[get_column_letter(col_i)].width = 30 if col_i == 3 else 17

    # Sheet 2: WBS Tree & Provenance
    ws2 = wb.create_sheet(title="الهيكل والمصادر" if is_ar else "WBS & Provenance")
    ws2.views.sheetView[0].rightToLeft = is_ar
    wbs_hdrs = [
        "WBS Code", "WBS Title", "Parent Code", "Discipline",
        "Activity ID", "Activity", "Quantity", "Unit", "Source Kind", "Source Reference",
        "BOQ Item ID", "Spec ID", "Calc ID", "Research Source ID", "CPM Block Reason",
    ]
    wbs_map = {w.wbs_code: w for w in data.wbs_items}
    for col_i, h_txt in enumerate(wbs_hdrs, start=1):
        c = ws2.cell(row=1, column=col_i, value=_safe_xlsx_text(h_txt))
        c.fill = navy_fill
        c.font = hdr_font
    r2 = 2
    for act in res.activities:
        w = wbs_map.get(act.wbs_code)
        vals = [
            act.wbs_code,
            w.title if w else "—",
            (w.parent_code or "—") if w else "—",
            w.discipline if w else "—",
            act.activity_id,
            act.name,
            act.quantity if act.quantity is not None else "",
            act.unit,
            act.source_kind,
            act.source_ref,
            act.boq_item_id or "",
            act.specification_id or "",
            act.calculation_id or "",
            act.research_source_id or "",
            act.branch_block_reason or "",
        ]
        for col_i, v in enumerate(vals, start=1):
            ws2.cell(row=r2, column=col_i, value=_safe_xlsx_text(v)).font = reg_font
        r2 += 1
    for col_i in range(1, len(wbs_hdrs) + 1):
        ws2.column_dimensions[get_column_letter(col_i)].width = 28 if col_i in {2, 6, 10, 15} else 16

    wb.save(str(out_path))
