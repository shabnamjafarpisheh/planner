"""Planning. Pure functions over plain dicts, so they are easy to test.

Principles: never plan more than a person can really do, protect time around
meetings, and say out loud what was assumed.
"""
from __future__ import annotations

from .store import (DEFAULT_ESTIMATE_MIN, add_days, days_between, from_min,
                    human_minutes, to_min, weekday_name)

BUFFER_MIN = 10          # breathing room between tasks
BREAK_AFTER_MIN = 90     # after this much continuous work, take a break
BREAK_MIN = 15
MIN_STINT_FOR_BREAK = 45  # short stints are covered by the buffer alone
FOCUS_RATIO = 0.65       # plan only this share of free time
MIN_BLOCK = 15


def estimate_of(task) -> int:
    return int(task.get("estimate_min") or DEFAULT_ESTIMATE_MIN)


def classify(task, today):
    """Sort a task into must / should / nice, with a reason a person can read."""
    due = task.get("due_date")
    priority = int(task.get("priority") or 3)
    if due and due < today:
        return "must", f"overdue by {days_between(due, today)} day(s)"
    if due == today:
        return "must", "due today"
    if priority == 1:
        return "must", "marked urgent"
    if due and days_between(today, due) <= 2:
        return "should", f"due {weekday_name(due)}"
    if task.get("scheduled_date") == today:
        return "should", "planned for today"
    if priority == 2:
        return "should", "marked high priority"
    if due and days_between(today, due) <= 7:
        return "nice", f"due {weekday_name(due)}"
    return "nice", "no deadline"


def free_windows(start_min, end_min, events):
    """Gaps between meetings, as (start, end) pairs."""
    busy = sorted(((to_min(e["start_time"]), to_min(e["end_time"])) for e in events))
    windows, cursor = [], start_min
    for bstart, bend in busy:
        if bend <= cursor or bstart >= end_min:
            continue
        if bstart > cursor:
            windows.append((cursor, min(bstart, end_min)))
        cursor = max(cursor, bend)
    if cursor < end_min:
        windows.append((cursor, end_min))
    return [(s, e) for s, e in windows if e - s >= MIN_BLOCK]


def plan_day(tasks, date, events=None, now=None, available_min=None,
             workday_start="09:00", workday_end="18:00"):
    """Build a timed, realistic plan for one day."""
    events = sorted(events or [], key=lambda e: e["start_time"])
    assumptions, warnings = [], []
    start, end = to_min(workday_start), to_min(workday_end)

    if now:
        nxt = -(-(to_min(now) + 5) // 15) * 15  # round up to the next quarter hour
        if nxt > start:
            start = nxt
            assumptions.append(f"Starting from {from_min(start)}, since the day is already under way.")
    if start >= end:
        warnings.append("The workday is already over, so this plan is for the time that's left.")
        end = min(24 * 60 - 1, start + 60)

    windows = free_windows(start, end, events)
    free_total = sum(e - s for s, e in windows)
    capacity = int(free_total * FOCUS_RATIO)
    if available_min:
        capacity = min(capacity, int(available_min))
        assumptions.append(f"You said you have about {human_minutes(int(available_min))}.")
    else:
        assumptions.append(
            f"Planning {int(FOCUS_RATIO * 100)}% of your {human_minutes(free_total)} of free time; "
            "the rest absorbs interruptions.")

    open_tasks = [t for t in tasks if t.get("status") in ("inbox", "planned", "in_progress")]
    if any(t.get("estimate_min") is None for t in open_tasks):
        assumptions.append(f"Tasks without an estimate are treated as {DEFAULT_ESTIMATE_MIN} minutes.")

    ranked = []
    for t in open_tasks:
        bucket, reason = classify(t, date)
        ranked.append({**t, "bucket": bucket, "reason": reason, "minutes": estimate_of(t)})
    order = {"must": 0, "should": 1, "nice": 2}
    ranked.sort(key=lambda t: (order[t["bucket"]], int(t.get("priority") or 3),
                               t.get("due_date") or "9999-12-31", t["id"]))

    blocked_ids = {t["id"] for t in ranked
                   if any(d.get("status") not in ("completed", "cancelled")
                          for d in (t.get("blocked_by") or []))}
    blocked = [t for t in ranked if t["id"] in blocked_ids]
    ready = [t for t in ranked if t["id"] not in blocked_ids]

    schedule = [{"type": "event", "title": e.get("title") or "Meeting", "start": e["start_time"],
                 "end": e["end_time"]} for e in events]
    placed, did_not_fit = [], []
    used = 0
    since_break = 0
    cursor_by_window = [list(w) for w in windows]
    last_end = None

    for task in ready:
        minutes = task["minutes"]
        if used + minutes > capacity:
            did_not_fit.append(task)
            continue
        spot = None
        for window in cursor_by_window:
            wstart, wend = window
            begin = wstart if last_end is None or wstart > last_end else max(wstart, last_end + BUFFER_MIN)
            rested = last_end is not None and begin - last_end >= BREAK_MIN
            if rested:
                since_break = 0
            need_break = (since_break >= MIN_STINT_FOR_BREAK
                          and since_break + minutes > BREAK_AFTER_MIN and not rested)
            if need_break:
                begin += BREAK_MIN
            if begin + minutes <= wend:
                spot = (window, begin, need_break)
                break
        if not spot:
            did_not_fit.append(task)
            continue
        window, begin, need_break = spot
        if need_break:
            schedule.append({"type": "break", "title": "Break",
                             "start": from_min(begin - BREAK_MIN), "end": from_min(begin)})
            since_break = 0
        schedule.append({
            "type": "task", "id": task["id"], "title": task["title"],
            "start": from_min(begin), "end": from_min(begin + minutes),
            "bucket": task["bucket"], "reason": task["reason"], "minutes": minutes,
            "project_name": task.get("project_name"),
        })
        placed.append({**task, "start": from_min(begin), "end": from_min(begin + minutes)})
        window[0] = begin + minutes
        last_end = begin + minutes
        since_break += minutes
        used += minutes

    if blocked:
        warnings.append(f"{len(blocked)} task(s) are waiting on something else and were left out.")
    must_missing = [t for t in did_not_fit if t["bucket"] == "must"]
    if must_missing:
        warnings.append(
            f"{len(must_missing)} urgent task(s) don't fit in the time available: "
            + ", ".join(t["title"] for t in must_missing[:3]) + ". Consider moving a deadline.")

    schedule.sort(key=lambda b: b["start"])
    return {
        "date": date, "weekday": weekday_name(date), "schedule": schedule,
        "planned_min": used, "capacity_min": capacity, "free_min": free_total,
        "must": [t for t in ranked if t["bucket"] == "must"],
        "should": [t for t in ranked if t["bucket"] == "should"],
        "nice": [t for t in ranked if t["bucket"] == "nice"],
        "placed": placed, "did_not_fit": did_not_fit, "blocked": blocked,
        "assumptions": assumptions, "warnings": warnings,
        "window": {"start": from_min(start), "end": from_min(end)},
    }


def plan_week(tasks, date, events_by_day=None, now=None,
              workday_start="09:00", workday_end="18:00", include_weekend=False):
    """Spread open work across the days left this week, respecting deadlines."""
    events_by_day = events_by_day or {}
    from .store import week_start
    start = week_start(date)
    days = []
    for i in range(7):
        d = add_days(start, i)
        if d < date:
            continue
        if not include_weekend and weekday_name(d) in ("Saturday", "Sunday"):
            continue
        day_start = max(to_min(workday_start), to_min(now)) if (d == date and now) else to_min(workday_start)
        free = 0 if day_start >= to_min(workday_end) else sum(
            e - s for s, e in free_windows(day_start, to_min(workday_end), events_by_day.get(d, [])))
        days.append({"date": d, "weekday": weekday_name(d), "capacity_min": int(free * FOCUS_RATIO),
                     "planned_min": 0, "tasks": []})

    open_tasks = [t for t in tasks if t.get("status") in ("inbox", "planned", "in_progress")]
    ranked = []
    for t in open_tasks:
        bucket, reason = classify(t, date)
        ranked.append({**t, "bucket": bucket, "reason": reason, "minutes": estimate_of(t)})
    order = {"must": 0, "should": 1, "nice": 2}
    ranked.sort(key=lambda t: (order[t["bucket"]], t.get("due_date") or "9999-12-31",
                               int(t.get("priority") or 3), t["id"]))

    changes, at_risk = [], []
    for task in ranked:
        deadline = task.get("due_date")
        pool = [d for d in days if not deadline or d["date"] <= deadline] or days[:1]
        fits = [d for d in pool if d["planned_min"] + task["minutes"] <= d["capacity_min"]]
        if not fits:
            at_risk.append(task)
            continue
        if task["bucket"] == "must":
            target = fits[0]  # urgent work goes as early as possible
        else:
            # Everything else goes to the least-loaded day, so the week stays
            # even instead of piling onto today.
            target = min(fits, key=lambda d: ((d["planned_min"] + task["minutes"]) / max(d["capacity_min"], 1),
                                              d["date"]))
        target["tasks"].append(task)
        target["planned_min"] += task["minutes"]
        if task.get("scheduled_date") != target["date"]:
            changes.append({"id": task["id"], "title": task["title"],
                            "from": task.get("scheduled_date"), "to": target["date"]})

    for d in days:
        d["tasks"].sort(key=lambda t: order[t["bucket"]])
    return {"start": start, "days": days, "changes": changes, "at_risk": at_risk,
            "assumptions": [f"Each day is filled to about {int(FOCUS_RATIO * 100)}% of its free hours "
                            f"({workday_start}–{workday_end})."]}
