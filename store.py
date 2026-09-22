"""Data layer: schema, validation and every read/write the app performs.

Nothing above this module touches SQL, so the Streamlit pages and the AI agent
share exactly the same business rules.
"""
from __future__ import annotations

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
