@echo off
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js 24 yoki undan yangi versiyani o'rnating.
  pause
  exit /b 1
)
echo Taksopark serveri ishga tushmoqda...
echo Brauzerda http://localhost:4317 ni oching.
node server.mjs
pause
