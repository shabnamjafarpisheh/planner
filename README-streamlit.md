# Planner

A calm daily planner with an AI assistant. Write down what's on your mind; Planner turns it into tasks and notes, fits them around your meetings, and helps you keep going day after day.

## Run it

**Easiest:** double-click **run.bat** (Windows) or **run.command** (macOS), or run **./run.sh** (Linux). The first run installs Streamlit into a private folder (about a minute), then your browser opens.

**By hand:**

```
pip install -r requirements.txt
streamlit run app.py
```

You need **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/); on Windows tick "Add python.exe to PATH" during setup).

**On Streamlit Community Cloud,** only `app.py` and `requirements.txt` are needed. Also upload `.streamlit/config.toml` if you can; the look holds without it, but it makes a few built-in controls match.

## Accounts

The first screen lets people **sign in** or **create an account**. Each account's tasks, notes, projects, goals, chat history and AI key are completely separate: every database query is limited to the signed-in person, and the tests check that one account can't read, change or delete another's things, even by guessing an id.

- Passwords must be at least 8 characters. They're stored as salted PBKDF2-SHA256 hashes (600,000 rounds), never as text.
- A wrong email and a wrong password get the same message, so the sign-in form doesn't reveal who has an account.
- After 5 wrong passwords, the account waits 10 minutes before trying again.
- **Keep me signed in** remembers you on that device for 30 days, so refreshing the page doesn't sign you out. The browser holds a random token; the database stores only its hash. Signing out ends it, and changing your password signs out every other device.
- **Settings → Account** lets you change your name or password, or delete the account and everything in it (password required).

If you used the earlier single-user version, the **first account created** on that database takes over its tasks, notes and settings automatically.

## The design

The colours are chosen for something you open every day: a soft sage-white background, deep pine text and sidebar, and a steady teal for actions. Brighter colours appear only when they mean something: rose for overdue, blue for "should do", and the sun.

Today opens with a greeting and a **day horizon**: your working hours drawn as a line, with meetings resting on it, planned work under it (coloured by urgency), and a sun showing where you are in the day. A small badge counts the days in a row you've finished something.

Other touches:
- A short welcome guide for new accounts.
- Plain-language empty screens that tell you what to do next.
- Friendly dates ("tomorrow", "Monday") instead of raw ones.
- Every change confirmed with a short message.
- A layout that works on phones.

Headings use Literata and the rest uses Nunito Sans, loaded from Google Fonts with system fallbacks.

## Turn the AI on, for free

Without AI, the built-in rules handle capture, "plan my day", "plan my week", overdue checks, moving unfinished tasks, and search. For full natural-language help, open **Settings → AI assistant**, pick a provider, paste a key and press **Test connection**. Each person's key is kept with their own account.

| Provider | Cost | Key | Notes |
|---|---|---|---|
| **Google Gemini** (recommended) | Free tier, no card | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Generous per-minute allowance. Free-tier prompts may be used by Google to improve its products. |
| **Groq** | Free tier, no card | [console.groq.com/keys](https://console.groq.com/keys) | Very fast; the small per-minute allowance can slow long requests. |
| **Ollama** | Free, offline | none | Runs on your own computer ([ollama.com](https://ollama.com), then `ollama pull llama3.1`). Not available on Streamlit Cloud. |
| **Other OpenAI-compatible** | varies | varies | OpenRouter, LM Studio and similar. |
| **Anthropic Claude** | Paid | [console.anthropic.com](https://console.anthropic.com/) | Best quality. |

If you put a key in Streamlit **Secrets** instead (see `.streamlit/secrets.toml.example`), everyone using the app shares it, and so shares its free-tier limits. The Settings page then shows as read-only.

If the AI is rate-limited or unreachable, the assistant retries briefly and then answers with the built-in rules, saying why.

## Before you share it on Streamlit Community Cloud

- **Accounts and data are wiped when the app restarts.** Community Cloud's disk is temporary, so everything, including accounts, disappears when the app restarts or goes to sleep. That's fine for trying it out, but for everyday use run it on your own computer or a server with a permanent disk (set `DATABASE_PATH` to a file on that disk).
- **Anyone with the link can create an account.** To limit who can reach it, use the Cloud app's viewer settings.

## Safety rules the assistant follows

- Deleting anything, moving more than two tasks at once, or applying more than three schedule changes waits for **Yes, do it**.
- Dates are never invented: "by Friday" becomes a deadline, while "soon" stays undated.
- Plans list their assumptions, such as "tasks without an estimate count as 30 minutes".
- Plans never schedule onto days that have already passed.

## Tests

```
python -m unittest discover -s tests
```

There are 57 tests. They cover:
- Accounts: sign-up rules, hashing, same message for wrong email or password, lockout, sessions, password change and account deletion.
- Isolation between accounts, including through the AI tools and pending confirmations.
- Moving data over from the single-user version.
- Tasks, projects, goals and search.
- Day and week planning, and the capture parser.
- The confirmation flow, the agent's tool loop, falling back when the AI is unavailable, and provider settings.

## What's in the folder

```
app.py                      the whole app: store, planning, capture, AI providers, agent, interface
requirements.txt            streamlit
tests/test_app.py           the test suite
run.sh / run.command / run.bat
.streamlit/config.toml      theme
.streamlit/secrets.toml.example
```

## Known limitations

- There's no password-reset email, since the app doesn't send email. If someone forgets their password, the person running the app can delete that user's row from the `users` table in `data/planner.db`, which also deletes their data.
- There's no sync with outside calendars; meetings are entered in the app.
- On phones, the menu stays open after you pick a page; tap the arrow to close it.
- Search matches words exactly rather than ranking results.
