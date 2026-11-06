@echo off
title Connect Google Account - JobApply Mailer
cd /d "%~dp0"

echo =======================================================
echo     JobApply Mailer - Connect Google Account
echo =======================================================
echo.
.\venv\Scripts\python.exe authenticate_google.py
echo.
pause
