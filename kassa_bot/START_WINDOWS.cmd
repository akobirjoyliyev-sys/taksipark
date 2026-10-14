@echo off
REM Kassa bot - Windows uchun ishga tushirish (Docker Desktop kerak).
REM Ikki marta bosing. Birinchi marta token va admin ID so'raladi.
chcp 65001 >nul
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo.
  echo [X] Docker topilmadi. Docker Desktop ni o'rnating va ishga tushiring:
  echo     https://www.docker.com/products/docker-desktop/
  echo.
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo.
  echo [X] Docker Desktop ishlamayapti. Uni oching, "Engine running" bo'lishini kuting
  echo     va bu faylni qayta ishga tushiring.
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  echo.
  echo === Birinchi sozlash ===
  set /p BOT_TOKEN_IN=Bot tokenini kiriting ^(@BotFather^): 
  set /p ADMIN_ID_IN=Admin Telegram ID ^(@userinfobot^): 
  call :write_env
  if errorlevel 1 (
    echo [X] .env yaratib bo'lmadi.
    pause
    exit /b 1
  )
  echo [OK] .env yaratildi.
)

echo.
echo === Bot ishga tushirilmoqda (birinchi marta 3-10 daqiqa) ===
docker compose up -d --build
if errorlevel 1 (
  echo [X] Xatolik. Yuqoridagi xabarni o'qing.
  pause
  exit /b 1
)

echo.
echo [OK] Bot ishga tushdi! Telegramda botga /admin yozing.
echo      To'xtatish: STOP_WINDOWS.cmd   Loglar: shu oynada (chiqish - Ctrl+C)
echo.
docker compose logs -f --tail 50 bot worker
exit /b 0

:write_env
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t = Get-Content -Raw -Encoding UTF8 '.env.example';" ^
  "$t = $t -replace '(?m)^BOT_TOKEN=.*$', ('BOT_TOKEN=' + $env:BOT_TOKEN_IN.Trim());" ^
  "$t = $t -replace '(?m)^ADMIN_IDS=.*$', ('ADMIN_IDS=' + $env:ADMIN_ID_IN.Trim() + ':superadmin');" ^
  "$t = $t -replace '(?m)^BOT_USERNAME=.*$', 'BOT_USERNAME=';" ^
  "$t = $t -replace '(?m)^MOBCASH_ENABLED=.*$', 'MOBCASH_ENABLED=true';" ^
  "[IO.File]::WriteAllText((Join-Path (Get-Location) '.env'), $t, (New-Object Text.UTF8Encoding $false))"
exit /b %errorlevel%
