"""The agent: what the model is allowed to do, and how a message is handled.

The model never touches the database directly. It calls tools; the tools call
the store. Anything destructive is parked until the person confirms it.
"""
from __future__ import annotations

import json

from . import capture as cap
from .planning import plan_day, plan_week
from .providers import AIUnavailable, make_caller, resolve_config
from .store import (ValidationError, add_days, human_minutes, week_start,
                    weekday_name)

MAX_STEPS = 8
BASIC_NOTE = ("Basic mode: I handle capture, planning, overdue checks and search. "
              "Connect a free AI in Settings for full natural-language help.")

_S = lambda **props: {"type": "object", "properties": props}


def tool_schemas():
    text = {"type": "string"}
    num = {"type": "integer"}
    date = {"type": "string", "description": "YYYY-MM-DD"}
    return [
        {"name": "create_task", "description": "Create a task. Only set dates the user actually gave.",
         "input_schema": {**_S(title=text, description=text, due_date=date, scheduled_date=date,
                               priority={"type": "integer", "description": "1 urgent to 4 low"},
                               estimate_min=num, project=text, tags={"type": "array", "items": text}),
                          "required": ["title"]}},
        {"name": "update_task", "description": "Change fields of a task.",
         "input_schema": {**_S(id=num, title=text, description=text, status=text, priority=num,
                               due_date=date, scheduled_date=date, estimate_min=num, project=text),
                          "required": ["id"]}},
        {"name": "complete_task", "description": "Mark a task done.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "reschedule_task", "description": "Move one task to a date.",
         "input_schema": {**_S(id=num, date=date), "required": ["id", "date"]}},
        {"name": "bulk_reschedule", "description": "Move several tasks to a date.",
         "input_schema": {**_S(ids={"type": "array", "items": num}, date=date), "required": ["ids", "date"]}},
        {"name": "split_task", "description": "Split a task into ordered subtasks.",
         "input_schema": {**_S(id=num, subtasks={"type": "array", "items": _S(title=text, estimate_min=num)}),
                          "required": ["id", "subtasks"]}},
        {"name": "delete_task", "description": "Delete a task. Prefer cancelling instead.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "search_tasks", "description": "Find tasks by text or filters.",
         "input_schema": _S(query=text, status=text, open_only={"type": "boolean"}, project_id=num)},
        {"name": "get_task", "description": "One task with its subtasks and blockers.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "create_note", "description": "Save a note.",
         "input_schema": {**_S(title=text, content=text, project=text,
                               tags={"type": "array", "items": text}), "required": ["content"]}},
        {"name": "update_note", "description": "Edit a note.",
         "input_schema": {**_S(id=num, title=text, content=text, project=text), "required": ["id"]}},
        {"name": "delete_note", "description": "Delete a note.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "search_notes", "description": "Find notes by text.",
         "input_schema": _S(query=text, since=date)},
        {"name": "get_note", "description": "Read one note.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "create_project", "description": "Create a project.",
         "input_schema": {**_S(name=text, description=text, due_date=date, goal_id=num), "required": ["name"]}},
        {"name": "search_projects", "description": "List projects with progress.", "input_schema": _S()},
        {"name": "get_project", "description": "A project with its tasks and notes.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "delete_project", "description": "Delete a project; its tasks and notes are kept.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "create_goal", "description": "Create a goal.",
         "input_schema": {**_S(title=text, description=text, deadline=date), "required": ["title"]}},
        {"name": "breakdown_goal", "description": "Create a goal with projects and their tasks in one step.",
         "input_schema": {**_S(title=text, deadline=date, description=text,
                               projects={"type": "array", "items": _S(
                                   name=text, due_date=date,
                                   tasks={"type": "array", "items": _S(title=text, estimate_min=num, due_date=date)})}),
                          "required": ["title", "projects"]}},
        {"name": "search_goals", "description": "List goals with progress.", "input_schema": _S()},
        {"name": "get_goal", "description": "One goal with its projects.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "create_event", "description": "Add a meeting or appointment.",
         "input_schema": {**_S(title=text, date=date, start_time=text, end_time=text),
                          "required": ["title", "date", "start_time", "end_time"]}},
        {"name": "list_events", "description": "Events in a date range.", "input_schema": _S(start=date, end=date)},
        {"name": "get_today", "description": "Today's dashboard: planned, due, overdue, events.",
         "input_schema": _S(date=date)},
        {"name": "get_week", "description": "This week's tasks and events.", "input_schema": _S(start=date)},
        {"name": "plan_day", "description": "Build a realistic timed plan for a day.",
         "input_schema": _S(date=date, available_min=num)},
        {"name": "plan_week", "description": "Spread open work across the days left this week.",
         "input_schema": _S(start=date)},
        {"name": "apply_schedule", "description": "Save scheduled dates from a proposed plan.",
         "input_schema": {**_S(changes={"type": "array", "items": _S(id=num, to=date)}), "required": ["changes"]}},
        {"name": "weekly_review", "description": "What got done, what slipped, what's next.",
         "input_schema": _S(start=date)},
        {"name": "search_context", "description": "Search everything: tasks, notes, projects, goals.",
         "input_schema": {**_S(query=text), "required": ["query"]}},
        {"name": "process_inbox", "description": "List inbox items with a suggested action for each.",
         "input_schema": _S()},
        {"name": "process_inbox_item", "description": "Turn one inbox item into a task or note, or archive it.",
         "input_schema": {**_S(id=num, type=text, title=text, due_date=date), "required": ["id", "type"]}},
        {"name": "remember_fact", "description": "Remember a lasting fact about the user.",
         "input_schema": {**_S(fact=text), "required": ["fact"]}},
    ]


READ_ONLY = {"search_tasks", "get_task", "search_notes", "get_note", "search_projects", "get_project",
             "search_goals", "get_goal", "list_events", "get_today", "get_week", "plan_day",
             "plan_week", "weekly_review", "search_context", "process_inbox"}


def needs_confirmation(name, args):
    """Destructive or sweeping changes wait for a person."""
    if name in ("delete_task", "delete_note", "delete_project"):
        return True
    if name == "bulk_reschedule" and len(args.get("ids") or []) > 2:
        return True
    if name == "apply_schedule" and len(args.get("changes") or []) > 3:
        return True
    return False


def summarize_pending(store, name, args):
    if name == "delete_task":
        return f'Delete the task "{store.get_task(args["id"])["title"]}"'
    if name == "delete_note":
        return f'Delete the note "{store.get_note(args["id"])["title"]}"'
    if name == "delete_project":
        return f'Delete the project "{store.get_project(args["id"])["name"]}" (its tasks and notes are kept)'
    if name == "bulk_reschedule":
        titles = []
        for i in args["ids"][:3]:
            try:
                titles.append(store.get_task(i)["title"])
            except ValidationError:
                pass
        more = "" if len(args["ids"]) <= 3 else f" and {len(args['ids']) - 3} more"
        return f'Move {len(args["ids"])} tasks to {args["date"]}: ' + ", ".join(f'"{t}"' for t in titles) + more
    if name == "apply_schedule":
        return f"Save {len(args['changes'])} scheduled dates from the plan"
    return f"Run {name}"


def day_plan(store, date, available_min=None, now=None):
    settings = store.get_settings()
    tasks = [store.get_task(t["id"]) for t in store.list_tasks(open_only=True)]
    return plan_day(tasks, date, events=store.list_events(date), now=now,
                    available_min=available_min, workday_start=settings["workday_start"],
                    workday_end=settings["workday_end"])


def week_plan(store, start, now=None):
    settings = store.get_settings()
    start = week_start(start)
    events = {}
    for i in range(7):
        d = add_days(start, i)
        events[d] = store.list_events(d)
    return plan_week(store.list_tasks(open_only=True), start, events_by_day=events, now=now,
                     workday_start=settings["workday_start"], workday_end=settings["workday_end"])


def apply_schedule(store, changes):
    by_date = {}
    for c in changes:
        by_date.setdefault(c["to"], []).append(int(c["id"]))
    applied = 0
    for date, ids in by_date.items():
        store.bulk_reschedule(ids, date)
        applied += len(ids)
    return {"applied": applied}


def run_tool(store, name, args, ctx):
    """Execute one tool call. Returns plain data the model can read."""
    args = args or {}
    today = ctx.get("today")
    if needs_confirmation(name, args):
        return store.park_action(name, args, summarize_pending(store, name, args))
    return run_tool_unchecked(store, name, args, ctx)


def run_tool_unchecked(store, name, args, ctx):
    today = ctx.get("today")
    now = ctx.get("now")
    if name == "create_task":
        return store.create_task(**args)
    if name == "update_task":
        return store.update_task(args.pop("id"), **args)
    if name == "complete_task":
        return store.complete_task(args["id"])
    if name == "reschedule_task":
        return store.reschedule_task(args["id"], args["date"])
    if name == "bulk_reschedule":
        return store.bulk_reschedule(args["ids"], args["date"])
    if name == "split_task":
        return store.split_task(args["id"], args["subtasks"])
    if name == "delete_task":
        return store.delete_task(args["id"])
    if name == "search_tasks":
        return store.list_tasks(query=args.get("query"), status=args.get("status"),
                                open_only=args.get("open_only", False), project_id=args.get("project_id"))
    if name == "get_task":
        return store.get_task(args["id"])
    if name == "create_note":
        return store.create_note(**args)
    if name == "update_note":
        return store.update_note(args.pop("id"), **args)
    if name == "delete_note":
        return store.delete_note(args["id"])
    if name == "search_notes":
        return store.list_notes(query=args.get("query"), since=args.get("since"))
    if name == "get_note":
        return store.get_note(args["id"])
    if name == "create_project":
        return store.create_project(**args)
    if name == "search_projects":
        return store.list_projects()
    if name == "get_project":
        return store.get_project(args["id"])
    if name == "delete_project":
        return store.delete_project(args["id"])
    if name == "create_goal":
        return store.create_goal(**args)
    if name == "breakdown_goal":
        return store.breakdown_goal(args["title"], args["projects"],
                                    deadline=args.get("deadline"), description=args.get("description", ""))
    if name == "search_goals":
        return store.list_goals()
    if name == "get_goal":
        return store.get_goal(args["id"])
    if name == "create_event":
        return store.create_event(args["title"], args["date"], args["start_time"], args["end_time"])
    if name == "list_events":
        return store.list_events(args.get("start"), args.get("end"))
    if name == "get_today":
        return store.get_today(args.get("date") or today)
    if name == "get_week":
        return store.get_week(args.get("start") or today)
    if name == "plan_day":
        date = args.get("date") or today
        return day_plan(store, date, args.get("available_min"), now if date == today else None)
    if name == "plan_week":
        return week_plan(store, args.get("start") or today, now)
    if name == "apply_schedule":
        return apply_schedule(store, args["changes"])
    if name == "weekly_review":
        return store.weekly_review(args.get("start") or today)
    if name == "search_context":
        return store.search(args["query"])
    if name == "process_inbox":
        return [{**item, "suggestion": cap.suggest_inbox_action(item["text"], today)}
                for item in store.list_inbox()]
    if name == "process_inbox_item":
        item = next((i for i in store.list_inbox() if i["id"] == args["id"]), None)
        if not item:
            raise ValidationError(f"No open inbox item with id {args['id']}")
        kind = args["type"]
        if kind == "task":
            made = store.create_task(title=args.get("title") or item["text"][:200],
                                     due_date=args.get("due_date"))
        elif kind == "note":
            made = store.create_note(title=args.get("title"), content=item["text"])
        else:
            made = {"archived": True}
        store.close_inbox(item["id"])
        return made
    if name == "remember_fact":
        return store.remember(args["fact"])
    raise ValidationError(f"Unknown tool {name}")


def resolve_pending(store, pid, decision, ctx):
    """Run or drop a parked action."""
    pending = store.get_pending(pid)
    if decision != "confirm":
        store.set_pending_state(pid, "rejected")
        return {"state": "rejected", "summary": pending["summary"]}
    store.set_pending_state(pid, "confirmed")
    result = run_tool_unchecked(store, pending["tool"], json.loads(pending["args"]), ctx)
    return {"state": "confirmed", "summary": pending["summary"], "result": result}


def describe_action(name, args, result):
    title = ""
    if isinstance(result, dict):
        title = result.get("title") or result.get("name") or ""
    title = title or args.get("title") or args.get("name") or ""
    labels = {
        "create_task": f'Added task "{title}"', "update_task": f'Updated task "{title}"',
        "complete_task": f'Completed "{title}"', "delete_task": f'Deleted task "{title}"',
        "reschedule_task": f'Moved "{title}" to {args.get("date")}',
        "bulk_reschedule": f'Moved {len(args.get("ids") or [])} tasks to {args.get("date")}',
        "split_task": f'Split a task into {len(args.get("subtasks") or [])} subtasks',
        "create_note": f'Saved note "{title}"', "update_note": f'Updated note "{title}"',
        "delete_note": f'Deleted note "{title}"',
        "create_project": f'Created project "{title}"', "delete_project": f'Deleted project "{title}"',
        "create_goal": f'Created goal "{title}"',
        "breakdown_goal": f'Set up goal "{args.get("title")}" with {len(args.get("projects") or [])} projects',
        "create_event": f'Added event "{title}"',
        "apply_schedule": f'Scheduled {len(args.get("changes") or [])} tasks',
        "process_inbox_item": f'Processed an inbox item as {args.get("type")}',
        "remember_fact": f'Remembered: {args.get("fact")}',
    }
    return labels.get(name, name)


def system_prompt(store, ctx):
    snap = store.snapshot(ctx["today"])
    facts = "\n".join(f"- {f}" for f in snap["memories"]) or "- (nothing yet)"
    projects = "\n".join(f"- #{p['id']} {p['name']}" + (f" (due {p['due_date']})" if p["due_date"] else "")
                         for p in snap["projects"]) or "- (none)"
    goals = "\n".join(f"- #{g['id']} {g['title']}" + (f" (by {g['deadline']})" if g["deadline"] else "")
                      for g in snap["goals"]) or "- (none)"
    return f"""You are the planning assistant inside a personal notes and planner app.

Today is {snap['weekday']} {snap['today']}. The working day runs
{snap['settings']['workday_start']}–{snap['settings']['workday_end']}.
Open tasks: {snap['counts']['open_tasks']}, overdue: {snap['counts']['overdue']},
inbox: {snap['counts']['inbox']}.

Active projects:
{projects}

Active goals:
{goals}

Remembered facts:
{facts}

Rules:
- Act only through tools. Look up ids with a search tool before changing anything.
- Never invent a deadline, an estimate or a detail the user didn't give. If a date is
  essential and missing, ask one short question instead of guessing.
- Separate facts from suggestions, and label assumptions as assumptions.
- When a tool answers that confirmation is needed, tell the user what will happen and stop.
- Prefer cancelling a task over deleting it.
- Save lasting facts with remember_fact.
- Be concise: short sentences, compact lists, no preamble. Refer to items by title, not id.
"""


def chat(store, message, ctx, call_model=None, config=None):
    """Handle one user message. Returns a dict the UI can render."""
    message = (message or "").strip()
    if not message:
        raise ValidationError("Type a message first")
    if len(message) > 8000:
        raise ValidationError("That message is too long (max 8000 characters)")

    cfg = config or resolve_config(store)
    call = call_model or make_caller(cfg)
    store.add_message("user", message)
    agent_store = store
    agent_store.actor = "agent"
    try:
        if call:
            try:
                out = _run_loop(agent_store, message, ctx, call)
            except AIUnavailable as e:
                out = fallback_agent(agent_store, message, ctx)
                out["notice"] = f"AI unavailable: {e} Answered in basic mode."
        else:
            out = fallback_agent(agent_store, message, ctx)
            out["notice"] = cfg["problem"] or BASIC_NOTE
    finally:
        agent_store.actor = "user"
    store.add_message("assistant", out["reply"])
    return out


def _run_loop(store, message, ctx, call_model):
    history = [{"role": m["role"], "content": m["content"]} for m in store.recent_messages(10)
               if m["content"].strip()]
    # Keep only plain text in history so tool calls and their results never split.
    messages = history[-8:] or [{"role": "user", "content": message}]
    if messages[-1]["content"] != message:
        messages.append({"role": "user", "content": message})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    system = system_prompt(store, ctx)
    tools = tool_schemas()
    actions, pending, plan = [], [], None

    for step in range(MAX_STEPS):
        try:
            res = call_model({"max_tokens": 2048, "system": system, "tools": tools, "messages": messages})
            if not isinstance(res, dict) or not isinstance(res.get("content"), list):
                raise AIUnavailable("The AI service returned an unexpected response")
        except AIUnavailable:
            if step == 0:
                raise
            return {"reply": "The AI stopped responding partway through. Anything listed below was saved.",
                    "actions": actions, "pending": pending, "plan": plan, "mode": "ai"}

        messages.append({"role": "assistant", "content": res["content"]})
        uses = [b for b in res["content"] if b["type"] == "tool_use"]
        if res.get("stop_reason") != "tool_use" or not uses:
            reply = "\n".join(b["text"] for b in res["content"] if b["type"] == "text").strip()
            return {"reply": reply or "Done.", "actions": actions, "pending": pending,
                    "plan": plan, "mode": "ai"}

        results = []
        for use in uses:
            try:
                result = run_tool(store, use["name"], use.get("input") or {}, ctx)
                if isinstance(result, dict) and result.get("needs_confirmation"):
                    pending.append({"id": result["pending_action_id"], "summary": result["summary"]})
                elif use["name"] not in READ_ONLY:
                    actions.append(describe_action(use["name"], use.get("input") or {}, result))
                if use["name"] in ("plan_day", "plan_week"):
                    plan = {"kind": use["name"], "data": result}
                results.append({"type": "tool_result", "tool_use_id": use["id"],
                                "content": json.dumps(result, default=str)[:40000]})
            except Exception as e:  # tool errors go back to the model, which can correct itself
                results.append({"type": "tool_result", "tool_use_id": use["id"],
                                "is_error": True, "content": str(e)})
        messages.append({"role": "user", "content": results})

    return {"reply": "I stopped after several steps without finishing. Try rephrasing the request.",
            "actions": actions, "pending": pending, "plan": plan, "mode": "ai"}


# ------------------------------------------------------------------ fallback
def fallback_agent(store, message, ctx, mode_hint=None):
    """Rule-based answers so the app is useful with no AI at all."""
    m = message.lower().strip()
    today = ctx["today"]
    actions, pending = [], []

    import re
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", m)
    mins = re.search(r"(\d+)\s*(minutes?|mins?|m)\b", m)
    available = int(float(hours.group(1)) * 60) if hours else (int(mins.group(1)) if mins else None)

    if mode_hint != "capture":
        if re.search(r"\b(plan my day|what should i (work on|do)|plan (for )?today|i (only )?have \d)", m):
            date = add_days(today, 1) if "tomorrow" in m else today
            plan = day_plan(store, date, available, ctx.get("now") if date == today else None)
            return {"reply": format_day_plan(plan), "actions": actions, "pending": pending,
                    "plan": {"kind": "plan_day", "data": plan}, "mode": "basic"}

        if re.search(r"\bplan (my |the )?week|next (three|3) days\b", m):
            plan = week_plan(store, today, ctx.get("now"))
            lines = [f"{d['weekday'][:3]} {d['date'][5:]}: " +
                     (", ".join(t["title"] for t in d["tasks"]) if d["tasks"] else "nothing planned")
                     for d in plan["days"]]
            return {"reply": "Proposed week:\n" + "\n".join(f"• {l}" for l in lines),
                    "actions": actions, "pending": pending,
                    "plan": {"kind": "plan_week", "data": plan}, "mode": "basic"}

        if re.search(r"\b(falling behind|overdue|late|behind on)\b", m):
            overdue = store.overdue_tasks(today)
            carried = store.unfinished_tasks(today)
            if not overdue and not carried:
                return {"reply": "Nothing is overdue. You're on top of it.", "actions": actions,
                        "pending": pending, "plan": None, "mode": "basic"}
            lines = [f"• {t['title']}, due {t['due_date']}" for t in overdue]
            lines += [f"• {t['title']}, planned {t['scheduled_date']}" for t in carried
                      if t not in overdue]
            head = f"Overdue ({len(overdue)})" if overdue else "Carried over"
            return {"reply": f"{head}:\n" + "\n".join(lines), "actions": actions,
                    "pending": pending, "plan": None, "mode": "basic"}

        if re.search(r"\bmove (all )?(unfinished|leftover|remaining).*(tomorrow|today)\b", m):
            target = add_days(today, 1) if "tomorrow" in m else today
            items = store.unfinished_tasks(today)
            if not items:
                return {"reply": "There are no unfinished tasks to move.", "actions": actions,
                        "pending": pending, "plan": None, "mode": "basic"}
            ids = [t["id"] for t in items]
            result = run_tool(store, "bulk_reschedule", {"ids": ids, "date": target}, ctx)
            if isinstance(result, dict) and result.get("needs_confirmation"):
                pending.append({"id": result["pending_action_id"], "summary": result["summary"]})
                return {"reply": "This needs your confirmation.", "actions": actions,
                        "pending": pending, "plan": None, "mode": "basic"}
            actions.append(f"Moved {len(ids)} tasks to {target}")
            return {"reply": f"Moved {len(ids)} task(s) to {target}.", "actions": actions,
                    "pending": pending, "plan": None, "mode": "basic"}

        if re.search(r"\b(summar(y|ize|ise)).*(week|wrote)\b", m):
            review = store.weekly_review(today)
            return {"reply": (f"This week: {len(review['completed'])} done, "
                              f"{len(review['unfinished'])} unfinished, "
                              f"{len(review['notes'])} note(s) written."),
                    "actions": actions, "pending": pending, "plan": None, "mode": "basic"}

        if re.search(r"\b(find|search|show me|everything (about|related))\b", m):
            query = re.sub(r"^.*?(find|search|show me|everything about|everything related to)\s+", "", m).strip(" ?.")
            if query:
                found = store.search(query)
                return {"reply": (f'"{query}": {len(found["tasks"])} task(s), {len(found["notes"])} note(s), '
                                  f'{len(found["projects"])} project(s).'),
                        "actions": actions, "pending": pending, "plan": None, "mode": "basic",
                        "search": found}

    # Anything else is treated as something to capture.
    parsed = cap.parse_capture(message, today)
    if not parsed["tasks"] and not parsed["notes"]:
        return {"reply": "I couldn't find anything to organize in that.", "actions": actions,
                "pending": pending, "plan": None, "mode": "basic"}
    for t in parsed["tasks"]:
        made = store.create_task(title=t["title"], due_date=t.get("due_date"),
                                 scheduled_date=t.get("scheduled_date"))
        actions.append(f'Added task "{made["title"]}"'
                       + (f', due {made["due_date"]}' if made["due_date"] else ""))
    for n in parsed["notes"]:
        made = store.create_note(title=n["title"], content=n["content"])
        actions.append(f'Saved note "{made["title"]}"')
    return {"reply": f"Organized {len(parsed['tasks'])} task(s) and {len(parsed['notes'])} note(s).",
            "actions": actions, "pending": pending, "plan": None, "mode": "basic"}


def format_day_plan(plan):
    if not any(b["type"] == "task" for b in plan["schedule"]):
        return ("There's nothing to schedule for that day. Add a task or two and ask again."
                if not plan["must"] and not plan["should"]
                else "Nothing fits in the time available.")
    lines = [f"{human_minutes(plan['planned_min'])} planned of "
             f"{human_minutes(plan['capacity_min'])} available "
             f"({plan['window']['start']}–{plan['window']['end']}):"]
    for block in plan["schedule"]:
        if block["type"] == "event":
            lines.append(f"• {block['start']} {block['title']} (meeting)")
        elif block["type"] == "break":
            lines.append(f"• {block['start']} break")
        else:
            lines.append(f"• {block['start']}–{block['end']} {block['title']} ({block['reason']})")
    if plan["did_not_fit"]:
        lines.append("Didn't fit: " + ", ".join(t["title"] for t in plan["did_not_fit"][:4]))
    for w in plan["warnings"]:
        lines.append(f"⚠ {w}")
    return "\n".join(lines)
