"""Turning a brain dump into structured items.

The rule that matters most: never invent a deadline. Vague wording ("soon",
"at some point") leaves the date empty rather than guessing.
"""
from __future__ import annotations

import re

from .store import WEEKDAYS, add_days, parse_iso, weekday_name

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
