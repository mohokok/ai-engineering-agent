"""Step 16 deterministic WBS, CPM forward/backward pass, Libya working-day calendar, baseline variance & optional Gemini narrative."""

from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
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
from app.schemas.planning import (
    AI_UNVERIFIED_DRAFT_LABEL_AR,
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    ActivityDependencyIn,
    EvaluatedActivityOut,
    NOT_PROVIDED_LABEL,
    PlanningPresetOut,
    ScheduleActivityIn,
    ScheduleResultOut,
    WbsItemIn,
    WorkCalendarIn,
)
from app.schemas.reports import ReportLanguage
from app.services.provider_settings import _load_provider_config, _summarize_usage, execute_provider_request
from app.services.research import estimate_prompt_tokens

_URL_RE = re.compile(r"(?:https?://|project-file://)[^\s,;\"')>\]]+", re.IGNORECASE)
_UNGROUNDED_STD_RE = re.compile(
    r"\b(?:ASTM|ACI|BS|EN|IEC|IEEE|ISO|ASHRAE|NFPA|ASME|ANSI|SBC|LBC)\s*[A-Z]?\s*\d[\w./-]*\b",
    re.IGNORECASE,
)

# Python weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
_PRESET_WEEKENDS: dict[str, tuple[list[int], str]] = {
    "libya_sun_thu": ([4, 5], "Libya Sun–Thu Workweek (Weekend: Fri & Sat)"),
    "mon_fri": ([5, 6], "Standard Mon–Fri Workweek (Weekend: Sat & Sun)"),
    "six_day_sat_thu": ([4], "6-Day Site Workweek Sat–Thu (Weekend: Fri only)"),
}

_DAY_NAMES = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


class PlanningInputError(ValueError):
    """Raised when WBS hierarchy, dependency graph, working calendar, or durations violate CPM rules."""


@dataclass
class ResolvedCalendar:
    start_date: date
    weekend_days: list[int]
    holidays: list[str]
    holiday_dates: set[date]
    preset: str
    summary: str
    workdays: list[date]

    def effective_start(self) -> str:
        return self.workdays[0].isoformat()

    def date_start(self, es_wd: int) -> str:
        return self.workdays[es_wd].isoformat()

    def date_finish(self, es_wd: int, ef_wd: int, is_milestone: bool) -> str:
        if is_milestone or ef_wd <= es_wd:
            return self.workdays[0].isoformat() if es_wd == 0 else self.workdays[es_wd - 1].isoformat()
        return self.workdays[ef_wd - 1].isoformat()


def resolve_working_calendar(
    *,
    start_date_str: str,
    calendar: WorkCalendarIn,
    horizon_working_days: int = 4000,
) -> ResolvedCalendar:
    """Resolve owner-selected weekend days & explicit holidays (never inventing unverified holidays)."""
    try:
        raw_start = date.fromisoformat(start_date_str.strip())
    except ValueError as exc:
        raise PlanningInputError(f"Invalid schedule start_date '{start_date_str}': expected YYYY-MM-DD.") from exc

    if calendar.preset == "custom":
        if calendar.weekend_days is None:
            raise PlanningInputError("Custom calendar requires explicit weekend_days list (0=Mon..6=Sun).")
        weekend_list = sorted(set(calendar.weekend_days))
        label = (
            "Custom Owner Calendar (Weekend: "
            + (", ".join(_DAY_NAMES[d] for d in weekend_list) if weekend_list else "None (7 days)")
            + ")"
        )
    else:
        default_wknd, label = _PRESET_WEEKENDS[calendar.preset]
        weekend_list = sorted(set(calendar.weekend_days if calendar.weekend_days is not None else default_wknd))

    if any(d < 0 or d > 6 for d in weekend_list):
        raise PlanningInputError(f"Invalid weekday index in weekend_days {weekend_list}: must be 0..6.")
    if len(weekend_list) >= 7:
        raise PlanningInputError("Calendar cannot mark all 7 days of the week as non-working weekends.")

    holiday_dates: set[date] = set()
    holiday_strs: list[str] = []
    for raw_h in calendar.holidays:
        tok = str(raw_h or "").strip()
        if not tok:
            continue
        try:
            hd = date.fromisoformat(tok)
        except ValueError as exc:
            raise PlanningInputError(f"Invalid holiday date '{tok}': expected YYYY-MM-DD.") from exc
        if hd not in holiday_dates:
            holiday_dates.add(hd)
            holiday_strs.append(hd.isoformat())
    holiday_strs.sort()

    weekend_set = set(weekend_list)
    workdays: list[date] = []
    cur = raw_start
    guard = 0
    while len(workdays) <= horizon_working_days and guard < 20000:
        if cur.weekday() not in weekend_set and cur not in holiday_dates:
            workdays.append(cur)
        cur += timedelta(days=1)
        guard += 1
    if len(workdays) <= 1:
        raise PlanningInputError("Unable to construct working-day lookup from calendar configuration.")

    hol_note = f"{len(holiday_strs)} owner-supplied holiday(s)" if holiday_strs else "0 owner-supplied holidays"
    summary = f"{label} | {calendar.hours_per_day:g} h/day | {hol_note}"
    return ResolvedCalendar(
        start_date=raw_start,
        weekend_days=weekend_list,
        holidays=holiday_strs,
        holiday_dates=holiday_dates,
        preset=calendar.preset,
        summary=summary,
        workdays=workdays,
    )


def _detect_graph_issues(
    *,
    wbs_items: list[WbsItemIn],
    activities: list[ScheduleActivityIn],
) -> tuple[list[str], list[str], list[str], dict[str, list[ActivityDependencyIn]], dict[str, list[str]], list[str]]:
    """Inspect WBS/activity graph returning (dup_errs, orphan_flags, cycle_nodes, preds_map, succs_map, topo_order)."""
    dup_errs: list[str] = []
    wbs_codes: set[str] = set()
    parent_by_wbs: dict[str, str | None] = {}
    for w in wbs_items:
        if w.wbs_code in wbs_codes:
            dup_errs.append(f"Duplicate wbs_code '{w.wbs_code}'.")
        wbs_codes.add(w.wbs_code)
        parent_by_wbs[w.wbs_code] = w.parent_code

    orphan_flags: list[str] = []
    for w in wbs_items:
        if w.parent_code and w.parent_code not in wbs_codes:
            orphan_flags.append(f"WBS '{w.wbs_code}' references missing parent_code '{w.parent_code}'.")
        # Detect WBS parent self/cycle chain
        seen_w: set[str] = set()
        cur: str | None = w.wbs_code
        while cur and cur in parent_by_wbs:
            if cur in seen_w:
                orphan_flags.append(f"WBS parent hierarchy contains cycle at '{cur}'.")
                break
            seen_w.add(cur)
            cur = parent_by_wbs.get(cur)

    act_by_id: dict[str, ScheduleActivityIn] = {}
    for a in activities:
        if a.activity_id in act_by_id:
            dup_errs.append(f"Duplicate activity_id '{a.activity_id}'.")
        act_by_id[a.activity_id] = a
        if a.wbs_code not in wbs_codes:
            orphan_flags.append(f"Orphan activity '{a.activity_id}' ('{a.name}') references missing WBS '{a.wbs_code}'.")

    preds_map: dict[str, list[ActivityDependencyIn]] = {a.activity_id: [] for a in activities}
    succs_map: dict[str, list[str]] = {a.activity_id: [] for a in activities}
    in_deg: dict[str, int] = {a.activity_id: 0 for a in activities}

    for a in activities:
        seen_p: set[str] = set()
        for dep in a.predecessors:
            if dep.predecessor_id not in act_by_id:
                orphan_flags.append(
                    f"Activity '{a.activity_id}' references missing predecessor '{dep.predecessor_id}'."
                )
                continue
            if dep.predecessor_id == a.activity_id:
                orphan_flags.append(f"Activity '{a.activity_id}' cannot depend on itself.")
                continue
            if dep.predecessor_id in seen_p:
                continue
            seen_p.add(dep.predecessor_id)
            preds_map[a.activity_id].append(dep)
            succs_map[dep.predecessor_id].append(a.activity_id)
            in_deg[a.activity_id] += 1

    # Kahn topological sort
    q: deque[str] = deque([aid for aid, deg in in_deg.items() if deg == 0])
    topo_order: list[str] = []
    while q:
        u = q.popleft()
        topo_order.append(u)
        for v in succs_map[u]:
            in_deg[v] -= 1
            if in_deg[v] == 0:
                q.append(v)

    cycle_nodes = [aid for aid in act_by_id if aid not in set(topo_order)]
    return dup_errs, orphan_flags, cycle_nodes, preds_map, succs_map, topo_order


def _weakly_connected_components(
    activity_ids: list[str],
    preds_map: dict[str, list[ActivityDependencyIn]],
    succs_map: dict[str, list[str]],
) -> list[list[str]]:
    visited: set[str] = set()
    components: list[list[str]] = []
    for aid in activity_ids:
        if aid in visited:
            continue
        comp: list[str] = []
        queue: deque[str] = deque([aid])
        visited.add(aid)
        while queue:
            u = queue.popleft()
            comp.append(u)
            neighbors = [d.predecessor_id for d in preds_map.get(u, [])] + list(succs_map.get(u, []))
            for nb in neighbors:
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        components.append(comp)
    return components


def evaluate_project_schedule(
    *,
    start_date: str,
    calendar: WorkCalendarIn,
    wbs_items: list[WbsItemIn],
    activities: list[ScheduleActivityIn],
    baseline_result: ScheduleResultOut | None = None,
    baseline_schedule_id: str | None = None,
    baseline_title: str | None = None,
    strict: bool = True,
) -> ScheduleResultOut:
    """Deterministically evaluate WBS, CPM forward/backward pass, float, working-calendar dates, missing-duration blocks, and baseline variance."""
    if not wbs_items:
        raise PlanningInputError("At least one WBS element is required.")
    if not activities:
        raise PlanningInputError("At least one activity or milestone is required.")

    cal = resolve_working_calendar(start_date_str=start_date, calendar=calendar)

    # Validate milestone/non-milestone durations cleanly
    for a in activities:
        if a.is_milestone:
            if a.duration_days not in (None, 0):
                if strict:
                    raise PlanningInputError(
                        f"Milestone '{a.activity_id}' must have duration_days=0 (got {a.duration_days})."
                    )
        else:
            if a.duration_days == 0 and strict:
                raise PlanningInputError(
                    f"Non-milestone activity '{a.activity_id}' cannot have duration 0; pass None for 'not provided' or set is_milestone=True."
                )

    dup_errs, orphan_flags, cycle_nodes, preds_map, succs_map, topo_order = _detect_graph_issues(
        wbs_items=wbs_items,
        activities=activities,
    )
    if strict:
        if dup_errs:
            raise PlanningInputError("; ".join(dup_errs))
        if orphan_flags:
            raise PlanningInputError("; ".join(orphan_flags))
        if cycle_nodes:
            raise PlanningInputError(
                f"Dependency cycle detected involving activities: {', '.join(cycle_nodes)}."
            )

    act_by_id = {a.activity_id: a for a in activities}
    missing_duration_flags: list[str] = []
    blocked_branch_flags: list[str] = []

    # Effective durations (milestones with None/0 -> 0; non-milestones with None -> None = 'not provided')
    eff_dur: dict[str, int | None] = {}
    for a in activities:
        if a.is_milestone:
            eff_dur[a.activity_id] = 0 if a.duration_days in (None, 0) else a.duration_days
        else:
            eff_dur[a.activity_id] = a.duration_days
            if a.duration_days is None:
                missing_duration_flags.append(
                    f"{a.activity_id} ({a.name}): duration is '{NOT_PROVIDED_LABEL}'"
                )

    # Forward Pass across topological order
    es_map: dict[str, int | None] = {a.activity_id: None for a in activities}
    ef_map: dict[str, int | None] = {a.activity_id: None for a in activities}
    ls_map: dict[str, int | None] = {a.activity_id: None for a in activities}
    lf_map: dict[str, int | None] = {a.activity_id: None for a in activities}
    float_map: dict[str, int | None] = {a.activity_id: None for a in activities}
    critical_set: set[str] = set()
    cpm_status_map: dict[str, str] = {a.activity_id: "computed" for a in activities}
    block_reason_map: dict[str, str | None] = {a.activity_id: None for a in activities}

    for aid in topo_order:
        preds = preds_map.get(aid, [])
        blocked_pred = next((d.predecessor_id for d in preds if ef_map.get(d.predecessor_id) is None), None)
        if blocked_pred is not None:
            cpm_status_map[aid] = "blocked_missing_duration"
            block_reason_map[aid] = (
                f"Blocked downstream of '{blocked_pred}' whose duration or predecessor chain is '{NOT_PROVIDED_LABEL}'."
            )
            continue
        es_val = 0
        if preds:
            cand_starts = [(ef_map[d.predecessor_id] or 0) + d.lag_days for d in preds]
            es_val = max(0, max(cand_starts))
        dur = eff_dur[aid]
        if dur is None:
            cpm_status_map[aid] = "blocked_missing_duration"
            block_reason_map[aid] = (
                f"Duration not supplied by owner ('{NOT_PROVIDED_LABEL}'); critical-path computation blocked for this branch."
            )
            continue
        es_map[aid] = es_val
        ef_map[aid] = es_val + dur

    # Backward Pass per weakly-connected branch component:
    # Any component with a cycle OR containing ANY node whose duration/EF is missing blocks critical-path computation on that branch!
    components = _weakly_connected_components([a.activity_id for a in activities], preds_map, succs_map)
    topo_pos = {aid: i for i, aid in enumerate(topo_order)}
    comp_max_finish: list[int] = []
    all_branches_complete = not cycle_nodes and len(missing_duration_flags) == 0

    for comp in components:
        comp_set = set(comp)
        comp_missing = [aid for aid in comp if eff_dur[aid] is None]
        comp_cycle = [aid for aid in comp if aid in set(cycle_nodes)]
        if comp_missing or comp_cycle:
            reasons: list[str] = []
            if comp_missing:
                reasons.append(f"missing duration ('{NOT_PROVIDED_LABEL}') on {', '.join(sorted(comp_missing))}")
            if comp_cycle:
                reasons.append(f"dependency cycle involving {', '.join(sorted(comp_cycle))}")
            msg = (
                f"Critical path blocked for branch [{', '.join(sorted(comp))}]: "
                + "; ".join(reasons)
                + "."
            )
            blocked_branch_flags.append(msg)
            for aid in comp:
                cpm_status_map[aid] = "blocked_missing_duration"
                if block_reason_map[aid] is None:
                    block_reason_map[aid] = msg
            continue

        # Complete branch component -> compute exact Backward Pass & Total Float!
        pf = max(ef_map[aid] or 0 for aid in comp)
        comp_max_finish.append(pf)
        comp_topo_rev = sorted([aid for aid in comp if aid in topo_pos], key=lambda x: topo_pos[x], reverse=True)
        for aid in comp_topo_rev:
            succs_in_comp = [s for s in succs_map.get(aid, []) if s in comp_set]
            if not succs_in_comp:
                lf_val = pf
            else:
                # For every outgoing edge aid -> s with lag_days, LF(aid) <= LS(s) - lag
                cand_finishes: list[int] = []
                for s in succs_in_comp:
                    dep_obj = next(d for d in preds_map[s] if d.predecessor_id == aid)
                    cand_finishes.append((ls_map[s] if ls_map[s] is not None else pf) - dep_obj.lag_days)
                lf_val = min(cand_finishes)
            dur = eff_dur[aid] or 0
            ls_val = lf_val - dur
            es_val = es_map[aid] or 0
            tf_val = ls_val - es_val
            lf_map[aid] = lf_val
            ls_map[aid] = ls_val
            float_map[aid] = tf_val
            if tf_val == 0:
                critical_set.add(aid)

    # Ensure workdays lookup covers the maximum finish day safely
    max_wd_needed = max(
        [0]
        + [v for v in ef_map.values() if v is not None]
        + [v for v in lf_map.values() if v is not None]
    )
    if max_wd_needed >= len(cal.workdays):
        cal = resolve_working_calendar(
            start_date_str=start_date,
            calendar=calendar,
            horizon_working_days=max_wd_needed + 100,
        )

    # Baseline comparison map
    base_by_id: dict[str, EvaluatedActivityOut] = {}
    base_notes: list[str] = []
    if baseline_result is not None:
        base_by_id = {ba.activity_id: ba for ba in baseline_result.activities}

    evaluated_activities: list[EvaluatedActivityOut] = []
    milestones: list[dict[str, Any]] = []

    for a in activities:
        aid = a.activity_id
        es = es_map[aid]
        ef = ef_map[aid]
        ls = ls_map[aid]
        lf = lf_map[aid]
        tf = float_map[aid]

        p_finish = cal.date_finish(es, ef, a.is_milestone) if (es is not None and ef is not None) else None
        p_start = p_finish if a.is_milestone else (cal.date_start(es) if es is not None else None)
        l_finish = cal.date_finish(ls, lf, a.is_milestone) if (ls is not None and lf is not None) else None
        l_start = l_finish if a.is_milestone else (cal.date_start(ls) if ls is not None else None)

        disp_dur = str(eff_dur[aid]) if eff_dur[aid] is not None else NOT_PROVIDED_LABEL

        b_dur = None
        b_start = None
        b_finish = None
        s_var = None
        f_var = None
        fl_var = None
        v_status = "no_baseline"
        if baseline_result is not None:
            b_act = base_by_id.get(aid)
            if b_act is None:
                v_status = "added_in_current"
            else:
                b_dur = b_act.duration_days
                b_start = b_act.planned_start
                b_finish = b_act.planned_finish
                if es is not None and b_act.early_start_wd is not None:
                    s_var = es - b_act.early_start_wd
                if ef is not None and b_act.early_finish_wd is not None:
                    f_var = ef - b_act.early_finish_wd
                if tf is not None and b_act.total_float_wd is not None:
                    fl_var = tf - b_act.total_float_wd
                if cpm_status_map[aid] != "computed" or b_act.cpm_status != "computed":
                    v_status = "blocked"
                elif f_var is None:
                    v_status = "blocked"
                elif f_var > 0:
                    v_status = "delayed"
                elif f_var < 0:
                    v_status = "ahead"
                else:
                    v_status = "on_baseline"

        ev_out = EvaluatedActivityOut(
            activity_id=aid,
            wbs_code=a.wbs_code,
            name=a.name,
            is_milestone=a.is_milestone,
            duration_days=eff_dur[aid],
            display_duration=disp_dur,
            quantity=a.quantity,
            unit=(a.unit or "").strip(),
            predecessors=a.predecessors,
            early_start_wd=es,
            early_finish_wd=ef,
            late_start_wd=ls,
            late_finish_wd=lf,
            total_float_wd=tf,
            planned_start=p_start,
            planned_finish=p_finish,
            late_start_date=l_start,
            late_finish_date=l_finish,
            is_critical=(aid in critical_set),
            cpm_status=cpm_status_map[aid],
            branch_block_reason=block_reason_map[aid],
            baseline_duration_days=b_dur,
            baseline_start=b_start,
            baseline_finish=b_finish,
            start_variance_wd=s_var,
            finish_variance_wd=f_var,
            float_variance_wd=fl_var,
            variance_status=v_status,
            source_kind=a.source_kind,
            source_ref=a.source_ref,
            boq_item_id=a.boq_item_id,
            specification_id=a.specification_id,
            calculation_id=a.calculation_id,
            research_source_id=a.research_source_id,
            notes=a.notes,
        )
        evaluated_activities.append(ev_out)
        if a.is_milestone:
            milestones.append(
                {
                    "activity_id": aid,
                    "name": a.name,
                    "target_date": p_finish or NOT_PROVIDED_LABEL,
                    "is_critical": ev_out.is_critical,
                    "finish_variance_wd": f_var,
                }
            )

    if baseline_result is not None:
        cur_ids = {a.activity_id for a in activities}
        removed = sorted(aid for aid in base_by_id if aid not in cur_ids)
        for r_id in removed:
            base_notes.append(f"Removed from current schedule (present in baseline): {r_id} ({base_by_id[r_id].name}).")

    total_dur: int | None = None
    proj_finish: str | None = None
    if all_branches_complete and comp_max_finish:
        total_dur = max(comp_max_finish)
        if total_dur == 0:
            proj_finish = cal.effective_start()
        else:
            proj_finish = cal.workdays[total_dur - 1].isoformat()

    proj_var: int | None = None
    if baseline_result is not None and total_dur is not None and baseline_result.total_duration_wd is not None:
        proj_var = total_dur - baseline_result.total_duration_wd

    crit_ordered = sorted(
        list(critical_set),
        key=lambda x: (es_map[x] if es_map[x] is not None else 999999, topo_pos.get(x, 999999), x),
    )
    blocked_ids = [aid for aid in act_by_id if cpm_status_map[aid] != "computed"]

    return ScheduleResultOut(
        project_start_date=cal.start_date.isoformat(),
        effective_start_date=cal.effective_start(),
        project_finish_date=proj_finish,
        total_duration_wd=total_dur,
        calendar_preset=cal.preset,
        calendar_summary=cal.summary,
        weekend_days=cal.weekend_days,
        holidays=cal.holidays,
        critical_path_complete=all_branches_complete,
        critical_path_ids=crit_ordered,
        blocked_activity_ids=blocked_ids,
        blocked_branch_flags=blocked_branch_flags,
        missing_duration_flags=missing_duration_flags,
        milestone_summary=milestones,
        baseline_schedule_id=baseline_schedule_id,
        baseline_title=baseline_title,
        project_finish_variance_wd=proj_var,
        baseline_comparison_notes=base_notes,
        activities=evaluated_activities,
    )


def _contains_ungrounded_standard(text: str, *, allowed_source_text: str) -> bool:
    for url_hit in _URL_RE.findall(text):
        if url_hit.lower() not in allowed_source_text:
            return True
    for std_hit in _UNGROUNDED_STD_RE.findall(text):
        if std_hit.lower() not in allowed_source_text:
            return True
    return False


class _AiScheduleNarrativePayload(BaseModel):
    executive_summary: str = Field(..., min_length=10, max_length=2500)


def draft_schedule_narrative_with_ai(
    db: Session,
    secret_store: SecretStore,
    *,
    project_id: str,
    project_code: str,
    project_name: str,
    title: str,
    language: ReportLanguage,
    result: ScheduleResultOut,
    complexity: TaskComplexity = "fast",
    client_factory: Callable[[str], Any] | None = None,
    task_id: str | None = None,
) -> tuple[str, TokenUsage, int, int]:
    """Optional Gemini prose schedule summary ONLY; never computes dates/durations/CPM and always tagged UNVERIFIED AI DRAFT."""
    prompt_payload = {
        "project": f"[{project_code}] {project_name}",
        "schedule_title": title,
        "language": language,
        "rules": [
            "Summarize the deterministic schedule, milestones, critical path, and blocked branches ONLY from provided facts.",
            "NEVER invent productivity rates, durations, holiday dates, costs, or standard citations.",
        ],
        "effective_start": result.effective_start_date,
        "project_finish": result.project_finish_date or NOT_PROVIDED_LABEL,
        "total_duration_wd": result.total_duration_wd,
        "calendar_summary": result.calendar_summary,
        "critical_path_ids": result.critical_path_ids,
        "blocked_branch_flags": result.blocked_branch_flags,
        "activities": [
            {
                "id": a.activity_id,
                "name": a.name,
                "duration": a.display_duration,
                "planned_start": a.planned_start or NOT_PROVIDED_LABEL,
                "planned_finish": a.planned_finish or NOT_PROVIDED_LABEL,
                "is_critical": a.is_critical,
                "float_wd": a.total_float_wd,
                "source_ref": a.source_ref,
            }
            for a in result.activities[:40]
        ],
    }
    prompt_text = json.dumps(prompt_payload, ensure_ascii=False)
    prompt_chars = len(prompt_text)
    est_tokens = estimate_prompt_tokens(prompt_text)

    cfg = _load_provider_config(db)
    daily_usage, monthly_usage = _summarize_usage(db)
    if daily_usage.total_tokens + est_tokens > cfg.usage_limits.daily_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated schedule AI narrative prompt ({est_tokens} tokens) plus daily usage "
            f"({daily_usage.total_tokens}) would exceed Step 04 daily limit ({cfg.usage_limits.daily_token_limit})."
        )
    if monthly_usage.total_tokens + est_tokens > cfg.usage_limits.monthly_token_limit:
        raise ProviderUsageLimitError(
            f"Estimated schedule AI narrative prompt ({est_tokens} tokens) plus monthly usage "
            f"({monthly_usage.total_tokens}) would exceed Step 04 monthly limit ({cfg.usage_limits.monthly_token_limit})."
        )

    sys_instr = (
        "You are a project planning controls editor. Write a concise executive schedule briefing strictly from the "
        "verified CPM schedule summary in the requested language ('ar' or 'en'). Do not invent productivity rates, "
        "durations, costs, URLs, or standards."
    )
    llm_req = LLMRequest(
        prompt=prompt_text,
        system_instruction=sys_instr,
        complexity=complexity,
        temperature=0.1,
        response_schema=_AiScheduleNarrativePayload,
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
        parsed = _AiScheduleNarrativePayload.model_validate(llm_resp.parsed_json)
    except ValidationError as exc:
        raise ProviderResponseError(
            f"Schedule AI narrative validation failed: {exc.errors()[0].get('msg', 'invalid schema')}"
        ) from exc

    allowed_text = " ".join(
        [title] + [a.name + " " + a.source_ref for a in result.activities]
    ).lower()
    note = sanitize_secret_text(parsed.executive_summary.strip())
    if _contains_ungrounded_standard(note, allowed_source_text=allowed_text):
        raise ProviderResponseError(
            "Schedule AI narrative referenced an ungrounded standard clause or URL not present in verified schedule inputs."
        )
    prefix = f"[{AI_UNVERIFIED_DRAFT_LABEL_AR}] " if language == "ar" else f"[{AI_UNVERIFIED_DRAFT_LABEL_EN}] "
    final_note = note if prefix.strip(" []") in note else f"{prefix}{note}"
    return final_note, llm_resp.usage, est_tokens, prompt_chars


def get_synthetic_planning_presets() -> list[PlanningPresetOut]:
    """Return synthetic clinic schedule fixtures (0% client data, owner-supplied durations, Libya weekend calendar)."""
    return [
        PlanningPresetOut(
            key="synthetic_clinic_fitout_libya",
            title_en="Synthetic Medical Clinic MEP & Finish Renovation Schedule (Libya Sun-Thu Calendar)",
            title_ar="الجدول الزمني التمثيلي لأعمال الكهروميكانيك والتشطيبات لعيادة طبية (أسبوع عمل ليبيا: الأحد–الخميس)",
            discipline="multidisciplinary",
            start_date="2026-11-22",  # Sunday
            calendar=WorkCalendarIn(
                preset="libya_sun_thu",
                weekend_days=[4, 5],
                holidays=[],
                hours_per_day=8.0,
                source_ref="Owner-selected Libya Sun-Thu calendar (Fri & Sat weekend, no unverified holidays assumed)",
            ),
            wbs_items=[
                WbsItemIn(wbs_code="1", title="Clinic Renovation Master Program", discipline="multidisciplinary"),
                WbsItemIn(wbs_code="1.1", title="Mobilization & Underground Plumbing Rough-in", parent_code="1", discipline="plumbing"),
                WbsItemIn(wbs_code="1.2", title="Electrical Conduits, MDB Panel & Sub-Mains", parent_code="1", discipline="electrical"),
                WbsItemIn(wbs_code="1.3", title="Tiling, Doors, Windows & Testing Commissioning", parent_code="1", discipline="architecture"),
            ],
            activities=[
                ScheduleActivityIn(
                    activity_id="M0",
                    wbs_code="1",
                    name="Owner Site Handover & Kickoff Milestone / استلام الموقع",
                    is_milestone=True,
                    duration_days=0,
                    predecessors=[],
                    source_kind="owner_entered",
                    source_ref="Owner kickoff directive (synthetic fixture)",
                ),
                ScheduleActivityIn(
                    activity_id="A1",
                    wbs_code="1.1",
                    name="Trench Excavation & PPR Main Line Rough-in / أعمال الحفر وتمديد أنابيب المياه",
                    duration_days=4,
                    quantity=35.0,
                    unit="m",
                    predecessors=[ActivityDependencyIn(predecessor_id="M0", dep_type="FS", lag_days=0)],
                    source_kind="owner_entered",
                    source_ref="Owner duration input (4 wd); synthetic BOQ P-01 quantity basis (NOT invented rate)",
                ),
                ScheduleActivityIn(
                    activity_id="A2",
                    wbs_code="1.2",
                    name="MDB Panel Mounting & Trunking Installation / تركيب اللوحة الرئيسية والترانكنج",
                    duration_days=3,
                    quantity=1.0,
                    unit="nos",
                    predecessors=[ActivityDependencyIn(predecessor_id="A1", dep_type="FS", lag_days=0)],
                    source_kind="owner_entered",
                    source_ref="Owner electrical foreman duration basis (3 wd)",
                ),
                ScheduleActivityIn(
                    activity_id="A3",
                    wbs_code="1.3",
                    name="Floor Screed, Porcelain Tile & Acoustic Wall Closeout / أعمال البلاط والأرضيات",
                    duration_days=5,
                    quantity=120.0,
                    unit="m2",
                    predecessors=[ActivityDependencyIn(predecessor_id="A1", dep_type="FS", lag_days=0)],
                    source_kind="owner_entered",
                    source_ref="Owner tiling duration input (5 wd)",
                ),
                ScheduleActivityIn(
                    activity_id="A4",
                    wbs_code="1.3",
                    name="Doors, Windows, Sanitary Trim & Load Testing / تركيب الأبواب والشبابيك والاختبارات",
                    duration_days=4,
                    predecessors=[
                        ActivityDependencyIn(predecessor_id="A2", dep_type="FS", lag_days=0),
                        ActivityDependencyIn(predecessor_id="A3", dep_type="FS", lag_days=1),
                    ],
                    source_kind="owner_entered",
                    source_ref="Owner commissioning duration (4 wd) + 1 wd screed cure lag after A3",
                ),
                ScheduleActivityIn(
                    activity_id="M1",
                    wbs_code="1",
                    name="Final QA Handover Readiness Milestone / الجاهزية للتسليم النهائي",
                    is_milestone=True,
                    duration_days=0,
                    predecessors=[ActivityDependencyIn(predecessor_id="A4", dep_type="FS", lag_days=0)],
                    source_kind="owner_entered",
                    source_ref="Owner target handover gate (synthetic fixture)",
                ),
            ],
        ),
    ]
