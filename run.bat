@echo off
REM Culture Connect - one-click local run (Windows)
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
echo.
echo Checking Qloo connectivity...
python scripts\qloo_smoke_test.py
echo.
echo Open http://localhost:8000 in your browser
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
