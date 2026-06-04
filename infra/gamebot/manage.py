import os
import subprocess
import sys
import signal
import time
import psutil
from pathlib import Path

# Configuration
BASE_DIR = Path(__file__).resolve().parent
PID_DIR = BASE_DIR / "pids"
LOG_DIR = BASE_DIR / "logs"
PID_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

PYTHON_EXE = sys.executable

SERVICES = {
    "bot": {
        "command": [PYTHON_EXE, "bot.py"],
        "log": LOG_DIR / "bot_service.log",
        "pid": PID_DIR / "bot.pid"
    },
    "maintenance": {
        "command": [PYTHON_EXE, "maintenance_service.py"],
        "log": LOG_DIR / "maintenance_service.log",
        "pid": PID_DIR / "maintenance.pid"
    },
    "dashboard": {
        "command": [PYTHON_EXE, "-m", "uvicorn", "super_admin.backend.main:app", "--port", "8080"],
        "log": LOG_DIR / "dashboard_service.log",
        "pid": PID_DIR / "dashboard.pid"
    }
}

def get_pid(service_name):
    pid_file = SERVICES[service_name]["pid"]
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if psutil.pid_exists(pid):
                return pid
        except ValueError:
            pass
    return None

def start_service(name):
    if get_pid(name):
        print(f"[-] Service '{name}' is already running.")
        return

    print(f"[+] Starting service '{name}'...")
    cfg = SERVICES[name]
    log_file = open(cfg["log"], "a")
    
    # Use subprocess.Popen to run in background
    process = subprocess.Popen(
        cfg["command"],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )
    
    cfg["pid"].write_text(str(process.pid))
    print(f"[OK] Started '{name}' (PID: {process.pid})")

def stop_service(name):
    pid = get_pid(name)
    if not pid:
        print(f"[-] Service '{name}' is not running.")
        return

    print(f"[!] Stopping service '{name}' (PID: {pid})...")
    try:
        proc = psutil.Process(pid)
        # Kill children first
        for child in proc.children(recursive=True):
            child.terminate()
        proc.terminate()
        
        # Wait for shutdown
        try:
            proc.wait(timeout=5)
        except psutil.TimeoutExpired:
            proc.kill()
            
        SERVICES[name]["pid"].unlink(missing_ok=True)
        print(f"[OK] Stopped '{name}'.")
    except psutil.NoSuchProcess:
        print(f"[!] Process {pid} not found.")
        SERVICES[name]["pid"].unlink(missing_ok=True)

def status():
    print(f"{'SERVICE':<15} {'STATUS':<10} {'PID':<10} {'UPTIME':<15}")
    print("-" * 50)
    for name in SERVICES:
        pid = get_pid(name)
        if pid:
            p = psutil.Process(pid)
            uptime_seconds = int(time.time() - p.create_time())
            uptime = time.strftime("%H:%M:%S", time.gmtime(uptime_seconds))
            print(f"{name:<15} {'RUNNING':<10} {pid:<10} {uptime:<15}")
        else:
            print(f"{name:<15} {'STOPPED':<10} {'-':<10} {'-':<15}")

def tail_logs(name, lines=20):
    log_path = SERVICES[name]["log"]
    if not log_path.exists():
        print(f"[-] Log file for '{name}' not found.")
        return

    print(f"--- Last {lines} lines of {name} logs ---")
    with open(log_path, "r") as f:
        content = f.readlines()
        for line in content[-lines:]:
            print(line.strip())

def main():
    if len(sys.argv) < 2:
        print("Usage: python manage.py [start|stop|restart|status|logs] [service_name|all]")
        return

    cmd = sys.argv[1].lower()
    target = sys.argv[2].lower() if len(sys.argv) > 2 else "all"

    if cmd == "start":
        if target == "all":
            for s in SERVICES: start_service(s)
        else:
            if target in SERVICES: start_service(target)
            else: print(f"Unknown service: {target}")

    elif cmd == "stop":
        if target == "all":
            for s in SERVICES: stop_service(s)
        else:
            if target in SERVICES: stop_service(target)
            else: print(f"Unknown service: {target}")

    elif cmd == "restart":
        if target == "all":
            for s in SERVICES:
                stop_service(s)
                start_service(s)
        else:
            if target in SERVICES:
                stop_service(target)
                start_service(target)
            else: print(f"Unknown service: {target}")

    elif cmd == "status":
        status()

    elif cmd == "logs":
        if target in SERVICES:
            tail_logs(target)
        else:
            print("Please specify a service: bot, maintenance, or dashboard")

if __name__ == "__main__":
    main()
