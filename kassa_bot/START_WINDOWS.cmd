@echo off
REM ============================================================
REM  Kassa bot - Windows uchun ishga tushirish. Ikki marta bosing.
REM  Docker Desktop bo'lsa - Docker orqali, bo'lmasa - Python 3.12
REM  orqali (PostgreSQL avtomatik, alohida o'rnatish shart emas).
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title Kassa bot

if exist ".env" goto env_ok
echo.
echo === Birinchi sozlash ===
set /p BOT_TOKEN_IN=Bot tokenini kiriting [@BotFather]: 
set /p ADMIN_ID_IN=Admin Telegram ID [@userinfobot]: 
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = Get-Content -Raw -Encoding UTF8 '.env.example';" ^
  "$t = $t -replace '(?m)^BOT_TOKEN=.*$', ('BOT_TOKEN=' + $env:BOT_TOKEN_IN.Trim());" ^
  "$t = $t -replace '(?m)^ADMIN_IDS=.*$', ('ADMIN_IDS=' + $env:ADMIN_ID_IN.Trim() + ':superadmin');" ^
  "$t = $t -replace '(?m)^BOT_USERNAME=.*$', 'BOT_USERNAME=';" ^
  "$t = $t -replace '(?m)^MOBCASH_ENABLED=.*$', 'MOBCASH_ENABLED=true';" ^
  "[IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $t, (New-Object Text.UTF8Encoding $false))"
if errorlevel 1 goto env_fail
echo [OK] .env yaratildi. Keyin o'zgartirish uchun: notepad .env
:env_ok

REM ------------------------------------------------ Docker bormi?
where docker >nul 2>nul
if errorlevel 1 goto python_mode
docker info >nul 2>nul
if errorlevel 1 goto python_mode

echo.
echo === Docker orqali ishga tushirilmoqda - birinchi marta 3-10 daqiqa ===
docker compose up -d --build
if errorlevel 1 goto fail
echo.
echo [OK] Bot ishga tushdi! Telegramda botga /admin yozing.
echo      To'xtatish: STOP_WINDOWS.cmd     Loglar shu oynada, chiqish: Ctrl+C
echo.
docker compose logs -f --tail 50 bot worker
goto end

REM ------------------------------------------------ Python 3.12 rejimi
:python_mode
echo.
echo Docker topilmadi - Python rejimida ishga tushiramiz.
set "PY="
py -3.12 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3.12"
if defined PY goto have_py
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto have_py

echo.
echo === Python 3.12 o'rnatilmoqda - winget, bir necha daqiqa ===
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
py -3.12 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3.12"
if defined PY goto have_py
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto have_py
echo.
echo [X] Python 3.12 topilmadi. Qo'lda o'rnating - "Add python.exe to PATH" ni belgilang:
echo     https://www.python.org/downloads/release/python-3129/
echo     So'ng bu faylni qayta ishga tushiring.
goto fail

:have_py
if exist ".venv312\installed.ok" goto run_py
echo.
echo === Kutubxonalar o'rnatilmoqda - faqat birinchi marta, 2-5 daqiqa ===
if not exist ".venv312\Scripts\python.exe" %PY% -m venv .venv312
if errorlevel 1 goto fail
".venv312\Scripts\python.exe" -m pip install --upgrade pip
".venv312\Scripts\python.exe" -m pip install -e . pgserver fakeredis
if errorlevel 1 goto fail
echo ok> ".venv312\installed.ok"

:run_py
echo.
echo === Bot ishga tushmoqda. Bu oynani yopmang! To'xtatish: Ctrl+C ===
echo.
".venv312\Scripts\python.exe" scripts\windows_local.py
goto end

:env_fail
echo [X] .env yaratib bo'lmadi.
:fail
echo.
echo [X] Xatolik. Yuqoridagi xabarni rasmga olib yuboring.
:end
pause
