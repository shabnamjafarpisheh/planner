# Planner (Streamlit edition)

An AI note and planning assistant. Type whatever is on your mind; it becomes tasks, notes, projects and goals, and the assistant builds a realistic plan for your day and week.

This is the Python/Streamlit version of the app. It has the same planner, capture parser, agent tools, safety rules and free AI options as the Node version, with a Streamlit interface.

## Run it

**Easiest:** double-click **run.bat** (Windows) or **run.command** (macOS), or run **./run.sh** (Linux). The first run sets up a private Python environment and installs Streamlit (about a minute); after that it starts straight away and opens your browser.

**By hand:**

```
pip install -r requirements.txt
streamlit run app.py
```

You need **Python 3.10 or newer** ([python.org](https://www.python.org/downloads/); on Windows tick "Add python.exe to PATH" during setup). The only package is `streamlit`; everything else uses the standard library, including the AI connections.

Your data is saved in `data/planner.db` (a SQLite file) next to the app.

## Turn the AI on, for free

The app works without any AI: capture, plan my day or week, overdue checks, search and "move unfinished tasks to tomorrow" all run on built-in rules. For full natural-language help, open **Settings → AI assistant**, pick a provider, paste a key and press **Test connection**.

| Provider | Cost | Key | Notes |
|---|---|---|---|
| **Google Gemini** (recommended) | Free tier, no card | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Generous per-minute allowance, so multi-step requests run smoothly. Free-tier prompts may be used by Google to improve its products. |
| **Groq** | Free tier, no card | [console.groq.com/keys](https://console.groq.com/keys) | Very fast; the small free per-minute token allowance can throttle long requests. |
| **Ollama** | Free, offline | none | Runs on your own computer: install [Ollama](https://ollama.com), then `ollama pull llama3.1`. Small models handle multi-step requests less reliably. Doesn't work on Streamlit Cloud. |
| **Other OpenAI-compatible** | varies | varies | OpenRouter, LM Studio and similar. Enter the URL and model. |
| **Anthropic Claude** | Paid | [console.anthropic.com](https://console.anthropic.com/) | Best quality. |

Free tiers and model names change often. If a model stops working you'll see a clear message and can change the model name in Settings.

If the AI is rate-limited or unreachable, the assistant retries for a few seconds and then answers with the built-in rules, telling you why, instead of failing.

## Putting it on Streamlit Community Cloud

1. Put `app.py` and `requirements.txt` in a GitHub repository, at the top level. Uploading the whole folder also works; the `.gitignore` keeps your data and secrets out.
2. On [share.streamlit.io](https://share.streamlit.io), create an app from the repo with `app.py` as the main file.
3. In the app's **Settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example` with your key filled in.

If you see `ModuleNotFoundError`, an older version of the app is still in the repository. Replace `app.py` with this one; it doesn't import anything outside itself except Streamlit.

Two things to know before you do this:

- **Data doesn't survive restarts there.** Community Cloud's disk is temporary, so `data/planner.db` is wiped whenever the app restarts or goes to sleep. Use it for trying things out, or run locally for real use.
- **Anyone with the link can use it.** The app is single-user with no login. In the Cloud app settings, restrict who can view it, and put the key in Secrets rather than typing it into the Settings page.

## Settings you can put in secrets or the environment

All optional. Values in `.streamlit/secrets.toml` or environment variables take priority over the Settings page, which then shows as read-only.

| Name | Purpose |
|---|---|
| `AI_PROVIDER` | `none`, `gemini`, `groq`, `ollama`, `openai_compatible` or `anthropic` |
| `AI_API_KEY` | Key for that provider |
| `AI_MODEL` | Model name; defaults per provider (e.g. `gemini-2.5-flash`) |
| `AI_BASE_URL` | Only for `openai_compatible` or a custom address |
| `ANTHROPIC_API_KEY` | Shortcut that selects Anthropic |
| `DATABASE_PATH` | Where the SQLite file lives (default `data/planner.db`) |

## What's inside

```
app.py                      the whole app in one file (see below)
requirements.txt            just streamlit
tests/test_app.py           35 tests (standard-library unittest)
run.sh / run.command / run.bat   one-click launchers
.streamlit/config.toml      theme and settings
.streamlit/secrets.toml.example
```

**Only `app.py` and `requirements.txt` are needed to run it**, so uploading those two files to GitHub is enough for Streamlit Cloud. Everything else is optional.

`app.py` is organised in sections, in the same layers as the Node version: store (database and rules) → planning → capture → providers (AI connections) → agent (tools, confirmations, model loop) → Streamlit interface. The model can only act through tools, never SQL. Importing the file doesn't start the interface, which is how the tests use it.

**Pages:** Today (capture, plan my day with a time limit, overdue, due, planned, carried over, deadlines), Inbox (with a suggested action per item), Tasks (filters, inline edit), Calendar (week view, plan my week with Apply, weekly review, events), Notes (editor, extract tasks), Projects and Goals (progress bars), Search (includes everything inside a matching project), Settings (AI provider, working hours, remembered facts, recent activity).

**Safety rules:** deleting anything, moving more than two tasks at once, or applying more than three schedule changes waits for you to press **Confirm** in the sidebar. Dates are never invented; vague wording like "soon" leaves the date empty. Plans list their assumptions separately.

**Realistic planning:** only about 65% of free time is planned, tasks get 10-minute buffers, a 15-minute break follows long stretches of work, meetings are planned around, tasks without estimates count as 30 minutes (and the plan says so), and the week planner spreads non-urgent work toward deadlines instead of piling it onto today.

## Tests

```
python -m unittest discover -s tests
```

The tests cover task validation and defaults, dependency loops, all-or-nothing bulk moves, subtasks, projects keeping their work when deleted, goal breakdown and progress, search, day and week planning, the capture parser (including the main example, with no invented deadlines), the confirmation flow, the agent tool loop, fallback when the AI is unavailable, and provider configuration and format conversion.

## Differences from the Node version

- Search uses simple text matching rather than SQLite full-text search, so it doesn't rank results or match word stems.
- Tags are stored as a comma-separated list on each task and note rather than in their own table.
- The interface follows Streamlit's layout: pages in the sidebar, the assistant underneath, and a page reload after each action.
- There's no access token; on a shared server, use Streamlit Cloud's viewer restrictions or put it behind your own login.

## Known limitations

- One user per database.
- No sync with outside calendars; events are entered in the app.
- Basic mode understands a fixed set of requests; free-form conversation needs a provider.
- A key typed into the Settings page is stored as plain text in your local database file; keep that file private.
