@echo off
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 goto nodocker
docker compose stop
echo Bot to'xtatildi. Qayta yoqish: START_WINDOWS.cmd
pause
exit /b 0
:nodocker
echo Python rejimida bot START_WINDOWS oynasida ishlaydi - o'sha oynada Ctrl+C bosing yoki oynani yoping.
pause
