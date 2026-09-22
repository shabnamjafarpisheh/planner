"""Streamlit front end for the note and planner agent.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import os

import streamlit as st

from planner_core import agent as ag
from planner_core import capture as cap
from planner_core import providers as pv
from planner_core.store import (PRIORITIES, Store, ValidationError, add_days, connect,
                                human_minutes, now_hm, today_str, week_start, weekday_name)

st.set_page_config(page_title="Planner", page_icon="🗓️", layout="wide",
                   initial_sidebar_state="expanded")

def load_secrets():
    """Streamlit Cloud keeps settings in st.secrets; pass them on as environment
    variables so the rest of the app reads them the same way everywhere."""
    try:
        secrets = dict(st.secrets)
    except Exception:  # no secrets.toml, which is normal when running locally
        return
    for key in ("AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_BASE_URL",
                "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "DATABASE_PATH"):
        if key in secrets and not os.environ.get(key):
            os.environ[key] = str(secrets[key])


load_secrets()
DB_PATH = os.environ.get("DATABASE_PATH", "data/planner.db")
PAGES = ["Today", "Inbox", "Tasks", "Calendar", "Notes", "Projects", "Goals", "Search", "Settings"]


@st.cache_resource
def get_store(path: str) -> Store:
    return Store(connect(path))


store = get_store(DB_PATH)
ctx = {"today": today_str(), "now": now_hm()}
state = st.session_state
state.setdefault("chat", [])
state.setdefault("week_start", week_start(ctx["today"]))
state.setdefault("week_proposal", None)
state.setdefault("day_plan", None)
state.setdefault("open_note", None)


def flash(message, kind="success"):
    """Queue a message that survives the rerun which follows most actions."""
    state.setdefault("flash", []).append((kind, message))


def show_flashes():
    for kind, message in state.pop("flash", []):
        getattr(st, kind)(message)


def run(fn, ok_message=None):
    """Call a store method, turning validation problems into a visible message."""
    try:
        result = fn()
        if ok_message:
            flash(ok_message)
        return result
    except ValidationError as e:
        st.error(str(e))
    except Exception as e:  # unexpected: show it rather than a blank screen
        st.error(f"Something went wrong: {e}")
    return None


def task_line(task, key_prefix, show_project=True):
    """One task row with a done checkbox and a short description underneath."""
    cols = st.columns([0.06, 0.94])
    with cols[0]:
        done = task["status"] == "completed"
        if st.checkbox("Done", value=done, key=f"{key_prefix}-done-{task['id']}",
                       label_visibility="collapsed") != done:
            run(lambda: store.complete_task(task["id"]) if not done else store.reopen_task(task["id"]))
            st.rerun()
    with cols[1]:
        title = f"~~{task['title']}~~" if task["status"] == "completed" else f"**{task['title']}**"
        st.markdown(title)
        bits = []
        if task["due_date"]:
            overdue = task["due_date"] < ctx["today"] and task["status"] != "completed"
            bits.append(f":red[Overdue · was due {task['due_date']}]" if overdue else f"Due {task['due_date']}")
        if task["scheduled_date"]:
            bits.append(f"Planned {task['scheduled_date']}")
        if task["estimate_min"]:
            bits.append(human_minutes(task["estimate_min"]))
        if task["priority"] != 3:
            bits.append(PRIORITIES[task["priority"]])
        if show_project and task.get("project_name"):
            bits.append(task["project_name"])
        if bits:
            st.caption(" · ".join(bits))


def render_plan(plan):
    st.caption(f"{human_minutes(plan['planned_min'])} planned of {human_minutes(plan['capacity_min'])} "
               f"available ({plan['window']['start']}–{plan['window']['end']})")
    if not plan["schedule"]:
        st.info("Nothing to schedule yet.")
    for block in plan["schedule"]:
        label = f"`{block['start']}–{block['end']}`  "
        if block["type"] == "event":
            st.markdown(label + f"📅 **{block['title']}** (meeting)")
        elif block["type"] == "break":
            st.markdown(label + "☕ Break")
        else:
            st.markdown(label + f"**{block['title']}** — {block['reason']}")
    for bucket, emoji in (("must", "🔴 Must do"), ("should", "🔵 Should do"), ("nice", "⚪ Nice to do")):
        items = plan[bucket]
        if items:
            st.markdown(f"**{emoji}** — " + ", ".join(t["title"] for t in items))
    if plan["did_not_fit"]:
        st.warning("Didn't fit: " + ", ".join(t["title"] for t in plan["did_not_fit"]))
    for w in plan["warnings"]:
        st.warning(w)
    if plan["assumptions"]:
        with st.expander("Assumptions"):
            for a in plan["assumptions"]:
                st.write("• " + a)
    if plan["placed"] and st.button(f"Save this schedule ({len(plan['placed'])} tasks)", key="save-plan"):
        run(lambda: ag.apply_schedule(store, [{"id": t["id"], "to": plan["date"]} for t in plan["placed"]]),
            "Schedule saved")
        st.rerun()


# ------------------------------------------------------------------ pages
def page_today():
    st.title(f"{weekday_name(ctx['today'])} {ctx['today']}")
    data = store.get_today(ctx["today"])
    cols = st.columns(4)
    cols[0].metric("On today's list", len(data["planned"]))
    cols[1].metric("Done today", len(data["completed_today"]))
    cols[2].metric("Overdue", len(data["overdue"]))
    cols[3].metric("In inbox", data["inbox_count"])

    st.subheader("Capture")
    with st.form("capture", clear_on_submit=True):
        text = st.text_area(
            "What's on your mind?",
            placeholder='e.g. "Finish the deck by Monday, call Alex, idea: simpler hero section"',
            label_visibility="collapsed")
        c1, c2 = st.columns([1, 6])
        organize = c1.form_submit_button("Organize", type="primary")
        to_inbox = c2.form_submit_button("Save to inbox")
    if organize and text.strip():
        parsed = cap.parse_capture(text, ctx["today"])
        if not parsed["tasks"] and not parsed["notes"]:
            st.warning("I couldn't find anything to organize in that. Saved nothing.")
        else:
            for t in parsed["tasks"]:
                run(lambda t=t: store.create_task(title=t["title"], due_date=t.get("due_date"),
                                                  scheduled_date=t.get("scheduled_date")))
            for n in parsed["notes"]:
                run(lambda n=n: store.create_note(title=n["title"], content=n["content"]))
            flash(f"Organized {len(parsed['tasks'])} task(s) and {len(parsed['notes'])} note(s).")
            st.rerun()
    if to_inbox and text.strip():
        run(lambda: store.add_inbox(text), "Saved to inbox")
        st.rerun()

    left, right = st.columns(2)
    with left:
        st.subheader("Plan")
        choice = st.selectbox("Time available", ["My whole workday", "30 minutes", "1 hour",
                                                 "2 hours", "3 hours", "4 hours"])
        minutes = {"30 minutes": 30, "1 hour": 60, "2 hours": 120, "3 hours": 180, "4 hours": 240}.get(choice)
        if st.button("Plan my day", type="primary"):
            state["day_plan"] = ag.day_plan(store, ctx["today"], minutes, ctx["now"])
        if state["day_plan"]:
            render_plan(state["day_plan"])
        elif data["events"]:
            for e in data["events"]:
                st.markdown(f"`{e['start_time']}–{e['end_time']}`  📅 **{e['title']}**")
    with right:
        if data["overdue"]:
            st.subheader("Overdue")
            for t in data["overdue"]:
                task_line(t, "od")
        st.subheader("Due today")
        if data["due_today"]:
            for t in data["due_today"]:
                task_line(t, "due")
        else:
            st.caption("Nothing due today.")
        if data["planned"]:
            st.subheader("Planned for today")
            for t in data["planned"]:
                task_line(t, "pl")
        if data["carried_over"]:
            st.subheader("Carried over")
            for t in data["carried_over"]:
                task_line(t, "co")
            if st.button(f"Move all {len(data['carried_over'])} to today"):
                run(lambda: store.bulk_reschedule([t["id"] for t in data["carried_over"]], ctx["today"]),
                    "Moved")
                st.rerun()
        if data["deadlines_this_week"]:
            st.subheader("Deadlines this week")
            for t in data["deadlines_this_week"]:
                task_line(t, "dl")


def page_inbox():
    st.title("Inbox")
    st.caption("Unsorted thoughts. Turn each one into a task or a note, or archive it.")
    with st.form("add-inbox", clear_on_submit=True):
        text = st.text_input("Add a thought")
        if st.form_submit_button("Add") and text.strip():
            run(lambda: store.add_inbox(text), "Added")
            st.rerun()
    items = store.list_inbox()
    if not items:
        st.info("Inbox is empty.")
        return
    for item in items:
        suggestion = cap.suggest_inbox_action(item["text"], ctx["today"])
        with st.container(border=True):
            st.markdown(item["text"])
            st.caption(f"Suggested: {suggestion['type']} — {suggestion['reason']}")
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Make task", key=f"it-{item['id']}",
                         type="primary" if suggestion["type"] == "task" else "secondary"):
                run(lambda: ag.run_tool_unchecked(store, "process_inbox_item",
                                                  {"id": item["id"], "type": "task",
                                                   "due_date": suggestion.get("due_date")}, ctx), "Task created")
                st.rerun()
            if c2.button("Make note", key=f"in-{item['id']}",
                         type="primary" if suggestion["type"] == "note" else "secondary"):
                run(lambda: ag.run_tool_unchecked(store, "process_inbox_item",
                                                  {"id": item["id"], "type": "note"}, ctx), "Note saved")
                st.rerun()
            if c3.button("Archive", key=f"ia-{item['id']}"):
                run(lambda: store.close_inbox(item["id"], "archived"), "Archived")
                st.rerun()
            if c4.button("Delete", key=f"id-{item['id']}"):
                # Deleting is explicit here: the button itself is the confirmation.
                run(lambda: store.delete_inbox(item["id"]), "Deleted")
                st.rerun()


def page_tasks():
    st.title("Tasks")
    projects = store.list_projects()
    with st.form("add-task", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 1.4, 1.4, 1])
        title = c1.text_input("New task", placeholder="What needs doing?")
        due = c2.date_input("Due", value=None, format="YYYY-MM-DD")
        project = c3.selectbox("Project", ["No project"] + [p["name"] for p in projects])
        estimate = c4.number_input("Minutes", min_value=0, step=15, value=0)
        if st.form_submit_button("Add task", type="primary") and title.strip():
            run(lambda: store.create_task(
                title=title, due_date=due.isoformat() if due else None,
                project=None if project == "No project" else project,
                estimate_min=estimate or None), "Task added")
            st.rerun()

    tab = st.radio("Filter", ["Open", "Inbox", "Planned", "In progress", "Overdue", "Completed"],
                   horizontal=True, label_visibility="collapsed")
    if tab == "Open":
        tasks = store.list_tasks(open_only=True)
    elif tab == "Overdue":
        tasks = store.overdue_tasks(ctx["today"])
    else:
        tasks = store.list_tasks(status=tab.lower().replace(" ", "_"))
    st.caption(f"{len(tasks)} shown")
    for t in tasks:
        with st.container(border=True):
            task_line(t, "tk")
            with st.expander("Edit"):
                edit_task_form(t, projects)


def edit_task_form(task, projects):
    with st.form(f"edit-{task['id']}"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Title", task["title"])
        status = c2.selectbox("Status", ["inbox", "planned", "in_progress", "completed", "cancelled"],
                              index=["inbox", "planned", "in_progress", "completed", "cancelled"].index(task["status"]))
        c3, c4, c5 = st.columns(3)
        due = c3.text_input("Due (YYYY-MM-DD)", task["due_date"] or "")
        sched = c4.text_input("Planned for", task["scheduled_date"] or "")
        priority = c5.selectbox("Priority", list(PRIORITIES), index=task["priority"] - 1,
                                format_func=lambda p: PRIORITIES[p])
        names = ["No project"] + [p["name"] for p in projects]
        current = task.get("project_name") or "No project"
        project = st.selectbox("Project", names, index=names.index(current) if current in names else 0)
        description = st.text_area("Notes", task["description"])
        c6, c7 = st.columns([1, 1])
        if c6.form_submit_button("Save", type="primary"):
            run(lambda: store.update_task(
                task["id"], title=title, status=status, due_date=due or None,
                scheduled_date=sched or None, priority=priority, description=description,
                project=None if project == "No project" else project), "Saved")
            st.rerun()
        if c7.form_submit_button("Delete"):
            run(lambda: store.delete_task(task["id"]), "Deleted")
            st.rerun()


def page_calendar():
    st.title("Calendar")
    c1, c2, c3, _ = st.columns([1, 1, 1, 4])
    if c1.button("← Previous"):
        state["week_start"] = add_days(state["week_start"], -7)
        state["week_proposal"] = None
    if c2.button("This week"):
        state["week_start"] = week_start(ctx["today"])
        state["week_proposal"] = None
    if c3.button("Next →"):
        state["week_start"] = add_days(state["week_start"], 7)
        state["week_proposal"] = None

    week = store.get_week(state["week_start"])
    st.caption(f"{week['start']} to {week['end']}")

    c1, c2 = st.columns([1, 1])
    if c1.button("Plan my week", type="primary"):
        state["week_proposal"] = ag.week_plan(store, state["week_start"], ctx["now"])
    if c2.button("Review this week"):
        state["week_proposal"] = None
        review = store.weekly_review(state["week_start"])
        with st.container(border=True):
            st.subheader("Week in review")
            st.write(f"Completed: {len(review['completed'])}")
            for t in review["completed"][:10]:
                st.markdown(f"• ~~{t['title']}~~")
            if review["missed_deadlines"]:
                st.write("Deadlines that slipped:")
                for t in review["missed_deadlines"]:
                    st.markdown(f"• {t['title']} (due {t['due_date']})")
            if review["next_focus"]:
                st.write("Suggested focus next:")
                for t in review["next_focus"]:
                    st.markdown(f"• {t['title']} (due {t['due_date']})")

    proposal = state["week_proposal"]
    if proposal:
        with st.container(border=True):
            st.subheader("Proposed plan")
            for a in proposal["assumptions"]:
                st.caption(a)
            for d in proposal["days"]:
                names = ", ".join(t["title"] for t in d["tasks"]) or "nothing planned"
                st.markdown(f"**{d['weekday'][:3]} {d['date'][5:]}** — {names} "
                            f"({human_minutes(d['planned_min'])} of {human_minutes(d['capacity_min'])})")
            if proposal["at_risk"]:
                st.warning("No room this week: " + ", ".join(t["title"] for t in proposal["at_risk"]))
            c1, c2 = st.columns([1, 6])
            if c1.button(f"Apply plan ({len(proposal['changes'])} changes)", type="primary"):
                run(lambda: ag.apply_schedule(store, proposal["changes"]), "Plan applied")
                state["week_proposal"] = None
                st.rerun()
            if c2.button("Dismiss"):
                state["week_proposal"] = None
                st.rerun()

    cols = st.columns(7)
    for col, day in zip(cols, week["days"]):
        with col:
            marker = "🔵 " if day["date"] == ctx["today"] else ""
            st.markdown(f"{marker}**{day['weekday'][:3]} {day['date'][8:]}**")
            for e in day["events"]:
                st.caption(f"📅 {e['start_time']} {e['title']}")
            for t in day["tasks"]:
                label = f"~~{t['title']}~~" if t["status"] == "completed" else t["title"]
                st.markdown(f"<small>{label}</small>", unsafe_allow_html=True)
            for t in day["due"]:
                st.caption(f"⏰ due: {t['title']}")

    with st.expander("Add an event"):
        with st.form("add-event", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns(4)
            title = c1.text_input("Title")
            date = c2.date_input("Date", format="YYYY-MM-DD")
            start = c3.text_input("Start", "10:00")
            end = c4.text_input("End", "11:00")
            if st.form_submit_button("Add event") and title.strip():
                run(lambda: store.create_event(title, date.isoformat(), start, end), "Event added")
                st.rerun()


def page_notes():
    st.title("Notes")
    left, right = st.columns([1, 2])
    with left:
        if st.button("New note", type="primary"):
            made = run(lambda: store.create_note(title="Untitled note", content=""))
            if made:
                state["open_note"] = made["id"]
                st.rerun()
        for n in store.list_notes():
            if st.button(n["title"][:40] or "Untitled", key=f"note-{n['id']}", use_container_width=True):
                state["open_note"] = n["id"]
                st.rerun()
    with right:
        if not state["open_note"]:
            st.info("Pick a note, or start a new one.")
            return
        try:
            note = store.get_note(state["open_note"])
        except ValidationError:
            state["open_note"] = None
            return
        with st.form(f"note-{note['id']}"):
            title = st.text_input("Title", note["title"])
            content = st.text_area("Content", note["content"], height=280)
            c1, c2, c3 = st.columns([1, 1, 1])
            if c1.form_submit_button("Save", type="primary"):
                run(lambda: store.update_note(note["id"], title=title, content=content), "Saved")
                st.rerun()
            if c2.form_submit_button("Extract tasks"):
                parsed = cap.parse_capture(content, ctx["today"])
                for t in parsed["tasks"]:
                    run(lambda t=t: store.create_task(title=t["title"], due_date=t.get("due_date"),
                                                      scheduled_date=t.get("scheduled_date")))
                flash(f"Created {len(parsed['tasks'])} task(s) from this note.")
                st.rerun()
            if c3.form_submit_button("Delete"):
                run(lambda: store.delete_note(note["id"]), "Deleted")
                state["open_note"] = None
                st.rerun()


def page_projects():
    st.title("Projects")
    with st.form("add-project", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("New project")
        due = c2.date_input("Due", value=None, format="YYYY-MM-DD")
        if st.form_submit_button("Create project", type="primary") and name.strip():
            run(lambda: store.create_project(name, due_date=due.isoformat() if due else None), "Created")
            st.rerun()
    projects = store.list_projects()
    if not projects:
        st.info("No projects yet.")
    for p in projects:
        with st.container(border=True):
            st.subheader(p["name"])
            st.caption(f"{p['done_count']} of {p['task_count']} tasks done"
                       + (f" · due {p['due_date']}" if p["due_date"] else ""))
            st.progress(p["progress"] / 100)
            with st.expander("Tasks and notes"):
                full = store.get_project(p["id"])
                for t in full["tasks"]:
                    task_line(t, f"pr{p['id']}", show_project=False)
                for n in full["notes"]:
                    st.caption(f"📝 {n['title']}")
                if st.button("Delete project", key=f"delp-{p['id']}"):
                    run(lambda: store.delete_project(p["id"]), "Deleted (tasks and notes kept)")
                    st.rerun()


def page_goals():
    st.title("Goals")
    with st.form("add-goal", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        title = c1.text_input("New goal", placeholder="e.g. Learn Python in 3 months")
        deadline = c2.date_input("Deadline", value=None, format="YYYY-MM-DD")
        if st.form_submit_button("Create goal", type="primary") and title.strip():
            run(lambda: store.create_goal(title, deadline=deadline.isoformat() if deadline else None),
                "Created")
            st.rerun()
    goals = store.list_goals()
    if not goals:
        st.info("No goals yet. Ask the assistant to break a big goal into projects and tasks.")
    for g in goals:
        with st.container(border=True):
            st.subheader(g["title"])
            st.caption(f"{g['done_count']} of {g['task_count']} tasks done"
                       + (f" · by {g['deadline']}" if g["deadline"] else ""))
            st.progress(g["progress"] / 100)
            for p in g["projects"]:
                st.markdown(f"• **{p['name']}**" + (f" (due {p['due_date']})" if p["due_date"] else ""))
            if st.button("Delete goal", key=f"delg-{g['id']}"):
                run(lambda: store.delete_goal(g["id"]), "Deleted")
                st.rerun()


def page_search():
    st.title("Search")
    query = st.text_input("Search everything", placeholder="A word, a project, a person…")
    if not query.strip():
        return
    found = store.search(query)
    st.caption(f"{len(found['tasks'])} tasks · {len(found['notes'])} notes · "
               f"{len(found['projects'])} projects · {len(found['goals'])} goals")
    if found["projects"]:
        st.subheader("Projects")
        for p in found["projects"]:
            st.markdown(f"• **{p['name']}**")
    if found["tasks"]:
        st.subheader("Tasks")
        for t in found["tasks"]:
            task_line(t, "se")
    if found["notes"]:
        st.subheader("Notes")
        for n in found["notes"]:
            with st.expander(n["title"]):
                st.write(n["content"])


def page_settings():
    st.title("Settings")
    settings = store.get_settings()

    st.subheader("AI assistant")
    cfg = pv.resolve_config(store)
    if cfg["source"] == "env":
        st.info("The AI provider is set in your environment. Remove AI_PROVIDER to manage it here.")
    ids = list(pv.PRESETS)
    labels = {i: pv.PRESETS[i]["label"] for i in ids}
    chosen = st.selectbox("Provider", ids, index=ids.index(cfg["provider"]),
                          format_func=lambda i: labels[i], disabled=cfg["source"] == "env")
    preset = pv.PRESETS[chosen]
    help_text = preset["help"]
    if preset["key_url"]:
        help_text += f"  \n[{'Get a key' if preset['needs_key'] else 'Get it here'}]({preset['key_url']})"
    st.caption(help_text)

    key = model = base_url = ""
    same = chosen == cfg["provider"]
    if preset["needs_key"]:
        key = st.text_input("API key", type="password", disabled=cfg["source"] == "env",
                            placeholder=f"Saved key {cfg['key_hint']} — leave blank to keep it"
                            if (same and cfg["api_key"]) else "Paste your API key")
    if chosen != "none":
        model = st.text_input("Model", value=cfg["model"] if same else preset["model"],
                              disabled=cfg["source"] == "env")
    if chosen == "openai_compatible":
        base_url = st.text_input("Service URL", value=cfg["base_url"] if same else "",
                                 placeholder="https://…", disabled=cfg["source"] == "env")

    c1, c2 = st.columns([1, 4])
    if c1.button("Save", type="primary", disabled=cfg["source"] == "env"):
        saved = run(lambda: pv.save_config(store, chosen, key, model, base_url), "AI settings saved")
        if saved:
            st.rerun()
    if c2.button("Test connection"):
        with st.spinner("Testing…"):
            ok, message = pv.test_connection(pv.resolve_config(store))
        (st.success if ok else st.error)(message)
    if cfg["enabled"]:
        st.caption(f"On: {cfg['label']}, model {cfg['model']}.")
    elif cfg["problem"]:
        st.caption(cfg["problem"])
    else:
        st.caption("Basic mode: built-in rules only.")

    st.subheader("Working hours")
    with st.form("hours"):
        c1, c2 = st.columns(2)
        start = c1.text_input("Start", settings["workday_start"])
        end = c2.text_input("End", settings["workday_end"])
        if st.form_submit_button("Save hours", type="primary"):
            run(lambda: store.update_hours(start, end), "Hours saved")
            st.rerun()

    st.subheader("What the assistant remembers")
    memories = store.list_memories()
    if not memories:
        st.caption("Nothing yet. Lasting facts you mention are kept here.")
    for m in memories:
        c1, c2 = st.columns([5, 1])
        c1.write(m["fact"])
        if c2.button("Forget", key=f"mem-{m['id']}"):
            run(lambda: store.forget(m["id"]), "Forgotten")
            st.rerun()

    st.subheader("Recent activity")
    for a in store.recent_activity(15):
        st.caption(f"{a['at']} · {a['actor']} · {a['action']} {a['detail']}")


# ------------------------------------------------------------------ assistant
def assistant_sidebar():
    with st.sidebar:
        st.markdown("### Assistant")
        cfg = pv.resolve_config(store)
        st.caption(f"AI on · {cfg['label']}" if cfg["enabled"] else "Basic mode")
        if not cfg["enabled"]:
            st.caption("Connect a free AI on the Settings page for full natural-language help.")

        for pending in store.open_pending():
            with st.container(border=True):
                st.write(f"**Confirm:** {pending['summary']}")
                c1, c2 = st.columns(2)
                if c1.button("Confirm", key=f"pc-{pending['id']}", type="primary"):
                    run(lambda: ag.resolve_pending(store, pending["id"], "confirm", ctx), "Done")
                    st.rerun()
                if c2.button("Cancel", key=f"px-{pending['id']}"):
                    run(lambda: ag.resolve_pending(store, pending["id"], "reject", ctx), "Cancelled")
                    st.rerun()

        for msg in state["chat"][-12:]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                for action in msg.get("actions", []):
                    st.caption(f"✓ {action}")
                if msg.get("notice"):
                    st.caption(msg["notice"])

        if not state["chat"]:
            st.caption("Try: “Plan my day”, “What am I falling behind on?”, "
                       "“Move unfinished tasks to tomorrow”.")

        prompt = st.chat_input("Ask, plan, or dump what's on your mind")
        if prompt:
            state["chat"].append({"role": "user", "content": prompt})
            with st.spinner("Thinking…"):
                try:
                    out = ag.chat(store, prompt, ctx)
                except ValidationError as e:
                    out = {"reply": str(e), "actions": [], "pending": [], "plan": None}
                except Exception as e:
                    out = {"reply": f"Something went wrong: {e}", "actions": [], "pending": [], "plan": None}
            state["chat"].append({"role": "assistant", "content": out["reply"],
                                  "actions": out.get("actions", []), "notice": out.get("notice")})
            if out.get("plan", {}) and out["plan"] and out["plan"]["kind"] == "plan_day":
                state["day_plan"] = out["plan"]["data"]
            if out.get("plan") and out["plan"]["kind"] == "plan_week":
                state["week_proposal"] = out["plan"]["data"]
            st.rerun()

        if state["chat"] and st.button("New chat"):
            state["chat"] = []
            store.clear_messages()
            st.rerun()


page = st.sidebar.radio("Go to", PAGES, label_visibility="collapsed")
st.sidebar.divider()
show_flashes()
{"Today": page_today, "Inbox": page_inbox, "Tasks": page_tasks, "Calendar": page_calendar,
 "Notes": page_notes, "Projects": page_projects, "Goals": page_goals, "Search": page_search,
 "Settings": page_settings}[page]()
assistant_sidebar()
