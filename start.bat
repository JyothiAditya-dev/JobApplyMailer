@echo off
title JobApply Mailer
cd /d "%~dp0"

echo =======================================================
echo          JobApply Mailer - Launching App
echo =======================================================
echo.
echo Connected Google Account: Official Gmail API (HTTPS/443)
echo Dashboard URL: http://127.0.0.1:8000
echo.
echo Opening browser...
start http://127.0.0.1:8000
echo.
echo Starting FastAPI server (Press Ctrl+C to stop)...
echo.
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
