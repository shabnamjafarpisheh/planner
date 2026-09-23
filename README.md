# Planner · برنامه‌ریز

A calm daily planner with an AI assistant, in **English and Persian**, with the **Gregorian or Jalali calendar**, **reminders**, and private **accounts**.

## Run it

**Easiest:** double-click **run.bat** (Windows) or **run.command** (macOS), or run **./run.sh** (Linux). The first run installs Streamlit (about a minute), then your browser opens.

**By hand:** `pip install -r requirements.txt`, then `streamlit run app.py`. You need Python 3.10 or newer.

**Streamlit Community Cloud:** only `app.py` and `requirements.txt` are needed. Adding `.streamlit/config.toml` is optional.

## Persian mode · حالت فارسی

Pick **فارسی** at the top of the sign-in page, or later in **Settings → Language and calendar**. The choice is saved with the account.

- **Layout:** the whole interface is in Persian and reads right to left, using the Vazirmatn font and Persian digits. The day horizon on Today runs right to left too.
- **Capture:** you can type in Persian. «باید ارائه را تا دوشنبه تمام کنم، فردا به علی زنگ بزنم و ایده: صفحهٔ اول ساده‌تر» becomes two tasks and a note.
- **Deadlines vs. plans:** «تا دوشنبه» becomes a deadline, «فردا» becomes a planned day, and vague words stay undated.
- **Dates Planner understands:** امروز، فردا، پس‌فردا, the weekday names, «۳ روز دیگر», «هفتهٔ بعد», and Jalali dates like «۱۵ مهر».
- **Your wording is kept exactly,** half-spaces included. «کتاب و دفتر بخرم» stays one task, and «شاید …» is saved as an idea, not a task.
- **The assistant answers in Persian,** both with an AI connected and in basic mode. Basic mode understands requests like «برنامهٔ امروزم را بچین», «چه کارهایی عقب افتاده؟» and «کارهای ناتمام را به فردا منتقل کن». Confirmation messages are in Persian too.

## Jalali calendar · تقویم شمسی

You can use it with either language; choosing Persian switches it on by default.

- **Dates everywhere** appear in Jalali, for example «سه‌شنبه ۳۱ شهریور ۱۴۰۵», or "Tuesday, 31 Shahrivar" in English.
- **Date pickers** become day / month / year lists in Jalali, because Streamlit's own picker only knows the Gregorian calendar.
- **Weeks** start on **Saturday**, and **Friday** is the day off, so plans never land on it.
- **Accuracy:** the conversion was checked day by day against the `jdatetime` library for 1950–2100 (55,152 days, no differences), including leap years.

Dates are still stored in the standard Gregorian format underneath, so switching calendars never changes your data.

## Reminders · یادآورها

A Streamlit app can't send anything while it's closed, so there are two routes. Both are in **Settings → Reminders**.

1. **Browser reminders while Planner is open.**
   - Press **Allow notifications** once; **Send a test** shows what they look like.
   - You're notified before each meeting and each task that has a time. Choose 5, 10, 15, 30 or 60 minutes ahead.
   - An optional morning summary tells you how many tasks, meetings and overdue items you have.
   - Works in desktop browsers (Chrome, Edge, Firefox, Safari). Phones generally don't allow this for websites.

2. **Your phone's calendar, even when Planner is closed.**
   - **Add to my phone calendar** (under a day plan), **Add week to my calendar** (Week page), or **Today and tomorrow (.ics)** (Settings) downloads a calendar file.
   - Open it on your phone. Your calendar app adds each meeting and timed task with an alarm and reminds you on time.
   - Downloading again after you change the plan updates the same items instead of duplicating them.

**Tasks get a time** when you press **Save this plan to today** (each task keeps the start time from the plan), or when you set one under **Edit** on the Tasks page. Moving a task to another day clears its old time.

## Shared tasks · کارهای مشترک

Two people with accounts can work on the same task.

- **Share it:** open a task, press **Edit**, enter the other person's email and choose what they can do — **editor** (change and finish it) or **viewer** (look only). They need an account with that email.
- **Both see it.** It appears in their task list, their day plan and their searches, marked **From Ana**; on your side it's marked **Shared with Nima**.
- **Either editor can finish it,** and it's done for both at once.
- **Only the owner** can delete it or share it further. Anyone shared with can remove it from their own list.
- **A nudge** ("Send a nudge") gives everyone else on the task a friendly reminder.
- **Nothing else is exposed.** Sharing one task shares exactly that task: not your other tasks, your notes, your projects or your AI key. There are tests for this.
- **The assistant can share too** ("share the venue task with ana@example.com"), but sharing always waits for your confirmation first, and it never invents an email address.

### Updates between people

The **Shared** page shows what happened: who shared something with you, who finished a shared task, and who nudged you. The sidebar shows how many are unread.

If browser reminders are on (see below), these updates also arrive as notifications while Planner is open, each one only once.

## Accounts

- **Sign in or create an account**; each person's data, AI key and settings are completely separate.
- **Passwords** are stored as salted PBKDF2-SHA256 hashes.
- **Failed sign-ins:** after 5 wrong tries, the account waits 10 minutes.
- **"Keep me signed in"** lasts 30 days. Changing the password signs out other devices.
- **Settings → Account** lets you rename yourself, change the password, or delete the account.

Data from the earlier single-user version moves automatically to the first account created.

## Free AI

In **Settings → AI assistant**, pick a provider, paste a key and press **Test connection**:
- **Google Gemini** has a free tier with no card needed: get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- **Groq** is also free, at [console.groq.com/keys](https://console.groq.com/keys).
- **Ollama** is free and runs offline on your own computer.
- Any OpenAI-compatible service or Anthropic also work.

Without a provider, basic mode still handles capture, planning, overdue checks, moving tasks and search in both languages. When Persian is on, the AI is told to reply in Persian. With the Jalali calendar, it's told to use weekday names rather than converting dates itself, so it can't get a Jalali date wrong.

## Before you share it on Streamlit Community Cloud

- **Accounts and data are wiped whenever the app restarts or sleeps,** because Community Cloud's disk is temporary. For everyday use, run it on your own computer or a server with a permanent disk (set `DATABASE_PATH`).
- **Anyone with the link can create an account;** restrict viewers in the Cloud app's settings.
- **Browser reminders** need the Planner tab to stay open.
- **Sharing needs both people on the same Planner,** so on Community Cloud they'd share an app whose data is wiped on restart. For real shared use, run it somewhere with a permanent disk.

## Tests

`python -m unittest discover -s tests` runs 81 tests, covering:
- The Jalali conversion, leap years and date formatting.
- Persian capture: dates, deadlines, splitting on «و», and ideas.
- Saturday weeks with Friday off.
- Persian replies and confirmations.
- Plan times and reminder timing.
- Calendar files: escaping, line folding, alarms, stable ids.
- Accounts, lockout and sessions.
- Isolation between accounts.
- Sharing: who can see, change, finish, delete and re-share; viewers being read-only; nudges; updates counted and delivered once; and that sharing one task leaks nothing else.
- Planning, the agent and the AI providers.

The code also compiles on Python 3.10, since Streamlit Cloud may use an older Python.

## Known limitations

- There's no password-reset email.
- Browser notifications don't work on most phones; use the calendar file there.
- On phones, the menu stays open after choosing a page; tap the arrow to close it.
- Persian capture understands common phrasing. For anything more complex, connect the AI.
- Sharing tells you if an email has no account yet, which reveals whether that address is registered. That suits a small, trusted group.
- Projects, notes and goals aren't shareable yet, only tasks.
- Planner reasons (like «مهلت: دوشنبه») are shown in Persian, but a few rare messages that come straight from an AI provider (for example error details) may appear in English.
