@echo off
set PROJECT_DIR=%~dp0
cd /d %PROJECT_DIR%

:menu
cls
echo ==========================================
echo       Telegram GameBot Management (v2.5)
echo ==========================================
echo 1. Start All Services (Bot + Admin + Maint)
echo 2. Stop All Services
echo 3. Restart All Services
echo 4. View Bot Status (Live Logs)
echo 5. View Admin Backend Logs
echo 6. View Maintenance Logs
echo 7. Exit
echo ==========================================
set /p choice="Select an option [1-7]: "

if "%choice%"=="1" goto start
if "%choice%"=="2" goto stop
if "%choice%"=="3" goto restart
if "%choice%"=="4" goto logs_bot
if "%choice%"=="5" goto logs_admin
if "%choice%"=="6" goto logs_maint
if "%choice%"=="7" goto exit
goto menu

:start
echo [SRE] Initializing 2.5-Stable Environment...
set PYTHONPATH=.

:: Start Bot Service
echo [SRE] Starting Telegram Bot + Integrated API (Port 8000)...
start "Telegram Bot" /min cmd /c ".\venv_new\Scripts\python.exe bot.py > logs\bot_service.log 2>&1"

:: Start Admin Backend
echo [SRE] Starting Admin Hub (Port 8080)...
set PYTHONPATH=../../
start "Admin Backend" /min cmd /c "cd super_admin\backend && ..\..\venv_new\Scripts\python.exe -m uvicorn main:app --port 8080 > ..\..\logs\admin_backend.log 2>&1"
set PYTHONPATH=.

:: Start Maintenance Service
echo [SRE] Starting Maintenance Loop...
start "Maintenance Service" /min cmd /c ".\venv_new\Scripts\python.exe maintenance_service.py > logs\maintenance_service.log 2>&1"

echo [OK] All services initiated.
timeout /t 3
goto menu

:stop
echo [SRE] Terminating all Python processes...
taskkill /IM python.exe /F
echo [OK] Services stopped.
pause
goto menu

:restart
call :stop
timeout /t 2 /nobreak
goto start

:logs_bot
powershell -Command "if (Test-Path logs\bot_service.log) { Get-Content logs\bot_service.log -Wait -Tail 20 } else { echo 'Log not found.' }"
goto menu

:logs_admin
powershell -Command "if (Test-Path logs\admin_backend.log) { Get-Content logs\admin_backend.log -Wait -Tail 20 } else { echo 'Log not found.' }"
goto menu

:logs_maint
powershell -Command "if (Test-Path logs\maintenance_service.log) { Get-Content logs\maintenance_service.log -Wait -Tail 20 } else { echo 'Log not found.' }"
goto menu

:exit
exit
