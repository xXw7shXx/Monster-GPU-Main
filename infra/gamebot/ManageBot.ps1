$projectDir = $PSScriptRoot
Set-Location $projectDir

function Show-Menu {
    Clear-Host
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "       Telegram GameBot Management        " -ForegroundColor Cyan
    Write-Host "==========================================" -ForegroundColor Cyan
    Write-Host "1. Start All Services (Bot + Admin)"
    Write-Host "2. Stop All Services"
    Write-Host "3. Restart All Services"
    Write-Host "4. Run DB Migration (Fix Schema)"
    Write-Host "5. View Bot Logs"
    Write-Host "6. View Admin Backend Logs"
    Write-Host "7. Exit"
    Write-Host "=========================================="
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Select an option [1-7]"

    switch ($choice) {
        "1" {
            Write-Host "Running DB Check..." -ForegroundColor Yellow
            & ".\venv_new\Scripts\python.exe" fix_db_v2.py
            
            Write-Host "Starting Bot..." -ForegroundColor Yellow
            Start-Process cmd -ArgumentList "/c start `"Telegram Bot`" /min cmd /c `".\venv_new\Scripts\python.exe bot.py > bot_final.log 2>&1`""
            
            Write-Host "Starting Admin Backend..." -ForegroundColor Yellow
            Start-Process cmd -ArgumentList "/c cd super_admin\backend && start `"Admin Backend`" /min cmd /c `"..\..\venv_new\Scripts\python.exe -m uvicorn main:app --port 8080 > ..\..\logs\admin_backend.log 2>&1`""
            
            Write-Host "Services started." -ForegroundColor Green
            pause
        }
        "2" {
            Write-Host "Stopping services..." -ForegroundColor Red
            taskkill /FI "WINDOWTITLE eq Telegram Bot*" /F /T
            taskkill /FI "WINDOWTITLE eq Admin Backend*" /F /T
            Write-Host "Done." -ForegroundColor Green
            pause
        }
        "3" {
            Write-Host "Restarting..." -ForegroundColor Yellow
            taskkill /FI "WINDOWTITLE eq Telegram Bot*" /F /T
            taskkill /FI "WINDOWTITLE eq Admin Backend*" /F /T
            Start-Sleep -Seconds 2
            # Recursively call start logic
            & ".\venv_new\Scripts\python.exe" fix_db_v2.py
            Start-Process cmd -ArgumentList "/c start `"Telegram Bot`" /min cmd /c `".\venv_new\Scripts\python.exe bot.py > bot_final.log 2>&1`""
            Start-Process cmd -ArgumentList "/c cd super_admin\backend && start `"Admin Backend`" /min cmd /c `"..\..\venv_new\Scripts\python.exe -m uvicorn main:app --port 8080 > ..\..\logs\admin_backend.log 2>&1`""
            pause
        }
        "4" {
            Write-Host "Running migration..." -ForegroundColor Yellow
            & ".\venv_new\Scripts\python.exe" fix_db_v2.py
            pause
        }
        "5" {
            Get-Content bot_final.log -Wait -Tail 20
        }
        "6" {
            if (Test-Path logs\admin_backend.log) {
                Get-Content logs\admin_backend.log -Wait -Tail 20
            } else {
                Write-Host "Log file not found." -ForegroundColor Red
                pause
            }
        }
        "7" {
            exit
        }
    }
}
