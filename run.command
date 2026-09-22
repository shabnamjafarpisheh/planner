#!/usr/bin/env bash
# Double-click (macOS: run.command) or run ./run.sh
set -e
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "Python isn't installed. Get Python 3.10 or newer from https://www.python.org/downloads/"
  read -r -p "Press Enter to close." _ || true; exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python $("$PY" -V) is too old. Version 3.10 or newer is needed."
  read -r -p "Press Enter to close." _ || true; exit 1
fi
if [ ! -d .venv ]; then
  echo "First run: setting things up (about a minute)…"
  "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python -m streamlit run app.py
