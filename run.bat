@echo off
REM Culture Connect - one-click local run (Windows). Keeps the window open if anything fails.
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if not errorlevel 1 (
  echo.
  echo Port 8000 is already in use - Culture Connect ^(or another app^) is probably already running.
  echo Open http://localhost:8000 in your browser, or close the other server window and run this file again.
  goto :fail
)

if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv || goto :fail
)
call .venv\Scripts\activate.bat || goto :fail
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :fail
echo.
echo Checking Qloo connectivity...
python scripts\qloo_smoke_test.py
echo.
echo Open http://localhost:8000 in your browser  (Ctrl+C to stop)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
echo.
echo Server stopped. If it stopped by itself, copy the messages above and share them.
pause
goto :eof

:fail
echo.
echo *** Culture Connect did not start. Copy the messages above and share them. ***
pause
exit /b 1
