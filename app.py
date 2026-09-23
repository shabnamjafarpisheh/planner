"""Planner: a calm AI day planner for Streamlit, in English and Persian.

Accounts, shared tasks, Jalali or Gregorian calendar, reminders, and an AI
assistant. Everything is in this one file, so it runs as long as app.py and
requirements.txt are present (for example on Streamlit Community Cloud).

Run with:  streamlit run app.py

Sections, in order: locale (Jalali, Persian digits) -> store (accounts,
sharing, database, rules) -> planning -> capture -> providers (AI connections)
-> notify (reminders, calendar files) -> agent -> Streamlit interface.
"""
from __future__ import annotations



# ======================================================================
# locale
# ======================================================================

from datetime import date as _date

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

JALALI_MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
JALALI_MONTHS_EN = ["Farvardin", "Ordibehesht", "Khordad", "Tir", "Mordad", "Shahrivar",
                    "Mehr", "Aban", "Azar", "Dey", "Bahman", "Esfand"]
GREG_MONTHS_FA = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
                  "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
GREG_MONTHS_EN = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
# Python's weekday(): Monday is 0.
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fa_digits(text) -> str:
    return str(text).translate(FA_DIGITS)


def ascii_digits(text) -> str:
    return str(text).translate(TO_ASCII)


# ------------------------------------------------------------------ Jalali
def g2j(gy: int, gm: int, gd: int):
    """Gregorian -> Jalali (year, month, day)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + gd + g_d_m[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def j2g(jy: int, jm: int, jd: int):
    """Jalali -> Gregorian (year, month, day)."""
    jy += 1595
    days = (-355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd
            + ((jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186))
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    month_len = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and gd > month_len[gm]:
        gd -= month_len[gm]
        gm += 1
    return gy, gm + 1, gd


def jalali_month_length(jy: int, jm: int) -> int:
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    # Esfand has 30 days in a leap year: check whether 30 Esfand round-trips.
    return 30 if g2j(*j2g(jy, 12, 30)) == (jy, 12, 30) else 29


def iso_to_jalali(iso: str):
    d = _date.fromisoformat(iso)
    return g2j(d.year, d.month, d.day)


def jalali_to_iso(jy: int, jm: int, jd: int) -> str:
    if not (1 <= jm <= 12) or not (1 <= jd <= jalali_month_length(jy, jm)):
        raise ValueError(f"{jy}/{jm}/{jd} is not a Jalali date")
    return _date(*j2g(jy, jm, jd)).isoformat()


# ------------------------------------------------------------------ formatting
def weekday_label(iso: str, lang: str) -> str:
    wd = _date.fromisoformat(iso).weekday()
    return WEEKDAYS_FA[wd] if lang == "fa" else WEEKDAYS_EN[wd]


def format_date(iso: str, lang: str = "en", calendar: str = "gregorian",
                with_year: bool = False, with_weekday: bool = False) -> str:
    """'22 September' / 'September 22' / '۳۱ شهریور' / '31 Shahrivar', etc."""
    if not iso:
        return ""
    d = _date.fromisoformat(iso)
    if calendar == "jalali":
        jy, jm, jd = g2j(d.year, d.month, d.day)
        month = (JALALI_MONTHS_FA if lang == "fa" else JALALI_MONTHS_EN)[jm - 1]
        text = f"{jd} {month}" + (f" {jy}" if with_year else "")
    elif lang == "fa":
        text = f"{d.day} {GREG_MONTHS_FA[d.month - 1]}" + (f" {d.year}" if with_year else "")
    else:
        text = f"{GREG_MONTHS_EN[d.month - 1]} {d.day}" + (f", {d.year}" if with_year else "")
    if with_weekday:
        wd = weekday_label(iso, lang)
        text = f"{wd} {text}" if lang == "fa" else f"{wd}, {text}"
    return fa_digits(text) if lang == "fa" else text


def short_day(iso: str, lang: str = "en", calendar: str = "gregorian") -> str:
    """Day-of-month number in the chosen calendar, for week columns."""
    d = _date.fromisoformat(iso)
    n = g2j(d.year, d.month, d.day)[2] if calendar == "jalali" else d.day
    return fa_digits(n) if lang == "fa" else str(n)


def month_span(start_iso: str, end_iso: str, lang: str, calendar: str) -> str:
    a = format_date(start_iso, lang, calendar)
    b = format_date(end_iso, lang, calendar, with_year=True)
    return f"{a} تا {b}" if lang == "fa" else f"{a} to {b}"


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
SCHEMA_VERSION = 5

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


def week_start(value: str, first: int = 0) -> str:
    """Start of the week containing value. first: 0 = Monday, 5 = Saturday."""
    d = parse_iso(value)
    return (d - timedelta(days=(d.weekday() - first) % 7)).isoformat()


HHMM_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def check_time(value, field="time"):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not HHMM_RE.fullmatch(value):
        raise ValidationError(f'"{value}" is not a time. Use HH:MM, for example 09:30.')
    return value


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
  scheduled_time TEXT,
  estimate_min INTEGER,
  project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
  goal_id INTEGER REFERENCES goals(id) ON DELETE SET NULL,
  parent_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  tags TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS task_shares (
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'editor' CHECK (role IN ('editor','viewer')),
  shared_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (task_id, user_id)
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  from_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  read_at TEXT,
  delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_shares_user ON task_shares(user_id);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, read_at);
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

DEFAULT_SETTINGS = {
    "workday_start": "09:00", "workday_end": "18:00",
    "lang": "en",               # en | fa
    "calendar": "gregorian",    # gregorian | jalali
    "remind_enabled": "0",      # browser reminders while the app is open
    "remind_lead": "10",        # minutes before a meeting or planned task
    "remind_morning": "",       # HH:MM for a start-of-day summary, or empty
}
LANGS = ("en", "fa")
CALENDARS = ("gregorian", "jalali")
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
    if "scheduled_time" not in _columns(conn, "tasks"):  # added in version 4
        conn.execute("ALTER TABLE tasks ADD COLUMN scheduled_time TEXT")
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

    def update_preferences(self, lang=None, calendar=None):
        if lang is not None:
            if lang not in LANGS:
                raise ValidationError("Unknown language")
            self.set_setting("lang", lang)
        if calendar is not None:
            if calendar not in CALENDARS:
                raise ValidationError("Unknown calendar")
            self.set_setting("calendar", calendar)

    def update_reminders(self, enabled, lead, morning):
        lead = int(lead)
        if not 0 <= lead <= 120:
            raise ValidationError("Choose between 0 and 120 minutes.")
        self.set_setting("remind_enabled", "1" if enabled else "0")
        self.set_setting("remind_lead", str(lead))
        self.set_setting("remind_morning", check_time(morning, "morning time") or "")

    def week_first(self):
        """Jalali weeks start on Saturday; Gregorian ones on Monday."""
        return 5 if self.get_settings()["calendar"] == "jalali" else 0

    def weekend(self):
        """Days off, as Python weekday numbers (Monday is 0)."""
        return (4,) if self.get_settings()["calendar"] == "jalali" else (5, 6)

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
                    goal_id=None, parent_id=None, tags=None, scheduled_time=None):
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
                "scheduled_time, estimate_min, project_id, goal_id, parent_id, tags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.uid, title, clean_text(description, "description", 4000, False), status, priority,
                 due_date or None, scheduled_date or None, check_time(scheduled_time) if scheduled_date else None,
                 estimate_min, project_id, goal_id, parent_id, norm_tags(tags)))
            self.log("create_task", title)
        return self.get_task(cur.lastrowid)

    # A task is yours, or someone shared it with you. Both can see it; only an
    # owner or an editor can change it.
    SHARED = ("(t.user_id = ? OR t.id IN (SELECT task_id FROM task_shares WHERE user_id = ?))")

    def _decorate(self, t):
        """Adds who owns a shared task, who it's shared with, and what you may do."""
        if not t:
            return t
        t["mine"] = t["user_id"] == self.uid
        t["can_edit"] = t["mine"] or bool(self._one(
            "SELECT 1 AS ok FROM task_shares WHERE task_id = ? AND user_id = ? AND role = 'editor'", (t["id"], self.uid)))
        t["shared_with"] = self._q(
            "SELECT s.user_id, s.role, u.name, u.email FROM task_shares s JOIN users u ON u.id = s.user_id "
            "WHERE s.task_id = ? ORDER BY u.name", (t["id"],))
        owner = self._one("SELECT name, email FROM users WHERE id = ?", (t["user_id"],))
        t["owner_name"] = (owner or {}).get("name") or (owner or {}).get("email", "")
        return t

    def get_task(self, tid, for_edit=False):
        t = self._one("SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
                      f"WHERE t.id = ? AND {self.SHARED}", (tid, self.uid, self.uid))
        if not t:
            raise NotFound(f"No task with id {tid}")
        t = self._decorate(t)
        if for_edit and not t["can_edit"]:
            raise ValidationError("This task was shared with you to read, not to change.")
        t["subtasks"] = self._q("SELECT * FROM tasks WHERE parent_id = ? AND user_id = ? ORDER BY id", (tid, self.uid))
        t["blocked_by"] = self._q("SELECT t.id, t.title, t.status FROM task_dependencies d "
                                  "JOIN tasks t ON t.id = d.depends_on_id WHERE d.task_id = ? AND t.user_id = ?",
                                  (tid, self.uid))
        return t

    def list_tasks(self, status=None, open_only=False, project_id=None, goal_id=None,
                   due_before=None, scheduled_on=None, query=None, limit=500, include_shared=True):
        sql = ("SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
               f"WHERE {self.SHARED}") if include_shared else (
               "SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
               "WHERE t.user_id = ?")
        args = [self.uid, self.uid] if include_shared else [self.uid]
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
        return [self._decorate(t) for t in self._q(sql, args)]

    def update_task(self, tid, **fields):
        current = self.get_task(tid, for_edit=True)
        allowed = {k: v for k, v in fields.items() if k in (
            "title", "description", "status", "priority", "due_date", "scheduled_date",
            "scheduled_time", "estimate_min", "project_id", "goal_id", "tags")}
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
        if "scheduled_time" in allowed:
            allowed["scheduled_time"] = check_time(allowed["scheduled_time"])
        elif "scheduled_date" in allowed and allowed["scheduled_date"] != current["scheduled_date"]:
            allowed["scheduled_time"] = None  # a time from the old day no longer applies
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
            c.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*allowed.values(), tid))
            self.log("update_task", str(tid))
        done = allowed.get("status") == "completed" and current["status"] != "completed"
        out = self.get_task(tid)
        if done:
            self._tell_others(out, "completed")
        return out

    def complete_task(self, tid):
        t = self.get_task(tid, for_edit=True)
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

    def bulk_reschedule(self, ids, date, times=None):
        """Move tasks to a date, optionally at given start times ({id: "HH:MM"})."""
        check_date(date, "date", required=True)
        ids = [int(i) for i in ids]
        times = {int(k): check_time(v) for k, v in (times or {}).items()}
        if not ids:
            raise ValidationError("No tasks given")
        with self.tx() as c:
            for tid in ids:
                self.get_task(tid, for_edit=True)  # yours, or shared with you as an editor
                c.execute("UPDATE tasks SET scheduled_date = ?, scheduled_time = ?, status = CASE WHEN status = 'inbox' "
                          "THEN 'planned' ELSE status END WHERE id = ?", (date, times.get(tid), tid))
            self.log("bulk_reschedule", f"{len(ids)} tasks to {date}")
        return {"moved": len(ids), "date": date, "ids": ids}

    def delete_task(self, tid):
        t = self.get_task(tid)
        if not t["mine"]:
            raise ValidationError("Only the person who created a shared task can delete it. "
                                  "You can remove it from your list instead.")
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

    # ------------------------------------------------------------ sharing
    def _user_by_email(self, email):
        email = clean_text(email, "Email", 254).lower()
        return self._one("SELECT id, name, email FROM users WHERE email = ?", (email,))

    def share_task(self, tid, email, role="editor"):
        """Let someone else see (and usually change) one of your tasks."""
        if role not in ("editor", "viewer"):
            raise ValidationError("Choose editor or viewer.")
        t = self.get_task(tid)
        if not t["mine"]:
            raise ValidationError("Only the person who created a task can share it.")
        other = self._user_by_email(email)
        if not other:
            raise ValidationError("No account uses that email yet. Ask them to create one first.")
        if other["id"] == self.uid:
            raise ValidationError("That's your own account.")
        with self.tx() as c:
            c.execute("INSERT INTO task_shares (task_id, user_id, role, shared_by) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT(task_id, user_id) DO UPDATE SET role = excluded.role",
                      (tid, other["id"], role, self.uid))
            self.log("share_task", f"{t['title']} -> {other['email']}")
        self._notify(other["id"], "shared", t["title"], tid)
        return {"task": self.get_task(tid), "shared_with": other["email"], "role": role}

    def unshare_task(self, tid, user_id):
        """The owner removes someone; anyone can remove themselves."""
        t = self.get_task(tid)
        user_id = int(user_id)
        if not t["mine"] and user_id != self.uid:
            raise ValidationError("You can only remove yourself from a shared task.")
        with self.tx() as c:
            c.execute("DELETE FROM task_shares WHERE task_id = ? AND user_id = ?", (tid, user_id))
            self.log("unshare_task", str(tid))
        return {"task_id": tid, "removed": user_id}

    def shared_with_me(self, open_only=True):
        rows = self._q("SELECT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
                       "JOIN task_shares s ON s.task_id = t.id WHERE s.user_id = ?"
                       + (" AND t.status IN ('inbox','planned','in_progress')" if open_only else "")
                       + " ORDER BY t.due_date IS NULL, t.due_date, t.id DESC", (self.uid,))
        return [self._decorate(t) for t in rows]

    def shared_by_me(self, open_only=True):
        rows = self._q("SELECT DISTINCT t.*, p.name AS project_name FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "
                       "JOIN task_shares s ON s.task_id = t.id WHERE t.user_id = ?"
                       + (" AND t.status IN ('inbox','planned','in_progress')" if open_only else "")
                       + " ORDER BY t.due_date IS NULL, t.due_date, t.id DESC", (self.uid,))
        return [self._decorate(t) for t in rows]

    def people_i_share_with(self):
        return self._q("SELECT DISTINCT u.email, u.name FROM task_shares s JOIN users u ON u.id = s.user_id "
                       "WHERE s.task_id IN (SELECT id FROM tasks WHERE user_id = ?) ORDER BY u.name", (self.uid,))

    def nudge(self, tid):
        """A gentle 'remember this one' to everyone else on a shared task."""
        t = self.get_task(tid)
        others = self._tell_others(t, "nudge")
        if not others:
            raise ValidationError("This task isn't shared with anyone yet.")
        return {"sent_to": others}

    # ------------------------------------------------------------ notifications
    def _notify(self, user_id, kind, title, task_id=None):
        if int(user_id) == self.uid:
            return
        with self.tx() as c:
            c.execute("INSERT INTO notifications (user_id, from_user_id, kind, task_id, title) VALUES (?, ?, ?, ?, ?)",
                      (int(user_id), self.uid, kind, task_id, title[:200]))

    def _tell_others(self, task, kind):
        """Everyone on a shared task except whoever did the thing."""
        people = [s["user_id"] for s in task.get("shared_with", [])] + [task["user_id"]]
        others = [p for p in dict.fromkeys(people) if p != self.uid]
        for uid in others:
            self._notify(uid, kind, task["title"], task["id"])
        return others

    def list_notifications(self, limit=30):
        return self._q("SELECT n.*, u.name AS from_name, u.email AS from_email FROM notifications n "
                       "LEFT JOIN users u ON u.id = n.from_user_id WHERE n.user_id = ? "
                       "ORDER BY n.id DESC LIMIT ?", (self.uid, limit))

    def unread_count(self):
        return self._one("SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
                         (self.uid,))["n"]

    def mark_notifications_read(self, ids=None):
        with self.tx() as c:
            if ids:
                marks = ",".join("?" * len(ids))
                c.execute(f"UPDATE notifications SET read_at = datetime('now') WHERE user_id = ? AND id IN ({marks})",
                          (self.uid, *[int(i) for i in ids]))
            else:
                c.execute("UPDATE notifications SET read_at = datetime('now') WHERE user_id = ? AND read_at IS NULL",
                          (self.uid,))

    def undelivered_notifications(self):
        """New updates that haven't been shown as a browser notification yet."""
        return self._q("SELECT n.*, u.name AS from_name, u.email AS from_email FROM notifications n "
                       "LEFT JOIN users u ON u.id = n.from_user_id "
                       "WHERE n.user_id = ? AND n.delivered_at IS NULL ORDER BY n.id", (self.uid,))

    def mark_delivered(self, ids):
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        with self.tx() as c:
            c.execute(f"UPDATE notifications SET delivered_at = datetime('now') WHERE user_id = ? AND id IN ({marks})",
                      (self.uid, *[int(i) for i in ids]))

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
        start = week_start(start, self.week_first())
        open_tasks = self.list_tasks(open_only=True)
        days = []
        for i in range(7):
            d = add_days(start, i)
            days.append({"date": d, "weekday": weekday_name(d), "tasks": self.list_tasks(scheduled_on=d),
                         "due": [t for t in open_tasks if t["due_date"] == d], "events": self.list_events(d)})
        return {"start": start, "end": add_days(start, 6), "days": days}

    def weekly_review(self, start):
        start = week_start(start, self.week_first())
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

    def upcoming(self, today):
        """Meetings and timed tasks for today and tomorrow, for reminders."""
        tomorrow = add_days(today, 1)
        events = self.list_events(today, tomorrow)
        tasks = [t for t in self.list_tasks(open_only=True)
                 if t["scheduled_date"] in (today, tomorrow) and t.get("scheduled_time")]
        return {"events": events, "tasks": tasks}

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
              workday_start="09:00", workday_end="18:00", include_weekend=False,
              week_first=0, weekend=(5, 6)):
    """Spread open work across the days left this week, respecting deadlines."""
    events_by_day = events_by_day or {}
    start = week_start(date, week_first)
    days = []
    for i in range(7):
        d = add_days(start, i)
        if d < date:
            continue
        if not include_weekend and parse_iso(d).weekday() in weekend:
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
    if PERSIAN_RE.search(text):
        return parse_capture_fa(text, today)

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
    if PERSIAN_RE.search(text or ""):
        norm = _fa_norm(text)
        if FA_LABEL_RE.match(norm) or (FA_IDEA_RE.search(norm) and not FA_ACTION_RE.search(norm)):
            return {"type": "note", "reason": "idea"}
        if FA_ACTION_RE.search(norm):
            found = parse_date_fa(text, today)
            extra = {}
            if found:
                extra["due_date" if found[2] == "due" else "scheduled_date"] = found[0]
            return {"type": "task", "reason": "task", **extra}
        return {"type": "note", "reason": "no_action"}
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


# ------------------------------------------------------------------ Persian
PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")
FA_WEEKDAYS = {"دوشنبه": 0, "دو شنبه": 0, "سه شنبه": 1, "سهشنبه": 1, "چهارشنبه": 2, "چهار شنبه": 2,
               "پنجشنبه": 3, "پنج شنبه": 3, "جمعه": 4, "شنبه": 5, "یکشنبه": 6, "یک شنبه": 6}
FA_WEEKDAY_RE = re.compile(r"(?<!\w)(سه ?شنبه|پنج ?شنبه|چهار ?شنبه|یک ?شنبه|دو ?شنبه|جمعه|شنبه)(?!\w)")
FA_DUE_RE = re.compile(r"(?<!\w)(تا|قبل از|مهلت|ددلاین|موعد|حداکثر)(?!\w)")
FA_ACTION_RE = re.compile(
    r"(تماس|زنگ|بخرم|بخریم|خرید|بفرستم|ارسال|تمام|تموم|بنویسم|نوشتن|پرداخت|بپردازم|رزرو|بررسی|آماده|"
    r"ایمیل|پیام|ملاقات|ببینم|تحویل|ثبت نام|تمیز|بشویم|بپزم|یاد بگیرم|تمرین|مطالعه|بخوانم|بخونم|"
    r"درست کنم|تعمیر|ببرم|بیاورم|بیارم|بگیرم|انجام|تکمیل|به روز|ارائه|چک کنم|بپرسم|یادم باشد|یادم باشه|"
    r"باید|برم|بروم|بزنم|کنم|بکنم|بدهم|بدم|بسازم|طراحی|تمدید|لغو|سفارش|نوبت|قرار)")
FA_IDEA_RE = re.compile(r"(ایده|فکر|شاید|یادداشت|نکته|چطوره|چطور است|چه طور است)")
FA_LABEL_RE = re.compile(r"^\s*(یک |یه )?(ایده|فکر|یادداشت|نکته)\s*[:：]\s*")


def _fa_norm(text):
    """Standard Persian letters, ASCII digits, spaces instead of half-spaces."""
    return (ascii_digits(text).replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")
            .replace("ة", "ه"))


def parse_date_fa(text, today):
    """Like parse_date, for Persian wording. Returns (iso, phrase, kind) or None."""
    t = _fa_norm(text)
    kind = "due" if FA_DUE_RE.search(t) else "scheduled"
    if re.search(r"پس ?فردا", t):
        return add_days(today, 2), "پس‌فردا", kind
    if re.search(r"(?<!\w)(امروز|امشب)(?!\w)", t):
        return today, "امروز", kind
    if re.search(r"(?<!\w)فردا(?!\w)", t):
        return add_days(today, 1), "فردا", kind
    if re.search(r"(?<!\w)دیروز(?!\w)", t):
        return add_days(today, -1), "دیروز", kind
    m = re.search(r"(\d{1,3})\s*(روز|هفته)\s*(دیگر|بعد|آینده)", t)
    if m:
        n = int(m.group(1)) * (7 if m.group(2) == "هفته" else 1)
        return add_days(today, n), m.group(0), kind
    if re.search(r"هفته ?(ی)? ?(بعد|آینده|دیگر)", t):
        return add_days(today, 7), "هفته بعد", kind
    m = re.search(r"(\d{1,2})\s*(" + "|".join(JALALI_MONTHS_FA) + r")(\s*(\d{4}))?", t)
    if m:
        jd, jm = int(m.group(1)), JALALI_MONTHS_FA.index(m.group(2)) + 1
        jy = int(m.group(4)) if m.group(4) else iso_to_jalali(today)[0]
        try:
            iso = jalali_to_iso(jy, jm, jd)
            if iso < today and not m.group(4):
                iso = jalali_to_iso(jy + 1, jm, jd)
            return iso, m.group(0), kind
        except ValueError:
            return None
    m = FA_WEEKDAY_RE.search(t)
    if m:
        target = FA_WEEKDAYS[re.sub(r"\s+", " ", m.group(1))] if re.sub(r"\s+", " ", m.group(1)) in FA_WEEKDAYS \
            else FA_WEEKDAYS[m.group(1).replace(" ", "")]
        delta = (target - parse_iso(today).weekday()) % 7 or 7
        return add_days(today, delta), m.group(1), kind
    return None


_Z = "[ \u200c]?"  # a space, a half-space, or nothing
FA_DATE_WORDS = re.compile(
    r"(?<!\w)((تا|قبل از|مهلت|ددلاین|موعد|حداکثر|برای)\s+)?"
    r"(پس" + _Z + r"فردا|امروز|امشب|فردا|دیروز|\d{1,3}\s*(روز|هفته)\s*(دیگر|بعد|آینده)|"
    r"هفته" + _Z + r"(ی)?\s*(بعد|آینده|دیگر)|"
    r"(سه" + _Z + r"شنبه|پنج" + _Z + r"شنبه|چهار" + _Z + r"شنبه|یک" + _Z + r"شنبه|دو" + _Z + r"شنبه|جمعه|شنبه)|"
    r"\d{1,2}\s*(" + "|".join(JALALI_MONTHS_FA) + r")(\s*\d{4})?)(?!\w)")


def _fa_clean(text):
    """Keep what the person typed (half-spaces included), only unify Arabic letter forms."""
    return text.replace("ي", "ی").replace("ك", "ک")


def _fa_title(part):
    t = FA_DATE_WORDS.sub(" ", _fa_clean(part))
    t = re.sub(r"^\s*(و|من|باید|یادم باشد|یادم باشه|لطفا|لطفاً)\s+", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ،,.؛")
    return t[:200]


def parse_capture_fa(text, today):
    out = {"tasks": [], "notes": [], "people": [], "dates": []}
    for sentence in re.split(r"[.!؟?\n؛]+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        chunks = []
        for piece in re.split(r"[،,]", sentence):
            piece = piece.strip()
            if not piece:
                continue
            # Split on "و" only when every side reads like its own action,
            # so "کتاب و دفتر بخرم" stays one task.
            sides = [x.strip() for x in re.split(r"\s+و\s+", piece) if x.strip()]
            if len(sides) > 1 and all(FA_ACTION_RE.search(_fa_norm(x)) or FA_LABEL_RE.match(x) for x in sides):
                chunks.extend(sides)
            else:
                chunks.append(re.sub(r"^\s*و\s+", "", piece))
        for chunk in chunks:
            norm = _fa_norm(chunk)
            original = _fa_clean(chunk).strip()
            label = FA_LABEL_RE.match(original) or FA_LABEL_RE.match(norm)
            maybe = re.match(r"^\s*(شاید|چطوره|چطور است)", norm)
            if label or maybe or (FA_IDEA_RE.search(norm) and not FA_ACTION_RE.search(norm)):
                body = FA_LABEL_RE.sub("", original).strip() if label else original
                body = body.rstrip("؟?.")
                if not body:
                    continue
                kind = label.group(2) if label else None
                shown = body if len(body) <= 50 else body[:50].rstrip() + "…"
                out["notes"].append({"title": f"{kind}: {shown}" if kind else shown[:80], "content": body})
                continue
            if not FA_ACTION_RE.search(norm):
                out["notes"].append({"title": original[:80], "content": original})
                continue
            title = _fa_title(chunk)
            if not title:
                continue
            task = {"title": title, "people": []}
            found = parse_date_fa(chunk, today)
            if found:
                iso, phrase, kind = found
                task["due_date" if kind == "due" else "scheduled_date"] = iso
                out["dates"].append({"date": iso, "phrase": phrase, "kind": kind})
            out["tasks"].append(task)
    return out


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
# notify
# ======================================================================

import hashlib
from datetime import datetime, timedelta, timezone



def _ics_escape(text: str) -> str:
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Lines longer than 75 bytes are folded, as the calendar format requires."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def _stamp(date_iso: str, hhmm: str) -> str:
    return date_iso.replace("-", "") + "T" + hhmm.replace(":", "") + "00"


def plan_items(events, tasks, default_minutes=30):
    """Meetings and timed tasks as calendar items."""
    items = []
    for e in events:
        items.append({"key": f"event-{e['id']}", "title": e["title"], "date": e["date"],
                      "start": e["start_time"], "end": e["end_time"], "kind": "event"})
    for t in tasks:
        if not (t.get("scheduled_date") and t.get("scheduled_time")):
            continue
        end = from_min(to_min(t["scheduled_time"]) + int(t.get("estimate_min") or default_minutes))
        items.append({"key": f"task-{t['id']}", "title": t["title"], "date": t["scheduled_date"],
                      "start": t["scheduled_time"], "end": end, "kind": "task"})
    return sorted(items, key=lambda i: (i["date"], i["start"]))


def build_ics(items, lead_min=10, calendar_name="Planner", user_key=""):
    """A calendar file with an alarm before each item. Times are local
    ("floating"), so the calendar app shows them in the person's own time."""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Planner//Daily plan//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(calendar_name)}"]
    for it in items:
        # A stable id means importing an updated plan replaces items instead of duplicating them.
        uid = hashlib.sha256(f"{user_key}|{it['key']}|{it['date']}".encode()).hexdigest()[:32] + "@planner"
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{now}",
                  f"DTSTART:{_stamp(it['date'], it['start'])}", f"DTEND:{_stamp(it['date'], it['end'])}",
                  f"SUMMARY:{_ics_escape(it['title'])}"]
        if lead_min is not None and lead_min >= 0:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(it['title'])}",
                      f"TRIGGER:-PT{int(lead_min)}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def build_reminders(upcoming, today, now_hm, lead_min=10, morning="", lang="en", summary=None):
    """Reminders for the next 24 hours: [{at, title, body, tag}].
    'at' is local time ('YYYY-MM-DDTHH:MM'); the browser works out the wait."""
    fa = lang == "fa"
    out = []
    now = datetime.fromisoformat(f"{today}T{now_hm}")
    horizon = now + timedelta(hours=24)
    for it in plan_items(upcoming.get("events", []), upcoming.get("tasks", [])):
        start = datetime.fromisoformat(f"{it['date']}T{it['start']}")
        at = start - timedelta(minutes=int(lead_min))
        if not now <= at <= horizon:
            continue
        when = fa_digits(it["start"]) if fa else it["start"]
        mins = fa_digits(lead_min) if fa else lead_min
        if it["kind"] == "event":
            title = f"جلسه ساعت {when}" if fa else f"Meeting at {when}"
        else:
            title = f"شروع کار ساعت {when}" if fa else f"Up next at {when}"
        body = it["title"] + ((f" (تا {mins} دقیقهٔ دیگر)" if fa else f" (in {mins} min)") if lead_min else "")
        out.append({"at": at.strftime("%Y-%m-%dT%H:%M"), "title": title, "body": body,
                    "tag": f"{it['key']}-{it['date']}-{it['start']}"})
    if morning and summary is not None:
        for day in (today, add_days(today, 1)):
            at = datetime.fromisoformat(f"{day}T{morning}")
            if now <= at <= horizon:
                s = summary(day)
                if fa:
                    body = f"{fa_digits(s['tasks'])} کار و {fa_digits(s['events'])} جلسه" + \
                           (f"، {fa_digits(s['overdue'])} کار عقب‌افتاده" if s["overdue"] else "")
                    title = "برنامهٔ امروز"
                else:
                    body = f"{s['tasks']} task(s) and {s['events']} meeting(s)" + \
                           (f", {s['overdue']} overdue" if s["overdue"] else "")
                    title = "Your day"
                out.append({"at": at.strftime("%Y-%m-%dT%H:%M"), "title": title, "body": body,
                            "tag": f"morning-{day}"})
    return sorted(out, key=lambda r: r["at"])


# ======================================================================
# agent
# ======================================================================

import json


MAX_STEPS = 8
BASIC_NOTE = ("Basic mode: I handle capture, planning, overdue checks and search. "
              "Connect a free AI in Settings for full natural-language help.")
BASIC_NOTE_FA = ("حالت ساده: ثبت، برنامه‌ریزی، کارهای عقب‌افتاده و جستجو را انجام می‌دهم. "
                 "برای گفتگوی کامل، در تنظیمات یک هوش مصنوعی رایگان وصل کنید.")

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
        {"name": "share_task", "description": "Share one of the user's tasks with another person by email. "
                                             "Both then see it; an editor can also change it.",
         "input_schema": {**_S(id=num, email=text, role={"type": "string", "description": "editor or viewer"}),
                          "required": ["id", "email"]}},
        {"name": "nudge_task", "description": "Send a short reminder about a shared task to the other people on it.",
         "input_schema": {**_S(id=num), "required": ["id"]}},
        {"name": "list_shared", "description": "Tasks shared with the user, and tasks the user shares with others.",
         "input_schema": _S()},
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


READ_ONLY = {"list_shared", "search_tasks", "get_task", "search_notes", "get_note", "search_projects", "get_project",
             "search_goals", "get_goal", "list_events", "get_today", "get_week", "plan_day",
             "plan_week", "weekly_review", "search_context", "process_inbox"}


def needs_confirmation(name, args):
    """Destructive or sweeping changes wait for a person."""
    if name in ("delete_task", "delete_note", "delete_project"):
        return True
    if name == "share_task":       # someone else would start seeing this task
        return True
    if name == "bulk_reschedule" and len(args.get("ids") or []) > 2:
        return True
    if name == "apply_schedule" and len(args.get("changes") or []) > 3:
        return True
    return False


def _prefs(store):
    st = store.get_settings()
    return st.get("lang", "en"), st.get("calendar", "gregorian")


def _date_text(store, iso):
    lang, cal = _prefs(store)
    return format_date(iso, lang, cal) if iso else ""


def summarize_pending(store, name, args):
    """What a parked action will do, in the person's language (shown on the confirm card)."""
    fa = _prefs(store)[0] == "fa"
    if name == "delete_task":
        t = store.get_task(args["id"])["title"]
        return f"حذف کار «{t}»" if fa else f'Delete the task "{t}"'
    if name == "delete_note":
        t = store.get_note(args["id"])["title"]
        return f"حذف یادداشت «{t}»" if fa else f'Delete the note "{t}"'
    if name == "delete_project":
        t = store.get_project(args["id"])["name"]
        return (f"حذف پروژه «{t}» (کارها و یادداشت‌هایش می‌مانند)" if fa
                else f'Delete the project "{t}" (its tasks and notes are kept)')
    if name == "bulk_reschedule":
        titles = []
        for i in args["ids"][:3]:
            try:
                titles.append(store.get_task(i)["title"])
            except ValidationError:
                pass
        n, when = len(args["ids"]), _date_text(store, args["date"])
        if fa:
            more = "" if n <= 3 else f" و {fa_digits(n - 3)} کار دیگر"
            return f"انتقال {fa_digits(n)} کار به {when}: " + "، ".join(f"«{t}»" for t in titles) + more
        more = "" if n <= 3 else f" and {n - 3} more"
        return f"Move {n} tasks to {when}: " + ", ".join(f'"{t}"' for t in titles) + more
    if name == "share_task":
        t = store.get_task(args["id"])["title"]
        who = args.get("email", "")
        viewer = (args.get("role") == "viewer")
        if fa:
            return f"به اشتراک گذاشتن «{t}» با {who}" + ("، فقط برای دیدن" if viewer else "")
        return f'Share "{t}" with {who}' + (" (view only)" if viewer else "")
    if name == "apply_schedule":
        n = len(args["changes"])
        return f"ثبت {fa_digits(n)} تاریخ از برنامهٔ پیشنهادی" if fa else f"Save {n} scheduled dates from the plan"
    return f"Run {name}"


def day_plan(store, date, available_min=None, now=None):
    """A timed plan for one day. Tasks deliberately planned for a later day
    stay there; everything else open is a candidate."""
    settings = store.get_settings()
    tasks = [store.get_task(t["id"]) for t in store.list_tasks(open_only=True)
             if not (t["scheduled_date"] and t["scheduled_date"] > date)]
    return plan_day(tasks, date, events=store.list_events(date), now=now,
                    available_min=available_min, workday_start=settings["workday_start"],
                    workday_end=settings["workday_end"])


def week_plan(store, start, now=None, today=None):
    """Plan the rest of a week. Days that have already passed are never used."""
    settings = store.get_settings()
    first_day = store.week_first()
    start = week_start(start, first_day)
    today = today or start
    first = max(start, today)
    fa = settings.get("lang") == "fa"
    if first > add_days(start, 6):
        return {"start": start, "days": [], "changes": [], "at_risk": [],
                "assumptions": ["این هفته تمام شده و چیزی برای برنامه‌ریزی نمانده." if fa else
                                "That week is already over, so there's nothing left to plan."]}
    events = {add_days(start, i): store.list_events(add_days(start, i)) for i in range(7)}
    return plan_week(store.list_tasks(open_only=True), first, events_by_day=events,
                     now=now if first == today else None,
                     workday_start=settings["workday_start"], workday_end=settings["workday_end"],
                     week_first=first_day, weekend=store.weekend())


def apply_schedule(store, changes):
    """Save dates (and start times, when a day plan gives them)."""
    by_date = {}
    for c in changes:
        by_date.setdefault(c["to"], []).append(c)
    applied = 0
    for date, items in by_date.items():
        times = {int(c["id"]): c["time"] for c in items if c.get("time")}
        store.bulk_reschedule([int(c["id"]) for c in items], date, times)
        applied += len(items)
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
    if name == "share_task":
        return store.share_task(args["id"], args["email"], args.get("role") or "editor")
    if name == "nudge_task":
        return store.nudge(args["id"])
    if name == "list_shared":
        keep = ("id", "title", "status", "due_date", "scheduled_date", "owner_name", "shared_with", "can_edit")
        trim = lambda rows: [{k: t.get(k) for k in keep} for t in rows]
        return {"shared_with_me": trim(store.shared_with_me()), "shared_by_me": trim(store.shared_by_me())}
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


def describe_action(name, args, result, lang="en"):
    title = ""
    if isinstance(result, dict):
        title = result.get("title") or result.get("name") or ""
    title = title or args.get("title") or args.get("name") or ""
    if lang == "fa":
        n = lambda v: fa_digits(len(v or []))
        labels = {
            "create_task": f"کار «{title}» اضافه شد", "update_task": f"کار «{title}» به‌روز شد",
            "complete_task": f"«{title}» انجام شد", "delete_task": f"کار «{title}» حذف شد",
            "reschedule_task": f"«{title}» جابه‌جا شد", "bulk_reschedule": f"{n(args.get('ids'))} کار جابه‌جا شد",
            "split_task": f"کار به {n(args.get('subtasks'))} بخش تقسیم شد",
            "create_note": f"یادداشت «{title}» ذخیره شد", "update_note": f"یادداشت «{title}» به‌روز شد",
            "delete_note": f"یادداشت «{title}» حذف شد", "create_project": f"پروژهٔ «{title}» ساخته شد",
            "delete_project": f"پروژهٔ «{title}» حذف شد", "create_goal": f"هدف «{title}» ساخته شد",
            "breakdown_goal": f"هدف «{args.get('title')}» با {n(args.get('projects'))} پروژه ساخته شد",
            "create_event": f"رویداد «{title}» اضافه شد",
            "share_task": f"«{title}» با {args.get('email', '')} به اشتراک گذاشته شد",
            "nudge_task": "یادآوری برای هم‌تیمی‌ها فرستاده شد", "apply_schedule": f"{n(args.get('changes'))} کار زمان‌بندی شد",
            "process_inbox_item": "یک مورد صندوق ورودی مرتب شد", "remember_fact": f"به خاطر سپردم: {args.get('fact')}",
        }
        return labels.get(name, name)
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
        "share_task": f'Shared "{title}" with {args.get("email", "")}',
        "nudge_task": "Sent a reminder to the others on that task",
        "apply_schedule": f'Scheduled {len(args.get("changes") or [])} tasks',
        "process_inbox_item": f'Processed an inbox item as {args.get("type")}',
        "remember_fact": f'Remembered: {args.get("fact")}',
    }
    return labels.get(name, name)


def system_prompt(store, ctx):
    snap = store.snapshot(ctx["today"])
    lang, cal = _prefs(store)
    facts = "\n".join(f"- {f}" for f in snap["memories"]) or "- (nothing yet)"
    projects = "\n".join(f"- #{p['id']} {p['name']}" + (f" (due {p['due_date']})" if p["due_date"] else "")
                         for p in snap["projects"]) or "- (none)"
    goals = "\n".join(f"- #{g['id']} {g['title']}" + (f" (by {g['deadline']})" if g["deadline"] else "")
                      for g in snap["goals"]) or "- (none)"
    jy, jm, jd = iso_to_jalali(ctx["today"])
    language = ""
    if lang == "fa":
        language = ("\n- Always reply in Persian (Farsi), in a warm, plain tone. Task and note titles you create "
                    "should be in the language the user wrote them in.")
    calendar = ""
    if cal == "jalali":
        calendar = (f"\n- The user reads dates in the Jalali (Solar Hijri) calendar. Today is Jalali {jy}/{jm:02d}/{jd:02d}. "
                    "Tools always take and return Gregorian YYYY-MM-DD; the app converts them for display. "
                    "When you mention a day, prefer weekday names or relative words (today, tomorrow, next Saturday) "
                    "over converting dates yourself. Weeks start on Saturday and Friday is the weekend.")
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
- Tasks can be shared with other people by email. Sharing asks the user to confirm first.
  Never guess an email address; use one the user gave you.
- Be concise: short sentences, compact lists, no preamble. Refer to items by title, not id.{language}{calendar}
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
                out["notice"] = (f"هوش مصنوعی در دسترس نبود ({e}). با حالت ساده جواب دادم."
                                 if _prefs(store)[0] == "fa" else f"AI unavailable: {e} Answered in basic mode.")
        else:
            out = fallback_agent(agent_store, message, ctx)
            out["notice"] = BASIC_NOTE_FA if _prefs(store)[0] == "fa" else (cfg["problem"] or BASIC_NOTE)
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
            return {"reply": ("هوش مصنوعی وسط کار قطع شد. هر چه در فهرست زیر آمده ذخیره شده است."
                              if _prefs(store)[0] == "fa" else
                              "The AI stopped responding partway through. Anything listed below was saved."),
                    "actions": actions, "pending": pending, "plan": plan, "mode": "ai"}

        messages.append({"role": "assistant", "content": res["content"]})
        uses = [b for b in res["content"] if b["type"] == "tool_use"]
        if res.get("stop_reason") != "tool_use" or not uses:
            reply = "\n".join(b["text"] for b in res["content"] if b["type"] == "text").strip()
            return {"reply": reply or ("انجام شد." if _prefs(store)[0] == "fa" else "Done."), "actions": actions, "pending": pending,
                    "plan": plan, "mode": "ai"}

        results = []
        for use in uses:
            try:
                result = run_tool(store, use["name"], use.get("input") or {}, ctx)
                if isinstance(result, dict) and result.get("needs_confirmation"):
                    pending.append({"id": result["pending_action_id"], "summary": result["summary"]})
                elif use["name"] not in READ_ONLY:
                    actions.append(describe_action(use["name"], use.get("input") or {}, result, _prefs(store)[0]))
                if use["name"] in ("plan_day", "plan_week"):
                    plan = {"kind": use["name"], "data": result}
                results.append({"type": "tool_result", "tool_use_id": use["id"],
                                "content": json.dumps(result, default=str)[:40000]})
            except Exception as e:  # tool errors go back to the model, which can correct itself
                results.append({"type": "tool_result", "tool_use_id": use["id"],
                                "is_error": True, "content": str(e)})
        messages.append({"role": "user", "content": results})

    return {"reply": ("بعد از چند مرحله کار تمام نشد. درخواست را طور دیگری بنویسید." if _prefs(store)[0] == "fa" else
                      "I stopped after several steps without finishing. Try rephrasing the request."),
            "actions": actions, "pending": pending, "plan": plan, "mode": "ai"}


# ------------------------------------------------------------------ fallback
def fallback_agent(store, message, ctx, mode_hint=None):
    """Rule-based answers so the app is useful with no AI at all. Understands
    common requests in English and Persian and answers in the person's language."""
    import re
    lang, cal = _prefs(store)
    fa = lang == "fa"
    m = ascii_digits(message).lower().strip()
    today = ctx["today"]
    actions, pending = [], []
    reply = lambda text, **extra: {"reply": text, "actions": actions, "pending": pending,
                                   "plan": extra.pop("plan", None), "mode": "basic", **extra}

    hours = re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h\b|ساعت)", m)
    mins = re.search(r"(\d+)\s*(minutes?|mins?|دقیقه)", m)
    available = int(float(hours.group(1)) * 60) if hours else (int(mins.group(1)) if mins else None)
    said_tomorrow = "tomorrow" in m or "فردا" in m

    if mode_hint != "capture":
        if re.search(r"\b(plan my day|what should i (work on|do)|plan (for )?today|i (only )?have \d)", m) or \
                re.search(r"برنامه(ٔ|ی)?\s*(امروز|روزم)|برنامه\s*ریزی\s*(امروز|روز)|الان چه کار|فقط \d+ ?(ساعت|دقیقه)", m):
            date = add_days(today, 1) if said_tomorrow else today
            plan = day_plan(store, date, available, ctx.get("now") if date == today else None)
            return reply(format_day_plan(plan, lang), plan={"kind": "plan_day", "data": plan})

        if re.search(r"\bplan (my |the )?week|next (three|3) days\b", m) or re.search(r"برنامه(ٔ|ی)?\s*(هفته|این هفته)", m):
            plan = week_plan(store, today, ctx.get("now"), today)
            lines = []
            for d in plan["days"]:
                names = ("، " if fa else ", ").join(t["title"] for t in d["tasks"]) or ("برنامه‌ای ندارد" if fa else "nothing planned")
                lines.append(f"{weekday_label(d['date'], lang)} {format_date(d['date'], lang, cal)}: {names}")
            head = "پیشنهاد برای این هفته:" if fa else "Proposed week:"
            return reply(head + "\n" + "\n".join(f"• {l}" for l in lines), plan={"kind": "plan_week", "data": plan})

        if re.search(r"\b(falling behind|overdue|late|behind on)\b", m) or re.search(r"عقب|دیر شده|سررسید گذشته|عقب‌افتاده", m):
            overdue = store.overdue_tasks(today)
            carried = [t for t in store.unfinished_tasks(today) if t not in overdue]
            if not overdue and not carried:
                return reply("هیچ کاری عقب نیفتاده. همه چیز روبه‌راه است." if fa else "Nothing is overdue. You're on top of it.")
            if fa:
                lines = [f"• {t['title']}، مهلتش {format_date(t['due_date'], lang, cal)} بود" for t in overdue]
                lines += [f"• {t['title']}، برای {format_date(t['scheduled_date'], lang, cal)} برنامه‌ریزی شده بود" for t in carried]
                head = f"عقب‌افتاده ({fa_digits(len(overdue))})" if overdue else "باقی‌مانده از روزهای قبل"
            else:
                lines = [f"• {t['title']}, due {format_date(t['due_date'], lang, cal)}" for t in overdue]
                lines += [f"• {t['title']}, planned {format_date(t['scheduled_date'], lang, cal)}" for t in carried]
                head = f"Overdue ({len(overdue)})" if overdue else "Carried over"
            return reply(f"{head}:\n" + "\n".join(lines))

        if re.search(r"\bmove (all )?(unfinished|leftover|remaining).*(tomorrow|today)\b", m) or \
                re.search(r"(ناتمام|باقی‌مانده|باقیمانده|انجام نشده).*(فردا|امروز)", m):
            target = add_days(today, 1) if said_tomorrow else today
            items = store.unfinished_tasks(today)
            if not items:
                return reply("کار ناتمامی برای جابه‌جایی نیست." if fa else "There are no unfinished tasks to move.")
            ids = [t["id"] for t in items]
            result = run_tool(store, "bulk_reschedule", {"ids": ids, "date": target}, ctx)
            if isinstance(result, dict) and result.get("needs_confirmation"):
                pending.append({"id": result["pending_action_id"], "summary": result["summary"]})
                return reply("این کار به تأیید شما نیاز دارد." if fa else "This needs your confirmation.")
            actions.append(describe_action("bulk_reschedule", {"ids": ids, "date": target}, None, lang))
            when = format_date(target, lang, cal)
            return reply(f"{fa_digits(len(ids))} کار به {when} منتقل شد." if fa else f"Moved {len(ids)} task(s) to {when}.")

        if re.search(r"\b(summar(y|ize|ise)).*(week|wrote)\b", m) or re.search(r"خلاصه", m):
            r = store.weekly_review(today)
            if fa:
                return reply(f"این هفته: {fa_digits(len(r['completed']))} کار انجام شد، "
                             f"{fa_digits(len(r['unfinished']))} کار ناتمام ماند و {fa_digits(len(r['notes']))} یادداشت نوشتید.")
            return reply(f"This week: {len(r['completed'])} done, {len(r['unfinished'])} unfinished, "
                         f"{len(r['notes'])} note(s) written.")

        query = None
        found_en = re.search(r"\b(find|search|show me|everything (about|related to))\s+(.+)", m)
        found_fa = re.search(r"(پیدا کن|جستجو کن|جستجو|همه چیز درباره(ٔ|ی)?)\s+(.+)", m)
        if found_en:
            query = found_en.group(3).strip(" ?.")
        elif found_fa:
            query = found_fa.group(3).strip(" ؟?.")
        if query:
            found = store.search(query)
            if fa:
                return reply(f"«{query}»: {fa_digits(len(found['tasks']))} کار، {fa_digits(len(found['notes']))} یادداشت، "
                             f"{fa_digits(len(found['projects']))} پروژه.", search=found)
            return reply(f'"{query}": {len(found["tasks"])} task(s), {len(found["notes"])} note(s), '
                         f'{len(found["projects"])} project(s).', search=found)

    # Anything else is treated as something to capture.
    parsed = parse_capture(message, today)
    if not parsed["tasks"] and not parsed["notes"]:
        return reply("چیزی برای مرتب کردن پیدا نکردم." if fa else "I couldn't find anything to organize in that.")
    for t in parsed["tasks"]:
        made = store.create_task(title=t["title"], due_date=t.get("due_date"), scheduled_date=t.get("scheduled_date"))
        actions.append(describe_action("create_task", {}, made, lang))
    for n in parsed["notes"]:
        made = store.create_note(title=n["title"], content=n["content"])
        actions.append(describe_action("create_note", {}, made, lang))
    if fa:
        return reply(f"{fa_digits(len(parsed['tasks']))} کار و {fa_digits(len(parsed['notes']))} یادداشت ثبت شد.")
    return reply(f"Organized {len(parsed['tasks'])} task(s) and {len(parsed['notes'])} note(s).")


def format_day_plan(plan, lang="en"):
    fa = lang == "fa"
    if not any(b["type"] == "task" for b in plan["schedule"]):
        if not plan["must"] and not plan["should"]:
            return ("برای آن روز کاری برای برنامه‌ریزی نیست. یکی دو کار اضافه کنید و دوباره بپرسید." if fa else
                    "There's nothing to schedule for that day. Add a task or two and ask again.")
        return "در وقتی که دارید چیزی جا نمی‌شود." if fa else "Nothing fits in the time available."
    if fa:
        lines = [fa_digits(f"{human_minutes_fa(plan['planned_min'])} برنامه از {human_minutes_fa(plan['capacity_min'])} وقت آزاد "
                           f"({plan['window']['start']} تا {plan['window']['end']}):")]
    else:
        lines = [f"{human_minutes(plan['planned_min'])} planned of {human_minutes(plan['capacity_min'])} available "
                 f"({plan['window']['start']}–{plan['window']['end']}):"]
    for b in plan["schedule"]:
        t = fa_digits(b["start"]) if fa else b["start"]
        if b["type"] == "event":
            lines.append(f"• {t} {b['title']} ({'جلسه' if fa else 'meeting'})")
        elif b["type"] == "break":
            lines.append(f"• {t} {'استراحت' if fa else 'break'}")
        else:
            end = fa_digits(b["end"]) if fa else b["end"]
            lines.append(f"• {t}–{end} {b['title']}" + ("" if fa else f" ({b['reason']})"))
    if plan["did_not_fit"]:
        sep = "، " if fa else ", "
        lines.append(("جا نشد: " if fa else "Didn't fit: ") + sep.join(t["title"] for t in plan["did_not_fit"][:4]))
    return "\n".join(lines)


def human_minutes_fa(total):
    h, m = divmod(int(total), 60)
    if h and m:
        return f"{h} ساعت و {m} دقیقه"
    return f"{h} ساعت" if h else f"{m} دقیقه"


# ======================================================================
# Streamlit interface
# ======================================================================

import html
import json
import math
import os
import re
from datetime import date as _date, datetime

import streamlit as st
import streamlit.components.v1 as components


COOKIE = "planner_session"
PAGES = {
    "today": (":material/wb_sunny:", "Today", "امروز"),
    "assistant": (":material/forum:", "Assistant", "دستیار"),
    "inbox": (":material/inbox:", "Inbox", "صندوق ورودی"),
    "tasks": (":material/check_circle:", "Tasks", "کارها"),
    "calendar": (":material/calendar_month:", "Week", "هفته"),
    "notes": (":material/edit_note:", "Notes", "یادداشت‌ها"),
    "projects": (":material/folder:", "Projects", "پروژه‌ها"),
    "goals": (":material/flag:", "Goals", "هدف‌ها"),
    "shared": (":material/group:", "Shared", "اشتراکی"),
    "search": (":material/search:", "Search", "جستجو"),
    "settings": (":material/settings:", "Settings", "تنظیمات"),
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
[data-testid="stAppDeployButton"], [data-testid="stHeaderActionElements"] { display: none; }
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
.horizon { width: 100%; height: auto; display: block; margin-top: 6px; direction: ltr; }

/* Tasks */
.t-title { font-weight: 600; color: var(--pine); line-height: 1.35; margin: 1px 0 3px; }
.t-title.done { text-decoration: line-through; color: var(--moss); font-weight: 400; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.chip { font-size: .8rem; padding: 2px 9px; border-radius: 999px; background: var(--mist); color: var(--moss); }
.chip.rose { background: var(--rose-soft); color: var(--rose); font-weight: 600; }
.chip.dusk { background: var(--dusk-soft); color: var(--dusk); }
.chip.teal { background: var(--teal-soft); color: var(--teal); }
.pri { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-inline-end: 7px; vertical-align: 2px; }
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
.slot .what { border-inline-start: 3px solid var(--line); padding-inline-start: 10px; }
.slot.must .what { border-color: var(--rose); } .slot.should .what { border-color: var(--dusk); }
.slot.nice .what { border-color: #B9C6C0; } .slot.event .what { border-color: var(--pine); }
.slot.break .what { border-color: var(--sun); color: var(--moss); }
.slot small { color: var(--moss); display: block; }

/* Week */
.day-head { font-weight: 700; color: var(--pine); margin-bottom: 6px; }
.day-head.today { color: var(--teal); }
.day-head.off { color: var(--moss); }
.stApp .stMarkdown p.field-label { font-size: .875rem; color: var(--pine); margin: 0 0 .25rem; }
.day-head span { font-family: var(--serif); font-weight: 500; font-size: 1.35rem; margin-inline-start: 4px; }
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
.auth-list { color: var(--pine); padding-inline-start: 1.1rem; margin-top: 12px; }
.auth-list li { margin: 4px 0; }
.welcome ol { margin: 6px 0 0; padding-inline-start: 1.2rem; color: var(--pine); }
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


FA_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700&display=swap');
:root { --serif: 'Vazirmatn', Tahoma, 'Segoe UI', sans-serif; --sans: 'Vazirmatn', Tahoma, 'Segoe UI', sans-serif; }
.stMain .block-container, [data-testid="stSidebarContent"], [data-testid="stDialog"] { direction: rtl; }
.stApp h1, .stApp h2, .stApp h3, .stApp .stMarkdown p.hello { letter-spacing: 0; }
.stApp .stMarkdown p.hello { font-weight: 700; line-height: 1.35; }
.stApp textarea, .stApp input[type="text"], .stApp input:not([type]) { direction: rtl; text-align: right; }
.stApp input[type="email"], .stApp input[autocomplete="email"], .stApp input[type="password"] { direction: ltr; text-align: left; }
[data-testid="stChatInput"] textarea { direction: rtl; }
.stMain [data-testid="stElementContainer"], .stMain [data-testid="stMarkdown"],
.stMain [data-testid="stMarkdownContainer"], .stMain [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stElementContainer"] { text-align: start; }
.stApp .stMarkdown .auth-hero h1 { line-height: 1.5; }
.stApp .stMarkdown .auth-hero p.wordmark { text-align: start; }
.slot time { unicode-bidi: isolate; }
.slot { grid-template-columns: 124px 1fr; }
.stApp ol { list-style-type: persian; }
.chip, .pill { unicode-bidi: plaintext; }
</style>
"""



# ------------------------------------------------------------------ language
def lang() -> str:
    return st.session_state.get("lang", "en")


def cal() -> str:
    return st.session_state.get("calendar", "gregorian")


def is_fa() -> bool:
    return lang() == "fa"


def L(en: str, fa: str) -> str:
    """The same words in the person's language. Persian gets Persian digits."""
    return fa_digits(fa) if is_fa() else en


def N(value) -> str:
    return fa_digits(value) if is_fa() else str(value)


def D(iso, **kw) -> str:
    return format_date(iso, lang(), cal(), **kw) if iso else ""


def minutes_text(total) -> str:
    h, m = divmod(int(total), 60)
    if is_fa():
        text = f"{h} ساعت و {m} دقیقه" if h and m else f"{h} ساعت" if h else f"{m} دقیقه"
        return fa_digits(text)
    return f"{h}h {m}m" if h and m else f"{h}h" if h else f"{m}m"


def esc(value) -> str:
    """Everything a person typed is escaped before it goes into HTML."""
    return html.escape(str(value or ""), quote=True)


_EN_WEEKDAY = {name: i for i, name in enumerate(WEEKDAYS_EN)}


def tr_reason(reason: str) -> str:
    """Planner reasons ('due Friday', 'overdue by 2 day(s)') in the person's language."""
    if not is_fa():
        return reason
    m = re.fullmatch(r"overdue by (\d+) day\(s\)", reason)
    if m:
        return fa_digits(f"{m.group(1)} روز از مهلت گذشته")
    m = re.fullmatch(r"due (\w+day)", reason)
    if m and m.group(1) in _EN_WEEKDAY:
        return f"مهلت: {WEEKDAYS_FA[_EN_WEEKDAY[m.group(1)]]}"
    return {"due today": "مهلتش امروز است", "marked urgent": "فوری", "planned for today": "برای امروز",
            "marked high priority": "اولویت بالا", "no deadline": "بدون مهلت"}.get(reason, reason)


def _fa_minutes(text: str) -> str:
    """'1h 30m' -> '۱ ساعت و ۳۰ دقیقه' inside a sentence."""
    def rep(m):
        h, mm = int(m.group(1) or 0), int(m.group(2) or 0)
        return minutes_text(h * 60 + mm)
    return re.sub(r"(?:(\d+)h)?\s?(?:(\d+)m)?(?=\W|$)", lambda m: rep(m) if (m.group(1) or m.group(2)) else m.group(0), text)


PLAN_NOTES_FA = [
    (r"Starting from (\d\d:\d\d), since the day is already under way\.", "از ساعت {0} شروع می‌کنم، چون روز شروع شده است."),
    (r"You said you have about (.+)\.", "گفتید حدود {0} وقت دارید."),
    (r"Planning (\d+)% of your (.+) of free time; the rest absorbs interruptions\.",
     "فقط {0}٪ از {1} وقت آزادتان را پر می‌کنم تا برای کارهای پیش‌بینی‌نشده جا بماند."),
    (r"Tasks without an estimate are treated as (\d+) minutes\.", "کارهای بدون تخمین زمان را {0} دقیقه حساب کردم."),
    (r"The workday is already over, so this plan is for the time that's left\.",
     "روز کاری تمام شده؛ این برنامه برای وقتی است که مانده."),
    (r"(\d+) task\(s\) are waiting on something else and were left out\.",
     "{0} کار منتظر کار دیگری است و کنار گذاشته شد."),
    (r"(\d+) urgent task\(s\) don't fit in the time available: (.+)\. Consider moving a deadline\.",
     "{0} کار فوری در وقتتان جا نمی‌شود: {1}. شاید بهتر باشد مهلتی را جابه‌جا کنید."),
    (r"Each day is filled to about (\d+)% of its free hours \((\d\d:\d\d)–(\d\d:\d\d)\)\.",
     "هر روز حدود {0}٪ از ساعت‌های آزادش ({1} تا {2}) پر می‌شود."),
    (r"That week is already over, so there's nothing left to plan\.", "این هفته تمام شده و چیزی برای برنامه‌ریزی نمانده."),
]


def tr_note(text: str) -> str:
    if not is_fa():
        return text
    for pattern, fa in PLAN_NOTES_FA:
        m = re.fullmatch(pattern, text)
        if m:
            return fa_digits(fa.format(*[_fa_minutes(g) for g in m.groups()]))
    return text


FIELD_FA = {"Task": "عنوان کار", "Email": "ایمیل", "Name": "نام", "Thought": "متن", "Search": "عبارت جستجو",
            "Project name": "نام پروژه", "Goal": "هدف", "Event": "عنوان", "content": "متن", "title": "عنوان"}
ERRORS_FA = [
    (r"(.+) is required", lambda m: f"{FIELD_FA.get(m.group(1), m.group(1))} را وارد کنید."),
    (r"Enter a valid email address.*", lambda m: "یک ایمیل درست وارد کنید، مثل name@example.com."),
    (r"Use at least (\d+) characters for your password\.", lambda m: f"رمز باید دست‌کم {m.group(1)} نویسه باشد."),
    (r"That password is too easy to guess.*", lambda m: "این رمز خیلی ساده است. از چند نویسهٔ متفاوت استفاده کنید."),
    (r"An account with this email already exists.*", lambda m: "با این ایمیل قبلاً حساب ساخته شده. لطفاً وارد شوید."),
    (r"That email and password don't match.*", lambda m: "ایمیل و رمز با هم نمی‌خوانند. دوباره بررسی کنید."),
    (r"Too many attempts\. Try again in (\d+) minute.*", lambda m: f"تلاش‌ها زیاد شد. {m.group(1)} دقیقهٔ دیگر دوباره امتحان کنید."),
    (r'You already have a project called "(.+)"\.', lambda m: f"پروژه‌ای به نام «{m.group(1)}» دارید."),
    (r"Your current password isn't right\.", lambda m: "رمز فعلی درست نیست."),
    (r"The end of the workday must be after the start\.", lambda m: "پایان روز کاری باید بعد از شروع آن باشد."),
    (r"The event must end after it starts\.", lambda m: "پایان رویداد باید بعد از شروع آن باشد."),
    (r"Choose between 0 and 120 minutes\.", lambda m: "عددی بین ۰ تا ۱۲۰ دقیقه انتخاب کنید."),
    (r".*is not a time.*", lambda m: "زمان را به شکل ۰۹:۳۰ وارد کنید."),
    (r".*is too long \(max (\d+) characters\)", lambda m: f"متن خیلی بلند است (حداکثر {m.group(1)} نویسه)."),
    (r"That action was already (\w+)", lambda m: "این مورد قبلاً انجام یا لغو شده است."),
]


def tr_error(msg: str) -> str:
    if not is_fa():
        return msg
    for pattern, fn in ERRORS_FA:
        m = re.fullmatch(pattern, msg.strip())
        if m:
            return fa_digits(fn(m))
    return msg


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
        st.error(tr_error(str(e)))
    except Exception as e:
        st.error(L(f"Something went wrong: {e}", f"مشکلی پیش آمد: {e}"))
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


def date_field(label, value=None, key=None, optional=True, where=st):
    """A date picker in the person's calendar. Returns ISO (YYYY-MM-DD) or None.

    Gregorian uses Streamlit's picker; Jalali uses day / month / year lists,
    because the built-in picker only knows the Gregorian calendar."""
    if cal() != "jalali":
        picked = where.date_input(label, value=_date.fromisoformat(value) if value else None,
                                  format="YYYY-MM-DD", key=key)
        return picked.isoformat() if picked else None
    today_j = iso_to_jalali(local_now().date().isoformat())
    jy, jm, jd = iso_to_jalali(value) if value else (None, None, None)
    months = JALALI_MONTHS_FA if is_fa() else JALALI_MONTHS_EN
    none = "—"
    where.markdown(f'<p class="field-label">{esc(label)}</p>', unsafe_allow_html=True)
    c1, c2, c3 = where.columns([1, 1.6, 1.3], gap="small")
    days = ([none] if optional else []) + list(range(1, 32))
    years = list(range(today_j[0] - 1, today_j[0] + 4))
    d = c1.selectbox(L("Day", "روز"), days, index=days.index(jd) if jd in days else 0, key=f"{key}-d",
                     format_func=lambda v: v if v == none else N(v), label_visibility="collapsed")
    mo = c2.selectbox(L("Month", "ماه"), list(range(1, 13)), index=(jm or today_j[1]) - 1, key=f"{key}-m",
                      format_func=lambda v: months[v - 1], label_visibility="collapsed")
    y = c3.selectbox(L("Year", "سال"), years, index=years.index(jy) if jy in years else 1, key=f"{key}-y",
                     format_func=N, label_visibility="collapsed")
    if d == none:
        return None
    return jalali_to_iso(y, mo, min(int(d), jalali_month_length(y, mo)))  # 31 Mehr becomes 30 Mehr


def friendly_date(iso, today):
    if not iso:
        return ""
    diff = (_date.fromisoformat(iso) - _date.fromisoformat(today)).days
    if diff == 0:
        return L("today", "امروز")
    if diff == 1:
        return L("tomorrow", "فردا")
    if diff == -1:
        return L("yesterday", "دیروز")
    if 1 < diff < 7:
        return weekday_label(iso, lang())
    return D(iso)


def empty(message):
    st.markdown(f'<div class="empty">{esc(message)}</div>', unsafe_allow_html=True)


def note(message):
    st.markdown(f'<p class="section-note">{esc(message)}</p>', unsafe_allow_html=True)


def plural(n, one, many):
    return one if n == 1 else many


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
<svg class="horizon" viewBox="0 0 520 230" role="img" aria-hidden="true">
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


def language_switch(key):
    """English / فارسی. Choosing Persian also switches to the Jalali calendar."""
    choice = st.segmented_control("Language", ["en", "fa"], default=lang(), key=key,
                                  format_func=lambda v: "English" if v == "en" else "فارسی",
                                  label_visibility="collapsed")
    if choice and choice != lang():
        st.session_state["lang"] = choice
        st.session_state["calendar"] = "jalali" if choice == "fa" else "gregorian"
        return True
    return False


def page_auth():
    st.markdown(AUTH_ONLY_CSS, unsafe_allow_html=True)
    if st.session_state.pop("clear_cookie", False):
        set_cookie(None)
    top = st.columns([4, 1.1])
    with top[1]:
        if language_switch("auth-lang"):
            st.rerun()
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        points = [L("Turns a messy thought into tasks with the right dates", "یک فکر شلوغ را به کارهایی با تاریخ درست تبدیل می‌کند"),
                  L("Builds a realistic plan when you only have two hours", "وقتی فقط دو ساعت وقت دارید، برنامه‌ای شدنی می‌چیند"),
                  L("Asks before it deletes or moves anything big", "قبل از حذف یا جابه‌جایی‌های بزرگ از شما می‌پرسد")]
        st.markdown(f"""
<div class="auth-hero">
  <p class="wordmark">{esc(L("Planner", "برنامه‌ریز"))}</p>
  <h1>{esc(L("Plan the day you actually have.", "روزی را برنامه‌ریزی کن که واقعاً داری."))}</h1>
  <p>{esc(L("Write down what's on your mind. Planner sorts it into tasks and notes, then fits them around your meetings.",
             "هر چه در ذهن دارید بنویسید. برنامه‌ریز آن را به کار و یادداشت تبدیل می‌کند و دور جلسه‌هایتان می‌چیند."))}</p>
  <ul class="auth-list">{"".join(f"<li>{esc(p)}</li>" for p in points)}</ul>
  {horizon_art()}
</div>""", unsafe_allow_html=True)
    with right:
        sign_in, create = st.tabs([L("Sign in", "ورود"), L("Create account", "ساخت حساب")])
        with sign_in:
            with st.form("sign-in"):
                email = st.text_input(L("Email", "ایمیل"), autocomplete="email")
                password = st.text_input(L("Password", "رمز"), type="password", autocomplete="current-password")
                remember = st.checkbox(L("Keep me signed in on this device", "در این دستگاه وارد بمانم"), value=True)
                if st.form_submit_button(L("Sign in", "ورود"), type="primary", use_container_width=True):
                    try:
                        user = Accounts(conn()).authenticate(email, password)
                        finish_sign_in(user, remember)
                    except ValidationError as e:
                        st.error(tr_error(str(e)))
        with create:
            with st.form("create-account"):
                name = st.text_input(L("Your name", "نام شما"), placeholder=L("What should I call you?", "چه صدایتان کنم؟"),
                                     autocomplete="given-name")
                email = st.text_input(L("Email", "ایمیل"), key="new-email", autocomplete="email")
                password = st.text_input(L("Password", "رمز"), type="password", key="new-password",
                                         help=L("At least 8 characters.", "دست‌کم ۸ نویسه."), autocomplete="new-password")
                confirm = st.text_input(L("Type the password again", "تکرار رمز"), type="password", autocomplete="new-password")
                remember = st.checkbox(L("Keep me signed in on this device", "در این دستگاه وارد بمانم"), value=True,
                                       key="new-remember")
                if st.form_submit_button(L("Create account", "ساخت حساب"), type="primary", use_container_width=True):
                    if password != confirm:
                        st.error(L("The two passwords don't match.", "دو رمز یکی نیستند."))
                    else:
                        try:
                            user = Accounts(conn()).create(email, password, name)
                            store = Store(conn(), user["id"])
                            store.update_preferences(lang=lang(), calendar=cal())  # keep the language they chose
                            finish_sign_in(user, remember)
                        except ValidationError as e:
                            st.error(tr_error(str(e)))
            st.caption(L("Your tasks and notes are private to your account. Passwords are stored as salted hashes, never as text.",
                         "کارها و یادداشت‌هایتان فقط برای خودتان است. رمزها به‌صورت درهم‌سازی‌شده نگه داشته می‌شوند، نه به‌صورت متن."))


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
    keep = {"conn", "lang", "calendar"}
    for k in list(st.session_state.keys()):
        if k not in keep:
            del st.session_state[k]
    st.session_state["signed_out"] = True  # don't re-read the old cookie before it's cleared
    st.session_state["clear_cookie"] = True
    st.rerun()


# ------------------------------------------------------------------ shared pieces
def task_row(store, ctx, task, key, show_project=True):
    done = task["status"] == "completed"
    box = st.container(key=f"trow-{key}-{task['id']}")
    c1, c2 = box.columns([0.06, 0.94], vertical_alignment="top")
    with c1:
        ticked = st.checkbox(L("Done", "انجام شد"), value=done, key=f"{key}-{task['id']}", label_visibility="collapsed")
        if ticked != done:
            run(lambda: store.complete_task(task["id"]) if ticked else store.reopen_task(task["id"]),
                L("Nice, that's done.", "آفرین، انجام شد.") if ticked else L("Moved back to your list.", "به فهرستتان برگشت."))
            st.rerun()
    with c2:
        chips = []
        today = ctx["today"]
        if task["due_date"]:
            if not done and task["due_date"] < today:
                chips.append(("rose", L(f"Overdue, was due {friendly_date(task['due_date'], today)}",
                                        f"عقب‌افتاده، مهلتش {friendly_date(task['due_date'], today)} بود")))
            elif task["due_date"] == today:
                chips.append(("rose", L("Due today", "مهلت: امروز")))
            else:
                chips.append(("dusk", L(f"Due {friendly_date(task['due_date'], today)}",
                                        f"مهلت: {friendly_date(task['due_date'], today)}")))
        if task["scheduled_date"] and task["scheduled_date"] != today:
            chips.append(("", L(f"Planned {friendly_date(task['scheduled_date'], today)}",
                                f"برنامه: {friendly_date(task['scheduled_date'], today)}")))
        if task.get("scheduled_time") and task["scheduled_date"] == today:
            chips.append(("teal", L(f"At {task['scheduled_time']}", f"ساعت {task['scheduled_time']}")))
        if task["estimate_min"]:
            chips.append(("", minutes_text(task["estimate_min"])))
        if show_project and task.get("project_name"):
            chips.append(("teal", task["project_name"]))
        if task.get("mine") is False:
            chips.append(("dusk", L(f"From {task.get('owner_name', '')}", f"از {task.get('owner_name', '')}")))
        elif task.get("shared_with"):
            names = ("، " if is_fa() else ", ").join((p["name"] or p["email"]) for p in task["shared_with"][:2])
            extra = len(task["shared_with"]) - 2
            if extra > 0:
                names += L(f" and {extra} more", f" و {extra} نفر دیگر")
            chips.append(("teal", L(f"Shared with {names}", f"مشترک با {names}")))
        chip_html = "".join(f'<span class="chip {c}">{esc(t)}</span>' for c, t in chips)
        pri = {1: L("Urgent", "فوری"), 2: L("High", "بالا"), 3: L("Normal", "معمولی"), 4: L("Low", "پایین")}[task["priority"]]
        st.markdown(
            f'<div class="t-title{" done" if done else ""}"><span class="pri p{task["priority"]}" '
            f'title="{esc(pri)}"></span>{esc(task["title"])}</div>'
            + (f'<div class="chips">{chip_html}</div>' if chips else ""), unsafe_allow_html=True)


def horizon_svg(settings, now_hm, events, plan):
    """Today's working hours as a horizon: meetings sit on it, planned work
    sits under it, and the sun shows where you are in the day. In Persian the
    day runs right to left, the way the page reads."""
    start, end = to_min(settings["workday_start"]), to_min(settings["workday_end"])
    span = max(end - start, 60)
    rtl = is_fa()

    def x(m):
        pos = (min(max(m, start), end) - start) / span * 920
        return 960 - pos if rtl else 40 + pos

    now = to_min(now_hm)
    frac = (min(max(now, start), end) - start) / span
    sun_x, sun_y = x(now), 118 - math.sin(math.pi * frac) * 70
    after = now > end
    sun_note = (L(f"Starts {settings['workday_start']}", f"شروع {settings['workday_start']}") if now < start
                else L("Done for today", "روز کاری تمام شد") if after else L(f"Now {now_hm}", f"اکنون {now_hm}"))
    font = "Vazirmatn, Nunito Sans, system-ui, sans-serif"
    label = L(f"Your working day from {settings['workday_start']} to {settings['workday_end']}, with {len(events)} meeting(s)",
              f"روز کاری شما از {settings['workday_start']} تا {settings['workday_end']} با {len(events)} جلسه")
    # direction="ltr" keeps text-anchor meaning the same in both languages;
    # Persian words inside still shape and order correctly.
    parts = [f'<svg class="horizon" direction="ltr" viewBox="0 0 1000 176" role="img" aria-label="{esc(label)}">',
             '<path d="M40 118 Q500 -22 960 118" fill="none" stroke="#C9D7D0" stroke-width="1.5" stroke-dasharray="3 7"/>',
             f'<circle cx="{sun_x:.1f}" cy="{sun_y:.1f}" r="26" fill="#E9B44C" opacity="{0.08 if after else 0.18}"/>',
             f'<circle cx="{sun_x:.1f}" cy="{sun_y:.1f}" r="13" fill="#E9B44C" opacity="{0.45 if after else 1}"/>']
    edge_left, edge_right = sun_x < 120, sun_x > 880
    anchor = "start" if edge_left else "end" if edge_right else "middle"
    parts.append(f'<text x="{sun_x:.1f}" y="{sun_y - 32:.1f}" font-size="13" text-anchor="{anchor}" fill="#5E726C" '
                 f'font-family="{font}">{esc(sun_note)}</text>')
    for e in events:
        a, b = x(to_min(e["start_time"])), x(to_min(e["end_time"]))
        x1, w = min(a, b), max(abs(b - a), 6)
        parts.append(f'<rect x="{x1:.1f}" y="86" width="{w:.1f}" height="26" rx="8" fill="#1F3A34" opacity=".13">'
                     f'<title>{esc(N(e["start_time"]))} {esc(e["title"])}</title></rect>')
        if w > 70:
            text = e["title"] if len(e["title"]) <= int(w / 8) else e["title"][: max(int(w / 8) - 1, 1)] + "…"
            tx, ta = (x1 + w - 8, "end") if rtl else (x1 + 8, "start")
            parts.append(f'<text x="{tx:.1f}" y="103" font-size="13" text-anchor="{ta}" fill="#1F3A34" '
                         f'font-family="{font}">{esc(text)}</text>')
    parts.append('<line x1="40" y1="118" x2="960" y2="118" stroke="#1F3A34" stroke-width="2"/>')
    colors = {"must": "#B8505A", "should": "#4A6FA5", "nice": "#2F7D6D"}
    for blk in (plan or {}).get("schedule", []):
        if blk["type"] != "task":
            continue
        a, b = x(to_min(blk["start"])), x(to_min(blk["end"]))
        x1, w = min(a, b), max(abs(b - a) - 3, 4)
        parts.append(f'<rect x="{x1:.1f}" y="125" width="{w:.1f}" height="9" rx="4.5" '
                     f'fill="{colors.get(blk.get("bucket"), "#2F7D6D")}"><title>{esc(blk["title"])}</title></rect>')
    step = 60 if span <= 6 * 60 else 120 if span <= 12 * 60 else 180
    for m in range(start, end + 1, step):
        parts.append(f'<text x="{x(m):.1f}" y="160" font-size="13" text-anchor="middle" fill="#5E726C" '
                     f'font-family="{font}">{N(f"{m // 60:02d}:{m % 60:02d}")}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render_plan(store, ctx, plan):
    note(L(f"{minutes_text(plan['planned_min'])} planned of {minutes_text(plan['capacity_min'])} available, "
           f"{plan['window']['start']} to {plan['window']['end']}.",
           f"{minutes_text(plan['planned_min'])} برنامه از {minutes_text(plan['capacity_min'])} وقت آزاد، "
           f"از {plan['window']['start']} تا {plan['window']['end']}."))
    if not plan["schedule"]:
        empty(L("There's nothing to fit in yet. Add a task or two and plan again.",
                "هنوز چیزی برای چیدن نیست. یکی دو کار اضافه کنید و دوباره برنامه بریزید."))
        return
    rows = []
    for b in plan["schedule"]:
        kind = b["type"] if b["type"] != "task" else b.get("bucket", "nice")
        detail = {"event": L("Meeting", "جلسه"), "break": L("A short break to reset", "کمی استراحت")}.get(
            b["type"], tr_reason(b.get("reason", "")))
        title = L("Break", "استراحت") if b["type"] == "break" else b["title"]
        span_text = L(f"{b['start']}–{b['end']}", f"{b['start']} تا {b['end']}")
        rows.append(f'<div class="slot {esc(kind)}"><time>{esc(span_text)}</time>'
                    f'<div class="what">{esc(title)}<small>{esc(detail)}</small></div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)
    if plan["did_not_fit"]:
        sep = "، " if is_fa() else ", "
        st.warning(L("Didn't fit today: ", "امروز جا نشد: ") + sep.join(t["title"] for t in plan["did_not_fit"][:6]))
    for w in plan["warnings"]:
        st.warning(tr_note(w))
    if plan["assumptions"]:
        with st.expander(L("How I planned this", "این برنامه چطور چیده شد")):
            for a in plan["assumptions"]:
                st.write(tr_note(a))
    if plan["placed"]:
        c1, c2 = st.columns([1.6, 1.4], gap="small")
        if c1.button(L(f"Save this plan to today ({len(plan['placed'])} tasks)",
                       f"ثبت این برنامه برای امروز ({len(plan['placed'])} کار)"), type="primary", key="save-plan"):
            run(lambda: apply_schedule(store, [{"id": t["id"], "to": plan["date"], "time": t["start"]}
                                                  for t in plan["placed"]]),
                L("Plan saved. Those tasks are on today's list, with their times.",
                  "برنامه ثبت شد. این کارها با ساعتشان در فهرست امروز هستند."))
            st.rerun()
        items = plan_items(store.list_events(plan["date"]),
                                  [{**t, "scheduled_date": plan["date"], "scheduled_time": t["start"]} for t in plan["placed"]])
        lead = int(store.get_settings().get("remind_lead") or 10)
        c2.download_button(L("Add to my phone calendar", "افزودن به تقویم گوشی"),
                           build_ics(items, lead, L("Planner", "برنامه‌ریز"), str(store.uid)),
                           file_name=f"plan-{plan['date']}.ics", mime="text/calendar", key="ics-plan",
                           help=L(f"Your calendar will remind you {lead} minutes before each item, even when Planner is closed.",
                                  f"تقویم گوشی {lead} دقیقه قبل از هر مورد یادآوری می‌کند، حتی وقتی برنامه‌ریز بسته است."))


def pending_banner(store, ctx):
    for p in store.open_pending():
        with st.container(border=True):
            st.markdown(f"**{esc(L('Waiting for your OK:', 'منتظر تأیید شما:'))}** {esc(p['summary'])}", unsafe_allow_html=True)
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button(L("Yes, do it", "بله، انجام بده"), key=f"pc-{p['id']}", type="primary"):
                run(lambda: resolve_pending(store, p["id"], "confirm", ctx), L("Done.", "انجام شد."))
                st.rerun()
            if c2.button(L("Cancel", "لغو"), key=f"px-{p['id']}"):
                run(lambda: resolve_pending(store, p["id"], "reject", ctx), L("Cancelled. Nothing changed.", "لغو شد. چیزی تغییر نکرد."))
                st.rerun()


def reminder_engine(store, ctx):
    """Schedules browser notifications for the next 24 hours while the tab is open.
    Timers live in the page (not the frame this runs in), so they survive Streamlit's
    reruns; each run clears and re-creates them from the latest plan."""
    s = store.get_settings()
    enabled = s.get("remind_enabled") == "1"
    reminders = []
    if enabled:
        def summary(day):
            d = store.get_today(day)
            return {"tasks": len({t["id"] for t in d["planned"] + d["due_today"]}), "events": len(d["events"]),
                    "overdue": len(d["overdue"])}
        reminders = build_reminders(store.upcoming(ctx["today"]), ctx["today"], ctx["now"],
                                           int(s.get("remind_lead") or 10), s.get("remind_morning") or "",
                                           lang(), summary)
    # Only when reminders are on: otherwise nothing would show them and they'd
    # be marked as delivered for nothing.
    fresh = store.undelivered_notifications() if enabled else []
    if fresh:
        heading = L("Planner", "برنامه‌ریز")
        # The person's own clock, not the server's: the browser compares against
        # local time, and on Streamlit Cloud the server runs in UTC.
        reminders += [{"at": f"{ctx['today']}T{ctx['now']}", "title": heading,
                       "body": notification_text(n), "tag": f"notif-{n['id']}"} for n in fresh]
        store.mark_delivered([n["id"] for n in fresh])
    data = json.dumps(reminders, ensure_ascii=False).replace("<", "\\u003c")
    components.html(f"""<script>
(function () {{
  var P = window.parent, list = {data};
  (P.__plannerTimers || []).forEach(function (id) {{ P.clearTimeout(id); }});
  P.__plannerTimers = [];
  P.__plannerShown = P.__plannerShown || {{}};
  if (!('Notification' in P) || P.Notification.permission !== 'granted') return;
  var fire = new P.Function('r', "if (window.__plannerShown[r.tag]) return; window.__plannerShown[r.tag] = 1;" +
    "try {{ new Notification(r.title, {{ body: r.body, tag: r.tag }}); }} catch (e) {{}}");
  list.forEach(function (r) {{
    var wait = new Date(r.at).getTime() - Date.now();   // 'YYYY-MM-DDTHH:MM' is read as local time
    if (wait < -60000 || wait > 86400000 || P.__plannerShown[r.tag]) return;
    P.__plannerTimers.push(P.setTimeout(fire, Math.max(wait, 0), r));
  }});
}})();
</script>""", height=0)


# ------------------------------------------------------------------ pages
def page_today(store, ctx, user):
    data = store.get_today(ctx["today"])
    settings = store.get_settings()
    hour = int(ctx["now"][:2])
    name = (user["name"] or "").split(" ")[0]
    if is_fa():
        greeting = "صبح بخیر" if hour < 12 else "عصر بخیر" if hour < 18 else "سلام"
    else:
        greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    hello = f"{greeting}{'، ' if is_fa() else ', '}{name}." if name else f"{greeting}."
    open_today = len({t["id"] for t in data["planned"] + data["due_today"]})
    bits = []
    if data["events"]:
        n = len(data["events"])
        bits.append(L(f"{n} {plural(n, 'meeting', 'meetings')}", f"{n} جلسه"))
    bits.append(L(f"{open_today} {plural(open_today, 'thing', 'things')} planned", f"{open_today} کار در برنامه")
                if open_today else L("nothing scheduled yet", "هنوز برنامه‌ای نچیده‌اید"))
    if data["overdue"]:
        bits.append(L(f"{len(data['overdue'])} overdue", f"{len(data['overdue'])} کار عقب‌افتاده"))
    summary = ("، ".join(bits) if is_fa() else ", ".join(bits))
    sub = L(f"{D(ctx['today'], with_weekday=True)}. You have {summary}.",
            f"{D(ctx['today'], with_weekday=True, with_year=True)}. امروز {summary} دارید.")
    streak = store.streak(ctx["today"])
    days_word = plural(streak, "day", "days")
    streak_text = L(f"{streak} {days_word} in a row", f"{streak} روز پشت سر هم")
    streak_html = (f'<span class="streak"><span class="dot"></span>{esc(streak_text)}</span>' if streak else "")
    st.markdown(f"""
<div class="hero">
  <div class="hero-row">
    <div><p class="hello">{esc(hello)}</p><p class="hero-sub">{esc(sub)}</p></div>
    {streak_html}
  </div>
  {horizon_svg(settings, ctx["now"], data["events"], st.session_state.get("day_plan"))}
</div>""", unsafe_allow_html=True)

    if not user["onboarded"]:
        with st.container(border=True):
            steps = [L("Write down what's on your mind in the box below and press <b>Organize</b>.",
                       "هر چه در ذهن دارید در کادر پایین بنویسید و <b>مرتب کن</b> را بزنید."),
                     L("Press <b>Plan my day</b>. If you only have an hour, choose that first.",
                       "<b>برنامهٔ امروزم</b> را بزنید. اگر فقط یک ساعت وقت دارید، اول همان را انتخاب کنید."),
                     L("Optional: connect a free AI in Settings, so you can ask for anything in plain words.",
                       "اختیاری: در تنظیمات یک هوش مصنوعی رایگان وصل کنید تا هر چیزی را با زبان ساده بپرسید.")]
            heading = esc(L("Welcome. Here is how to get going", "خوش آمدید. از این‌جا شروع کنید"))
            items = "".join("<li>" + s + "</li>" for s in steps)
            st.markdown(f'<div class="welcome"><h3 style="margin-top:0">{heading}</h3><ol>{items}</ol></div>',
                        unsafe_allow_html=True)
            c1, c2, _ = st.columns([0.8, 2.2, 4], gap="small")
            if c1.button(L("Got it", "فهمیدم"), type="primary"):
                Accounts(conn()).set_onboarded(user["id"])
                st.rerun()
            c2.button(L("Connect a free AI", "وصل کردن هوش مصنوعی رایگان"), on_click=go, args=("settings",))

    with st.form("capture", clear_on_submit=True):
        text = st.text_area(L("What's on your mind?", "چه در ذهن دارید؟"), height=96,
                            placeholder=L("Finish the deck by Monday, call Alex, and an idea: a simpler hero section",
                                          "ارائه را تا دوشنبه تمام کنم، فردا به علی زنگ بزنم، ایده: صفحهٔ اول ساده‌تر"))
        st.caption(L('I\'ll split it into tasks and notes. Phrases like "by Friday" become deadlines; vague ones like "soon" stay undated.',
                     "آن را به کار و یادداشت تقسیم می‌کنم. عبارتی مثل «تا جمعه» مهلت می‌شود؛ عبارت‌های مبهم مثل «به‌زودی» بی‌تاریخ می‌مانند."))
        c1, c2, _ = st.columns([0.9, 1.2, 5], gap="small")
        organize = c1.form_submit_button(L("Organize", "مرتب کن"), type="primary")
        to_inbox = c2.form_submit_button(L("Save to inbox", "ذخیره در صندوق"))
    if organize and text.strip():
        parsed = parse_capture(text, ctx["today"])
        if not parsed["tasks"] and not parsed["notes"]:
            st.warning(L('I couldn\'t find anything to organize. Try naming an action, like "call Alex".',
                         "چیزی برای مرتب کردن پیدا نکردم. یک کار مشخص بنویسید، مثل «به علی زنگ بزنم»."))
        else:
            for t in parsed["tasks"]:
                run(lambda t=t: store.create_task(title=t["title"], due_date=t.get("due_date"),
                                                  scheduled_date=t.get("scheduled_date")))
            for n in parsed["notes"]:
                run(lambda n=n: store.create_note(title=n["title"], content=n["content"]))
            nt, nn = len(parsed["tasks"]), len(parsed["notes"])
            flash(L(f"Added {nt} {plural(nt, 'task', 'tasks')} and {nn} {plural(nn, 'note', 'notes')}.",
                    f"{nt} کار و {nn} یادداشت اضافه شد."))
            st.rerun()
    if to_inbox and text.strip():
        run(lambda: store.add_inbox(text), L("Saved to your inbox.", "در صندوق ورودی ذخیره شد."))
        st.rerun()

    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.subheader(L("Your plan", "برنامهٔ شما"))
        c1, c2 = st.columns([1.3, 1], vertical_alignment="bottom")
        options = [None, 30, 60, 120, 180, 240]
        choice = c1.selectbox(L("How much time do you have?", "چقدر وقت دارید؟"), options,
                              format_func=lambda v: L("My whole workday", "کل روز کاری") if v is None else minutes_text(v))
        if c2.button(L("Plan my day", "برنامهٔ امروزم"), type="primary", use_container_width=True):
            st.session_state["day_plan"] = day_plan(store, ctx["today"], choice, ctx["now"])
            st.rerun()
        if st.session_state.get("day_plan"):
            render_plan(store, ctx, st.session_state["day_plan"])
        else:
            note(L("I'll fit your tasks around meetings, leave room for interruptions, and tell you what won't fit.",
                   "کارهایتان را دور جلسه‌ها می‌چینم، برای کارهای پیش‌بینی‌نشده جا می‌گذارم و می‌گویم چه چیزی جا نمی‌شود."))
            for e in data["events"]:
                span_text = L(f"{e['start_time']}–{e['end_time']}", f"{e['start_time']} تا {e['end_time']}")
                st.markdown(f'<div class="slot event"><time>{esc(span_text)}</time>'
                            f'<div class="what">{esc(e["title"])}<small>{esc(L("Meeting", "جلسه"))}</small></div></div>',
                            unsafe_allow_html=True)
    with right:
        shown = False
        if data["overdue"]:
            shown = True
            st.subheader(L("Overdue", "عقب‌افتاده"))
            for t in data["overdue"]:
                task_row(store, ctx, t, "od")
        overdue_ids = {t["id"] for t in data["overdue"]}
        todays = sorted({t["id"]: t for t in data["due_today"] + data["planned"] if t["id"] not in overdue_ids}.values(),
                        key=lambda t: (t.get("scheduled_time") or "99", t["priority"]))
        if todays:
            shown = True
            st.subheader(L("Today", "امروز"))
            for t in todays:
                task_row(store, ctx, t, "td")
        if data["carried_over"]:
            shown = True
            st.subheader(L("Left over from before", "مانده از روزهای قبل"))
            for t in data["carried_over"]:
                task_row(store, ctx, t, "co")
            if st.button(L("Move to today", "انتقال به امروز")):
                run(lambda: store.bulk_reschedule([t["id"] for t in data["carried_over"]], ctx["today"]),
                    L("Moved to today.", "به امروز منتقل شد."))
                st.rerun()
        if data["deadlines_this_week"]:
            shown = True
            st.subheader(L("Coming up this week", "مهلت‌های این هفته"))
            for t in data["deadlines_this_week"]:
                task_row(store, ctx, t, "dl")
        undated = [t for t in store.list_tasks(open_only=True) if not t["due_date"] and not t["scheduled_date"]]
        if undated:
            shown = True
            c1, c2 = st.columns([3, 1.2], vertical_alignment="center")
            n = len(undated)
            tasks_word = plural(n, "task", "tasks")
            msg = L(f"{n} {tasks_word} without a date. Plan my day can fit them in.",
                    f"{n} کار بدون تاریخ دارید. «برنامهٔ امروزم» می‌تواند آن‌ها را جا بدهد.")
            c1.markdown(f'<p class="section-note" style="margin:0">{esc(msg)}</p>', unsafe_allow_html=True)
            c2.button(L("See them", "دیدن"), on_click=go, args=("tasks",), use_container_width=True)
        if data["completed_today"]:
            st.caption(L(f"Done today: {len(data['completed_today'])}. Nice work.", f"امروز {len(data['completed_today'])} کار انجام دادید. آفرین."))
        if not shown:
            empty(L("Nothing is waiting on you today. Write something in the box above, or open Tasks to pick something up.",
                    "امروز کاری منتظر شما نیست. در کادر بالا چیزی بنویسید یا از «کارها» یکی را بردارید."))


def page_assistant(store, ctx):
    st.title(L("Assistant", "دستیار"))
    cfg = resolve_config(store)
    if cfg["enabled"]:
        note(L(f"Using {cfg['label']}. Ask in your own words; I'll check with you before deleting or moving several things.",
               f"با {cfg['label']}. با زبان خودتان بپرسید؛ قبل از حذف یا جابه‌جایی چند کار با هم، از شما می‌پرسم."))
    else:
        c1, c2 = st.columns([4, 1.5], vertical_alignment="center")
        c1.markdown(f'<p class="section-note" style="margin:0">{esc(L("Basic mode: I understand planning, overdue checks, moving unfinished tasks, search and capture. Connect a free AI to ask anything.", "حالت ساده: برنامه‌ریزی، کارهای عقب‌افتاده، جابه‌جایی کارهای ناتمام، جستجو و ثبت را می‌فهمم. برای پرسیدن هر چیزی، یک هوش مصنوعی رایگان وصل کنید."))}</p>',
                    unsafe_allow_html=True)
        c2.button(L("Connect a free AI", "وصل کردن هوش مصنوعی"), on_click=go, args=("settings",), use_container_width=True)

    pending_banner(store, ctx)
    chat = st.session_state.setdefault("chat", [])
    if not chat:
        st.write("")
        st.markdown(f"**{esc(L('Try one of these', 'یکی از این‌ها را امتحان کنید'))}**")
        ideas = ([("Plan my day", "برنامهٔ امروزم را بچین"), ("What am I falling behind on?", "چه کارهایی عقب افتاده؟"),
                  ("Move unfinished tasks to tomorrow", "کارهای ناتمام را به فردا منتقل کن"), ("Plan my week", "برنامهٔ هفته را بچین"),
                  ("Summarize what I wrote this week", "خلاصهٔ این هفته"), ("I only have 2 hours today", "امروز فقط ۲ ساعت وقت دارم")])
        labels = [fa if is_fa() else en for en, fa in ideas]
        for row in (labels[:3], labels[3:]):
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
    prompt = st.chat_input(L("Ask, plan, or write down what's on your mind", "بپرسید، برنامه بریزید یا هر چه در ذهن دارید بنویسید")) \
        or st.session_state.pop("ask", None)
    if prompt:
        chat.append({"role": "user", "content": prompt})
        with st.spinner(L("Thinking…", "در حال فکر کردن…")):
            try:
                out = chat(store, prompt, ctx)
            except ValidationError as e:
                out = {"reply": tr_error(str(e)), "actions": []}
            except Exception as e:
                out = {"reply": L(f"Something went wrong: {e}", f"مشکلی پیش آمد: {e}"), "actions": []}
        chat.append({"role": "assistant", "content": out["reply"], "actions": out.get("actions", []),
                     "notice": out.get("notice")})
        plan = out.get("plan") or {}
        if plan.get("kind") == "plan_day":
            st.session_state["day_plan"] = plan["data"]
        elif plan.get("kind") == "plan_week":
            st.session_state["week_proposal"] = plan["data"]
        st.rerun()
    if chat and st.button(L("Start a new conversation", "گفتگوی تازه")):
        st.session_state["chat"] = []
        store.clear_messages()
        st.rerun()


def page_inbox(store, ctx):
    st.title(L("Inbox", "صندوق ورودی"))
    note(L("A place for thoughts you haven't sorted yet. Each one has a suggestion; one click turns it into a task or a note.",
           "جای فکرهایی که هنوز مرتب نشده‌اند. برای هر کدام پیشنهادی هست؛ با یک کلیک کار یا یادداشت می‌شود."))
    with st.form("add-inbox", clear_on_submit=True):
        c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
        text = c1.text_input(L("Add a thought", "یک فکر اضافه کنید"), placeholder=L("Anything, big or small", "هر چیزی، کوچک یا بزرگ"))
        if c2.form_submit_button(L("Add", "افزودن"), use_container_width=True) and text.strip():
            run(lambda: store.add_inbox(text), L("Added to your inbox.", "به صندوق اضافه شد."))
            st.rerun()
    items = store.list_inbox()
    if not items:
        empty(L("Your inbox is clear.", "صندوق ورودی خالی است."))
        return
    for item in items:
        tip = suggest_inbox_action(item["text"], ctx["today"])
        when = tip.get("due_date") or tip.get("scheduled_date")
        if tip["type"] == "task":
            why = L("Looks like a task", "به نظر یک کار است") + (L(f", for {D(when)}", f"، برای {D(when)}") if when else "")
        else:
            why = L("Looks like an idea or a note", "به نظر یک ایده یا یادداشت است")
        with st.container(border=True):
            st.markdown(f'<div class="t-title">{esc(item["text"])}</div>'
                        f'<div class="chips"><span class="chip teal">{esc(why)}</span></div>', unsafe_allow_html=True)
            c1, c2, c3, c4, _ = st.columns([1.1, 1.2, 0.9, 0.8, 2], gap="small")
            if c1.button(L("Make a task", "کار شود"), key=f"it-{item['id']}", type="primary" if tip["type"] == "task" else "secondary"):
                run(lambda: run_tool_unchecked(store, "process_inbox_item", {"id": item["id"], "type": "task",
                    "due_date": tip.get("due_date")}, ctx), L("Turned into a task.", "به کار تبدیل شد."))
                st.rerun()
            if c2.button(L("Make a note", "یادداشت شود"), key=f"in-{item['id']}", type="primary" if tip["type"] == "note" else "secondary"):
                run(lambda: run_tool_unchecked(store, "process_inbox_item", {"id": item["id"], "type": "note"}, ctx),
                    L("Saved as a note.", "به‌عنوان یادداشت ذخیره شد."))
                st.rerun()
            if c3.button(L("Archive", "بایگانی"), key=f"ia-{item['id']}"):
                run(lambda: store.close_inbox(item["id"], "archived"), L("Archived.", "بایگانی شد."))
                st.rerun()
            if c4.button(L("Delete", "حذف"), key=f"id-{item['id']}"):
                run(lambda: store.delete_inbox(item["id"]), L("Deleted.", "حذف شد."))
                st.rerun()


def page_tasks(store, ctx):
    st.title(L("Tasks", "کارها"))
    projects = store.list_projects()
    with st.form("add-task", clear_on_submit=True):
        title = st.text_input(L("New task", "کار تازه"), placeholder=L("What needs doing?", "چه کاری باید انجام شود؟"))
        c2, c3, c4 = st.columns([2.2, 1.5, 1.1], vertical_alignment="bottom")
        with c2:
            due = date_field(L("Due", "مهلت"), key="new-due")
        project = c3.selectbox(L("Project", "پروژه"), [None] + [p["name"] for p in projects],
                               format_func=lambda v: L("None", "بدون پروژه") if v is None else v)
        estimate = c4.selectbox(L("Time", "زمان"), [None, 15, 30, 60, 120, 180],
                                format_func=lambda v: "?" if v is None else minutes_text(v))
        if st.form_submit_button(L("Add task", "افزودن کار"), type="primary") and title.strip():
            run(lambda: store.create_task(title=title, due_date=due, project=project, estimate_min=estimate),
                L("Task added.", "کار اضافه شد."))
            st.rerun()
    views = {"open": L("Open", "باز"), "overdue": L("Overdue", "عقب‌افتاده"), "inbox": L("Not planned", "بدون برنامه"),
             "in_progress": L("In progress", "در حال انجام"), "shared": L("Shared", "اشتراکی"),
             "completed": L("Done", "انجام‌شده")}
    view = st.segmented_control(L("Show", "نمایش"), list(views), default="open", format_func=views.get,
                                label_visibility="collapsed") or "open"
    if view == "open":
        tasks = store.list_tasks(open_only=True)
    elif view == "overdue":
        tasks = store.overdue_tasks(ctx["today"])
    elif view == "shared":
        seen, tasks = set(), []
        for t in store.shared_with_me() + store.shared_by_me():
            if t["id"] not in seen:
                seen.add(t["id"])
                tasks.append(t)
    else:
        tasks = store.list_tasks(status=view)
    if not tasks:
        empty({"open": L("No open tasks. Enjoy it, or add one above.", "کار بازی ندارید. لذت ببرید یا از بالا یکی اضافه کنید."),
               "overdue": L("Nothing overdue.", "هیچ کاری عقب نیفتاده."),
               "shared": L("No shared tasks yet. Open a task, press Edit, and share it by email.",
                           "هنوز کار مشترکی ندارید. یک کار را باز کنید، «ویرایش» را بزنید و با ایمیل به اشتراک بگذارید."),
               "completed": L("Finished tasks will show up here.", "کارهای انجام‌شده این‌جا نشان داده می‌شوند.")}.get(
            view, L("Nothing here.", "این‌جا چیزی نیست.")))
    else:
        note(L(f"{len(tasks)} {plural(len(tasks), 'task', 'tasks')}", f"{len(tasks)} کار"))
    for t in tasks:
        c1, c2 = st.container(key=f"tline-{t['id']}").columns([12, 1.4], vertical_alignment="center")
        with c1:
            task_row(store, ctx, t, "tk")
        with c2:
            with st.popover(L("Edit", "ویرایش"), use_container_width=True):
                edit_task(store, t, projects)
        st.markdown('<div class="rule"></div>', unsafe_allow_html=True)


def edit_task(store, task, projects):
    with st.form(f"edit-{task['id']}"):
        title = st.text_input(L("Task", "کار"), task["title"])
        c1, c2, c3 = st.columns(3)
        labels = {"inbox": L("Not planned", "بدون برنامه"), "planned": L("Planned", "برنامه‌ریزی‌شده"),
                  "in_progress": L("In progress", "در حال انجام"), "completed": L("Done", "انجام‌شده"),
                  "cancelled": L("Cancelled", "لغوشده")}
        statuses = list(labels)
        status = c1.selectbox(L("Status", "وضعیت"), statuses, index=statuses.index(task["status"]), format_func=labels.get)
        pri = {1: L("Urgent", "فوری"), 2: L("High", "بالا"), 3: L("Normal", "معمولی"), 4: L("Low", "پایین")}
        priority = c2.selectbox(L("Priority", "اولویت"), list(PRIORITIES), index=task["priority"] - 1, format_func=pri.get)
        names = [None] + [p["name"] for p in projects]
        current = task.get("project_name")
        project = c3.selectbox(L("Project", "پروژه"), names, index=names.index(current) if current in names else 0,
                               format_func=lambda v: L("None", "بدون پروژه") if v is None else v)
        due = date_field(L("Due", "مهلت"), task["due_date"], key=f"due-{task['id']}")
        sched = date_field(L("Planned for", "برنامه برای"), task["scheduled_date"], key=f"sch-{task['id']}")
        at = st.time_input(L("At (optional)", "ساعت (اختیاری)"),
                           value=datetime.strptime(task["scheduled_time"], "%H:%M").time() if task.get("scheduled_time") else None,
                           step=900, key=f"at-{task['id']}")
        notes = st.text_area(L("Notes", "توضیحات"), task["description"])
        c6, c7, _ = st.columns([1.2, 1.1, 2])
        if c6.form_submit_button(L("Save changes", "ذخیره"), type="primary"):
            run(lambda: store.update_task(task["id"], title=title, status=status, priority=priority, due_date=due,
                                          scheduled_date=sched, scheduled_time=at.strftime("%H:%M") if (at and sched) else None,
                                          description=notes, project=project), L("Changes saved.", "تغییرات ذخیره شد."))
            st.rerun()
        if task.get("mine", True) and c7.form_submit_button(L("Delete task", "حذف کار")):
            run(lambda: store.delete_task(task["id"]), L("Task deleted.", "کار حذف شد."))
            st.rerun()
    share_controls(store, task)


def share_controls(store, task):
    """Share a task with someone, see who has it, nudge them, or step away."""
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    if not task.get("mine", True):
        st.caption(L(f"Shared with you by {task.get('owner_name', '')}"
                     + ("" if task.get("can_edit") else ", to read only"),
                     f"{task.get('owner_name', '')} این کار را با شما به اشتراک گذاشته"
                     + ("" if task.get("can_edit") else "، فقط برای دیدن")))
        c1, c2 = st.columns(2, gap="small")
        if c1.button(L("Send a nudge", "یادآوری بفرست"), key=f"nudge-{task['id']}", use_container_width=True):
            run(lambda: store.nudge(task["id"]), L("Nudge sent.", "یادآوری فرستاده شد."))
            st.rerun()
        if c2.button(L("Remove from my list", "حذف از فهرست من"), key=f"leave-{task['id']}", use_container_width=True):
            run(lambda: store.unshare_task(task["id"], store.uid), L("Removed from your list.", "از فهرست شما حذف شد."))
            st.rerun()
        return
    st.markdown(f"**{esc(L('Share this task', 'اشتراک‌گذاری این کار'))}**")
    known = [p["email"] for p in store.people_i_share_with()]
    with st.form(f"share-{task['id']}", clear_on_submit=True):
        email = st.text_input(L("Their email", "ایمیل طرف مقابل"), placeholder="name@example.com",
                              help=L("They need a Planner account with this email.",
                                     "باید با همین ایمیل در برنامه‌ریز حساب داشته باشند."))
        roles = {"editor": L("Can change and finish it", "می‌تواند تغییر دهد و انجامش کند"),
                 "viewer": L("Can only look at it", "فقط می‌تواند ببیند")}
        role = st.radio(L("What can they do?", "چه کاری بتواند بکند؟"), list(roles), format_func=roles.get, horizontal=True)
        if st.form_submit_button(L("Share", "اشتراک‌گذاری"), type="primary") and email.strip():
            if run(lambda: store.share_task(task["id"], email, role), L("Shared. They'll see it right away.",
                                                                        "به اشتراک گذاشته شد. بلافاصله آن را می‌بیند.")):
                st.rerun()
    if known:
        st.caption(L("People you already share with: ", "کسانی که قبلاً با آن‌ها اشتراک دارید: ") + ("، " if is_fa() else ", ").join(known))
    for person in task.get("shared_with", []):
        c1, c2, c3 = st.columns([2.6, 1.2, 1.2], vertical_alignment="center")
        c1.write((person["name"] or person["email"]))
        c2.caption(L("Editor", "ویرایشگر") if person["role"] == "editor" else L("Viewer", "بیننده"))
        if c3.button(L("Remove", "حذف"), key=f"rm-{task['id']}-{person['user_id']}", use_container_width=True):
            run(lambda: store.unshare_task(task["id"], person["user_id"]), L("Removed.", "حذف شد."))
            st.rerun()
    if task.get("shared_with") and st.button(L("Send a nudge to everyone", "یادآوری برای همه"), key=f"nudgeo-{task['id']}"):
        run(lambda: store.nudge(task["id"]), L("Nudge sent.", "یادآوری فرستاده شد."))
        st.rerun()


def notification_text(n):
    who = n.get("from_name") or n.get("from_email") or L("Someone", "یک نفر")
    title = n["title"]
    if n["kind"] == "shared":
        return L(f"{who} shared \"{title}\" with you", f"{who} کار «{title}» را با شما به اشتراک گذاشت")
    if n["kind"] == "completed":
        return L(f"{who} finished \"{title}\"", f"{who} کار «{title}» را انجام داد")
    if n["kind"] == "nudge":
        return L(f"{who} nudged you about \"{title}\"", f"{who} دربارهٔ «{title}» یادآوری فرستاد")
    return title


def page_shared(store, ctx):
    st.title(L("Shared", "اشتراکی"))
    note(L("Tasks you share with other people, and what they've been doing with them.",
           "کارهایی که با دیگران به اشتراک گذاشته‌اید و خبرهایی که از آن‌ها رسیده."))
    updates = store.list_notifications()
    unread = store.unread_count()
    st.subheader(L("Updates", "خبرها"))
    if not updates:
        empty(L("Nothing yet. Share a task from the Tasks page and updates will appear here.",
                "هنوز خبری نیست. از صفحهٔ کارها یک کار را به اشتراک بگذارید تا خبرها این‌جا بیایند."))
    else:
        if unread and st.button(L(f"Mark all as read ({unread})", f"همه را خوانده‌شده کن ({unread})")):
            store.mark_notifications_read()
            st.rerun()
        for n in updates[:12]:
            fresh = n["read_at"] is None
            when = n["created_at"][:10]
            st.markdown(f'<div class="slot {"must" if fresh else ""}"><time>{esc(D(when))}</time>'
                        f'<div class="what">{esc(notification_text(n))}'
                        f'<small>{esc(L("New", "تازه") if fresh else "")}</small></div></div>', unsafe_allow_html=True)
    mine, theirs = store.shared_by_me(), store.shared_with_me()
    st.subheader(L("Shared with me", "با من به اشتراک گذاشته شده"))
    if not theirs:
        empty(L("Nothing yet.", "هنوز چیزی نیست."))
    for t in theirs:
        task_row(store, ctx, t, "shm")
    st.subheader(L("I share these", "این‌ها را من به اشتراک گذاشته‌ام"))
    if not mine:
        empty(L("Open a task, press Edit, and share it with someone's email.",
                "یک کار را باز کنید، «ویرایش» را بزنید و با ایمیل کسی به اشتراک بگذارید."))
    for t in mine:
        task_row(store, ctx, t, "shb")


def page_week(store, ctx):
    state = st.session_state
    first = store.week_first()
    if state.get("week_first") != first:  # calendar changed: realign to the right first day
        state["week_start"] = week_start(ctx["today"], first)
        state["week_first"] = first
        state["week_proposal"] = None
    state.setdefault("week_start", week_start(ctx["today"], first))
    week = store.get_week(state["week_start"])
    head, nav = st.columns([2, 1.5], vertical_alignment="bottom")
    head.title(L("Your week", "هفتهٔ شما"))
    head.markdown(f'<p class="section-note">{esc(month_span(week["start"], week["end"], lang(), cal()))}</p>', unsafe_allow_html=True)
    with nav:
        b1, b2, b3 = st.columns(3, gap="small")
        if b1.button(L("Previous", "قبلی"), use_container_width=True):
            state["week_start"] = add_days(state["week_start"], -7)
            state["week_proposal"] = None
            st.rerun()
        if b2.button(L("This week", "این هفته"), use_container_width=True):
            state["week_start"] = week_start(ctx["today"], first)
            state["week_proposal"] = None
            st.rerun()
        if b3.button(L("Next", "بعدی"), use_container_width=True):
            state["week_start"] = add_days(state["week_start"], 7)
            state["week_proposal"] = None
            st.rerun()

    c1, c2, c3, _ = st.columns([1.2, 1.1, 1.7, 2.6], gap="small")
    if c1.button(L("Plan my week", "برنامهٔ هفته"), type="primary", use_container_width=True):
        state["week_proposal"] = week_plan(store, state["week_start"], ctx["now"], ctx["today"])
        st.rerun()
    review = c2.button(L("Review week", "مرور هفته"), use_container_width=True)
    up = store.list_events(week["start"], week["end"])
    timed = [t for d in week["days"] for t in d["tasks"] if t.get("scheduled_time") and t["status"] != "completed"]
    lead = int(store.get_settings().get("remind_lead") or 10)
    c3.download_button(L("Add week to my calendar", "افزودن هفته به تقویم"),
                       build_ics(plan_items(up, timed), lead, L("Planner", "برنامه‌ریز"), str(store.uid)),
                       file_name=f"week-{week['start']}.ics", mime="text/calendar", use_container_width=True,
                       help=L("Meetings, and tasks that have a time, with a reminder before each.",
                              "جلسه‌ها و کارهای ساعت‌دار، با یادآوری قبل از هر کدام."))

    proposal = state.get("week_proposal")
    new_by_day, moving = {}, set()
    if proposal:
        for ch in proposal["changes"]:
            new_by_day.setdefault(ch["to"], []).append(ch["title"])
            moving.add(ch["id"])
        with st.container(border=True):
            first_note = tr_note(proposal["assumptions"][0]) if proposal["assumptions"] else ""
            st.markdown(f"**{esc(L('Suggested plan.', 'برنامهٔ پیشنهادی.'))}** "
                        f"{esc(L('New placements are highlighted below.', 'جای‌گذاری‌های تازه در پایین مشخص شده‌اند.'))} {esc(first_note)}",
                        unsafe_allow_html=True)
            if proposal["at_risk"]:
                st.warning(L("No room this week for: ", "این هفته جایی برای این‌ها نیست: ")
                           + ("، " if is_fa() else ", ").join(t["title"] for t in proposal["at_risk"]))
            b1, b2, _ = st.columns([1.5, 1, 4], gap="small")
            n = len(proposal["changes"])
            if b1.button(L(f"Apply plan ({n} changes)", f"اعمال برنامه ({n} تغییر)"), type="primary", disabled=not n):
                run(lambda: apply_schedule(store, proposal["changes"]), L("Week planned.", "هفته برنامه‌ریزی شد."))
                state["week_proposal"] = None
                st.rerun()
            if b2.button(L("Dismiss", "بستن")):
                state["week_proposal"] = None
                st.rerun()

    cols = st.columns(7, gap="small")
    weekend = store.weekend()
    for col, day in zip(cols, week["days"]):
        with col:
            is_today = day["date"] == ctx["today"]
            wd = _date.fromisoformat(day["date"]).weekday()
            name = WEEKDAYS_FA[wd] if is_fa() else WEEKDAYS_EN[wd][:3]
            st.markdown(f'<div class="day-head{" today" if is_today else ""}{" off" if wd in weekend else ""}">{esc(name)}'
                        f'<span>{esc(short_day(day["date"], lang(), cal()))}</span></div>', unsafe_allow_html=True)
            pills = [f'<div class="pill event">{esc(N(ev["start_time"]))} {esc(ev["title"])}</div>' for ev in day["events"]]
            pills += [f'<div class="pill{" done" if t["status"] == "completed" else ""}">'
                      f'{esc(N(t["scheduled_time"]) + " ") if t.get("scheduled_time") else ""}{esc(t["title"])}</div>'
                      for t in day["tasks"] if t["id"] not in moving]
            pills += [f'<div class="pill new">{esc(title)}</div>' for title in new_by_day.get(day["date"], [])]
            pills += [f'<div class="pill due">{esc(L("Due: ", "مهلت: "))}{esc(t["title"])}</div>' for t in day["due"]]
            free = L("Day off", "تعطیل") if wd in weekend else L("Free", "آزاد")
            st.markdown("".join(pills) or f'<div class="pill" style="color:var(--moss)">{esc(free)}</div>', unsafe_allow_html=True)

    if review:
        r = store.weekly_review(state["week_start"])
        with st.container(border=True):
            st.subheader(L("Looking back", "مرور هفته"))
            nc, nn = len(r["completed"]), len(r["notes"])
            st.write(L(f"You finished {nc} {plural(nc, 'task', 'tasks')} and wrote {nn} {plural(nn, 'note', 'notes')}.",
                       f"{nc} کار را تمام کردید و {nn} یادداشت نوشتید."))
            sep = "، " if is_fa() else ", "
            if r["missed_deadlines"]:
                st.write(L("Still open past their deadline: ", "هنوز باز، با مهلت گذشته: ") + sep.join(t["title"] for t in r["missed_deadlines"]))
            if r["next_focus"]:
                st.write(L("Worth focusing on next: ", "بهتر است بعد سراغ این‌ها بروید: ") + sep.join(t["title"] for t in r["next_focus"]))

    with st.expander(L("Add a meeting or appointment", "افزودن جلسه یا قرار")):
        with st.form("add-event", clear_on_submit=True):
            title = st.text_input(L("What", "عنوان"))
            when = date_field(L("Date", "تاریخ"), ctx["today"], key="ev-date", optional=False)
            c3, c4 = st.columns(2)
            start = c3.time_input(L("Starts", "شروع"), value=datetime.strptime("10:00", "%H:%M").time(), step=900)
            end = c4.time_input(L("Ends", "پایان"), value=datetime.strptime("11:00", "%H:%M").time(), step=900)
            if st.form_submit_button(L("Add to calendar", "افزودن"), type="primary") and title.strip():
                run(lambda: store.create_event(title, when, start.strftime("%H:%M"), end.strftime("%H:%M")),
                    L("Added to your calendar.", "به تقویم اضافه شد."))
                st.rerun()


def page_notes(store, ctx):
    state = st.session_state
    st.title(L("Notes", "یادداشت‌ها"))
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        if st.button(L("New note", "یادداشت تازه"), type="primary", use_container_width=True):
            made = run(lambda: store.create_note(title=L("Untitled note", "یادداشت بی‌عنوان"), content=""))
            if made:
                state["open_note"] = made["id"]
                st.rerun()
        q = st.text_input(L("Find a note", "پیدا کردن یادداشت"), placeholder=L("Search notes", "جستجو در یادداشت‌ها"),
                          label_visibility="collapsed")
        notes = store.list_notes(query=q.strip() or None)
        if not notes:
            st.caption(L("No notes yet.", "هنوز یادداشتی ندارید.") if not q else L("No notes match that.", "یادداشتی پیدا نشد."))
        for n in notes:
            if st.button(n["title"][:42] or L("Untitled", "بی‌عنوان"), key=f"note-{n['id']}", use_container_width=True,
                         type="primary" if state.get("open_note") == n["id"] else "secondary"):
                state["open_note"] = n["id"]
                st.rerun()
    with right:
        if not state.get("open_note"):
            empty(L("Pick a note on the left, or start a new one. Ideas you capture on Today land here too.",
                    "یک یادداشت را انتخاب کنید یا یادداشت تازه بسازید. ایده‌هایی که در «امروز» می‌نویسید هم این‌جا می‌آیند."))
            return
        try:
            n = store.get_note(state["open_note"])
        except ValidationError:
            state["open_note"] = None
            st.rerun()
        with st.form(f"note-{n['id']}"):
            title = st.text_input(L("Title", "عنوان"), n["title"])
            content = st.text_area(L("Note", "متن"), n["content"], height=320,
                                   placeholder=L("Write freely. Lines with actions can become tasks.",
                                                 "آزادانه بنویسید. جمله‌هایی که کار هستند می‌توانند کار شوند."))
            c1, c2, c3, _ = st.columns([0.9, 1.5, 0.9, 2], gap="small")
            if c1.form_submit_button(L("Save", "ذخیره"), type="primary"):
                run(lambda: store.update_note(n["id"], title=title, content=content), L("Note saved.", "یادداشت ذخیره شد."))
                st.rerun()
            if c2.form_submit_button(L("Make tasks from this", "ساختن کار از این متن")):
                store.update_note(n["id"], title=title, content=content)
                parsed = parse_capture(content, ctx["today"])
                for t in parsed["tasks"]:
                    run(lambda t=t: store.create_task(title=t["title"], due_date=t.get("due_date"),
                                                      scheduled_date=t.get("scheduled_date")))
                k = len(parsed["tasks"])
                flash(L(f"Made {k} {plural(k, 'task', 'tasks')} from this note.", f"{k} کار از این یادداشت ساخته شد.")
                      if k else L("I didn't find any actions in this note.", "در این یادداشت کاری پیدا نکردم."),
                      "success" if k else "info")
                st.rerun()
            if c3.form_submit_button(L("Delete", "حذف")):
                run(lambda: store.delete_note(n["id"]), L("Note deleted.", "یادداشت حذف شد."))
                state["open_note"] = None
                st.rerun()
        edited = n["updated_at"][:10]
        st.caption(L(f"Last edited {D(edited, with_year=True)} at {n['updated_at'][11:16]}",
                     f"آخرین ویرایش {D(edited, with_year=True)} ساعت {n['updated_at'][11:16]}"))


def page_projects(store, ctx):
    st.title(L("Projects", "پروژه‌ها"))
    with st.form("add-project", clear_on_submit=True):
        name = st.text_input(L("New project", "پروژهٔ تازه"), placeholder=L("For example: Kitchen renovation", "مثلاً: بازسازی آشپزخانه"))
        due = date_field(L("Due", "مهلت"), key="proj-due")
        if st.form_submit_button(L("Create", "ساختن"), type="primary") and name.strip():
            run(lambda: store.create_project(name, due_date=due), L("Project created.", "پروژه ساخته شد."))
            st.rerun()
    projects = store.list_projects()
    if not projects:
        empty(L("Projects group related tasks and notes. Create one above, or add a project name when you make a task.",
                "پروژه کارها و یادداشت‌های مرتبط را کنار هم نگه می‌دارد. از بالا یکی بسازید یا هنگام ساختن کار، نام پروژه را بنویسید."))
    for p in projects:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1.2], vertical_alignment="center")
            c1.markdown(f"### {esc(p['name'])}", unsafe_allow_html=True)
            done_n, total_n = p["done_count"], p["task_count"]
            progress_text = L(f"{done_n} of {total_n} done", f"{done_n} از {total_n} انجام شد")
            c2.markdown(f'<div style="text-align:end;color:var(--moss)">{esc(progress_text)}</div>', unsafe_allow_html=True)
            st.progress(p["progress"] / 100)
            if p["due_date"]:
                st.caption(L(f"Due {friendly_date(p['due_date'], ctx['today'])}", f"مهلت: {friendly_date(p['due_date'], ctx['today'])}"))
            with st.expander(L("Tasks and notes", "کارها و یادداشت‌ها")):
                full = store.get_project(p["id"])
                if not full["tasks"] and not full["notes"]:
                    st.caption(L("Nothing in this project yet.", "هنوز چیزی در این پروژه نیست."))
                for t in full["tasks"]:
                    task_row(store, ctx, t, f"pr{p['id']}", show_project=False)
                for nt in full["notes"]:
                    st.caption(L(f"Note: {nt['title']}", f"یادداشت: {nt['title']}"))
                if st.button(L("Delete project", "حذف پروژه"), key=f"delp-{p['id']}"):
                    run(lambda: store.delete_project(p["id"]), L("Project deleted. Its tasks and notes are kept.",
                                                                  "پروژه حذف شد. کارها و یادداشت‌هایش باقی ماندند."))
                    st.rerun()


def page_goals(store, ctx):
    st.title(L("Goals", "هدف‌ها"))
    note(L("Big things you're working towards. With the AI connected, ask the assistant to break a goal into projects and tasks.",
           "کارهای بزرگی که به سمتشان می‌روید. با وصل کردن هوش مصنوعی، از دستیار بخواهید هدف را به پروژه و کار تقسیم کند."))
    with st.form("add-goal", clear_on_submit=True):
        title = st.text_input(L("New goal", "هدف تازه"), placeholder=L("For example: Learn Python in 3 months", "مثلاً: یادگیری پایتون در ۳ ماه"))
        deadline = date_field(L("By", "تا تاریخ"), key="goal-by")
        if st.form_submit_button(L("Create", "ساختن"), type="primary") and title.strip():
            run(lambda: store.create_goal(title, deadline=deadline), L("Goal created.", "هدف ساخته شد."))
            st.rerun()
    goals = store.list_goals()
    if not goals:
        empty(L("No goals yet.", "هنوز هدفی ندارید."))
    for g in goals:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1], vertical_alignment="center")
            c1.markdown(f"### {esc(g['title'])}", unsafe_allow_html=True)
            c2.markdown(f'<div style="text-align:end;color:var(--moss)">{esc(N(g["progress"]))}٪</div>' if is_fa()
                        else f'<div style="text-align:end;color:var(--moss)">{g["progress"]}%</div>', unsafe_allow_html=True)
            st.progress(g["progress"] / 100)
            bits = [L(f"{g['done_count']} of {g['task_count']} tasks done", f"{g['done_count']} از {g['task_count']} کار انجام شد")]
            if g["deadline"]:
                bits.append(L(f"by {friendly_date(g['deadline'], ctx['today'])}", f"تا {friendly_date(g['deadline'], ctx['today'])}"))
            st.caption(("، " if is_fa() else ", ").join(bits))
            for p in g["projects"]:
                st.markdown(f"- {esc(p['name'])}", unsafe_allow_html=True)
            if st.button(L("Delete goal", "حذف هدف"), key=f"delg-{g['id']}"):
                run(lambda: store.delete_goal(g["id"]), L("Goal deleted.", "هدف حذف شد."))
                st.rerun()


def page_search(store, ctx):
    st.title(L("Search", "جستجو"))
    q = st.text_input(L("Search everything", "جستجو در همه چیز"), placeholder=L("A word, a person, a project…", "یک کلمه، یک نام، یک پروژه…"),
                      label_visibility="collapsed")
    if not q.strip():
        empty(L("Search looks through tasks, notes, projects and goals. Searching a project's name also shows everything inside it.",
                "در کارها، یادداشت‌ها، پروژه‌ها و هدف‌ها جستجو می‌کند. جستجوی نام یک پروژه، همهٔ محتوای آن را هم نشان می‌دهد."))
        return
    found = store.search(q)
    if not (found["tasks"] or found["notes"] or found["projects"] or found["goals"]):
        empty(L(f'Nothing matches "{q}". Try a shorter word.', f"چیزی با «{q}» پیدا نشد. کلمهٔ کوتاه‌تری امتحان کنید."))
        return
    if found["projects"] or found["goals"]:
        st.subheader(L("Projects and goals", "پروژه‌ها و هدف‌ها"))
        for p in found["projects"]:
            st.markdown(f"- {esc(L('Project', 'پروژه'))}: **{esc(p['name'])}**", unsafe_allow_html=True)
        for g in found["goals"]:
            st.markdown(f"- {esc(L('Goal', 'هدف'))}: **{esc(g['title'])}**", unsafe_allow_html=True)
    if found["tasks"]:
        st.subheader(L("Tasks", "کارها"))
        for t in found["tasks"]:
            task_row(store, ctx, t, "se")
    if found["notes"]:
        st.subheader(L("Notes", "یادداشت‌ها"))
        for n in found["notes"]:
            with st.expander(n["title"]):
                st.write(n["content"] or L("(empty)", "(خالی)"))


def notification_permission_widget():
    """A small in-page control: ask the browser for permission and send a test."""
    t = {"allow": L("Allow notifications", "اجازهٔ اعلان"), "test": L("Send a test", "ارسال آزمایشی"),
         "on": L("Notifications are on in this browser.", "اعلان‌ها در این مرورگر فعال است."),
         "off": L("Not allowed yet.", "هنوز اجازه داده نشده."),
         "blocked": L("Blocked. Allow notifications for this site in your browser settings.",
                      "مسدود است. در تنظیمات مرورگر، اعلان این سایت را مجاز کنید."),
         "none": L("This browser can't show notifications here. Use the calendar option below.",
                   "این مرورگر این‌جا اعلان نشان نمی‌دهد. از گزینهٔ تقویم در پایین استفاده کنید."),
         "title": L("Planner", "برنامه‌ریز"), "body": L("Reminders will look like this.", "یادآورها این شکلی هستند.")}
    direction = "rtl" if is_fa() else "ltr"
    texts = json.dumps(t, ensure_ascii=False).replace("<", "\\u003c")
    components.html(f"""
<div dir="{direction}" style="font-family: Vazirmatn, 'Nunito Sans', system-ui, sans-serif; color:#1F3A34; font-size:14px;
     display:flex; gap:10px; align-items:center; flex-wrap:wrap; padding:2px">
  <button id="a" style="background:#2F7D6D;color:#fff;border:0;border-radius:10px;padding:8px 14px;font:inherit;font-weight:600;cursor:pointer">{esc(t['allow'])}</button>
  <button id="b" style="background:#fff;color:#1F3A34;border:1px solid #DCE3DE;border-radius:10px;padding:8px 14px;font:inherit;cursor:pointer">{esc(t['test'])}</button>
  <span id="s" style="color:#5E726C"></span>
</div>
<script>
var P = window.parent, T = {texts};
function show() {{
  var s = document.getElementById('s');
  if (!('Notification' in P)) {{ s.textContent = T.none; return; }}
  var p = P.Notification.permission;
  s.textContent = p === 'granted' ? T.on : p === 'denied' ? T.blocked : T.off;
  document.getElementById('a').style.display = p === 'granted' ? 'none' : '';
}}
document.getElementById('a').onclick = function () {{
  if ('Notification' in P) P.Notification.requestPermission().then(show);
}};
document.getElementById('b').onclick = function () {{
  if ('Notification' in P && P.Notification.permission === 'granted') {{
    try {{ new P.Notification(T.title, {{ body: T.body }}); }} catch (e) {{ document.getElementById('s').textContent = T.none; }}
  }} else show();
}};
show();
</script>""", height=56)


def page_settings(store, ctx, user):
    st.title(L("Settings", "تنظیمات"))
    tab_lang, tab_remind, tab_ai, tab_day, tab_account = st.tabs(
        [L("Language and calendar", "زبان و تقویم"), L("Reminders", "یادآورها"), L("AI assistant", "هوش مصنوعی"),
         L("Your day", "روز شما"), L("Account", "حساب")])

    with tab_lang:
        s = store.get_settings()
        with st.form("prefs"):
            new_lang = st.radio(L("Language", "زبان"), ["en", "fa"], index=["en", "fa"].index(s["lang"]),
                                format_func=lambda v: "English" if v == "en" else "فارسی", horizontal=True)
            new_cal = st.radio(L("Calendar", "تقویم"), ["gregorian", "jalali"], index=["gregorian", "jalali"].index(s["calendar"]),
                               format_func=lambda v: L("Gregorian", "میلادی") if v == "gregorian" else L("Jalali (Solar Hijri)", "شمسی (جلالی)"),
                               horizontal=True)
            st.caption(L("With the Jalali calendar, weeks start on Saturday and Friday is the day off.",
                         "در تقویم شمسی، هفته از شنبه شروع می‌شود و جمعه تعطیل است."))
            if st.form_submit_button(L("Save", "ذخیره"), type="primary"):
                run(lambda: store.update_preferences(lang=new_lang, calendar=new_cal))
                st.session_state["lang"], st.session_state["calendar"] = new_lang, new_cal
                st.session_state["day_plan"] = None
                st.session_state["week_proposal"] = None
                flash("تنظیمات ذخیره شد." if new_lang == "fa" else "Saved.")
                st.rerun()

    with tab_remind:
        s = store.get_settings()
        st.markdown(f"**{esc(L('Reminders in this browser', 'یادآور در همین مرورگر'))}**")
        note(L("While Planner is open in a tab, you'll get a notification before each meeting and each planned task that has a time. "
               "Works in desktop browsers; on phones, use the calendar option below.",
               "تا وقتی برنامه‌ریز در یک زبانه باز است، قبل از هر جلسه و هر کار ساعت‌دار اعلان می‌گیرید. "
               "در مرورگر رایانه کار می‌کند؛ روی گوشی از گزینهٔ تقویم در پایین استفاده کنید."))
        notification_permission_widget()
        with st.form("reminders"):
            enabled = st.checkbox(L("Remind me before meetings and planned tasks", "قبل از جلسه‌ها و کارهای برنامه‌ریزی‌شده یادآوری کن"),
                                  value=s["remind_enabled"] == "1")
            leads = [5, 10, 15, 30, 60]
            cur = int(s.get("remind_lead") or 10)
            lead = st.selectbox(L("How long before", "چقدر زودتر"), leads, index=leads.index(cur) if cur in leads else 1,
                                format_func=lambda v: minutes_text(v))
            morning_on = st.checkbox(L("A short summary of the day each morning", "خلاصهٔ کوتاه روز، هر صبح"), value=bool(s.get("remind_morning")))
            morning = st.time_input(L("At", "ساعت"), value=datetime.strptime(s.get("remind_morning") or "08:30", "%H:%M").time(), step=900)
            if st.form_submit_button(L("Save reminders", "ذخیرهٔ یادآورها"), type="primary"):
                run(lambda: store.update_reminders(enabled, lead, morning.strftime("%H:%M") if morning_on else ""),
                    L("Reminders saved.", "یادآورها ذخیره شد."))
                st.rerun()
        st.caption(L("Tasks get a time when you save a day plan, or when you set one while editing a task.",
                     "کارها وقتی ساعت می‌گیرند که برنامهٔ روز را ثبت کنید یا هنگام ویرایش کار ساعت بگذارید."))
        st.markdown(f"**{esc(L('Reminders on your phone, even when Planner is closed', 'یادآور روی گوشی، حتی وقتی برنامه‌ریز بسته است'))}**")
        note(L("Download your plan as a calendar file and open it on your phone. Your calendar app adds each item with an alarm "
               "and reminds you on time. Download again after you change your plan; items update instead of duplicating.",
               "برنامه‌تان را به‌صورت فایل تقویم بگیرید و روی گوشی باز کنید. برنامهٔ تقویم هر مورد را با هشدار اضافه می‌کند "
               "و به‌موقع یادآوری می‌کند. بعد از تغییر برنامه دوباره بگیرید؛ موارد به‌روز می‌شوند و تکراری نمی‌شوند."))
        up = store.upcoming(ctx["today"])
        items = plan_items(up["events"], up["tasks"])
        c1, c2 = st.columns([1.5, 3], vertical_alignment="center")
        c1.download_button(L("Today and tomorrow (.ics)", "امروز و فردا (.ics)"),
                           build_ics(items, int(s.get("remind_lead") or 10), L("Planner", "برنامه‌ریز"), str(store.uid)),
                           file_name=f"planner-{ctx['today']}.ics", mime="text/calendar", use_container_width=True,
                           disabled=not items)
        c2.caption(L(f"{len(items)} {plural(len(items), 'item', 'items')} with a time.", f"{len(items)} مورد ساعت‌دار.")
                   if items else L("Nothing with a time yet. Save a day plan first.", "هنوز مورد ساعت‌داری نیست. اول برنامهٔ روز را ثبت کنید."))

    with tab_ai:
        cfg = resolve_config(store)
        locked = cfg["source"] == "env"
        if locked:
            st.info(L("The AI is set up by whoever runs this app, so there's nothing to change here.",
                      "هوش مصنوعی را مدیر این برنامه تنظیم کرده و این‌جا چیزی برای تغییر نیست."))
        ids = list(PRESETS)
        chosen = st.selectbox(L("Provider", "سرویس"), ids, index=ids.index(cfg["provider"]),
                              format_func=lambda i: PRESETS[i]["label"], disabled=locked)
        preset = PRESETS[chosen]
        help_text = preset["help"]
        if preset["key_url"]:
            help_text += f" [{L('Get a key', 'گرفتن کلید')}]({preset['key_url']})"
        st.caption(help_text)
        same = chosen == cfg["provider"]
        key = model = base_url = ""
        if preset["needs_key"]:
            key = st.text_input(L("API key", "کلید API"), type="password", disabled=locked,
                                placeholder=L(f"Saved key ending {cfg['key_hint']}. Leave blank to keep it.",
                                              f"کلید ذخیره‌شده ({cfg['key_hint']}). برای نگه داشتن، خالی بگذارید.")
                                if (same and cfg["api_key"]) else L("Paste your key", "کلید را این‌جا بچسبانید"))
        if chosen != "none":
            model = st.text_input(L("Model", "مدل"), value=cfg["model"] if same else preset["model"], disabled=locked)
        if chosen == "openai_compatible":
            base_url = st.text_input(L("Service URL", "نشانی سرویس"), value=cfg["base_url"] if same else "",
                                     placeholder="https://…", disabled=locked)
        c1, c2, _ = st.columns([0.8, 1.4, 5], gap="small")
        if c1.button(L("Save", "ذخیره"), type="primary", disabled=locked):
            if run(lambda: save_config(store, chosen, key, model, base_url), L("AI settings saved.", "تنظیمات ذخیره شد.")):
                st.rerun()
        if c2.button(L("Test connection", "آزمایش اتصال")):
            with st.spinner(L("Testing…", "در حال آزمایش…")):
                ok, message = test_connection(resolve_config(store))
            (st.success if ok else st.error)(message)
        if cfg["enabled"]:
            st.caption(L(f"On: {cfg['label']}, model {cfg['model']}.", f"فعال: {cfg['label']}، مدل {cfg['model']}."))
        st.caption(L("Your key is kept with your account and isn't shown to anyone else.",
                     "کلید شما فقط در حساب خودتان نگه داشته می‌شود."))

    with tab_day:
        s = store.get_settings()
        with st.form("hours"):
            st.markdown(f"**{esc(L('Working hours', 'ساعت کاری'))}**")
            st.caption(L("Plans are built inside these hours.", "برنامه‌ها در همین ساعت‌ها چیده می‌شوند."))
            c1, c2 = st.columns(2)
            start = c1.time_input(L("Start", "شروع"), value=datetime.strptime(s["workday_start"], "%H:%M").time(), step=900)
            end = c2.time_input(L("End", "پایان"), value=datetime.strptime(s["workday_end"], "%H:%M").time(), step=900)
            if st.form_submit_button(L("Save hours", "ذخیرهٔ ساعت‌ها"), type="primary"):
                run(lambda: store.update_hours(start.strftime("%H:%M"), end.strftime("%H:%M")), L("Working hours saved.", "ساعت کاری ذخیره شد."))
                st.session_state["day_plan"] = None
                st.rerun()
        st.markdown(f"**{esc(L('What the assistant remembers about you', 'آنچه دستیار دربارهٔ شما به یاد دارد'))}**")
        memories = store.list_memories()
        if not memories:
            st.caption(L("Nothing yet. When you mention a lasting fact, like a thesis deadline, it's kept here.",
                         "هنوز چیزی نیست. وقتی نکتهٔ ماندگاری بگویید، مثل مهلت پایان‌نامه، این‌جا نگه داشته می‌شود."))
        for m in memories:
            c1, c2 = st.columns([5, 1])
            c1.write(m["fact"])
            if c2.button(L("Forget", "فراموش کن"), key=f"mem-{m['id']}"):
                run(lambda: store.forget(m["id"]), L("Forgotten.", "فراموش شد."))
                st.rerun()

    with tab_account:
        acc = Accounts(conn())
        with st.form("name"):
            name = st.text_input(L("Your name", "نام شما"), user["name"])
            st.caption(L(f"Signed in as {user['email']}", f"وارد شده با {user['email']}"))
            if st.form_submit_button(L("Save name", "ذخیرهٔ نام"), type="primary"):
                run(lambda: acc.update_name(user["id"], name), L("Name saved.", "نام ذخیره شد."))
                st.rerun()
        with st.form("password", clear_on_submit=True):
            st.markdown(f"**{esc(L('Change password', 'تغییر رمز'))}**")
            current = st.text_input(L("Current password", "رمز فعلی"), type="password")
            new = st.text_input(L("New password", "رمز تازه"), type="password", help=L("At least 8 characters.", "دست‌کم ۸ نویسه."))
            again = st.text_input(L("New password again", "تکرار رمز تازه"), type="password")
            if st.form_submit_button(L("Change password", "تغییر رمز")):
                if new != again:
                    st.error(L("The new passwords don't match.", "دو رمز تازه یکی نیستند."))
                elif run(lambda: acc.change_password(user["id"], current, new) or True,
                         L("Password changed. Other devices have been signed out.", "رمز تغییر کرد. دستگاه‌های دیگر از حساب خارج شدند.")):
                    st.session_state.pop("token", None)
                    st.rerun()
        with st.expander(L("Delete account", "حذف حساب")):
            st.write(L("This permanently deletes your account and every task, note, project and goal in it.",
                       "با این کار حساب شما و همهٔ کارها، یادداشت‌ها، پروژه‌ها و هدف‌هایش برای همیشه پاک می‌شود."))
            with st.form("delete", clear_on_submit=True):
                pw = st.text_input(L("Enter your password to confirm", "برای تأیید، رمزتان را وارد کنید"), type="password")
                sure = st.checkbox(L("I understand this can't be undone", "می‌دانم این کار برگشت‌پذیر نیست"))
                if st.form_submit_button(L("Delete my account", "حساب من را حذف کن")):
                    if not sure:
                        st.error(L("Tick the box to confirm.", "برای تأیید، گزینه را علامت بزنید."))
                    elif run(lambda: acc.delete(user["id"], pw) or True):
                        sign_out()


def sidebar(store, user, ctx):
    with st.sidebar:
        st.markdown(f'<p class="brand">{esc(L("Planner", "برنامه‌ریز"))}</p>'
                    f'<p class="brand-sub">{esc(L("Your day, calmly planned", "روزتان، آرام و سنجیده"))}</p>',
                    unsafe_allow_html=True)
        initial = (user["name"] or user["email"])[:1].upper()
        st.markdown(f'<div class="who"><span class="avatar">{esc(initial)}</span><div>{esc(user["name"] or L("Welcome", "خوش آمدید"))}'
                    f'<small>{esc(user["email"])}</small></div></div>', unsafe_allow_html=True)
        badges = {"inbox": len(store.list_inbox()), "assistant": len(store.open_pending()),
                  "shared": store.unread_count()}

        def label(key):
            icon, en, fa = PAGES[key]
            n = badges.get(key)
            return f"{icon}  {fa if is_fa() else en}" + (f"  ({N(n)})" if n else "")

        st.radio("Go to", list(PAGES), key="page", format_func=label, label_visibility="collapsed")
        st.write("")
        cfg = resolve_config(store)
        st.caption(L("AI: ", "هوش مصنوعی: ") + (cfg["label"].split(" (")[0] if cfg["enabled"] else L("basic mode", "حالت ساده")))
        if st.button(L("Sign out", "خروج"), use_container_width=True):
            sign_out()


def main():
    st.set_page_config(page_title="Planner", page_icon="☀️", layout="wide", initial_sidebar_state="auto")
    load_secrets()
    restore_session()
    uid = st.session_state.get("uid")
    if uid:
        try:
            user = Accounts(conn()).public(uid)
        except ValidationError:  # account was deleted elsewhere
            sign_out()
            return
        store = Store(conn(), uid)
        prefs = store.get_settings()  # the account's saved choice wins once signed in
        st.session_state["lang"], st.session_state["calendar"] = prefs["lang"], prefs["calendar"]
    st.markdown(CSS, unsafe_allow_html=True)
    if is_fa():
        st.markdown(FA_CSS, unsafe_allow_html=True)
    if not uid:
        page_auth()
        return
    if st.session_state.get("set_cookie"):
        set_cookie(st.session_state.pop("set_cookie"))

    now = local_now()
    ctx = {"today": now.date().isoformat(), "now": now.strftime("%H:%M")}
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
     "shared": lambda: page_shared(store, ctx), "search": lambda: page_search(store, ctx), "settings": lambda: page_settings(store, ctx, user)}[page]()
    reminder_engine(store, ctx)


if __name__ == "__main__":
    main()
