@echo off
title Push to GitHub - JobApply Mailer
cd /d "%~dp0"

echo =======================================================
echo     Pushing code to GitHub: JyothiAditya-dev/JobApplyMailer
echo =======================================================
echo.
git branch -M main
git push -u origin main
echo.
echo =======================================================
echo If you see 'Everything up-to-date' or branch created, 
echo your code is pushed! Now refresh your GitHub page.
echo =======================================================
pause
