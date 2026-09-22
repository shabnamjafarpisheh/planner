@echo off
REM Double-click this file to start Planner on Windows.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python isn't installed. Get Python 3.10 or newer from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH".
  pause
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Your Python is too old. Version 3.10 or newer is needed.
  pause
  exit /b 1
)
if not exist .venv (
  echo First run: setting things up, about a minute...
  python -m venv .venv
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
.venv\Scripts\python -m streamlit run app.py
pause
