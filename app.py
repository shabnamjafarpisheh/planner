"""Planner: an AI note and planning assistant for Streamlit, with accounts.

Everything is in this one file, so it runs as long as app.py and
requirements.txt are present (for example on Streamlit Community Cloud).

Run with:  streamlit run app.py

Sections, in order: store (accounts, database, rules) -> planning ->
capture -> providers (AI connections) -> agent -> Streamlit interface.
"""
from __future__ import annotations



# ======================================================================
# store
# ======================================================================

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date as _date, datetime, timedelta
from pathlib import Path

DEFAULT_ESTIMATE_MIN = 30
STATUSES = ["inbox", "planned", "in_progress", "completed", "cancelled"]
PRIORITIES = {1: "Urgent", 2: "High", 3: "Normal", 4: "Low"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SCHEMA_VERSION = 3

# Password hashing: PBKDF2-SHA256 at the OWASP-recommended work factor.
# Stored per user so the factor can be raised later without breaking logins.
PASSWORD_ITERATIONS = 600_000
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 10
MIN_PASSWORD_LEN = 8
SESSION_DAYS = 30


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
    parse_iso(value)
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
        raise ValidationError(f'"{hhmm}" is not a time. Use HH:MM, for example 09:30.')
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def from_min(total: int) -> str:
    total = max(0, min(24 * 60 - 1, int(total)))
    return f"{total // 60:02d}:{total % 60:02d}"


def human_minutes(total: int) -> str:
    h, m = divmod(int(total), 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def now_hm() -> str:
    return datetime.now().strftime("%H:%M")


def clean_text(value, field, limit=2000, required=True):
    text = value.strip() if isinstance(value, str) else ""
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
    parts = tags.replace("#", "").split(",") if isinstance(tags, str) else [str(t) for t in tags]
    seen, out = set(), []
    for p in parts:
        t = p.strip().lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out[:12])


def derive_title(content: str) -> str:
    first = next((line.strip() for line in (content or "").splitlines() if line.strip()), "")
    return first[:77] + "…" if len(first) > 80 else first


# ---------------------------------------------------------------- schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  iterations INTEGER NOT NULL,
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  onboarded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  deadline TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  due_date TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, name)
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  date TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  fact TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (user_id, fact)
);
CREATE TABLE IF NOT EXISTS pending_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tool TEXT NOT NULL,
  args TEXT NOT NULL,
  summary TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  actor TEXT NOT NULL DEFAULT 'user',
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_user_due ON tasks(user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_user_sched ON tasks(user_id, scheduled_date);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_events_user_date ON events(user_id, date);
"""

DEFAULT_SETTINGS = {"workday_start": "09:00", "workday_end": "18:00"}
LEGACY_TABLES = ["settings", "goals", "projects", "tasks", "task_dependencies", "notes",
                 "events", "inbox_items", "memories", "activity", "messages", "pending_actions"]


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _set_aside_legacy(conn):
    """A database from the single-user version has tables without user_id.
    Rename them so the new schema can be created; the first account made
    afterwards takes the old data over (see Accounts.create)."""
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "tasks" not in names or "user_id" in _columns(conn, "tasks"):
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    for t in LEGACY_TABLES:
        if t in names and f"legacy_{t}" not in names:
            conn.execute(f"ALTER TABLE {t} RENAME TO legacy_{t}")
    conn.commit()


def connect(path: str = "data/planner.db") -> sqlite3.Connection:
    """Open the database, creating the file and tables if needed.

    Use one connection per browser session: a shared connection would mix
    different people's transactions together.
    """
    if path != ":memory:":
        Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    _set_aside_legacy(conn)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn


# ---------------------------------------------------------------- accounts
def _hash(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()


EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def check_password_rules(password: str):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise ValidationError(f"Use at least {MIN_PASSWORD_LEN} characters for your password.")
    if len(password) > 200:
        raise ValidationError("That password is too long (max 200 characters).")
    if len(set(password)) < 4:
        raise ValidationError("That password is too easy to guess. Mix in a few different characters.")


class Accounts:
    """Sign-up, sign-in and account changes. Separate from Store because it
    works before anyone is signed in."""

    def __init__(self, conn: sqlite3.Connection, iterations: int = PASSWORD_ITERATIONS):
        self.conn = conn
        self.iterations = iterations

    def _user(self, sql, args):
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def create(self, email, password, name=""):
        email = clean_text(email, "Email", 254).lower()
        if not EMAIL_RE.match(email):
            raise ValidationError("Enter a valid email address, like name@example.com.")
        name = clean_text(name, "Name", 80, required=False)
        check_password_rules(password)
        if self._user("SELECT id FROM users WHERE email = ?", (email,)):
            raise ValidationError("An account with this email already exists. Sign in instead.")
        salt = secrets.token_hex(16)
        with_legacy = self._has_legacy() and not self._user("SELECT id FROM users LIMIT 1", ())
        try:
            try:
                cur = self.conn.execute(
                    "INSERT INTO users (email, name, password_hash, salt, iterations) VALUES (?, ?, ?, ?, ?)",
                    (email, name, _hash(password, salt, self.iterations), salt, self.iterations))
            except sqlite3.IntegrityError:  # someone signed up with it a moment ago
                raise ValidationError("An account with this email already exists. Sign in instead.")
            uid = cur.lastrowid
            for k, v in DEFAULT_SETTINGS.items():
                self.conn.execute("INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?)", (uid, k, v))
            if with_legacy:
                self._adopt_legacy(uid)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if with_legacy:
            self._drop_legacy()
        return self.public(uid)

    def authenticate(self, email, password):
        """Returns the user on success. Failures say the same thing whether
        the email or the password was wrong, and repeated failures lock the
        account for a few minutes."""
        email = (email or "").strip().lower()
        user = self._user("SELECT * FROM users WHERE email = ?", (email,))
        generic = ValidationError("That email and password don't match. Check them and try again.")
        if not user:
            _hash(password or "", "00" * 16, self.iterations)  # same work, so timing doesn't reveal it
            raise generic
        now = datetime.now()
        if user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > now:
            wait = max(1, int((datetime.fromisoformat(user["locked_until"]) - now).total_seconds() // 60) + 1)
            raise ValidationError(f"Too many attempts. Try again in {wait} minute(s).")
        if not hmac.compare_digest(_hash(password or "", user["salt"], user["iterations"]), user["password_hash"]):
            failed = user["failed_logins"] + 1
            locked = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds") \
                if failed >= MAX_FAILED_LOGINS else None
            self.conn.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                              (0 if locked else failed, locked, user["id"]))
            self.conn.commit()
            if locked:
                raise ValidationError(f"Too many attempts. Try again in {LOCKOUT_MINUTES} minutes.")
            raise generic
        self.conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL, "
                          "last_login_at = datetime('now') WHERE id = ?", (user["id"],))
        self.conn.commit()
        return self.public(user["id"])

    # -- "keep me signed in"
    def start_session(self, uid, days=SESSION_DAYS):
        """Returns a random token for the browser; only its hash is stored,
        so a copy of the database can't be used to sign in."""
        token = secrets.token_urlsafe(32)
        expires = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
        self.conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(timespec="seconds"),))
        self.conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                          (hashlib.sha256(token.encode()).hexdigest(), uid, expires))
        self.conn.commit()
        return token

    def user_from_session(self, token):
        if not token or not isinstance(token, str) or len(token) > 200:
            return None
        row = self._user("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
                         (hashlib.sha256(token.encode()).hexdigest(),))
        if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return None
        try:
            return self.public(row["user_id"])
        except NotFound:
            return None

    def end_session(self, token):
        if token:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
            self.conn.commit()

    def end_all_sessions(self, uid):
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        self.conn.commit()

    def public(self, uid):
        u = self._user("SELECT id, email, name, onboarded, created_at FROM users WHERE id = ?", (uid,))
        if not u:
            raise NotFound("That account no longer exists.")
        return u

    def update_name(self, uid, name):
        name = clean_text(name, "Name", 80, required=False)
        self.conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, uid))
        self.conn.commit()
        return self.public(uid)

    def set_onboarded(self, uid):
        self.conn.execute("UPDATE users SET onboarded = 1 WHERE id = ?", (uid,))
        self.conn.commit()

    def _verify(self, uid, password):
        u = self._user("SELECT * FROM users WHERE id = ?", (uid,))
        if not u or not hmac.compare_digest(_hash(password or "", u["salt"], u["iterations"]), u["password_hash"]):
            raise ValidationError("Your current password isn't right.")

    def change_password(self, uid, current, new):
        self._verify(uid, current)
        check_password_rules(new)
        salt = secrets.token_hex(16)
        self.conn.execute("UPDATE users SET password_hash = ?, salt = ?, iterations = ? WHERE id = ?",
                          (_hash(new, salt, self.iterations), salt, self.iterations, uid))
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))  # sign out other devices
        self.conn.commit()

    def delete(self, uid, password):
        """Deletes the account and everything in it."""
        self._verify(uid, password)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        self.conn.commit()

    # -- data from the single-user version
    def _has_legacy(self):
        return bool(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='legacy_tasks'").fetchone())

    def _adopt_legacy(self, uid):
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        order = ["goals", "projects", "tasks", "task_dependencies", "notes", "events",
                 "inbox_items", "memories", "activity", "messages"]
        for t in order:
            if f"legacy_{t}" not in names:
                continue
            old = _columns(self.conn, f"legacy_{t}")
            info = {r[1]: r for r in self.conn.execute(f"PRAGMA table_info({t})")}
            shared = [c for c in old if c in info and c != "user_id"]
            # Old rows may hold NULL where the new table needs a value; use the
            # column's default instead of dropping the row.
            exprs = [f"COALESCE({c}, {info[c][4]})" if info[c][3] and info[c][4] is not None else c
                     for c in shared]
            cols, select = ", ".join(shared), ", ".join(exprs)
            if "user_id" in info:
                self.conn.execute(f"INSERT INTO {t} (user_id, {cols}) SELECT ?, {select} FROM legacy_{t}", (uid,))
            else:
                self.conn.execute(f"INSERT INTO {t} ({cols}) SELECT {select} FROM legacy_{t}")
        if "legacy_settings" in names:
            self.conn.execute("INSERT OR REPLACE INTO settings (user_id, key, value) "
                              "SELECT ?, key, value FROM legacy_settings", (uid,))

    def _drop_legacy(self):
        """Remove the old tables once their data is safely copied. The old
        tables point at each other, so foreign-key checks are paused (that
        can only change outside a transaction, hence a separate step)."""
        names = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'legacy_%'")]
        if not names:
            return
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            for n in names:
                self.conn.execute(f"DROP TABLE IF EXISTS {n}")
            self.conn.commit()
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")


# ---------------------------------------------------------------- store
class Store:
    """Every read and write for one signed-in person."""

    def __init__(self, conn: sqlite3.Connection, user_id: int, actor: str = "user"):
        if not user_id:
            raise ValidationError("Sign in first.")
        self.conn = conn
        self.uid = int(user_id)
        self.actor = actor

    # ------------------------------------------------------------ plumbing
    @contextmanager
    def tx(self):
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
        self.conn.execute("INSERT INTO activity (user_id, actor, action, detail) VALUES (?, ?, ?, ?)",
                          (self.uid, self.actor, action, detail[:300]))

    def recent_activity(self, limit=30):
        return self._q("SELECT * FROM activity WHERE user_id = ? ORDER BY id DESC LIMIT ?", (self.uid, limit))

    # ------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        out.update({r["key"]: r["value"] for r in
                    self._q("SELECT key, value FROM settings WHERE user_id = ?", (self.uid,))})
        return out

    def set_setting(self, key, value):
        with self.tx() as c:
            c.execute("INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
                      "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (self.uid, key, value))

    def update_hours(self, start, end):
        if to_min(end) <= to_min(start):
            raise ValidationError("The end of the workday must be after the start.")
        self.set_setting("workday_start", start)
        self.set_setting("workday_end", end)

    # ------------------------------------------------------------ projects
    def project_by_name(self, name, create=True):
        name = clean_text(name, "project name", 120, required=False)
        if not name:
            return None
        found = self._one("SELECT * FROM projects WHERE user_id = ? AND lower(name) = lower(?)", (self.uid, name))
        if found or not create:
            return found
        return self.create_project(name=name)

    def create_project(self, name, description="", goal_id=None, due_date=None):
        name = clean_text(name, "Project name", 120)
        if self._one("SELECT id FROM projects WHERE user_id = ? AND lower(name) = lower(?)", (self.uid, name)):
            raise ValidationError(f'You already have a project called "{name}".')
        check_date(due_date, "due_date")
        if goal_id:
            self.get_goal(goal_id)
        with self.tx() as c:
            cur = c.execute("INSERT INTO projects (user_id, name, description, goal_id, due_date) VALUES (?, ?, ?, ?, ?)",
                            (self.uid, name, clean_text(description, "description", 4000, False), goal_id, due_date or None))
            self.log("create_project", name)
        return self.get_project(cur.lastrowid)

    def get_project(self, pid):
        p = self._one("SELECT * FROM projects WHERE id = ? AND user_id = ?", (pid, self.uid))
        if not p:
            raise NotFound(f"No project with id {pid}")
        p["tasks"] = self.list_tasks(project_id=pid)
        p["notes"] = self._q("SELECT * FROM notes WHERE project_id = ? AND user_id = ? ORDER BY updated_at DESC",
                             (pid, self.uid))
        live = [t for t in p["tasks"] if t["status"] != "cancelled"]
        done = [t for t in live if t["status"] == "completed"]
        p["progress"] = round(100 * len(done) / len(live)) if live else 0
        return p

    def list_projects(self):
        rows = self._q("SELECT * FROM projects WHERE user_id = ? ORDER BY status, name", (self.uid,))
        for p in rows:
            c = self._one("SELECT COUNT(*) AS total, SUM(status = 'completed') AS done FROM tasks "
                          "WHERE project_id = ? AND user_id = ? AND status != 'cancelled'", (p["id"], self.uid))
            p["task_count"], p["done_count"] = c["total"] or 0, c["done"] or 0
            p["progress"] = round(100 * p["done_count"] / p["task_count"]) if p["task_count"] else 0
        return rows

    def update_project(self, pid, **fields):
        self.get_project(pid)
        allowed = {k: v for k, v in fields.items() if k in ("name", "description", "goal_id", "due_date", "status")}
        if "due_date" in allowed:
            check_date(allowed["due_date"], "due_date")
        if allowed.get("goal_id"):
            self.get_goal(allowed["goal_id"])
        if not allowed:
            return self.get_project(pid)
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE projects SET {sets} WHERE id = ? AND user_id = ?", (*allowed.values(), pid, self.uid))
            self.log("update_project", str(pid))
        return self.get_project(pid)

    def delete_project(self, pid):
        p = self.get_project(pid)
        with self.tx() as c:
            c.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (pid, self.uid))
            self.log("delete_project", p["name"])
        return {"deleted": pid, "name": p["name"]}

    # ------------------------------------------------------------ goals
    def create_goal(self, title, description="", deadline=None):
        title = clean_text(title, "Goal", 200)
        check_date(deadline, "deadline")
        with self.tx() as c:
            cur = c.execute("INSERT INTO goals (user_id, title, description, deadline) VALUES (?, ?, ?, ?)",
                            (self.uid, title, clean_text(description, "description", 4000, False), deadline or None))
            self.log("create_goal", title)
        return self.get_goal(cur.lastrowid)

    def get_goal(self, gid):
        g = self._one("SELECT * FROM goals WHERE id = ? AND user_id = ?", (gid, self.uid))
        if not g:
            raise NotFound(f"No goal with id {gid}")
        g["projects"] = self._q("SELECT * FROM projects WHERE goal_id = ? AND user_id = ? ORDER BY name", (gid, self.uid))
        tasks = self._q("SELECT * FROM tasks WHERE user_id = ? AND (goal_id = ? OR project_id IN "
                        "(SELECT id FROM projects WHERE goal_id = ? AND user_id = ?))", (self.uid, gid, gid, self.uid))
        live = [t for t in tasks if t["status"] != "cancelled"]
        done = [t for t in live if t["status"] == "completed"]
        g["task_count"], g["done_count"] = len(live), len(done)
        g["progress"] = round(100 * len(done) / len(live)) if live else 0
        return g

    def list_goals(self):
        ids = self._q("SELECT id FROM goals WHERE user_id = ? ORDER BY status, deadline IS NULL, deadline", (self.uid,))
        return [self.get_goal(r["id"]) for r in ids]

    def update_goal(self, gid, **fields):
        self.get_goal(gid)
        allowed = {k: v for k, v in fields.items() if k in ("title", "description", "deadline", "status")}
        if "deadline" in allowed:
            check_date(allowed["deadline"], "deadline")
        if not allowed:
            return self.get_goal(gid)
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE goals SET {sets} WHERE id = ? AND user_id = ?", (*allowed.values(), gid, self.uid))
            self.log("update_goal", str(gid))
        return self.get_goal(gid)

    def delete_goal(self, gid):
        g = self.get_goal(gid)
        with self.tx() as c:
            c.execute("DELETE FROM goals WHERE id = ? AND user_id = ?", (gid, self.uid))
            self.log("delete_goal", g["title"])
        return {"deleted": gid, "title": g["title"]}

    def breakdown_goal(self, title, projects, deadline=None, description=""):
        """A goal with its projects and their tasks, all or nothing."""
        if not projects:
            raise ValidationError("Give at least one project for the goal")
        with self.tx() as c:
            gid = c.execute("INSERT INTO goals (user_id, title, description, deadline) VALUES (?, ?, ?, ?)",
                            (self.uid, clean_text(title, "Goal", 200),
                             clean_text(description, "description", 4000, False),
                             check_date(deadline, "deadline"))).lastrowid
            made = []
            for spec in projects:
                pname = clean_text(spec.get("name"), "project name", 120)
                if self._one("SELECT id FROM projects WHERE user_id = ? AND lower(name) = lower(?)", (self.uid, pname)):
                    pname = f"{pname} ({title})"[:120]
                pid = c.execute("INSERT INTO projects (user_id, name, goal_id, due_date) VALUES (?, ?, ?, ?)",
                                (self.uid, pname, gid, check_date(spec.get("due_date"), "due_date"))).lastrowid
                for t in spec.get("tasks") or []:
                    is_dict = isinstance(t, dict)
                    c.execute("INSERT INTO tasks (user_id, title, status, project_id, goal_id, due_date, estimate_min) "
                              "VALUES (?, ?, 'planned', ?, ?, ?, ?)",
                              (self.uid, clean_text(t.get("title") if is_dict else t, "task title", 200), pid, gid,
                               check_date(t.get("due_date") if is_dict else None, "due_date"),
                               t.get("estimate_min") if is_dict else None))
                made.append(pid)
            self.log("breakdown_goal", title)
        return {"goal": self.get_goal(gid), "projects": [self.get_project(p) for p in made]}

    # ------------------------------------------------------------ tasks
    def _own_or_none(self, table, rid):
        if rid in (None, "", 0):
            return None
        if not self._one(f"SELECT id FROM {table} WHERE id = ? AND user_id = ?", (rid, self.uid)):
            raise NotFound(f"No {table[:-1]} with id {rid}")
        return rid

    def create_task(self, title, description="", status=None, priority=3, due_date=None,
                    scheduled_date=None, estimate_min=None, project=None, project_id=None,
                    goal_id=None, parent_id=None, tags=None):
        title = clean_text(title, "Task", 200)
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
        project_id = self._own_or_none("projects", project_id)
        goal_id = self._own_or_none("goals", goal_id)
        parent_id = self._own_or_none("tasks", parent_id)
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO tasks (user_id, title, description, status, priority, due_date, scheduled_date, "
                "estimate_min, project_id, goal_id, parent_id, tags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.uid, title, clean_text(description, "description", 4000, False), status, priority,
                 due_date or None, scheduled_date or None, estimate_min, project_id, goal_id, parent_id,
                 norm_tags(tags)))
            self.log("create_task", title)
        return self.get_task(cur.lastrowid)

    def get_task(self, tid):
        t = self._one("SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
                      "WHERE t.id = ? AND t.user_id = ?", (tid, self.uid))
        if not t:
            raise NotFound(f"No task with id {tid}")
        t["subtasks"] = self._q("SELECT * FROM tasks WHERE parent_id = ? AND user_id = ? ORDER BY id", (tid, self.uid))
        t["blocked_by"] = self._q("SELECT t.id, t.title, t.status FROM task_dependencies d "
                                  "JOIN tasks t ON t.id = d.depends_on_id WHERE d.task_id = ? AND t.user_id = ?",
                                  (tid, self.uid))
        return t

    def list_tasks(self, status=None, open_only=False, project_id=None, goal_id=None,
                   due_before=None, scheduled_on=None, query=None, limit=500):
        sql = ("SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
               "WHERE t.user_id = ?")
        args = [self.uid]
        if status:
            status = [status] if isinstance(status, str) else list(status)
            sql += f" AND t.status IN ({','.join('?' * len(status))})"
            args += status
        if open_only:
            sql += " AND t.status IN ('inbox','planned','in_progress')"
        if project_id:
            sql += " AND t.project_id = ?"
            args.append(project_id)
        if goal_id:
            sql += " AND (t.goal_id = ? OR t.project_id IN (SELECT id FROM projects WHERE goal_id = ? AND user_id = ?))"
            args += [goal_id, goal_id, self.uid]
        if due_before:
            sql += " AND t.due_date IS NOT NULL AND t.due_date <= ?"
            args.append(due_before)
        if scheduled_on:
            sql += " AND t.scheduled_date = ?"
            args.append(scheduled_on)
        if query:
            sql += " AND (t.title LIKE ? OR t.description LIKE ? OR t.tags LIKE ?)"
            args += [f"%{query}%"] * 3
        sql += " ORDER BY t.status = 'completed', t.priority, t.due_date IS NULL, t.due_date, t.id DESC LIMIT ?"
        args.append(limit)
        return self._q(sql, args)

    def update_task(self, tid, **fields):
        current = self.get_task(tid)
        allowed = {k: v for k, v in fields.items() if k in (
            "title", "description", "status", "priority", "due_date", "scheduled_date",
            "estimate_min", "project_id", "goal_id", "tags")}
        if "project" in fields and "project_id" not in allowed:
            p = self.project_by_name(fields["project"])
            allowed["project_id"] = p["id"] if p else None
        if "project_id" in allowed:
            allowed["project_id"] = self._own_or_none("projects", allowed["project_id"])
        if "goal_id" in allowed:
            allowed["goal_id"] = self._own_or_none("goals", allowed["goal_id"])
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
            allowed["title"] = clean_text(allowed["title"], "Task", 200)
        if not allowed:
            return current
        if allowed.get("status") == "completed" and current["status"] != "completed":
            allowed["completed_at"] = datetime.now().isoformat(timespec="seconds")
        elif allowed.get("status") and allowed["status"] != "completed":
            allowed["completed_at"] = None
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE tasks SET {sets} WHERE id = ? AND user_id = ?", (*allowed.values(), tid, self.uid))
            self.log("update_task", str(tid))
        return self.get_task(tid)

    def complete_task(self, tid):
        t = self.get_task(tid)
        waiting = [d for d in t["blocked_by"] if d["status"] not in ("completed", "cancelled")]
        result = self.update_task(tid, status="completed")
        result["warning"] = f"Note: this was waiting on {waiting[0]['title']}, which isn't done." if waiting else None
        return result

    def reopen_task(self, tid):
        return self.update_task(tid, status="planned")

    def reschedule_task(self, tid, date):
        check_date(date, "date", required=True)
        t = self.get_task(tid)
        return self.update_task(tid, scheduled_date=date,
                                status="planned" if t["status"] == "inbox" else t["status"])

    def bulk_reschedule(self, ids, date):
        check_date(date, "date", required=True)
        ids = [int(i) for i in ids]
        if not ids:
            raise ValidationError("No tasks given")
        with self.tx() as c:
            for tid in ids:
                if not self._one("SELECT id FROM tasks WHERE id = ? AND user_id = ?", (tid, self.uid)):
                    raise NotFound(f"No task with id {tid}")  # rolls the whole move back
                c.execute("UPDATE tasks SET scheduled_date = ?, status = CASE WHEN status = 'inbox' "
                          "THEN 'planned' ELSE status END WHERE id = ? AND user_id = ?", (date, tid, self.uid))
            self.log("bulk_reschedule", f"{len(ids)} tasks to {date}")
        return {"moved": len(ids), "date": date, "ids": ids}

    def delete_task(self, tid):
        t = self.get_task(tid)
        with self.tx() as c:
            c.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (tid, self.uid))
            self.log("delete_task", t["title"])
        return {"deleted": tid, "title": t["title"]}

    def split_task(self, tid, subtasks):
        parent = self.get_task(tid)
        if not subtasks:
            raise ValidationError("Give at least one subtask")
        made = []
        with self.tx() as c:
            for s in subtasks:
                is_dict = isinstance(s, dict)
                made.append(c.execute(
                    "INSERT INTO tasks (user_id, title, status, priority, project_id, goal_id, parent_id, due_date, "
                    "estimate_min) VALUES (?, ?, 'planned', ?, ?, ?, ?, ?, ?)",
                    (self.uid, clean_text(s.get("title") if is_dict else s, "subtask title", 200),
                     parent["priority"], parent["project_id"], parent["goal_id"], tid, parent["due_date"],
                     s.get("estimate_min") if is_dict else None)).lastrowid)
            for earlier, later in zip(made, made[1:]):
                c.execute("INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)", (later, earlier))
            self.log("split_task", parent["title"])
        return {"parent": self.get_task(tid), "subtasks": [self.get_task(i) for i in made]}

    def add_dependency(self, task_id, depends_on_id):
        task_id, depends_on_id = int(task_id), int(depends_on_id)
        if task_id == depends_on_id:
            raise ValidationError("A task can't wait on itself")
        self.get_task(task_id)
        self.get_task(depends_on_id)  # both must belong to this person
        seen, stack = set(), [depends_on_id]
        while stack:
            cur = stack.pop()
            if cur == task_id:
                raise ValidationError("That would make two tasks wait on each other")
            if cur not in seen:
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
        return [t for t in self.list_tasks(open_only=True) if t["scheduled_date"] and t["scheduled_date"] < today]

    def streak(self, today):
        """Days in a row, ending today or yesterday, with at least one task done."""
        days = {r["d"] for r in self._q(
            "SELECT DISTINCT date(completed_at) AS d FROM tasks WHERE user_id = ? AND status = 'completed' "
            "AND completed_at IS NOT NULL", (self.uid,))}
        cursor = today if today in days else add_days(today, -1)
        count = 0
        while cursor in days:
            count += 1
            cursor = add_days(cursor, -1)
        return count

    # ------------------------------------------------------------ notes
    def create_note(self, title=None, content="", project=None, project_id=None, goal_id=None, tags=None):
        content = clean_text(content, "content", 20000, required=False)
        title = clean_text(title, "title", 200, required=False) or derive_title(content) or "Untitled note"
        if project and not project_id:
            p = self.project_by_name(project)
            project_id = p["id"] if p else None
        project_id = self._own_or_none("projects", project_id)
        goal_id = self._own_or_none("goals", goal_id)
        with self.tx() as c:
            cur = c.execute("INSERT INTO notes (user_id, title, content, project_id, goal_id, tags) VALUES (?, ?, ?, ?, ?, ?)",
                            (self.uid, title, content, project_id, goal_id, norm_tags(tags)))
            self.log("create_note", title)
        return self.get_note(cur.lastrowid)

    def get_note(self, nid):
        n = self._one("SELECT n.*, p.name AS project_name FROM notes n LEFT JOIN projects p ON p.id = n.project_id "
                      "WHERE n.id = ? AND n.user_id = ?", (nid, self.uid))
        if not n:
            raise NotFound(f"No note with id {nid}")
        return n

    def list_notes(self, project_id=None, query=None, since=None, limit=200):
        sql = ("SELECT n.*, p.name AS project_name FROM notes n LEFT JOIN projects p ON p.id = n.project_id "
               "WHERE n.user_id = ?")
        args = [self.uid]
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
        allowed = {k: v for k, v in fields.items() if k in ("title", "content", "project_id", "goal_id", "tags")}
        if "project" in fields and "project_id" not in allowed:
            p = self.project_by_name(fields["project"])
            allowed["project_id"] = p["id"] if p else None
        if "project_id" in allowed:
            allowed["project_id"] = self._own_or_none("projects", allowed["project_id"])
        if "tags" in allowed:
            allowed["tags"] = norm_tags(allowed["tags"])
        if "title" in allowed:
            allowed["title"] = clean_text(allowed["title"], "title", 200, required=False) or "Untitled note"
        if not allowed:
            return self.get_note(nid)
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.tx() as c:
            c.execute(f"UPDATE notes SET {sets}, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
                      (*allowed.values(), nid, self.uid))
            self.log("update_note", str(nid))
        return self.get_note(nid)

    def delete_note(self, nid):
        n = self.get_note(nid)
        with self.tx() as c:
            c.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (nid, self.uid))
            self.log("delete_note", n["title"])
        return {"deleted": nid, "title": n["title"]}

    # ------------------------------------------------------------ events
    def create_event(self, title, date, start_time, end_time):
        title = clean_text(title, "Event", 200)
        check_date(date, "date", required=True)
        if to_min(end_time) <= to_min(start_time):
            raise ValidationError("The event must end after it starts.")
        with self.tx() as c:
            cur = c.execute("INSERT INTO events (user_id, title, date, start_time, end_time) VALUES (?, ?, ?, ?, ?)",
                            (self.uid, title, date, start_time, end_time))
            self.log("create_event", title)
        return self._one("SELECT * FROM events WHERE id = ?", (cur.lastrowid,))

    def list_events(self, start=None, end=None):
        if start and end:
            return self._q("SELECT * FROM events WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date, start_time",
                           (self.uid, start, end))
        if start:
            return self._q("SELECT * FROM events WHERE user_id = ? AND date = ? ORDER BY start_time", (self.uid, start))
        return self._q("SELECT * FROM events WHERE user_id = ? ORDER BY date, start_time", (self.uid,))

    def delete_event(self, eid):
        with self.tx() as c:
            c.execute("DELETE FROM events WHERE id = ? AND user_id = ?", (eid, self.uid))
            self.log("delete_event", str(eid))
        return {"deleted": eid}

    # ------------------------------------------------------------ inbox
    def add_inbox(self, text):
        text = clean_text(text, "Thought", 4000)
        with self.tx() as c:
            cur = c.execute("INSERT INTO inbox_items (user_id, text) VALUES (?, ?)", (self.uid, text))
            self.log("add_inbox", text[:60])
        return self._one("SELECT * FROM inbox_items WHERE id = ?", (cur.lastrowid,))

    def list_inbox(self, status="open"):
        return self._q("SELECT * FROM inbox_items WHERE user_id = ? AND status = ? ORDER BY id DESC", (self.uid, status))

    def close_inbox(self, iid, status="done"):
        with self.tx() as c:
            c.execute("UPDATE inbox_items SET status = ? WHERE id = ? AND user_id = ?", (status, iid, self.uid))
        return {"id": iid, "status": status}

    def delete_inbox(self, iid):
        with self.tx() as c:
            c.execute("DELETE FROM inbox_items WHERE id = ? AND user_id = ?", (iid, self.uid))
            self.log("delete_inbox", str(iid))
        return {"deleted": iid}

    # ------------------------------------------------------------ memories
    def remember(self, fact):
        fact = clean_text(fact, "fact", 500)
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO memories (user_id, fact) VALUES (?, ?)", (self.uid, fact))
            self.log("remember", fact[:60])
        return {"fact": fact}

    def list_memories(self):
        return self._q("SELECT * FROM memories WHERE user_id = ? ORDER BY id DESC", (self.uid,))

    def forget(self, mid):
        with self.tx() as c:
            c.execute("DELETE FROM memories WHERE id = ? AND user_id = ?", (mid, self.uid))
        return {"deleted": mid}

    # ------------------------------------------------------------ search
    def search(self, query, limit=40):
        q = clean_text(query, "Search", 200)
        tasks = self.list_tasks(query=q, limit=limit)
        notes = self.list_notes(query=q, limit=limit)
        like = f"%{q}%"
        projects = self._q("SELECT * FROM projects WHERE user_id = ? AND (name LIKE ? OR description LIKE ?)",
                           (self.uid, like, like))
        goals = self._q("SELECT * FROM goals WHERE user_id = ? AND (title LIKE ? OR description LIKE ?)",
                        (self.uid, like, like))
        seen_t, seen_n = {t["id"] for t in tasks}, {n["id"] for n in notes}
        for p in projects:  # a matching project brings its contents with it
            for t in self.list_tasks(project_id=p["id"]):
                if t["id"] not in seen_t:
                    seen_t.add(t["id"])
                    tasks.append(t)
            for n in self.list_notes(project_id=p["id"]):
                if n["id"] not in seen_n:
                    seen_n.add(n["id"])
                    notes.append(n)
        return {"query": q, "tasks": tasks[:limit], "notes": notes[:limit], "projects": projects, "goals": goals}

    # ------------------------------------------------------------ dashboards
    def get_today(self, today):
        check_date(today, "today", required=True)
        open_tasks = self.list_tasks(open_only=True)
        return {
            "date": today,
            "weekday": weekday_name(today),
            "planned": [t for t in open_tasks if t["scheduled_date"] == today],
            "due_today": [t for t in open_tasks if t["due_date"] == today],
            "overdue": self.overdue_tasks(today),
            "carried_over": self.unfinished_tasks(today),
            "events": self.list_events(today),
            "completed_today": self._q("SELECT * FROM tasks WHERE user_id = ? AND status = 'completed' "
                                       "AND date(completed_at) = ?", (self.uid, today)),
            "deadlines_this_week": [t for t in open_tasks
                                    if t["due_date"] and today < t["due_date"] <= add_days(today, 7)],
            "inbox_count": len(self.list_inbox()),
            "recent_notes": self.list_notes(limit=5),
        }

    def get_week(self, start):
        start = week_start(start)
        open_tasks = self.list_tasks(open_only=True)
        days = []
        for i in range(7):
            d = add_days(start, i)
            days.append({"date": d, "weekday": weekday_name(d), "tasks": self.list_tasks(scheduled_on=d),
                         "due": [t for t in open_tasks if t["due_date"] == d], "events": self.list_events(d)})
        return {"start": start, "end": add_days(start, 6), "days": days}

    def weekly_review(self, start):
        start = week_start(start)
        end = add_days(start, 6)
        open_tasks = self.list_tasks(open_only=True)
        return {
            "start": start, "end": end,
            "completed": self._q("SELECT * FROM tasks WHERE user_id = ? AND status = 'completed' "
                                 "AND date(completed_at) BETWEEN ? AND ?", (self.uid, start, end)),
            "missed_deadlines": [t for t in open_tasks if t["due_date"] and start <= t["due_date"] <= end],
            "unfinished": [t for t in open_tasks if t["scheduled_date"] and start <= t["scheduled_date"] <= end],
            "notes": self.list_notes(since=start),
            "next_focus": sorted([t for t in open_tasks if t["due_date"]], key=lambda t: t["due_date"])[:5],
        }

    def snapshot(self, today):
        return {
            "today": today, "weekday": weekday_name(today), "settings": self.get_settings(),
            "projects": [{"id": p["id"], "name": p["name"], "due_date": p["due_date"]}
                         for p in self.list_projects() if p["status"] == "active"][:20],
            "goals": [{"id": g["id"], "title": g["title"], "deadline": g["deadline"]}
                      for g in self.list_goals() if g["status"] == "active"][:10],
            "counts": {"open_tasks": len(self.list_tasks(open_only=True)),
                       "overdue": len(self.overdue_tasks(today)), "inbox": len(self.list_inbox())},
            "memories": [m["fact"] for m in self.list_memories()][:20],
        }

    # ------------------------------------------------------------ pending actions
    def park_action(self, tool, args, summary):
        with self.tx() as c:
            cur = c.execute("INSERT INTO pending_actions (user_id, tool, args, summary) VALUES (?, ?, ?, ?)",
                            (self.uid, tool, json.dumps(args), summary))
        return {"pending_action_id": cur.lastrowid, "needs_confirmation": True, "summary": summary}

    def get_pending(self, pid):
        p = self._one("SELECT * FROM pending_actions WHERE id = ? AND user_id = ?", (pid, self.uid))
        if not p:
            raise NotFound(f"No pending action with id {pid}")
        return p

    def set_pending_state(self, pid, state):
        p = self.get_pending(pid)
        if p["state"] != "pending":
            raise ValidationError(f"That action was already {p['state']}")
        with self.tx() as c:
            c.execute("UPDATE pending_actions SET state = ? WHERE id = ? AND user_id = ?", (state, pid, self.uid))
        return self.get_pending(pid)

    def open_pending(self):
        return self._q("SELECT * FROM pending_actions WHERE user_id = ? AND state = 'pending' ORDER BY id", (self.uid,))

    # ------------------------------------------------------------ chat log
    def add_message(self, role, content):
        with self.tx() as c:
            c.execute("INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)", (self.uid, role, content))

    def recent_messages(self, limit=20):
        rows = self._q("SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?", (self.uid, limit))
        return list(reversed(rows))

    def clear_messages(self):
        with self.tx() as c:
            c.execute("DELETE FROM messages WHERE user_id = ?", (self.uid,))


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


def week_plan(store, start, now=None, today=None):
    """Plan the rest of a week. Days that have already passed are never used."""
    settings = store.get_settings()
    start = week_start(start)
    today = today or start
    first = max(start, today)
    if first > add_days(start, 6):
        return {"start": start, "days": [], "changes": [], "at_risk": [],
                "assumptions": ["That week is already over, so there's nothing left to plan."]}
    events = {add_days(start, i): store.list_events(add_days(start, i)) for i in range(7)}
    return plan_week(store.list_tasks(open_only=True), first, events_by_day=events,
                     now=now if first == today else None,
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
        return week_plan(store, args.get("start") or today, now, today)
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
            plan = week_plan(store, today, ctx.get("now"), today)
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

import html
import math
import os
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components


COOKIE = "planner_session"
PAGES = {
    "today": (":material/wb_sunny:", "Today"),
    "assistant": (":material/forum:", "Assistant"),
    "inbox": (":material/inbox:", "Inbox"),
    "tasks": (":material/check_circle:", "Tasks"),
    "calendar": (":material/calendar_month:", "Week"),
    "notes": (":material/edit_note:", "Notes"),
    "projects": (":material/folder:", "Projects"),
    "goals": (":material/flag:", "Goals"),
    "search": (":material/search:", "Search"),
    "settings": (":material/settings:", "Settings"),
}

# Calm palette for something you open every day: sage-white paper, deep pine
# ink, a steady teal for actions. Colour otherwise appears only when it means
# something: rose for overdue, dusk blue for "should", and the sun.
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Literata:opsz,wght@7..72,400;7..72,500;7..72,600&family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700&display=swap');
:root {
  --paper: #F3F5F1; --surface: #FFFFFF; --pine: #1F3A34; --moss: #5E726C;
  --teal: #2F7D6D; --teal-soft: #E1EFEA; --sun: #E9B44C; --rose: #B8505A; --rose-soft: #F6E4E5;
  --dusk: #4A6FA5; --dusk-soft: #E4EAF4; --line: #DCE3DE; --mist: #E9EEEA;
  --serif: 'Literata', Georgia, 'Times New Roman', serif;
  --sans: 'Nunito Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
}
.stApp { background: var(--paper); }
.stApp, .stMarkdown, .stMarkdown p, label, input, textarea, button, .stCaption, [data-testid="stWidgetLabel"] p {
  font-family: var(--sans);
}
.stApp h1, .stApp h2, .stApp h3 { font-family: var(--serif); color: var(--pine); font-weight: 500; letter-spacing: -0.01em; }
.stApp h1 { font-size: 2.1rem; }
.stApp h2 { font-size: 1.45rem; }
.stApp h3 { font-size: 1.12rem; font-family: var(--sans); font-weight: 700; letter-spacing: 0; }
[data-testid="stAppDeployButton"] { display: none; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }

/* Sidebar: deep pine, nav as a quiet list */
[data-testid="stSidebar"] { background: var(--pine); }
[data-testid="stSidebar"] * { color: #E4ECE8; }
[data-testid="stSidebar"] [role="radiogroup"] { gap: 2px; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  width: 100%; padding: 7px 10px; border-radius: 10px; margin: 0; cursor: pointer;
}
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child:not([data-testid="stMarkdownContainer"]) { display: none; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(255,255,255,.06); }
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"],
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background: rgba(255,255,255,.13); }
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p { color: #fff; font-weight: 700; }
[data-testid="stSidebar"] [data-testid="stRadioOption"]:has(input:focus-visible) { outline: 2px solid var(--sun); outline-offset: 1px; }
[data-testid="stSidebar"] [role="radiogroup"] label p { font-size: 0.98rem; }
[data-testid="stSidebar"] .stButton > button {
  background: transparent; border: 1px solid rgba(255,255,255,.22); color: #E4ECE8;
}
[data-testid="stSidebar"] .stButton > button:hover { border-color: rgba(255,255,255,.5); }
.stApp .stMarkdown p.brand { font-family: var(--serif); font-size: 1.6rem; color: #fff; margin: 0 0 2px; }
.stApp .stMarkdown p.brand-sub { color: #A9BDB5; font-size: .88rem; margin: 0 0 14px; }
.who { display: flex; align-items: center; gap: 10px; margin: 6px 0 14px; }
.avatar { width: 34px; height: 34px; border-radius: 50%; background: var(--sun); color: var(--pine) !important;
  display: grid; place-items: center; font-weight: 700; }
.who small { display: block; color: #A9BDB5 !important; }

/* Controls */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 10px; font-weight: 600; padding: .45rem 1rem; border-color: var(--line);
}
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible { outline: 3px solid var(--sun); outline-offset: 2px; }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border-radius: 10px !important; }
[data-testid="stForm"] { border: 1px solid var(--line); border-radius: 16px; background: var(--surface); padding: 1rem 1.1rem; }
[data-testid="stExpander"] details { border-radius: 12px; border-color: var(--line); background: var(--surface); }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; }

/* Theme colours set here too, so the look holds even without .streamlit/config.toml */
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"],
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--teal) !important; border-color: var(--teal) !important; color: #fff !important; }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover {
  background: #276A5C !important; border-color: #276A5C !important; }
.stButton > button:not([kind="primary"]):hover, .stFormSubmitButton > button:not([kind="primary"]):hover {
  border-color: var(--teal); color: var(--teal); }
[data-testid="stCheckbox"] input:checked + div, [data-testid="stCheckbox"] [data-checked="true"] { background-color: var(--teal) !important; border-color: var(--teal) !important; }
button[role="tab"][aria-selected="true"] p { color: var(--teal); }
[data-baseweb="tab-highlight"] { background-color: var(--teal) !important; }
.stProgress [role="progressbar"] > div > div > div { background-color: var(--teal) !important; }
.stApp a { color: var(--teal); }

/* Hero: the day as a horizon */
.hero { background: linear-gradient(180deg, #E5EFEA 0%, var(--paper) 100%); border-radius: 22px;
  padding: 26px 28px 8px; margin-bottom: 18px; }
.stApp .stMarkdown p.hello { font-family: var(--serif); font-size: clamp(1.9rem, 3.6vw, 2.8rem); line-height: 1.12;
  color: var(--pine); margin: 0; font-weight: 500; letter-spacing: -0.015em; }
.stApp .stMarkdown p.hero-sub { color: var(--moss); font-size: 1.05rem; margin: 8px 0 0; }
.hero-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
.streak { display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 999px; padding: 6px 14px 6px 8px; color: var(--pine); font-weight: 600; font-size: .92rem; }
.streak .dot { width: 20px; height: 20px; border-radius: 50%; background: var(--sun); display: inline-block; }
.horizon { width: 100%; height: auto; display: block; margin-top: 6px; }

/* Tasks */
.t-title { font-weight: 600; color: var(--pine); line-height: 1.35; margin: 1px 0 3px; }
.t-title.done { text-decoration: line-through; color: var(--moss); font-weight: 400; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.chip { font-size: .8rem; padding: 2px 9px; border-radius: 999px; background: var(--mist); color: var(--moss); }
.chip.rose { background: var(--rose-soft); color: var(--rose); font-weight: 600; }
.chip.dusk { background: var(--dusk-soft); color: var(--dusk); }
.chip.teal { background: var(--teal-soft); color: var(--teal); }
.pri { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 7px; vertical-align: 2px; }
.pri.p1 { background: var(--rose); } .pri.p2 { background: var(--dusk); }
.pri.p3 { background: #B9C6C0; } .pri.p4 { background: transparent; border: 1px solid #B9C6C0; }
.stApp .stMarkdown p.section-note { color: var(--moss); font-size: .95rem; margin: -4px 0 10px; }
.empty { color: var(--moss); background: var(--surface); border: 1px dashed var(--line); border-radius: 14px;
  padding: 16px 18px; font-size: .95rem; }

.rule { border-top: 1px solid var(--line); margin: 2px 0 8px; }
[data-testid="stPopover"] button { border-radius: 10px; }

/* Plan timeline */
.slot { display: grid; grid-template-columns: 92px 1fr; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--line); }
.slot:last-child { border-bottom: 0; }
.slot time { color: var(--moss); font-variant-numeric: tabular-nums; font-size: .9rem; padding-top: 1px; }
.slot .what { border-left: 3px solid var(--line); padding-left: 10px; }
.slot.must .what { border-color: var(--rose); } .slot.should .what { border-color: var(--dusk); }
.slot.nice .what { border-color: #B9C6C0; } .slot.event .what { border-color: var(--pine); }
.slot.break .what { border-color: var(--sun); color: var(--moss); }
.slot small { color: var(--moss); display: block; }

/* Week */
.day-head { font-weight: 700; color: var(--pine); margin-bottom: 6px; }
.day-head.today { color: var(--teal); }
.day-head span { font-family: var(--serif); font-weight: 500; font-size: 1.35rem; margin-left: 4px; }
.pill { font-size: .86rem; background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  padding: 6px 9px; margin-bottom: 6px; color: var(--pine); }
.pill.event { background: #E5EFEA; border-color: #CFE0D8; }
.pill.done { color: var(--moss); text-decoration: line-through; }
.pill.due { border-style: dashed; }
.pill.new { border-color: var(--teal); background: var(--teal-soft); }

/* Sign-in */
.auth-hero h1 { font-size: clamp(2.2rem, 4.4vw, 3.3rem); line-height: 1.08; margin: 10px 0 12px; }
.stApp .stMarkdown .auth-hero p { color: var(--moss); font-size: 1.1rem; max-width: 34ch; line-height: 1.55; }
.stApp .stMarkdown .auth-hero p.wordmark { font-family: var(--serif); font-size: 1.3rem; color: var(--pine); margin: 0; }
.auth-list { color: var(--pine); padding-left: 1.1rem; margin-top: 12px; }
.auth-list li { margin: 4px 0; }
.welcome ol { margin: 6px 0 0; padding-left: 1.2rem; color: var(--pine); }
.welcome li { margin: 4px 0; }
/* Keep a task's checkbox beside its title (and Edit beside the task) on phones */
[class*="st-key-trow-"] > div > [data-testid="stHorizontalBlock"],
[class*="st-key-trow-"] [data-testid="stHorizontalBlock"],
[class*="st-key-tline-"] > [data-testid="stHorizontalBlock"],
[class*="st-key-tline-"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: .6rem; }
[class*="st-key-trow-"] [data-testid="stColumn"]:first-child {
  flex: 0 0 26px !important; min-width: 26px !important; width: 26px !important; }
[class*="st-key-tline-"] [data-testid="stColumn"]:last-child {
  flex: 0 0 auto !important; min-width: 74px !important; width: auto !important; }
[class*="st-key-trow-"] [data-testid="stColumn"]:last-child { min-width: 0 !important; flex: 1 1 auto !important; }
@media (max-width: 640px) {
  .hero { padding: 18px 16px 4px; border-radius: 16px; }
  .slot { grid-template-columns: 70px 1fr; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
"""

AUTH_ONLY_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { display: none; }
.block-container { max-width: 1040px; padding-top: 4rem; }
</style>
"""


def esc(value) -> str:
    """Everything a person typed is escaped before it goes into HTML."""
    return html.escape(str(value or ""), quote=True)


# ------------------------------------------------------------------ plumbing
def load_secrets():
    """Streamlit Cloud keeps settings in st.secrets; pass them on as environment variables."""
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for key in ("AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_BASE_URL",
                "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "DATABASE_PATH"):
        if key in secrets and not os.environ.get(key):
            os.environ[key] = str(secrets[key])


def local_now():
    """The person's own time, not the server's (Streamlit Cloud runs in UTC)."""
    tz_name = None
    try:
        tz_name = st.context.timezone
    except Exception:
        pass
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


def conn():
    # One connection per browser session, so two people's writes never share a transaction.
    if "conn" not in st.session_state:
        st.session_state["conn"] = connect(os.environ.get("DATABASE_PATH", "data/planner.db"))
    return st.session_state["conn"]


def flash(message, kind="success"):
    st.session_state.setdefault("flash", []).append((kind, message))


def show_flashes():
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind)(message)


def run(fn, ok_message=None):
    try:
        result = fn()
        if ok_message:
            flash(ok_message)
        return result
    except ValidationError as e:
        st.error(str(e))
    except Exception as e:
        st.error(f"Something went wrong: {e}")
    return None


def go(page):
    st.session_state["page"] = page


def set_cookie(token, days=30):
    """Stores the sign-in token in the browser. Runs in a same-origin frame."""
    value = esc(token) if token else ""
    age = days * 86400 if token else 0
    components.html(
        "<script>"
        f"var c='{COOKIE}={value}; path=/; max-age={age}; SameSite=Lax';"
        "if (window.parent.location.protocol==='https:') c+='; Secure';"
        "window.parent.document.cookie=c;"
        "</script>", height=0)


# ------------------------------------------------------------------ sign in
def restore_session():
    if st.session_state.get("uid"):
        return
    try:
        token = st.context.cookies.get(COOKIE)
    except Exception:
        token = None
    if token and not st.session_state.get("signed_out"):
        user = Accounts(conn()).user_from_session(token)
        if user:
            st.session_state["uid"] = user["id"]
            st.session_state["token"] = token


def horizon_art():
    """Decorative sunrise used on the sign-in page."""
    return """
<svg class="horizon" viewBox="0 0 520 230" role="img" aria-label="A sun rising over a calm horizon">
  <defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#E5EFEA"/><stop offset="1" stop-color="#F3F5F1"/></linearGradient></defs>
  <rect width="520" height="230" rx="26" fill="url(#sky)"/>
  <path d="M40 176 Q260 20 480 176" fill="none" stroke="#C9D7D0" stroke-width="2" stroke-dasharray="3 7"/>
  <circle cx="186" cy="92" r="40" fill="#E9B44C" opacity=".16"/>
  <circle cx="186" cy="92" r="22" fill="#E9B44C"/>
  <line x1="28" y1="176" x2="492" y2="176" stroke="#1F3A34" stroke-width="2"/>
  <rect x="250" y="146" width="84" height="22" rx="8" fill="#1F3A34" opacity=".12"/>
  <rect x="96" y="182" width="58" height="9" rx="4.5" fill="#2F7D6D"/>
  <rect x="164" y="182" width="36" height="9" rx="4.5" fill="#2F7D6D" opacity=".7"/>
  <rect x="352" y="182" width="72" height="9" rx="4.5" fill="#4A6FA5" opacity=".75"/>
</svg>"""


def page_auth():
    st.markdown(AUTH_ONLY_CSS, unsafe_allow_html=True)
    if st.session_state.pop("clear_cookie", False):
        set_cookie(None)
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        st.markdown(f"""
<div class="auth-hero">
  <p class="wordmark">Planner</p>
  <h1>Plan the day you actually have.</h1>
  <p>Write down what's on your mind. Planner sorts it into tasks and notes, then fits them around your meetings.</p>
  <ul class="auth-list">
    <li>Turns a messy thought into tasks with the right dates</li>
    <li>Builds a realistic plan when you only have two hours</li>
    <li>Asks before it deletes or moves anything big</li>
  </ul>
  {horizon_art()}
</div>""", unsafe_allow_html=True)
    with right:
        st.write("")
        sign_in, create = st.tabs(["Sign in", "Create account"])
        with sign_in:
            with st.form("sign-in"):
                email = st.text_input("Email", autocomplete="email")
                password = st.text_input("Password", type="password", autocomplete="current-password")
                remember = st.checkbox("Keep me signed in on this device", value=True)
                if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                    try:
                        user = Accounts(conn()).authenticate(email, password)
                        finish_sign_in(user, remember)
                    except ValidationError as e:
                        st.error(str(e))
        with create:
            with st.form("create-account"):
                name = st.text_input("Your name", placeholder="What should I call you?", autocomplete="given-name")
                email = st.text_input("Email", key="new-email", autocomplete="email")
                password = st.text_input("Password", type="password", key="new-password",
                                         help="At least 8 characters.", autocomplete="new-password")
                confirm = st.text_input("Type the password again", type="password", autocomplete="new-password")
                remember = st.checkbox("Keep me signed in on this device", value=True, key="new-remember")
                if st.form_submit_button("Create account", type="primary", use_container_width=True):
                    if password != confirm:
                        st.error("The two passwords don't match.")
                    else:
                        try:
                            user = Accounts(conn()).create(email, password, name)
                            finish_sign_in(user, remember)
                        except ValidationError as e:
                            st.error(str(e))
            st.caption("Your tasks and notes are private to your account. Passwords are stored "
                       "as salted hashes, never as text.")


def finish_sign_in(user, remember):
    st.session_state["uid"] = user["id"]
    st.session_state.pop("signed_out", None)
    if remember:
        token = Accounts(conn()).start_session(user["id"])
        st.session_state["token"] = token
        st.session_state["set_cookie"] = token  # written on the next run, once the page is stable
    st.rerun()


def sign_out():
    Accounts(conn()).end_session(st.session_state.get("token"))
    keep = {"conn"}
    for k in list(st.session_state.keys()):
        if k not in keep:
            del st.session_state[k]
    st.session_state["signed_out"] = True  # don't re-read the old cookie before it's cleared
    st.session_state["clear_cookie"] = True
    st.rerun()


# ------------------------------------------------------------------ pieces
def task_row(store, ctx, task, key, show_project=True):
    done = task["status"] == "completed"
    box = st.container(key=f"trow-{key}-{task['id']}")
    c1, c2 = box.columns([0.06, 0.94], vertical_alignment="top")
    with c1:
        ticked = st.checkbox("Done", value=done, key=f"{key}-{task['id']}", label_visibility="collapsed")
        if ticked != done:
            run(lambda: store.complete_task(task["id"]) if ticked else store.reopen_task(task["id"]),
                "Nice, that's done." if ticked else "Moved back to your list.")
            st.rerun()
    with c2:
        chips = []
        today = ctx["today"]
        if task["due_date"]:
            if not done and task["due_date"] < today:
                chips.append(("rose", f"Overdue, was due {friendly_date(task['due_date'], today)}"))
            elif task["due_date"] == today:
                chips.append(("rose", "Due today"))
            else:
                chips.append(("dusk", f"Due {friendly_date(task['due_date'], today)}"))
        if task["scheduled_date"] and task["scheduled_date"] != today:
            chips.append(("", f"Planned {friendly_date(task['scheduled_date'], today)}"))
        if task["estimate_min"]:
            chips.append(("", human_minutes(task["estimate_min"])))
        if show_project and task.get("project_name"):
            chips.append(("teal", task["project_name"]))
        chip_html = "".join(f'<span class="chip {c}">{esc(t)}</span>' for c, t in chips)
        st.markdown(
            f'<div class="t-title{" done" if done else ""}"><span class="pri p{task["priority"]}" '
            f'title="{esc(PRIORITIES[task["priority"]])} priority"></span>{esc(task["title"])}</div>'
            + (f'<div class="chips">{chip_html}</div>' if chips else ""), unsafe_allow_html=True)


def friendly_date(iso, today):
    if not iso:
        return ""
    diff = (datetime.fromisoformat(iso) - datetime.fromisoformat(today)).days
    if diff == 0:
        return "today"
    if diff == 1:
        return "tomorrow"
    if diff == -1:
        return "yesterday"
    if 1 < diff < 7:
        return weekday_name(iso)
    d = datetime.fromisoformat(iso)
    return d.strftime("%b %-d") if os.name != "nt" else d.strftime("%b %d").replace(" 0", " ")


def empty(message):
    st.markdown(f'<div class="empty">{esc(message)}</div>', unsafe_allow_html=True)


def horizon_svg(settings, now_hm, events, plan):
    """Today's working hours as a horizon: meetings sit on it, planned work
    sits under it, and the sun shows where you are in the day."""
    start, end = to_min(settings["workday_start"]), to_min(settings["workday_end"])
    span = max(end - start, 60)
    x = lambda m: 40 + (min(max(m, start), end) - start) / span * 920
    now = to_min(now_hm)
    frac = (min(max(now, start), end) - start) / span
    sun_x, sun_y = x(now), 118 - math.sin(math.pi * frac) * 70
    after = now > end
    sun_note = (f"Starts {settings['workday_start']}" if now < start else "Done for today" if after else f"Now {now_hm}")
    parts = [f'<svg class="horizon" viewBox="0 0 1000 176" role="img" aria-label="Your working day from '
             f'{esc(settings["workday_start"])} to {esc(settings["workday_end"])}, with '
             f'{len(events)} meeting(s)">']
    parts.append('<path d="M40 118 Q500 -22 960 118" fill="none" stroke="#C9D7D0" stroke-width="1.5" stroke-dasharray="3 7"/>')
    parts.append(f'<circle cx="{sun_x:.1f}" cy="{sun_y:.1f}" r="26" fill="#E9B44C" opacity="{0.08 if after else 0.18}"/>')
    parts.append(f'<circle cx="{sun_x:.1f}" cy="{sun_y:.1f}" r="13" fill="#E9B44C" opacity="{0.45 if after else 1}"/>')
    anchor = "start" if sun_x < 120 else "end" if sun_x > 880 else "middle"
    parts.append(f'<text x="{sun_x:.1f}" y="{sun_y - 32:.1f}" font-size="13" text-anchor="{anchor}" fill="#5E726C" '
                 f'font-family="Nunito Sans, system-ui, sans-serif">{esc(sun_note)}</text>')
    for e in events:
        x1, x2 = x(to_min(e["start_time"])), x(to_min(e["end_time"]))
        w = max(x2 - x1, 6)
        parts.append(f'<rect x="{x1:.1f}" y="86" width="{w:.1f}" height="26" rx="8" fill="#1F3A34" opacity=".13">'
                     f'<title>{esc(e["start_time"])} {esc(e["title"])}</title></rect>')
        if w > 70:
            label = e["title"] if len(e["title"]) <= int(w / 8) else e["title"][: max(int(w / 8) - 1, 1)] + "…"
            parts.append(f'<text x="{x1 + 8:.1f}" y="103" font-size="13" fill="#1F3A34" '
                         f'font-family="Nunito Sans, system-ui, sans-serif">{esc(label)}</text>')
    parts.append('<line x1="40" y1="118" x2="960" y2="118" stroke="#1F3A34" stroke-width="2"/>')
    colors = {"must": "#B8505A", "should": "#4A6FA5", "nice": "#2F7D6D"}
    for b in (plan or {}).get("schedule", []):
        if b["type"] != "task":
            continue
        x1, x2 = x(to_min(b["start"])), x(to_min(b["end"]))
        parts.append(f'<rect x="{x1:.1f}" y="125" width="{max(x2 - x1 - 3, 4):.1f}" height="9" rx="4.5" '
                     f'fill="{colors.get(b.get("bucket"), "#2F7D6D")}"><title>{esc(b["title"])}</title></rect>')
    step = 60 if span <= 6 * 60 else 120 if span <= 12 * 60 else 180
    for m in range(start, end + 1, step):
        parts.append(f'<text x="{x(m):.1f}" y="160" font-size="13" text-anchor="middle" fill="#5E726C" '
                     f'font-family="Nunito Sans, system-ui, sans-serif">{m // 60:02d}:{m % 60:02d}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_plan(store, plan):
    st.markdown(f'<p class="section-note">{human_minutes(plan["planned_min"])} planned of '
                f'{human_minutes(plan["capacity_min"])} available, {esc(plan["window"]["start"])} to '
                f'{esc(plan["window"]["end"])}.</p>', unsafe_allow_html=True)
    if not plan["schedule"]:
        empty("There's nothing to fit in yet. Add a task or two and plan again.")
        return
    rows = []
    for b in plan["schedule"]:
        kind = b["type"] if b["type"] != "task" else b.get("bucket", "nice")
        detail = {"event": "Meeting", "break": "A short break to reset"}.get(b["type"], b.get("reason", ""))
        title = "Break" if b["type"] == "break" else b["title"]
        rows.append(f'<div class="slot {esc(kind)}"><time>{esc(b["start"])}–{esc(b["end"])}</time>'
                    f'<div class="what">{esc(title)}<small>{esc(detail)}</small></div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    if plan["did_not_fit"]:
        st.warning("Didn't fit today: " + ", ".join(t["title"] for t in plan["did_not_fit"][:6]))
    for w in plan["warnings"]:
        st.warning(w)
    if plan["assumptions"]:
        with st.expander("How I planned this"):
            for a in plan["assumptions"]:
                st.write(a)
    if plan["placed"] and st.button(f"Save this plan to today ({len(plan['placed'])} tasks)", type="primary",
                                    key="save-plan"):
        run(lambda: apply_schedule(store, [{"id": t["id"], "to": plan["date"]} for t in plan["placed"]]),
            "Plan saved. Those tasks are on today's list.")
        st.rerun()


def pending_banner(store, ctx):
    for p in store.open_pending():
        with st.container(border=True):
            st.markdown(f"**Waiting for your OK:** {esc(p['summary'])}", unsafe_allow_html=True)
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("Yes, do it", key=f"pc-{p['id']}", type="primary"):
                run(lambda: resolve_pending(store, p["id"], "confirm", ctx), "Done.")
                st.rerun()
            if c2.button("Cancel", key=f"px-{p['id']}"):
                run(lambda: resolve_pending(store, p["id"], "reject", ctx), "Cancelled. Nothing changed.")
                st.rerun()


# ------------------------------------------------------------------ pages
def page_today(store, ctx, user):
    data = store.get_today(ctx["today"])
    settings = store.get_settings()
    hour = int(ctx["now"][:2])
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    name = (user["name"] or "").split(" ")[0]
    open_today = len(data["planned"]) + len([t for t in data["due_today"] if t not in data["planned"]])
    summary = []
    if data["events"]:
        summary.append(f"{len(data['events'])} meeting{'s' if len(data['events']) != 1 else ''}")
    summary.append(f"{open_today} thing{'s' if open_today != 1 else ''} planned" if open_today else "nothing scheduled yet")
    if data["overdue"]:
        summary.append(f"{len(data['overdue'])} overdue")
    streak = store.streak(ctx["today"])
    streak_html = (f'<span class="streak"><span class="dot"></span>{streak} day{"s" if streak != 1 else ""} in a row</span>'
                   if streak else "")
    date_line = datetime.fromisoformat(ctx["today"]).strftime("%A, %B %d").replace(" 0", " ")
    st.markdown(f"""
<div class="hero">
  <div class="hero-row">
    <div>
      <p class="hello">{esc(greeting)}{", " + esc(name) if name else ""}.</p>
      <p class="hero-sub">{esc(date_line)}. You have {esc(", ".join(summary))}.</p>
    </div>
    {streak_html}
  </div>
  {horizon_svg(settings, ctx["now"], data["events"], st.session_state.get("day_plan"))}
</div>""", unsafe_allow_html=True)

    if not user["onboarded"]:
        with st.container(border=True):
            st.markdown("""<div class="welcome"><h3 style="margin-top:0">Welcome. Here's how to get going</h3><ol>
<li>Write down what's on your mind in the box below and press <b>Organize</b>.</li>
<li>Press <b>Plan my day</b>. If you only have an hour, choose that first.</li>
<li>Optional: connect a free AI in Settings, so you can ask for anything in plain words.</li>
</ol></div>""", unsafe_allow_html=True)
            c1, c2, _ = st.columns([0.7, 1.4, 5], gap="small")
            if c1.button("Got it", type="primary"):
                Accounts(conn()).set_onboarded(user["id"])
                st.rerun()
            c2.button("Connect a free AI", on_click=go, args=("settings",))

    with st.form("capture", clear_on_submit=True):
        text = st.text_area("What's on your mind?", height=96,
                            placeholder="Finish the deck by Monday, call Alex, and an idea: a simpler hero section")
        st.caption("I'll split it into tasks and notes. Phrases like \"by Friday\" become deadlines; "
                   "vague ones like \"soon\" stay undated.")
        c1, c2, _ = st.columns([0.8, 1.1, 5], gap="small")
        organize = c1.form_submit_button("Organize", type="primary")
        to_inbox = c2.form_submit_button("Save to inbox")
    if organize and text.strip():
        parsed = parse_capture(text, ctx["today"])
        if not parsed["tasks"] and not parsed["notes"]:
            st.warning("I couldn't find anything to organize. Try naming an action, like \"call Alex\".")
        else:
            for t in parsed["tasks"]:
                run(lambda t=t: store.create_task(title=t["title"], due_date=t.get("due_date"),
                                                  scheduled_date=t.get("scheduled_date")))
            for n in parsed["notes"]:
                run(lambda n=n: store.create_note(title=n["title"], content=n["content"]))
            flash(f"Added {len(parsed['tasks'])} task{'s' if len(parsed['tasks']) != 1 else ''} and "
                  f"{len(parsed['notes'])} note{'s' if len(parsed['notes']) != 1 else ''}.")
            st.rerun()
    if to_inbox and text.strip():
        run(lambda: store.add_inbox(text), "Saved to your inbox.")
        st.rerun()

    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.subheader("Your plan")
        c1, c2 = st.columns([1.3, 1], vertical_alignment="bottom")
        choice = c1.selectbox("How much time do you have?", ["My whole workday", "30 minutes", "1 hour",
                                                              "2 hours", "3 hours", "4 hours"])
        minutes = {"30 minutes": 30, "1 hour": 60, "2 hours": 120, "3 hours": 180, "4 hours": 240}.get(choice)
        if c2.button("Plan my day", type="primary", use_container_width=True):
            st.session_state["day_plan"] = day_plan(store, ctx["today"], minutes, ctx["now"])
            st.rerun()
        if st.session_state.get("day_plan"):
            render_plan(store, st.session_state["day_plan"])
        else:
            st.markdown('<p class="section-note">I\'ll fit your tasks around meetings, leave room for '
                        'interruptions, and tell you what won\'t fit.</p>', unsafe_allow_html=True)
            for e in data["events"]:
                st.markdown(f'<div class="slot event"><time>{esc(e["start_time"])}–{esc(e["end_time"])}</time>'
                            f'<div class="what">{esc(e["title"])}<small>Meeting</small></div></div>',
                            unsafe_allow_html=True)
    with right:
        shown = False
        if data["overdue"]:
            shown = True
            st.subheader("Overdue")
            for t in data["overdue"]:
                task_row(store, ctx, t, "od")
        due_only = [t for t in data["due_today"] if t not in data["overdue"]]
        planned = [t for t in data["planned"] if t not in due_only]
        if due_only or planned:
            shown = True
            st.subheader("Today")
            for t in due_only + planned:
                task_row(store, ctx, t, "td")
        if data["carried_over"]:
            shown = True
            st.subheader("Left over from before")
            for t in data["carried_over"]:
                task_row(store, ctx, t, "co")
            if st.button(f"Move {'all ' if len(data['carried_over']) > 1 else ''}to today"):
                run(lambda: store.bulk_reschedule([t["id"] for t in data["carried_over"]], ctx["today"]),
                    "Moved to today.")
                st.rerun()
        if data["deadlines_this_week"]:
            shown = True
            st.subheader("Coming up this week")
            for t in data["deadlines_this_week"]:
                task_row(store, ctx, t, "dl")
        undated = [t for t in store.list_tasks(open_only=True) if not t["due_date"] and not t["scheduled_date"]]
        if undated:
            c1, c2 = st.columns([3, 1.2], vertical_alignment="center")
            c1.markdown(f'<p class="section-note" style="margin:0">{len(undated)} task{"s" if len(undated) != 1 else ""} '
                        f'without a date. Plan my day can fit them in.</p>', unsafe_allow_html=True)
            c2.button("See them", on_click=go, args=("tasks",), use_container_width=True)
            shown = True
        if data["completed_today"]:
            st.caption(f"Done today: {len(data['completed_today'])}. Nice work.")
        if not shown:
            empty("Nothing is waiting on you today. Write something in the box above, "
                  "or open Tasks to pick something up.")


def page_assistant(store, ctx):
    st.title("Assistant")
    cfg = resolve_config(store)
    if cfg["enabled"]:
        st.markdown(f'<p class="section-note">Using {esc(cfg["label"])}. Ask in your own words; '
                    f'I\'ll check with you before deleting or moving several things.</p>', unsafe_allow_html=True)
    else:
        c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
        c1.markdown('<p class="section-note" style="margin:0">Basic mode: I understand planning, overdue checks, '
                    'moving unfinished tasks, search and capture. Connect a free AI to ask anything.</p>',
                    unsafe_allow_html=True)
        c2.button("Connect a free AI", on_click=go, args=("settings",), use_container_width=True)

    pending_banner(store, ctx)
    chat = st.session_state.setdefault("chat", [])
    if not chat:
        st.write("")
        st.markdown("**Try one of these**")
        ideas = ["Plan my day", "What am I falling behind on?", "Move unfinished tasks to tomorrow",
                 "Plan my week", "Summarize what I wrote this week", "I only have 2 hours today"]
        for row in (ideas[:3], ideas[3:]):
            for col, idea in zip(st.columns(3), row):
                if col.button(idea, use_container_width=True):
                    st.session_state["ask"] = idea
                    st.rerun()
    for msg in chat[-20:]:
        with st.chat_message(msg["role"], avatar=":material/person:" if msg["role"] == "user" else ":material/wb_sunny:"):
            st.write(msg["content"])
            for a in msg.get("actions", []):
                st.caption(f"✓ {a}")
            if msg.get("notice"):
                st.caption(msg["notice"])
    prompt = st.chat_input("Ask, plan, or write down what's on your mind") or st.session_state.pop("ask", None)
    if prompt:
        chat.append({"role": "user", "content": prompt})
        with st.spinner("Thinking…"):
            try:
                out = chat(store, prompt, ctx)
            except ValidationError as e:
                out = {"reply": str(e), "actions": []}
            except Exception as e:
                out = {"reply": f"Something went wrong: {e}", "actions": []}
        chat.append({"role": "assistant", "content": out["reply"], "actions": out.get("actions", []),
                     "notice": out.get("notice")})
        plan = out.get("plan") or {}
        if plan.get("kind") == "plan_day":
            st.session_state["day_plan"] = plan["data"]
        elif plan.get("kind") == "plan_week":
            st.session_state["week_proposal"] = plan["data"]
        st.rerun()
    if chat and st.button("Start a new conversation"):
        st.session_state["chat"] = []
        store.clear_messages()
        st.rerun()


def page_inbox(store, ctx):
    st.title("Inbox")
    st.markdown('<p class="section-note">A place for thoughts you haven\'t sorted yet. Each one has a '
                'suggestion; one click turns it into a task or a note.</p>', unsafe_allow_html=True)
    with st.form("add-inbox", clear_on_submit=True):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        text = c1.text_input("Add a thought", placeholder="Anything, big or small")
        if c2.form_submit_button("Add", use_container_width=True) and text.strip():
            run(lambda: store.add_inbox(text), "Added to your inbox.")
            st.rerun()
    items = store.list_inbox()
    if not items:
        empty("Your inbox is clear.")
        return
    for item in items:
        tip = suggest_inbox_action(item["text"], ctx["today"])
        with st.container(border=True):
            st.markdown(f'<div class="t-title">{esc(item["text"])}</div>'
                        f'<div class="chips"><span class="chip teal">Suggested: {esc(tip["type"])}</span>'
                        f'<span class="chip">{esc(tip["reason"])}</span></div>', unsafe_allow_html=True)
            c1, c2, c3, c4, _ = st.columns([1, 1, 1, 1, 2])
            if c1.button("Make a task", key=f"it-{item['id']}", type="primary" if tip["type"] == "task" else "secondary"):
                run(lambda: run_tool_unchecked(store, "process_inbox_item", {"id": item["id"], "type": "task",
                    "due_date": tip.get("due_date")}, ctx), "Turned into a task.")
                st.rerun()
            if c2.button("Make a note", key=f"in-{item['id']}", type="primary" if tip["type"] == "note" else "secondary"):
                run(lambda: run_tool_unchecked(store, "process_inbox_item", {"id": item["id"], "type": "note"}, ctx),
                    "Saved as a note.")
                st.rerun()
            if c3.button("Archive", key=f"ia-{item['id']}"):
                run(lambda: store.close_inbox(item["id"], "archived"), "Archived.")
                st.rerun()
            if c4.button("Delete", key=f"id-{item['id']}"):
                run(lambda: store.delete_inbox(item["id"]), "Deleted.")
                st.rerun()


def page_tasks(store, ctx):
    st.title("Tasks")
    projects = store.list_projects()
    with st.form("add-task", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([3, 1.4, 1.5, 1.1], vertical_alignment="bottom")
        title = c1.text_input("New task", placeholder="What needs doing?")
        due = c2.date_input("Due", value=None, format="YYYY-MM-DD")
        project = c3.selectbox("Project", ["None"] + [p["name"] for p in projects])
        estimate = c4.selectbox("Time", ["?", "15m", "30m", "1h", "2h", "3h"])
        if st.form_submit_button("Add task", type="primary") and title.strip():
            mins = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "3h": 180}.get(estimate)
            run(lambda: store.create_task(title=title, due_date=due.isoformat() if due else None,
                                          project=None if project == "None" else project, estimate_min=mins),
                "Task added.")
            st.rerun()
    view = st.segmented_control("Show", ["Open", "Overdue", "Inbox", "In progress", "Done"], default="Open",
                                label_visibility="collapsed") or "Open"
    if view == "Open":
        tasks = store.list_tasks(open_only=True)
    elif view == "Overdue":
        tasks = store.overdue_tasks(ctx["today"])
    elif view == "Done":
        tasks = store.list_tasks(status="completed")
    else:
        tasks = store.list_tasks(status=view.lower().replace(" ", "_"))
    if not tasks:
        empty({"Open": "No open tasks. Enjoy it, or add one above.", "Overdue": "Nothing overdue.",
               "Done": "Finished tasks will show up here."}.get(view, "Nothing here."))
    if tasks:
        st.markdown(f'<p class="section-note">{len(tasks)} task{"s" if len(tasks) != 1 else ""}</p>',
                    unsafe_allow_html=True)
    for t in tasks:
        c1, c2 = st.container(key=f"tline-{t['id']}").columns([12, 1.3], vertical_alignment="center")
        with c1:
            task_row(store, ctx, t, "tk")
        with c2:
            with st.popover("Edit", use_container_width=True):
                edit_task(store, t, projects)
        st.markdown('<div class="rule"></div>', unsafe_allow_html=True)


def edit_task(store, task, projects):
    with st.form(f"edit-{task['id']}"):
        title = st.text_input("Task", task["title"])
        c1, c2, c3 = st.columns(3)
        statuses = ["inbox", "planned", "in_progress", "completed", "cancelled"]
        labels = {"inbox": "Not planned", "planned": "Planned", "in_progress": "In progress",
                  "completed": "Done", "cancelled": "Cancelled"}
        status = c1.selectbox("Status", statuses, index=statuses.index(task["status"]), format_func=labels.get)
        priority = c2.selectbox("Priority", list(PRIORITIES), index=task["priority"] - 1, format_func=PRIORITIES.get)
        names = ["None"] + [p["name"] for p in projects]
        current = task.get("project_name") or "None"
        project = c3.selectbox("Project", names, index=names.index(current) if current in names else 0)
        c4, c5 = st.columns(2)
        due = c4.date_input("Due", value=datetime.fromisoformat(task["due_date"]) if task["due_date"] else None,
                            format="YYYY-MM-DD", key=f"due-{task['id']}")
        sched = c5.date_input("Planned for", value=datetime.fromisoformat(task["scheduled_date"])
                              if task["scheduled_date"] else None, format="YYYY-MM-DD", key=f"sch-{task['id']}")
        notes = st.text_area("Notes", task["description"])
        c6, c7, _ = st.columns([1, 1, 3])
        if c6.form_submit_button("Save changes", type="primary"):
            run(lambda: store.update_task(task["id"], title=title, status=status, priority=priority,
                                          due_date=due.isoformat() if due else None,
                                          scheduled_date=sched.isoformat() if sched else None,
                                          description=notes, project=None if project == "None" else project),
                "Changes saved.")
            st.rerun()
        if c7.form_submit_button("Delete task"):
            run(lambda: store.delete_task(task["id"]), "Task deleted.")
            st.rerun()


def page_week(store, ctx):
    state = st.session_state
    state.setdefault("week_start", week_start(ctx["today"]))
    week = store.get_week(state["week_start"])
    head, nav = st.columns([2, 1.4], vertical_alignment="bottom")
    s, e = datetime.fromisoformat(week["start"]), datetime.fromisoformat(week["end"])
    head.title("Your week")
    head.markdown(f'<p class="section-note">{s.strftime("%B %d").replace(" 0", " ")} to '
                  f'{e.strftime("%B %d").replace(" 0", " ")}</p>', unsafe_allow_html=True)
    with nav:
        b1, b2, b3 = st.columns(3)
        if b1.button("Previous", use_container_width=True):
            state["week_start"] = add_days(state["week_start"], -7)
            state["week_proposal"] = None
            st.rerun()
        if b2.button("This week", use_container_width=True):
            state["week_start"] = week_start(ctx["today"])
            state["week_proposal"] = None
            st.rerun()
        if b3.button("Next", use_container_width=True):
            state["week_start"] = add_days(state["week_start"], 7)
            state["week_proposal"] = None
            st.rerun()

    c1, c2, _ = st.columns([1.1, 1, 4], gap="small")
    if c1.button("Plan my week", type="primary", use_container_width=True):
        state["week_proposal"] = week_plan(store, state["week_start"], ctx["now"], ctx["today"])
        st.rerun()
    review = c2.button("Review week", use_container_width=True)

    proposal = state.get("week_proposal")
    new_by_day, moving = {}, set()
    if proposal:
        for ch in proposal["changes"]:
            new_by_day.setdefault(ch["to"], []).append(ch["title"])
            moving.add(ch["id"])
        with st.container(border=True):
            st.markdown(f"**Suggested plan.** New placements are highlighted below. "
                        f"{esc(proposal['assumptions'][0])}", unsafe_allow_html=True)
            if proposal["at_risk"]:
                st.warning("No room this week for: " + ", ".join(t["title"] for t in proposal["at_risk"]))
            b1, b2, _ = st.columns([1.4, 1, 4])
            if b1.button(f"Apply plan ({len(proposal['changes'])} changes)", type="primary",
                         disabled=not proposal["changes"]):
                run(lambda: apply_schedule(store, proposal["changes"]), "Week planned.")
                state["week_proposal"] = None
                st.rerun()
            if b2.button("Dismiss"):
                state["week_proposal"] = None
                st.rerun()

    cols = st.columns(7, gap="small")
    for col, day in zip(cols, week["days"]):
        with col:
            is_today = day["date"] == ctx["today"]
            st.markdown(f'<div class="day-head{" today" if is_today else ""}">{esc(day["weekday"][:3])}'
                        f'<span>{int(day["date"][8:])}</span></div>', unsafe_allow_html=True)
            pills = [f'<div class="pill event">{esc(ev["start_time"])} {esc(ev["title"])}</div>' for ev in day["events"]]
            pills += [f'<div class="pill{" done" if t["status"] == "completed" else ""}">{esc(t["title"])}</div>'
                      for t in day["tasks"] if t["id"] not in moving]
            pills += [f'<div class="pill new">{esc(title)}</div>' for title in new_by_day.get(day["date"], [])]
            pills += [f'<div class="pill due">Due: {esc(t["title"])}</div>' for t in day["due"]]
            st.markdown("".join(pills) or '<div class="pill" style="color:var(--moss)">Free</div>',
                        unsafe_allow_html=True)

    if review:
        r = store.weekly_review(state["week_start"])
        with st.container(border=True):
            st.subheader("Looking back")
            st.write(f"You finished {len(r['completed'])} task{'s' if len(r['completed']) != 1 else ''}"
                     f" and wrote {len(r['notes'])} note{'s' if len(r['notes']) != 1 else ''}.")
            if r["missed_deadlines"]:
                st.write("Still open past their deadline: " + ", ".join(t["title"] for t in r["missed_deadlines"]))
            if r["next_focus"]:
                st.write("Worth focusing on next: " + ", ".join(t["title"] for t in r["next_focus"]))

    with st.expander("Add a meeting or appointment"):
        with st.form("add-event", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([2, 1.3, 1, 1])
            title = c1.text_input("What")
            date = c2.date_input("Date", format="YYYY-MM-DD")
            start = c3.time_input("Starts", value=datetime.strptime("10:00", "%H:%M").time(), step=900)
            end = c4.time_input("Ends", value=datetime.strptime("11:00", "%H:%M").time(), step=900)
            if st.form_submit_button("Add to calendar", type="primary") and title.strip():
                run(lambda: store.create_event(title, date.isoformat(), start.strftime("%H:%M"),
                                               end.strftime("%H:%M")), "Added to your calendar.")
                st.rerun()


def page_notes(store, ctx):
    state = st.session_state
    st.title("Notes")
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        if st.button("New note", type="primary", use_container_width=True):
            made = run(lambda: store.create_note(title="Untitled note", content=""))
            if made:
                state["open_note"] = made["id"]
                st.rerun()
        q = st.text_input("Find a note", placeholder="Search notes", label_visibility="collapsed")
        notes = store.list_notes(query=q.strip() or None)
        if not notes:
            st.caption("No notes yet." if not q else "No notes match that.")
        for n in notes:
            label = n["title"][:42] or "Untitled"
            if st.button(label, key=f"note-{n['id']}", use_container_width=True,
                         type="primary" if state.get("open_note") == n["id"] else "secondary"):
                state["open_note"] = n["id"]
                st.rerun()
    with right:
        if not state.get("open_note"):
            empty("Pick a note on the left, or start a new one. Ideas you capture on Today land here too.")
            return
        try:
            note = store.get_note(state["open_note"])
        except ValidationError:
            state["open_note"] = None
            st.rerun()
        with st.form(f"note-{note['id']}"):
            title = st.text_input("Title", note["title"])
            content = st.text_area("Note", note["content"], height=320,
                                   placeholder="Write freely. Lines with actions can become tasks.")
            c1, c2, c3, _ = st.columns([1, 1.2, 1, 2])
            if c1.form_submit_button("Save", type="primary"):
                run(lambda: store.update_note(note["id"], title=title, content=content), "Note saved.")
                st.rerun()
            if c2.form_submit_button("Make tasks from this"):
                store.update_note(note["id"], title=title, content=content)
                parsed = parse_capture(content, ctx["today"])
                for t in parsed["tasks"]:
                    run(lambda t=t: store.create_task(title=t["title"], due_date=t.get("due_date"),
                                                      scheduled_date=t.get("scheduled_date")))
                flash(f"Made {len(parsed['tasks'])} task{'s' if len(parsed['tasks']) != 1 else ''} from this note."
                      if parsed["tasks"] else "I didn't find any actions in this note.",
                      "success" if parsed["tasks"] else "info")
                st.rerun()
            if c3.form_submit_button("Delete"):
                run(lambda: store.delete_note(note["id"]), "Note deleted.")
                state["open_note"] = None
                st.rerun()
        st.caption(f"Last edited {esc(note['updated_at'][:16].replace('T', ' '))}")


def page_projects(store, ctx):
    st.title("Projects")
    with st.form("add-project", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1.4, 1], vertical_alignment="bottom")
        name = c1.text_input("New project", placeholder="For example: Kitchen renovation")
        due = c2.date_input("Due", value=None, format="YYYY-MM-DD")
        if c3.form_submit_button("Create", type="primary", use_container_width=True) and name.strip():
            run(lambda: store.create_project(name, due_date=due.isoformat() if due else None), "Project created.")
            st.rerun()
    projects = store.list_projects()
    if not projects:
        empty("Projects group related tasks and notes. Create one above, or add a project name when you make a task.")
    for p in projects:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(f"### {esc(p['name'])}", unsafe_allow_html=True)
            c2.markdown(f'<div style="text-align:right;color:var(--moss)">{p["done_count"]} of {p["task_count"]} done</div>',
                        unsafe_allow_html=True)
            st.progress(p["progress"] / 100)
            if p["due_date"]:
                st.caption(f"Due {friendly_date(p['due_date'], ctx['today'])}")
            with st.expander("Tasks and notes"):
                full = store.get_project(p["id"])
                if not full["tasks"] and not full["notes"]:
                    st.caption("Nothing in this project yet.")
                for t in full["tasks"]:
                    task_row(store, ctx, t, f"pr{p['id']}", show_project=False)
                for n in full["notes"]:
                    st.caption(f"Note: {n['title']}")
                if st.button("Delete project", key=f"delp-{p['id']}"):
                    run(lambda: store.delete_project(p["id"]), "Project deleted. Its tasks and notes are kept.")
                    st.rerun()


def page_goals(store, ctx):
    st.title("Goals")
    st.markdown('<p class="section-note">Big things you\'re working towards. With the AI connected, ask the '
                'assistant to break a goal into projects and tasks.</p>', unsafe_allow_html=True)
    with st.form("add-goal", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1.4, 1], vertical_alignment="bottom")
        title = c1.text_input("New goal", placeholder="For example: Learn Python in 3 months")
        deadline = c2.date_input("By", value=None, format="YYYY-MM-DD")
        if c3.form_submit_button("Create", type="primary", use_container_width=True) and title.strip():
            run(lambda: store.create_goal(title, deadline=deadline.isoformat() if deadline else None), "Goal created.")
            st.rerun()
    goals = store.list_goals()
    if not goals:
        empty("No goals yet.")
    for g in goals:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(f"### {esc(g['title'])}", unsafe_allow_html=True)
            c2.markdown(f'<div style="text-align:right;color:var(--moss)">{g["progress"]}%</div>',
                        unsafe_allow_html=True)
            st.progress(g["progress"] / 100)
            bits = [f"{g['done_count']} of {g['task_count']} tasks done"]
            if g["deadline"]:
                bits.append(f"by {friendly_date(g['deadline'], ctx['today'])}")
            st.caption(", ".join(bits))
            for p in g["projects"]:
                st.markdown(f"- {esc(p['name'])}", unsafe_allow_html=True)
            if st.button("Delete goal", key=f"delg-{g['id']}"):
                run(lambda: store.delete_goal(g["id"]), "Goal deleted.")
                st.rerun()


def page_search(store, ctx):
    st.title("Search")
    q = st.text_input("Search everything", placeholder="A word, a person, a project…", label_visibility="collapsed")
    if not q.strip():
        empty("Search looks through tasks, notes, projects and goals. Searching a project's name "
              "also shows everything inside it.")
        return
    found = store.search(q)
    total = len(found["tasks"]) + len(found["notes"]) + len(found["projects"]) + len(found["goals"])
    if not total:
        empty(f"Nothing matches \"{q}\". Try a shorter word.")
        return
    if found["projects"] or found["goals"]:
        st.subheader("Projects and goals")
        for p in found["projects"]:
            st.markdown(f"- Project: **{esc(p['name'])}**", unsafe_allow_html=True)
        for g in found["goals"]:
            st.markdown(f"- Goal: **{esc(g['title'])}**", unsafe_allow_html=True)
    if found["tasks"]:
        st.subheader("Tasks")
        for t in found["tasks"]:
            task_row(store, ctx, t, "se")
    if found["notes"]:
        st.subheader("Notes")
        for n in found["notes"]:
            with st.expander(n["title"]):
                st.write(n["content"] or "(empty)")


def page_settings(store, ctx, user):
    st.title("Settings")
    tab_ai, tab_day, tab_account = st.tabs(["AI assistant", "Your day", "Account"])

    with tab_ai:
        cfg = resolve_config(store)
        locked = cfg["source"] == "env"
        if locked:
            st.info("The AI is set up by whoever runs this app, so there's nothing to change here.")
        ids = list(PRESETS)
        chosen = st.selectbox("Provider", ids, index=ids.index(cfg["provider"]),
                              format_func=lambda i: PRESETS[i]["label"], disabled=locked)
        preset = PRESETS[chosen]
        help_text = preset["help"]
        if preset["key_url"]:
            help_text += f" [{'Get a free key' if 'free' in preset['label'] else 'Get a key' if preset['needs_key'] else 'Download it'}]({preset['key_url']})"
        st.caption(help_text)
        same = chosen == cfg["provider"]
        key = model = base_url = ""
        if preset["needs_key"]:
            key = st.text_input("API key", type="password", disabled=locked,
                                placeholder=f"Saved key ending {cfg['key_hint']}. Leave blank to keep it."
                                if (same and cfg["api_key"]) else "Paste your key")
        if chosen != "none":
            model = st.text_input("Model", value=cfg["model"] if same else preset["model"], disabled=locked)
        if chosen == "openai_compatible":
            base_url = st.text_input("Service URL", value=cfg["base_url"] if same else "", placeholder="https://…",
                                     disabled=locked)
        c1, c2, _ = st.columns([0.7, 1.3, 5], gap="small")
        if c1.button("Save", type="primary", disabled=locked):
            if run(lambda: save_config(store, chosen, key, model, base_url), "AI settings saved."):
                st.rerun()
        if c2.button("Test connection"):
            with st.spinner("Testing…"):
                ok, message = test_connection(resolve_config(store))
            (st.success if ok else st.error)(message)
        if cfg["enabled"]:
            st.caption(f"On: {cfg['label']}, model {cfg['model']}.")
        elif cfg["problem"]:
            st.caption(cfg["problem"])
        st.caption("Your key is kept with your account and isn't shown to anyone else.")

    with tab_day:
        settings = store.get_settings()
        with st.form("hours"):
            st.markdown("**Working hours**")
            st.caption("Plans are built inside these hours.")
            c1, c2 = st.columns(2)
            start = c1.time_input("Start", value=datetime.strptime(settings["workday_start"], "%H:%M").time(), step=900)
            end = c2.time_input("End", value=datetime.strptime(settings["workday_end"], "%H:%M").time(), step=900)
            if st.form_submit_button("Save hours", type="primary"):
                run(lambda: store.update_hours(start.strftime("%H:%M"), end.strftime("%H:%M")), "Working hours saved.")
                st.session_state["day_plan"] = None
                st.rerun()
        st.markdown("**What the assistant remembers about you**")
        memories = store.list_memories()
        if not memories:
            st.caption("Nothing yet. When you mention a lasting fact, like a thesis deadline, it's kept here.")
        for m in memories:
            c1, c2 = st.columns([5, 1])
            c1.write(m["fact"])
            if c2.button("Forget", key=f"mem-{m['id']}"):
                run(lambda: store.forget(m["id"]), "Forgotten.")
                st.rerun()

    with tab_account:
        acc = Accounts(conn())
        with st.form("name"):
            name = st.text_input("Your name", user["name"])
            st.caption(f"Signed in as {user['email']}")
            if st.form_submit_button("Save name", type="primary"):
                run(lambda: acc.update_name(user["id"], name), "Name saved.")
                st.rerun()
        with st.form("password", clear_on_submit=True):
            st.markdown("**Change password**")
            current = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password", help="At least 8 characters.")
            again = st.text_input("New password again", type="password")
            if st.form_submit_button("Change password"):
                if new != again:
                    st.error("The new passwords don't match.")
                elif run(lambda: acc.change_password(user["id"], current, new) or True,
                         "Password changed. Other devices have been signed out."):
                    st.session_state.pop("token", None)
                    st.rerun()
        with st.expander("Delete account"):
            st.write("This permanently deletes your account and every task, note, project and goal in it.")
            with st.form("delete", clear_on_submit=True):
                pw = st.text_input("Enter your password to confirm", type="password")
                sure = st.checkbox("I understand this can't be undone")
                if st.form_submit_button("Delete my account"):
                    if not sure:
                        st.error("Tick the box to confirm.")
                    elif run(lambda: acc.delete(user["id"], pw) or True):
                        sign_out()


def sidebar(store, user, ctx):
    with st.sidebar:
        st.markdown('<p class="brand">Planner</p><p class="brand-sub">Your day, calmly planned</p>',
                    unsafe_allow_html=True)
        initial = (user["name"] or user["email"])[:1].upper()
        st.markdown(f'<div class="who"><span class="avatar">{esc(initial)}</span><div>{esc(user["name"] or "Welcome")}'
                    f'<small>{esc(user["email"])}</small></div></div>', unsafe_allow_html=True)
        inbox = len(store.list_inbox())
        pending = len(store.open_pending())
        badges = {"inbox": inbox, "assistant": pending}

        def label(key):
            icon, text = PAGES[key]
            n = badges.get(key)
            return f"{icon}  {text}" + (f"  ({n})" if n else "")

        st.radio("Go to", list(PAGES), key="page", format_func=label, label_visibility="collapsed")
        st.write("")
        cfg = resolve_config(store)
        st.caption("AI: " + (cfg["label"].split(" (")[0] if cfg["enabled"] else "basic mode"))
        if st.button("Sign out", use_container_width=True):
            sign_out()


def main():
    st.set_page_config(page_title="Planner", page_icon="☀️", layout="wide", initial_sidebar_state="auto")
    st.markdown(CSS, unsafe_allow_html=True)
    load_secrets()
    restore_session()

    uid = st.session_state.get("uid")
    if not uid:
        page_auth()
        return
    try:
        user = Accounts(conn()).public(uid)
    except ValidationError:  # account was deleted elsewhere
        sign_out()
        return
    if st.session_state.get("set_cookie"):
        set_cookie(st.session_state.pop("set_cookie"))

    now = local_now()
    ctx = {"today": now.date().isoformat(), "now": now.strftime("%H:%M")}
    store = Store(conn(), uid)
    st.session_state.setdefault("page", "today")
    sidebar(store, user, ctx)
    show_flashes()
    page = st.session_state["page"]
    if page != "assistant":
        pending_banner(store, ctx)
    {"today": lambda: page_today(store, ctx, user), "assistant": lambda: page_assistant(store, ctx),
     "inbox": lambda: page_inbox(store, ctx), "tasks": lambda: page_tasks(store, ctx),
     "calendar": lambda: page_week(store, ctx), "notes": lambda: page_notes(store, ctx),
     "projects": lambda: page_projects(store, ctx), "goals": lambda: page_goals(store, ctx),
     "search": lambda: page_search(store, ctx), "settings": lambda: page_settings(store, ctx, user)}[page]()


if __name__ == "__main__":
    main()
