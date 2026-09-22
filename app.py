"""Planner: an AI note and planning assistant for Streamlit.

Everything is in this one file, so it runs as long as app.py and
requirements.txt are present (for example on Streamlit Community Cloud).

Run with:  streamlit run app.py
"""
from __future__ import annotations



# ======================================================================
# store
# ======================================================================

import sqlite3
import re
from contextlib import contextmanager
from datetime import date as _date, datetime, timedelta
from pathlib import Path

DEFAULT_ESTIMATE_MIN = 30
STATUSES = ["inbox", "planned", "in_progress", "completed", "cancelled"]
PRIORITIES = {1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ValidationError(ValueError):
    """Bad input from a person or from the model. Shown as-is in the UI."""


class NotFound(ValidationError):
    pass


# ---------------------------------------------------------------- dates
def today_str() -> str:
    return _date.today().isoformat()


def parse_iso(value: str) -> _date:
    try:
        return _date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f'"{value}" is not a date. Use YYYY-MM-DD.')


def check_date(value, field="date", required=False):
    if value in (None, ""):
        if required:
            raise ValidationError(f"{field} is required")
        return None
    parse_iso(value)  # rejects 2026-02-30 as well as nonsense
    return value


def add_days(value: str, days: int) -> str:
    return (parse_iso(value) + timedelta(days=days)).isoformat()


def days_between(a: str, b: str) -> int:
    return (parse_iso(b) - parse_iso(a)).days


def weekday_name(value: str) -> str:
    return WEEKDAYS[parse_iso(value).weekday()]


def week_start(value: str) -> str:
    d = parse_iso(value)
    return (d - timedelta(days=d.weekday())).isoformat()


def to_min(hhmm: str) -> int:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hhmm or ""):
        raise ValidationError(f'"{hhmm}" is not a time. Use HH:MM.')
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def from_min(total: int) -> str:
    total = max(0, min(24 * 60 - 1, int(total)))
    return f"{total // 60:02d}:{total % 60:02d}"


def human_minutes(total: int) -> str:
    total = int(total)
    h, m = divmod(total, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def now_hm() -> str:
    return datetime.now().strftime("%H:%M")


def clean_text(value, field, limit=2000, required=True):
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text:
        if required:
            raise ValidationError(f"{field} is required")
        return ""
    if len(text) > limit:
        raise ValidationError(f"{field} is too long (max {limit} characters)")
    return text


def norm_tags(tags) -> str:
    if not tags:
        return ""
    if isinstance(tags, str):
        parts = tags.replace("#", "").split(",")
    else:
        parts = [str(t) for t in tags]
    seen, out = set(), []
    for p in parts:
        t = p.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out[:12])


# ---------------------------------------------------------------- schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  deadline TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  due_date TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'inbox' CHECK (status IN ('inbox','planned','in_progress','completed','cancelled')),
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 4),
  due_date TEXT,
  scheduled_date TEXT,
  estimate_min INTEGER,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS task_dependencies (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, depends_on_id)
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  date TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pending_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool TEXT NOT NULL,
  args TEXT NOT NULL,
  summary TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL DEFAULT 'user',
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_sched ON tasks(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
"""

DEFAULT_SETTINGS = {"workday_start": "09:00", "workday_end": "18:00"}


def connect(path: str = "data/planner.db") -> sqlite3.Connection:
    """Open the database, creating the file and tables if needed."""
    if path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    return conn


class Store:
    """Every read and write. One instance per database connection."""

    def __init__(self, conn: sqlite3.Connection, actor: str = "user"):
        self.conn = conn
        self.actor = actor

    # ------------------------------------------------------------ plumbing
    @contextmanager
    def tx(self):
        """Group writes so a half-finished operation never lands."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _q(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def log(self, action, detail=""):
        self.conn.execute(
            "INSERT INTO activity (actor, action, detail) VALUES (?, ?, ?)",
            (self.actor, action, detail[:300]),
        )

    def recent_activity(self, limit=30):
        return self._q("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        rows = self._q("SELECT key, value FROM settings")
        out = dict(DEFAULT_SETTINGS)
        out.update({r["key"]: r["value"] for r in rows})
        return out

    def set_setting(self, key: str, value: str):
        with self.tx() as c:
            c.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def update_hours(self, start: str, end: str):
        if to_min(end) <= to_min(start):
            raise ValidationError("The end of the workday must be after the start")
        self.set_setting("workday_start", start)
        self.set_setting("workday_end", end)

    # ------------------------------------------------------------ projects
    def project_by_name(self, name, create=True):
        """Projects are referred to by name in conversation, so resolve loosely."""
        name = clean_text(name, "project name", 120, required=False)
        if not name:
            return None
        found = self._one("SELECT * FROM projects WHERE lower(name) = lower(?)", (name,))
        if found:
            return found
        if not create:
            return None
        return self.create_project(name=name)

    def create_project(self, name, description="", goal_id=None, due_date=None):
        name = clean_text(name, "project name", 120)
        if self._one("SELECT id FROM projects WHERE lower(name) = lower(?)", (name,)):
            raise ValidationError(f'A project called "{name}" already exists')
        check_date(due_date, "due_date")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO projects (name, description, goal_id, due_date) VALUES (?, ?, ?, ?)",
                (name, clean_text(description, "description", 4000, False), goal_id, due_date or None),
            )
            self.log("create_project", name)
        return self.get_project(cur.lastrowid)

    def get_project(self, pid):
        p = self._one("SELECT * FROM projects WHERE id = ?", (pid,))
        if not p:
            raise NotFound(f"No project with id {pid}")
        p["tasks"] = self.list_tasks(project_id=pid)
        p["notes"] = self._q("SELECT * FROM notes WHERE project_id = ? ORDER BY updated_at DESC", (pid,))
        done = len([t for t in p["tasks"] if t["status"] == "completed"])
        total = len([t for t in p["tasks"] if t["status"] != "cancelled"])
        p["progress"] = round(100 * done / total) if total else 0
        return p

    def list_projects(self):
        rows = self._q("SELECT * FROM projects ORDER BY status, name")
        for p in rows:
            counts = self._one(
                "SELECT COUNT(*) AS total, SUM(status = 'completed') AS done "
                "FROM tasks WHERE project_id = ? AND status != 'cancelled'",
                (p["id"],),
            )
            total, done = counts["total"] or 0, counts["done"] or 0
            p["task_count"], p["done_count"] = total, done
            p["progress"] = round(100 * done / total) if total else 0
        return rows

    def update_project(self, pid, **fields):
        self.get_project(pid)
        allowed = {k: v for k, v in fields.items() if k in ("name", "description", "goal_id", "due_date", "status")}
        if "due_date" in allowed:
            check_date(allowed["due_date"], "due_date")
        if not allowed:
            return self.get_project(pid)
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE projects SET {sets} WHERE id = ?", (*allowed.values(), pid))
            self.log("update_project", str(pid))
        return self.get_project(pid)

    def delete_project(self, pid):
        """Tasks and notes survive; they simply lose the project link."""
        p = self.get_project(pid)
        with self.tx() as c:
            c.execute("DELETE FROM projects WHERE id = ?", (pid,))
            self.log("delete_project", p["name"])
        return {"deleted": pid, "name": p["name"]}

    # ------------------------------------------------------------ goals
    def create_goal(self, title, description="", deadline=None):
        title = clean_text(title, "title", 200)
        check_date(deadline, "deadline")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO goals (title, description, deadline) VALUES (?, ?, ?)",
                (title, clean_text(description, "description", 4000, False), deadline or None),
            )
            self.log("create_goal", title)
        return self.get_goal(cur.lastrowid)

    def get_goal(self, gid):
        g = self._one("SELECT * FROM goals WHERE id = ?", (gid,))
        if not g:
            raise NotFound(f"No goal with id {gid}")
        g["projects"] = self._q("SELECT * FROM projects WHERE goal_id = ? ORDER BY name", (gid,))
        ids = [p["id"] for p in g["projects"]]
        tasks = []
        if ids:
            marks = ",".join("?" * len(ids))
            tasks = self._q(f"SELECT * FROM tasks WHERE project_id IN ({marks})", ids)
        tasks += self._q("SELECT * FROM tasks WHERE goal_id = ? AND project_id IS NULL", (gid,))
        live = [t for t in tasks if t["status"] != "cancelled"]
        done = [t for t in live if t["status"] == "completed"]
        g["task_count"], g["done_count"] = len(live), len(done)
        g["progress"] = round(100 * len(done) / len(live)) if live else 0
        return g

    def list_goals(self):
        return [self.get_goal(g["id"]) for g in self._q("SELECT id FROM goals ORDER BY status, deadline IS NULL, deadline")]

    def update_goal(self, gid, **fields):
        self.get_goal(gid)
        allowed = {k: v for k, v in fields.items() if k in ("title", "description", "deadline", "status")}
        if "deadline" in allowed:
            check_date(allowed["deadline"], "deadline")
        if not allowed:
            return self.get_goal(gid)
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE goals SET {sets} WHERE id = ?", (*allowed.values(), gid))
            self.log("update_goal", str(gid))
        return self.get_goal(gid)

    def delete_goal(self, gid):
        g = self.get_goal(gid)
        with self.tx() as c:
            c.execute("DELETE FROM goals WHERE id = ?", (gid,))
            self.log("delete_goal", g["title"])
        return {"deleted": gid, "title": g["title"]}

    def breakdown_goal(self, title, projects, deadline=None, description=""):
        """Create a goal with its projects and their tasks, all or nothing."""
        if not projects:
            raise ValidationError("Give at least one project for the goal")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO goals (title, description, deadline) VALUES (?, ?, ?)",
                (clean_text(title, "title", 200), clean_text(description, "description", 4000, False),
                 check_date(deadline, "deadline")),
            )
            gid = cur.lastrowid
            made = []
            for spec in projects:
                pname = clean_text(spec.get("name"), "project name", 120)
                if self._one("SELECT id FROM projects WHERE lower(name) = lower(?)", (pname,)):
                    pname = f"{pname} ({title})"[:120]
                pc = c.execute(
                    "INSERT INTO projects (name, goal_id, due_date) VALUES (?, ?, ?)",
                    (pname, gid, check_date(spec.get("due_date"), "due_date")),
                )
                pid = pc.lastrowid
                for t in spec.get("tasks", []) or []:
                    ttitle = clean_text(t.get("title") if isinstance(t, dict) else t, "task title", 200)
                    est = t.get("estimate_min") if isinstance(t, dict) else None
                    due = check_date(t.get("due_date") if isinstance(t, dict) else None, "due_date")
                    c.execute(
                        "INSERT INTO tasks (title, status, project_id, goal_id, due_date, estimate_min) "
                        "VALUES (?, 'planned', ?, ?, ?, ?)",
                        (ttitle, pid, gid, due, est),
                    )
                made.append(pid)
            self.log("breakdown_goal", title)
        return {"goal": self.get_goal(gid), "projects": [self.get_project(p) for p in made]}

    # ------------------------------------------------------------ tasks
    def create_task(self, title, description="", status=None, priority=3, due_date=None,
                    scheduled_date=None, estimate_min=None, project=None, project_id=None,
                    goal_id=None, parent_id=None, tags=None):
        title = clean_text(title, "title", 200)
        if status is None:
            status = "planned" if (due_date or scheduled_date) else "inbox"
        if status not in STATUSES:
            raise ValidationError(f"Unknown status '{status}'")
        priority = int(priority or 3)
        if priority not in PRIORITIES:
            raise ValidationError("Priority must be 1 (urgent) to 4 (low)")
        check_date(due_date, "due_date")
        check_date(scheduled_date, "scheduled_date")
        if estimate_min is not None:
            estimate_min = int(estimate_min)
            if not 1 <= estimate_min <= 8 * 60:
                raise ValidationError("Estimate must be between 1 minute and 8 hours")
        if project and not project_id:
            p = self.project_by_name(project)
            project_id = p["id"] if p else None
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO tasks (title, description, status, priority, due_date, scheduled_date, "
                "estimate_min, project_id, goal_id, parent_id, tags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (title, clean_text(description, "description", 4000, False), status, priority,
                 due_date or None, scheduled_date or None, estimate_min, project_id, goal_id,
                 parent_id, norm_tags(tags)),
            )
            self.log("create_task", title)
        return self.get_task(cur.lastrowid)

    def get_task(self, tid):
        t = self._one(
            "SELECT t.*, p.name AS project_name FROM tasks t "
            "LEFT JOIN projects p ON p.id = t.project_id WHERE t.id = ?", (tid,))
        if not t:
            raise NotFound(f"No task with id {tid}")
        t["subtasks"] = self._q("SELECT * FROM tasks WHERE parent_id = ? ORDER BY id", (tid,))
        t["blocked_by"] = self._q(
            "SELECT t.id, t.title, t.status FROM task_dependencies d JOIN tasks t ON t.id = d.depends_on_id "
            "WHERE d.task_id = ?", (tid,))
        return t

    def list_tasks(self, status=None, open_only=False, project_id=None, goal_id=None,
                   due_before=None, scheduled_on=None, query=None, limit=500):
        sql = ("SELECT t.*, p.name AS project_name FROM tasks t "
               "LEFT JOIN projects p ON p.id = t.project_id WHERE 1=1")
        args = []
        if status:
            if isinstance(status, str):
                status = [status]
            sql += f" AND t.status IN ({','.join('?' * len(status))})"
            args += list(status)
        if open_only:
            sql += " AND t.status IN ('inbox','planned','in_progress')"
        if project_id:
            sql += " AND t.project_id = ?"
            args.append(project_id)
        if goal_id:
            sql += " AND (t.goal_id = ? OR t.project_id IN (SELECT id FROM projects WHERE goal_id = ?))"
            args += [goal_id, goal_id]
        if due_before:
            sql += " AND t.due_date IS NOT NULL AND t.due_date <= ?"
            args.append(due_before)
        if scheduled_on:
            sql += " AND t.scheduled_date = ?"
            args.append(scheduled_on)
        if query:
            sql += " AND (t.title LIKE ? OR t.description LIKE ? OR t.tags LIKE ?)"
            args += [f"%{query}%"] * 3
        sql += (" ORDER BY t.status = 'completed', t.priority, "
                "t.due_date IS NULL, t.due_date, t.id DESC LIMIT ?")
        args.append(limit)
        return self._q(sql, args)

    def update_task(self, tid, **fields):
        self.get_task(tid)
        allowed = {k: v for k, v in fields.items() if k in (
            "title", "description", "status", "priority", "due_date", "scheduled_date",
            "estimate_min", "project_id", "goal_id", "tags")}
        if "project" in fields and "project_id" not in allowed:
            p = self.project_by_name(fields["project"])
            allowed["project_id"] = p["id"] if p else None
        if allowed.get("status") and allowed["status"] not in STATUSES:
            raise ValidationError(f"Unknown status '{allowed['status']}'")
        for f in ("due_date", "scheduled_date"):
            if f in allowed:
                check_date(allowed[f], f)
                allowed[f] = allowed[f] or None
        if "priority" in allowed and int(allowed["priority"]) not in PRIORITIES:
            raise ValidationError("Priority must be 1 (urgent) to 4 (low)")
        if "tags" in allowed:
            allowed["tags"] = norm_tags(allowed["tags"])
        if "title" in allowed:
            allowed["title"] = clean_text(allowed["title"], "title", 200)
        if not allowed:
            return self.get_task(tid)
        if allowed.get("status") == "completed":
            allowed["completed_at"] = datetime.now().isoformat(timespec="seconds")
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*allowed.values(), tid))
            self.log("update_task", str(tid))
        return self.get_task(tid)

    def complete_task(self, tid):
        t = self.get_task(tid)
        unfinished = [d for d in t["blocked_by"] if d["status"] not in ("completed", "cancelled")]
        result = self.update_task(tid, status="completed")
        result["warning"] = (
            f"Note: this was waiting on {unfinished[0]['title']}, which isn't done."
            if unfinished else None)
        return result

    def reopen_task(self, tid):
        with self.tx() as c:
            c.execute("UPDATE tasks SET status = 'planned', completed_at = NULL WHERE id = ?", (tid,))
            self.log("reopen_task", str(tid))
        return self.get_task(tid)

    def reschedule_task(self, tid, date):
        check_date(date, "date", required=True)
        return self.update_task(tid, scheduled_date=date,
                                status="planned" if self.get_task(tid)["status"] == "inbox" else None
                                or self.get_task(tid)["status"])

    def bulk_reschedule(self, ids, date):
        check_date(date, "date", required=True)
        ids = [int(i) for i in ids]
        if not ids:
            raise ValidationError("No tasks given")
        with self.tx() as c:
            for tid in ids:
                if not self._one("SELECT id FROM tasks WHERE id = ?", (tid,)):
                    raise NotFound(f"No task with id {tid}")  # rolls the whole move back
                c.execute(
                    "UPDATE tasks SET scheduled_date = ?, status = CASE WHEN status = 'inbox' "
                    "THEN 'planned' ELSE status END WHERE id = ?", (date, tid))
            self.log("bulk_reschedule", f"{len(ids)} tasks to {date}")
        return {"moved": len(ids), "date": date, "ids": ids}

    def delete_task(self, tid):
        t = self.get_task(tid)
        with self.tx() as c:
            c.execute("DELETE FROM tasks WHERE id = ?", (tid,))
            self.log("delete_task", t["title"])
        return {"deleted": tid, "title": t["title"]}

    def split_task(self, tid, subtasks):
        parent = self.get_task(tid)
        if not subtasks:
            raise ValidationError("Give at least one subtask")
        made = []
        with self.tx() as c:
            for s in subtasks:
                title = clean_text(s.get("title") if isinstance(s, dict) else s, "subtask title", 200)
                est = s.get("estimate_min") if isinstance(s, dict) else None
                cur = c.execute(
                    "INSERT INTO tasks (title, status, priority, project_id, goal_id, parent_id, "
                    "due_date, estimate_min) VALUES (?, 'planned', ?, ?, ?, ?, ?, ?)",
                    (title, parent["priority"], parent["project_id"], parent["goal_id"], tid,
                     parent["due_date"], est))
                made.append(cur.lastrowid)
            for earlier, later in zip(made, made[1:]):
                c.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)",
                          (later, earlier))
            self.log("split_task", parent["title"])
        return {"parent": self.get_task(tid), "subtasks": [self.get_task(i) for i in made]}

    def add_dependency(self, task_id, depends_on_id):
        task_id, depends_on_id = int(task_id), int(depends_on_id)
        if task_id == depends_on_id:
            raise ValidationError("A task can't wait on itself")
        self.get_task(task_id), self.get_task(depends_on_id)
        # Walk the chain to make sure we aren't creating a loop.
        seen, stack = set(), [depends_on_id]
        while stack:
            cur = stack.pop()
            if cur == task_id:
                raise ValidationError("That would make two tasks wait on each other")
            if cur in seen:
                continue
            seen.add(cur)
            stack += [r["depends_on_id"] for r in
                      self._q("SELECT depends_on_id FROM task_dependencies WHERE task_id = ?", (cur,))]
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)",
                      (task_id, depends_on_id))
        return self.get_task(task_id)

    def overdue_tasks(self, today):
        return self.list_tasks(open_only=True, due_before=add_days(today, -1))

    def unfinished_tasks(self, today):
        """Planned for a day that has passed, still not done."""
        return [t for t in self.list_tasks(open_only=True)
                if t["scheduled_date"] and t["scheduled_date"] < today]

    # ------------------------------------------------------------ notes
    def create_note(self, title=None, content="", project=None, project_id=None, goal_id=None, tags=None):
        content = clean_text(content, "content", 20000, required=False)
        title = clean_text(title, "title", 200, required=False) or derive_title(content) or "Untitled note"
        if project and not project_id:
            p = self.project_by_name(project)
            project_id = p["id"] if p else None
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO notes (title, content, project_id, goal_id, tags) VALUES (?, ?, ?, ?, ?)",
                (title, content, project_id, goal_id, norm_tags(tags)))
            self.log("create_note", title)
        return self.get_note(cur.lastrowid)

    def get_note(self, nid):
        n = self._one("SELECT n.*, p.name AS project_name FROM notes n "
                      "LEFT JOIN projects p ON p.id = n.project_id WHERE n.id = ?", (nid,))
        if not n:
            raise NotFound(f"No note with id {nid}")
        return n

    def list_notes(self, project_id=None, query=None, since=None, limit=200):
        sql = ("SELECT n.*, p.name AS project_name FROM notes n "
               "LEFT JOIN projects p ON p.id = n.project_id WHERE 1=1")
        args = []
        if project_id:
            sql += " AND n.project_id = ?"
            args.append(project_id)
        if query:
            sql += " AND (n.title LIKE ? OR n.content LIKE ? OR n.tags LIKE ?)"
            args += [f"%{query}%"] * 3
        if since:
            sql += " AND date(n.updated_at) >= ?"
            args.append(since)
        sql += " ORDER BY n.updated_at DESC LIMIT ?"
        args.append(limit)
        return self._q(sql, args)

    def update_note(self, nid, **fields):
        self.get_note(nid)
        allowed = {k: v for k, v in fields.items()
                   if k in ("title", "content", "project_id", "goal_id", "tags")}
        if "project" in fields and "project_id" not in allowed:
            p = self.project_by_name(fields["project"])
            allowed["project_id"] = p["id"] if p else None
        if "tags" in allowed:
            allowed["tags"] = norm_tags(allowed["tags"])
        if not allowed:
            return self.get_note(nid)
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE notes SET {sets}, updated_at = datetime('now') WHERE id = ?",
                      (*allowed.values(), nid))
            self.log("update_note", str(nid))
        return self.get_note(nid)

    def delete_note(self, nid):
        n = self.get_note(nid)
        with self.tx() as c:
            c.execute("DELETE FROM notes WHERE id = ?", (nid,))
            self.log("delete_note", n["title"])
        return {"deleted": nid, "title": n["title"]}

    # ------------------------------------------------------------ events
    def create_event(self, title, date, start_time, end_time):
        title = clean_text(title, "title", 200)
        check_date(date, "date", required=True)
        if to_min(end_time) <= to_min(start_time):
            raise ValidationError("The event must end after it starts")
        with self.tx() as c:
            cur = c.execute("INSERT INTO events (title, date, start_time, end_time) VALUES (?,?,?,?)",
                            (title, date, start_time, end_time))
            self.log("create_event", title)
        return self._one("SELECT * FROM events WHERE id = ?", (cur.lastrowid,))

    def list_events(self, start=None, end=None):
        if start and end:
            return self._q("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start_time",
                           (start, end))
        if start:
            return self._q("SELECT * FROM events WHERE date = ? ORDER BY start_time", (start,))
        return self._q("SELECT * FROM events ORDER BY date, start_time")

    def delete_event(self, eid):
        with self.tx() as c:
            c.execute("DELETE FROM events WHERE id = ?", (eid,))
            self.log("delete_event", str(eid))
        return {"deleted": eid}

    # ------------------------------------------------------------ inbox
    def add_inbox(self, text):
        text = clean_text(text, "text", 4000)
        with self.tx() as c:
            cur = c.execute("INSERT INTO inbox_items (text) VALUES (?)", (text,))
            self.log("add_inbox", text[:60])
        return self._one("SELECT * FROM inbox_items WHERE id = ?", (cur.lastrowid,))

    def list_inbox(self, status="open"):
        return self._q("SELECT * FROM inbox_items WHERE status = ? ORDER BY id DESC", (status,))

    def close_inbox(self, iid, status="done"):
        with self.tx() as c:
            c.execute("UPDATE inbox_items SET status = ? WHERE id = ?", (status, iid))
        return {"id": iid, "status": status}

    def delete_inbox(self, iid):
        with self.tx() as c:
            c.execute("DELETE FROM inbox_items WHERE id = ?", (iid,))
            self.log("delete_inbox", str(iid))
        return {"deleted": iid}

    # ------------------------------------------------------------ memories
    def remember(self, fact):
        fact = clean_text(fact, "fact", 500)
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO memories (fact) VALUES (?)", (fact,))
            self.log("remember", fact[:60])
        return {"fact": fact}

    def list_memories(self):
        return self._q("SELECT * FROM memories ORDER BY id DESC")

    def forget(self, mid):
        with self.tx() as c:
            c.execute("DELETE FROM memories WHERE id = ?", (mid,))
        return {"deleted": mid}

    # ------------------------------------------------------------ search
    def search(self, query, limit=40):
        """Search titles, bodies and tags, and include a project's contents
        when the project name itself matches."""
        q = clean_text(query, "query", 200)
        tasks = self.list_tasks(query=q, limit=limit)
        notes = self.list_notes(query=q, limit=limit)
        projects = self._q("SELECT * FROM projects WHERE name LIKE ? OR description LIKE ?",
                           (f"%{q}%", f"%{q}%"))
        goals = self._q("SELECT * FROM goals WHERE title LIKE ? OR description LIKE ?",
                        (f"%{q}%", f"%{q}%"))
        seen_tasks = {t["id"] for t in tasks}
        seen_notes = {n["id"] for n in notes}
        for p in projects:
            for t in self.list_tasks(project_id=p["id"]):
                if t["id"] not in seen_tasks:
                    seen_tasks.add(t["id"])
                    tasks.append(t)
            for n in self.list_notes(project_id=p["id"]):
                if n["id"] not in seen_notes:
                    seen_notes.add(n["id"])
                    notes.append(n)
        return {"query": q, "tasks": tasks[:limit], "notes": notes[:limit],
                "projects": projects, "goals": goals}

    # ------------------------------------------------------------ dashboards
    def get_today(self, today):
        check_date(today, "today", required=True)
        planned = self.list_tasks(open_only=True, scheduled_on=today)
        due = [t for t in self.list_tasks(open_only=True) if t["due_date"] == today]
        return {
            "date": today,
            "weekday": weekday_name(today),
            "planned": planned,
            "due_today": due,
            "overdue": self.overdue_tasks(today),
            "carried_over": self.unfinished_tasks(today),
            "events": self.list_events(today),
            "completed_today": self._q(
                "SELECT * FROM tasks WHERE status = 'completed' AND date(completed_at) = ?", (today,)),
            "deadlines_this_week": [
                t for t in self.list_tasks(open_only=True)
                if t["due_date"] and today < t["due_date"] <= add_days(today, 7)],
            "inbox_count": len(self.list_inbox()),
            "recent_notes": self.list_notes(limit=5),
        }

    def get_week(self, start):
        start = week_start(start)
        days = []
        for i in range(7):
            d = add_days(start, i)
            days.append({
                "date": d,
                "weekday": weekday_name(d),
                "tasks": self.list_tasks(scheduled_on=d),
                "due": [t for t in self.list_tasks(open_only=True) if t["due_date"] == d],
                "events": self.list_events(d),
            })
        return {"start": start, "end": add_days(start, 6), "days": days}

    def weekly_review(self, start):
        start = week_start(start)
        end = add_days(start, 6)
        done = self._q("SELECT * FROM tasks WHERE status = 'completed' "
                       "AND date(completed_at) BETWEEN ? AND ?", (start, end))
        slipped = [t for t in self.list_tasks(open_only=True)
                   if t["due_date"] and start <= t["due_date"] <= end]
        unfinished = [t for t in self.list_tasks(open_only=True)
                      if t["scheduled_date"] and start <= t["scheduled_date"] <= end]
        notes = self.list_notes(since=start)
        return {"start": start, "end": end, "completed": done, "missed_deadlines": slipped,
                "unfinished": unfinished, "notes": notes,
                "next_focus": sorted(
                    [t for t in self.list_tasks(open_only=True) if t["due_date"]],
                    key=lambda t: t["due_date"])[:5]}

    def snapshot(self, today):
        """Compact context for the model's system prompt."""
        return {
            "today": today,
            "weekday": weekday_name(today),
            "settings": self.get_settings(),
            "projects": [{"id": p["id"], "name": p["name"], "due_date": p["due_date"]}
                         for p in self.list_projects() if p["status"] == "active"][:20],
            "goals": [{"id": g["id"], "title": g["title"], "deadline": g["deadline"]}
                      for g in self.list_goals() if g["status"] == "active"][:10],
            "counts": {
                "open_tasks": len(self.list_tasks(open_only=True)),
                "overdue": len(self.overdue_tasks(today)),
                "inbox": len(self.list_inbox()),
            },
            "memories": [m["fact"] for m in self.list_memories()][:20],
        }

    # ------------------------------------------------------------ pending actions
    def park_action(self, tool, args, summary):
        import json
        with self.tx() as c:
            cur = c.execute("INSERT INTO pending_actions (tool, args, summary) VALUES (?, ?, ?)",
                            (tool, json.dumps(args), summary))
        return {"pending_action_id": cur.lastrowid, "needs_confirmation": True, "summary": summary}

    def get_pending(self, pid):
        p = self._one("SELECT * FROM pending_actions WHERE id = ?", (pid,))
        if not p:
            raise NotFound(f"No pending action with id {pid}")
        return p

    def set_pending_state(self, pid, state):
        p = self.get_pending(pid)
        if p["state"] != "pending":
            raise ValidationError(f"That action was already {p['state']}")
        with self.tx() as c:
            c.execute("UPDATE pending_actions SET state = ? WHERE id = ?", (state, pid))
        return self.get_pending(pid)

    def open_pending(self):
        return self._q("SELECT * FROM pending_actions WHERE state = 'pending' ORDER BY id")

    # ------------------------------------------------------------ chat log
    def add_message(self, role, content):
        with self.tx() as c:
            c.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))

    def recent_messages(self, limit=20):
        rows = self._q("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    def clear_messages(self):
        with self.tx() as c:
            c.execute("DELETE FROM messages")


def derive_title(content: str) -> str:
    first = next((line.strip() for line in (content or "").splitlines() if line.strip()), "")
    return first[:77] + "…" if len(first) > 80 else first


# ======================================================================
# planning
# ======================================================================

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


# ======================================================================
# capture
# ======================================================================

import re


ACTION_RE = re.compile(
    r"\b(call|email|write|send|buy|finish|complete|book|schedule|prepare|review|fix|update|"
    r"draft|plan|order|pay|submit|clean|pick up|renew|cancel|check|ask|follow up|make|"
    r"read|research|build|design|test|deploy|meet|remind)\b", re.I)
NEED_RE = re.compile(r"^\s*(i\s+)?(need|have|want|should|must|got)\s+to\s+", re.I)
IDEA_RE = re.compile(r"\b(idea|thought|maybe|what if|consider|wondering|note to self)\b", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def parse_date(text, today):
    """Find a date in a phrase. Returns (iso_date, matched_phrase, kind) or None.

    kind is "due" for "by Monday" wording, otherwise "scheduled".
    """
    if not text:
        return None
    t = text.lower()
    kind = "due" if re.search(r"\b(by|before|due|deadline)\b", t) else "scheduled"

    if re.search(r"\b(today|tonight)\b", t):
        return today, "today", kind
    if re.search(r"\btomorrow\b", t):
        return add_days(today, 1), "tomorrow", kind
    if re.search(r"\byesterday\b", t):
        return add_days(today, -1), "yesterday", kind

    m = re.search(r"\bin (\d{1,3}) (day|days|week|weeks)\b", t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
        return add_days(today, n), m.group(0), kind

    m = re.search(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        target = WEEKDAYS.index(m.group(2).capitalize())
        current = parse_iso(today).weekday()
        delta = (target - current) % 7
        if delta == 0:
            delta = 7
        if m.group(1):  # "next Monday" means the week after, when it's close
            delta += 7 if delta < 7 else 0
        return add_days(today, delta), m.group(0), kind

    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", t)
    if m:
        try:
            parse_iso(m.group(1))
            return m.group(1), m.group(1), kind
        except Exception:
            return None

    m = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})\b", t)
    if m:
        month = MONTHS.index(m.group(1)) + 1
        day = int(m.group(2))
        year = parse_iso(today).year
        try:
            candidate = f"{year}-{month:02d}-{day:02d}"
            parse_iso(candidate)
        except Exception:
            return None
        if candidate < today:  # a month already gone means next year
            candidate = f"{year + 1}-{month:02d}-{day:02d}"
        return candidate, m.group(0), kind

    return None  # "soon", "at some point", "later" deliberately produce nothing


def _people(text):
    """Names after a preposition, e.g. "call Alex", "gift for Sarah"."""
    found = []
    for m in re.finditer(r"\b(?:call|email|ask|meet|with|for|to|from)\s+([A-Z][a-z]{1,20})\b", text):
        name = m.group(1)
        if name not in found and name not in ("I", "The", "This", "Monday", "Tuesday", "Wednesday",
                                              "Thursday", "Friday", "Saturday", "Sunday"):
            found.append(name)
    return found


def _title_from(chunk):
    title = chunk.strip().strip(".,;")
    title = NEED_RE.sub("", title)
    title = re.sub(r"^(and|also|then|please)\s+", "", title, flags=re.I)
    # Drop the date words from the title; the date is stored in its own field.
    title = re.sub(r"\b(by|before|due|on)?\s*(today|tonight|tomorrow|yesterday|next\s+\w+day|"
                   r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                   r"in \d{1,3} (?:days?|weeks?)|\d{4}-\d{2}-\d{2})\b", "", title, flags=re.I)
    title = re.sub(r"\s{2,}", " ", title).strip().strip(",")
    if title:
        title = title[0].upper() + title[1:]
    return title[:200]


IDEA_SPLIT = re.compile(
    r",?\s+and\s+(?=i\s+(?:had|have)\s+an?\s+idea|maybe|what if|"
    r"(?:an?\s+|another\s+)?(?:idea|thought|note)\s*:)", re.I)
CLAUSE_SPLIT = re.compile(r",\s*(?:and\s+)?|\s+and\s+(?=(?:i\s+)?(?:need|have|want|should|must)\s+to\b)", re.I)


def parse_capture(text, today):
    """Split free text into tasks and notes. Returns a dict with both."""
    out = {"tasks": [], "notes": [], "people": [], "dates": []}
    if not (text or "").strip():
        return out

    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        for chunk in IDEA_SPLIT.split(sentence):
            chunk = chunk.strip()
            if not chunk:
                continue
            # An idea with no action verb becomes a note, not a task.
            if IDEA_RE.search(chunk) and not ACTION_RE.search(NEED_RE.sub("", chunk)):
                body = re.sub(r"^and\s+", "", chunk, flags=re.I).strip()
                colon = body.find(":")
                title = (body[:colon] if 0 < colon < 80 else body[:60]).strip()
                title = re.sub(r"^i\s+(had|have)\s+an?\s+", "", title, flags=re.I).strip()
                content = body
                if 0 < colon < 80 and re.fullmatch(r"(an?\s+|another\s+)?(idea|thought|note)", title, re.I):
                    rest = body[colon + 1:].strip().rstrip(".!?")
                    label = re.sub(r"^(an?|another)\s+", "", title, flags=re.I)
                    content = rest[:1].upper() + rest[1:]
                    shown = rest if len(rest) <= 50 else rest[:50].rstrip() + "…"
                    title = f"{label.capitalize()}: {shown}"
                out["notes"].append({"title": title[:1].upper() + title[1:], "content": content})
                continue

            for part in CLAUSE_SPLIT.split(chunk):
                part = (part or "").strip()
                if not part or len(part) < 3:
                    continue
                if IDEA_RE.search(part) and not ACTION_RE.search(NEED_RE.sub("", part)):
                    out["notes"].append({"title": _title_from(part)[:80] or "Note", "content": part})
                    continue
                if not (ACTION_RE.search(part) or NEED_RE.search(part)):
                    out["notes"].append({"title": _title_from(part)[:80] or "Note", "content": part})
                    continue
                found = parse_date(part, today)
                title = _title_from(part)
                if not title:
                    continue
                task = {"title": title, "people": _people(part)}
                if found:
                    iso, phrase, kind = found
                    task["due_date" if kind == "due" else "scheduled_date"] = iso
                    out["dates"].append({"date": iso, "phrase": phrase, "kind": kind})
                out["tasks"].append(task)
                for p in task["people"]:
                    if p not in out["people"]:
                        out["people"].append(p)
    return out


def suggest_inbox_action(text, today):
    """What to do with an inbox item, and why."""
    found = parse_date(text, today)
    if IDEA_RE.search(text) and not ACTION_RE.search(text):
        return {"type": "note", "reason": "Looks like an idea or reference"}
    if ACTION_RE.search(text) or NEED_RE.search(text):
        reason = "Looks like a task"
        extra = {}
        if found:
            iso, phrase, kind = found
            reason += f" {kind} {iso}"
            extra["due_date" if kind == "due" else "scheduled_date"] = iso
        return {"type": "task", "reason": reason, **extra}
    return {"type": "note", "reason": "No clear action, so keeping it as a note"}


# ======================================================================
# providers
# ======================================================================

import json
import os
import time
import urllib.error
import urllib.request


PRESETS = {
    "none": {
        "label": "Basic mode (no AI)",
        "help": "Built-in rules only: capture, plan my day or week, overdue, search, move unfinished.",
        "needs_key": False, "format": None, "base_url": "", "model": "", "key_url": "",
    },
    "gemini": {
        "label": "Google Gemini (free tier)",
        "help": "Free key from Google AI Studio, no credit card. Free-tier prompts may be used by "
                "Google to improve its products.",
        "needs_key": True, "format": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash", "key_url": "https://aistudio.google.com/apikey",
    },
    "groq": {
        "label": "Groq (free tier)",
        "help": "Free key, no credit card. Very fast, but the free per-minute token allowance is "
                "small, so long requests can be throttled.",
        "needs_key": True, "format": "openai", "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile", "key_url": "https://console.groq.com/keys",
    },
    "ollama": {
        "label": "Ollama (free, runs on your computer)",
        "help": "No key and no internet needed. Install Ollama, then run: ollama pull llama3.1",
        "needs_key": False, "format": "openai", "base_url": "http://127.0.0.1:11434/v1",
        "model": "llama3.1", "key_url": "https://ollama.com/download",
    },
    "openai_compatible": {
        "label": "Other OpenAI-compatible API",
        "help": "Any service with a /chat/completions endpoint that supports tool calling "
                "(OpenRouter, LM Studio, and so on).",
        "needs_key": False, "format": "openai", "base_url": "", "model": "", "key_url": "",
    },
    "anthropic": {
        "label": "Anthropic Claude (paid)",
        "help": "Best results; needs a paid API key.",
        "needs_key": True, "format": "anthropic", "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-5", "key_url": "https://console.anthropic.com/",
    },
}

FIELDS = ("provider", "api_key", "model", "base_url")


def save_config(store, provider, api_key=None, model=None, base_url=None):
    """Store the choice made on the Settings page."""
    if provider not in PRESETS:
        raise ValidationError(f'Unknown provider "{provider}"')
    current = {f: store.get_settings().get(f"ai.{f}", "") for f in FIELDS}
    model = (model or "").strip()[:300]
    base_url = (base_url or "").strip()[:300]
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ValidationError("The service URL must start with http:// or https://")
    key = (api_key or "").strip()
    if len(key) > 500:
        raise ValidationError("That API key is too long")
    # Keep a saved key only for the same provider at the same address, so a
    # changed URL can never inherit a key that was meant for somewhere else.
    same_target = current["provider"] == provider and current["base_url"] == base_url
    values = {"provider": provider, "api_key": key or (current["api_key"] if same_target else ""),
              "model": model, "base_url": base_url}
    for f in FIELDS:
        store.set_setting(f"ai.{f}", values[f])
    return resolve_config(store)


def resolve_config(store, env=None):
    """Environment variables win over the saved settings."""
    env = os.environ if env is None else env
    source = "app"
    settings = store.get_settings()
    raw = {f: settings.get(f"ai.{f}", "") for f in FIELDS}
    if env.get("AI_PROVIDER"):
        source = "env"
        raw = {"provider": env.get("AI_PROVIDER", ""), "api_key": env.get("AI_API_KEY", ""),
               "model": env.get("AI_MODEL", ""), "base_url": env.get("AI_BASE_URL", "")}
    elif env.get("ANTHROPIC_API_KEY"):
        source = "env"
        raw = {"provider": "anthropic", "api_key": env["ANTHROPIC_API_KEY"],
               "model": env.get("ANTHROPIC_MODEL", ""), "base_url": ""}

    provider = raw["provider"] if raw.get("provider") in PRESETS else "none"
    preset = PRESETS[provider]
    cfg = {
        "provider": provider, "label": preset["label"], "format": preset["format"],
        "api_key": raw.get("api_key") or "",
        "model": raw.get("model") or preset["model"],
        "base_url": (raw.get("base_url") or preset["base_url"]).rstrip("/"),
        "source": source, "help": preset["help"], "key_url": preset["key_url"],
        "needs_key": preset["needs_key"],
    }
    if provider == "none":
        cfg["problem"] = None
    elif preset["needs_key"] and not cfg["api_key"]:
        cfg["problem"] = "Add an API key to turn the AI on."
    elif not cfg["base_url"]:
        cfg["problem"] = "Add the service URL."
    elif not cfg["model"]:
        cfg["problem"] = "Add a model name."
    else:
        cfg["problem"] = None
    cfg["enabled"] = provider != "none" and not cfg["problem"]
    cfg["key_hint"] = f"…{cfg['api_key'][-4:]}" if cfg["api_key"] else ""
    return cfg


# ------------------------------------------------------------------ format
def to_openai_request(body, model):
    """Internal block format -> OpenAI chat format."""
    messages = []
    if body.get("system"):
        messages.append({"role": "system", "content": body["system"]})
    for m in body["messages"]:
        content = m["content"]
        if isinstance(content, str):
            messages.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "\n".join(b["text"] for b in content if b["type"] == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                     for b in content if b["type"] == "tool_use"]
            msg = {"role": "assistant", "content": text or (None if calls else "")}
            if calls:
                msg["tool_calls"] = calls
            messages.append(msg)
        else:
            for b in content:
                if b["type"] == "tool_result":
                    payload = b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])
                    messages.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                     "content": f"Error: {payload}" if b.get("is_error") else payload})
            text = "\n".join(b["text"] for b in content if b["type"] == "text")
            if text:
                messages.append({"role": "user", "content": text})
    req = {"model": model, "max_tokens": body.get("max_tokens", 2048), "messages": messages}
    if body.get("tools"):
        req["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in body["tools"]]
    return req


def from_openai_response(data):
    """OpenAI chat format -> internal block format."""
    choices = data.get("choices") or []
    if not choices:
        raise ValidationError("The AI service returned an empty response")
    msg = choices[0].get("message") or {}
    content = []
    raw = msg.get("content")
    text = raw if isinstance(raw, str) else "".join(p.get("text", "") for p in (raw or []))
    # Some local models wrap private reasoning in <think> tags.
    import re
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    if text:
        content.append({"type": "text", "text": text})
    for i, call in enumerate(msg.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        try:
            parsed = json.loads(args) if isinstance(args, str) and args.strip() else (args or {})
            if not isinstance(parsed, dict):
                raise ValueError
        except Exception:
            parsed = {"_invalid_arguments": str(args)[:500]}
        content.append({"type": "tool_use", "id": call.get("id") or f"call_{i}",
                        "name": fn.get("name"), "input": parsed})
    stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
    return {"content": content, "stop_reason": stop}


class AIUnavailable(Exception):
    """The provider couldn't be reached or refused the request."""


# ------------------------------------------------------------------ http
def _post(url, headers, payload, label, retries=2, timeout=90, opener=None, max_wait=6.0):
    data = json.dumps(payload).encode()
    waited = 0.0
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"content-type": "application/json", **headers})
        try:
            send = opener or urllib.request.urlopen
            with send(req, timeout=timeout) as res:
                return json.loads(res.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode() or "{}")
            except Exception:
                body = {}
            if isinstance(body, list):
                body = body[0] if body else {}
            detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) \
                else body.get("error") or f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                wait = min(2.0 ** attempt, 5.0)
                if waited + wait <= max_wait:
                    waited += wait
                    attempt += 1
                    time.sleep(wait)
                    continue
            if e.code in (401, 403):
                raise AIUnavailable(f"{label} rejected the API key ({detail})")
            if e.code == 429:
                raise AIUnavailable(f"{label} free-tier limit reached. Wait a minute and try again. ({detail})")
            if e.code == 404:
                raise AIUnavailable(f"{label} doesn't recognise the model or URL ({detail})")
            raise AIUnavailable(f"{label} error: {detail}")
        except urllib.error.URLError as e:
            raise AIUnavailable(f"Can't reach {label}. Is it running and is the URL right? ({e.reason})")
        except TimeoutError:
            raise AIUnavailable(f"{label} took too long to answer")


def make_caller(cfg, **opts):
    """Return call_model(body) for the agent loop, or None in basic mode."""
    if not cfg["enabled"]:
        return None
    label = cfg["label"].split(" (")[0]

    def call(body):
        if cfg["format"] == "anthropic":
            payload = {**body, "model": cfg["model"]}
            return _post(f"{cfg['base_url']}/messages",
                         {"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"},
                         payload, label, **opts)
        headers = {"authorization": f"Bearer {cfg['api_key']}"} if cfg["api_key"] else {}
        data = _post(f"{cfg['base_url']}/chat/completions", headers,
                     to_openai_request(body, cfg["model"]), label, **opts)
        return from_openai_response(data)

    return call


def test_connection(cfg, **opts):
    """Used by the Test button on the Settings page."""
    if cfg["provider"] == "none":
        return True, "Basic mode needs no connection."
    if not cfg["enabled"]:
        return False, cfg["problem"]
    call = make_caller(cfg, retries=0, **opts)
    started = time.time()
    try:
        res = call({"max_tokens": 50, "system": "Reply with the single word OK.",
                    "messages": [{"role": "user", "content": "Ping"}]})
        text = " ".join(b["text"] for b in res["content"] if b["type"] == "text").strip()
        ms = int((time.time() - started) * 1000)
        return True, f"Connected to {cfg['label']} ({cfg['model']}) in {ms} ms." + (f' Reply: "{text[:40]}"' if text else "")
    except Exception as e:
        return False, str(e)


# ======================================================================
# agent
# ======================================================================

import json


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
        return [{**item, "suggestion": suggest_inbox_action(item["text"], today)}
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
    parsed = parse_capture(message, today)
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


# ======================================================================
# Streamlit interface
# ======================================================================

import os

import streamlit as st



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


PAGES = ["Today", "Inbox", "Tasks", "Calendar", "Notes", "Projects", "Goals", "Search", "Settings"]


@st.cache_resource
def get_store(path: str) -> Store:
    return Store(connect(path))




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
        run(lambda: apply_schedule(store, [{"id": t["id"], "to": plan["date"]} for t in plan["placed"]]),
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
        parsed = parse_capture(text, ctx["today"])
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
            state["day_plan"] = day_plan(store, ctx["today"], minutes, ctx["now"])
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
        suggestion = suggest_inbox_action(item["text"], ctx["today"])
        with st.container(border=True):
            st.markdown(item["text"])
            st.caption(f"Suggested: {suggestion['type']} — {suggestion['reason']}")
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Make task", key=f"it-{item['id']}",
                         type="primary" if suggestion["type"] == "task" else "secondary"):
                run(lambda: run_tool_unchecked(store, "process_inbox_item",
                                                  {"id": item["id"], "type": "task",
                                                   "due_date": suggestion.get("due_date")}, ctx), "Task created")
                st.rerun()
            if c2.button("Make note", key=f"in-{item['id']}",
                         type="primary" if suggestion["type"] == "note" else "secondary"):
                run(lambda: run_tool_unchecked(store, "process_inbox_item",
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
        state["week_proposal"] = week_plan(store, state["week_start"], ctx["now"])
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
                run(lambda: apply_schedule(store, proposal["changes"]), "Plan applied")
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
                parsed = parse_capture(content, ctx["today"])
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
    cfg = resolve_config(store)
    if cfg["source"] == "env":
        st.info("The AI provider is set in your environment. Remove AI_PROVIDER to manage it here.")
    ids = list(PRESETS)
    labels = {i: PRESETS[i]["label"] for i in ids}
    chosen = st.selectbox("Provider", ids, index=ids.index(cfg["provider"]),
                          format_func=lambda i: labels[i], disabled=cfg["source"] == "env")
    preset = PRESETS[chosen]
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
        saved = run(lambda: save_config(store, chosen, key, model, base_url), "AI settings saved")
        if saved:
            st.rerun()
    if c2.button("Test connection"):
        with st.spinner("Testing…"):
            ok, message = test_connection(resolve_config(store))
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
        cfg = resolve_config(store)
        st.caption(f"AI on · {cfg['label']}" if cfg["enabled"] else "Basic mode")
        if not cfg["enabled"]:
            st.caption("Connect a free AI on the Settings page for full natural-language help.")

        for pending in store.open_pending():
            with st.container(border=True):
                st.write(f"**Confirm:** {pending['summary']}")
                c1, c2 = st.columns(2)
                if c1.button("Confirm", key=f"pc-{pending['id']}", type="primary"):
                    run(lambda: resolve_pending(store, pending["id"], "confirm", ctx), "Done")
                    st.rerun()
                if c2.button("Cancel", key=f"px-{pending['id']}"):
                    run(lambda: resolve_pending(store, pending["id"], "reject", ctx), "Cancelled")
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
                    out = chat(store, prompt, ctx)
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


def main():
    global store, ctx, state
    st.set_page_config(page_title="Planner", page_icon="🗓️", layout="wide",
                       initial_sidebar_state="expanded")
    load_secrets()
    store = get_store(os.environ.get("DATABASE_PATH", "data/planner.db"))
    ctx = {"today": today_str(), "now": now_hm()}
    state = st.session_state
    state.setdefault("chat", [])
    state.setdefault("week_start", week_start(ctx["today"]))
    state.setdefault("week_proposal", None)
    state.setdefault("day_plan", None)
    state.setdefault("open_note", None)

    page = st.sidebar.radio("Go to", PAGES, label_visibility="collapsed")
    st.sidebar.divider()
    show_flashes()
    {"Today": page_today, "Inbox": page_inbox, "Tasks": page_tasks, "Calendar": page_calendar,
     "Notes": page_notes, "Projects": page_projects, "Goals": page_goals, "Search": page_search,
     "Settings": page_settings}[page]()
    assistant_sidebar()


# Streamlit runs this file as __main__; tests import it without starting the UI.
if __name__ == "__main__":
    main()
