#!/usr/bin/env python3
"""W7SH production server agent v2 with security audit fixes."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import random
import re
import shlex
import socket
import ssl
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MEMORY_DIR = Path(os.environ.get("W7SH_SHARED_MEMORY", "/srv/w7sh/ai-agent-memory"))
LOG_DIR = Path(os.environ.get("W7SH_AGENT_LOG_DIR", "/var/log/w7sh-agent"))

_interval_raw = int(os.environ.get("W7SH_AGENT_INTERVAL_SECONDS", "900"))
if _interval_raw <= 0 or _interval_raw > 86400:
    raise ValueError(f"W7SH_AGENT_INTERVAL_SECONDS must be in 1..86400, got {_interval_raw}")
INTERVAL_SECONDS = _interval_raw

REPORT_PREFIX = "server_agent_watch"
BUG_FEATURE_BACKLOG = "server_agent_bug_feature_backlog.md"
BACKLOG_JSON = "server_agent_backlog.json"
SNAPSHOT_JSON = "server_agent_snapshot.json"
APPROVAL_QUEUE_JSON = "server_agent_approval_queue.json"
HEARTBEAT_JSON = "server_agent_heartbeat.json"
SCHEMA_VERSION = 1
ACTIVE_BACKLOG_STATES = {"open", "acknowledged", "in_progress", "blocked", "deferred"}
TERMINAL_BACKLOG_STATES = {"fixed", "verified", "closed"}
SAFE_STATUS_FILE = Path(os.environ.get("W7SH_SAFE_STATUS_JSON", "/var/lib/w7sh-agent/safe_status.json"))
REPO_CANDIDATES = [
    Path("/tmp/github-export"),
    Path("/srv/w7sh/repo-snapshots"),
    Path("/srv/w7sh/repos"),
    Path("/srv/w7sh"),
]
WATCHED_SYSTEMD_UNITS = [
    "w7sh-server-agent.service",
    "docker.service",
]
WATCHED_CONTAINERS = [
    "telegram_gamebot",
    "movie_bot",
    "super_admin_backend",
    "super_admin_frontend",
    "w7sh_website",
    "w7sh_n8n",
    "postgres_db",
]
SAFE_HTTP_HEALTH_ENDPOINTS = {
    "website": "https://w7sh.us/health",
    "admin": "https://admin.w7sh.us/health",
    "n8n": "https://auto.w7sh.us/healthz",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization|database_url)\s*[:=]\s*[^,\s]+"),
    re.compile(r"(?i)(Bearer)\s+[A-Za-z0-9._\-]+"),
]
SECRET_KEY_PATTERN = re.compile(r"(?i)^(.*\b)?(api_key|token|secret|password|passwd|authorization|database_url)(\b.*)?$")

BUG_MARKERS = [
    (r"\bTraceback\b", "error traces", "runtime exception escaped a handler or worker", "high"),
    (r"\bBadRequest\b", "Telegram BadRequest", "malformed media/message/callback response", "high"),
    (r"\bdatabase is locked\b", "DB lock pattern", "SQLite or long transaction contention", "high"),
    (r"\bIntegrityError\b", "DB integrity error", "duplicate key or constraint mismatch", "high"),
    (r"\brollback\b", "rollback marker", "transaction failure or retry path", "medium"),
    (r"\bduplicate key\b", "duplicate key pattern", "identity/upsert regression", "high"),
    (r"\bCallbackQuery\b", "callback activity/error pattern", "callback routing or malformed callback data", "medium"),
    (r"\bNo handler\b", "missing handler", "command/callback registration gap", "medium"),
    (r"\bempty response\b", "empty response marker", "handler returned without user-visible reply", "medium"),
    (r"\blanguage[_-]?routing\b", "language-routing marker", "language selection or localization mismatch", "medium"),
    (r"\bsync failure\b", "sync failure", "background sync adapter or DB failure", "medium"),
]
BUG_SIGNAL_RULES = [
    ("Traceback", "Investigate runtime tracebacks even if the service is technically up."),
    ("BadRequest", "Investigate Telegram response formatting or media fallback failures."),
    ("database is locked", "Investigate DB lock contention and make handlers fail open where safe."),
    ("IntegrityError", "Investigate uniqueness/upsert regressions before they affect chat paths."),
    ("CallbackQuery", "Review callback routing for malformed or stale buttons."),
    ("failed", "Investigate failed service state reported by systemd."),
    ("unavailable or not permitted", "Verify whether the safe server-agent user needs a read-only permission grant or whether the dependency is intentionally unavailable."),
    ("not visible to service environment", "Configure missing runtime environment for the service without writing secrets to disk."),
    ("journal read unavailable", "Grant safe journal read access or add a redacted log export for observability."),
    ("No readable git workspaces found", "Expose a read-only repo snapshot path for deployed commit and hygiene checks."),
    ("Runtime app directories are not readable", "Expose sanitized read-only health metadata for runtime freshness checks."),
    ("dirty", "Review dirty repo state before future deploys or automation."),
]
FEATURE_SIGNAL_RULES = [
    ("No training worker control action was attempted", "Add a safe read-only training status endpoint before enabling any training controls."),
    ("No matching W7SH service names found", "Standardize W7SH service naming or add an allowlist file for service discovery."),
    ("No warning-or-higher journal entries", "Keep log triage baseline active and add app-level structured health events."),
    ("docker: unavailable or not permitted", "Add a least-privilege container health summary if Docker visibility is needed."),
    ("pg_isready: unavailable or not permitted", "Add a sanitized DB health check command or local health endpoint."),
]


def now() -> dt.datetime:
    """Return current UTC datetime."""
    return dt.datetime.now(dt.timezone.utc)


def stamp() -> str:
    """Return ISO-8601-ish compact timestamp."""
    return now().strftime("%Y%m%dT%H%M%SZ")


def redact(value: str) -> str:
    """Redact secrets from a string using SECRET_PATTERNS."""
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(0).split(match.group(1))[0] + match.group(1) + "=<redacted>", redacted)
    return redacted


def redact_obj(value: Any) -> Any:
    """Recursively redact secrets from dicts, lists, and strings.

    Dict keys matching secret patterns unconditionally redact their values.
    """
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            str_key = str(key)
            if SECRET_KEY_PATTERN.search(str_key):
                result[str_key] = "<redacted>"
            else:
                result[str_key] = redact_obj(item)
        return result
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def stable_id(*parts: str) -> str:
    """Compute a short stable SHA-256 ID from ordered parts."""
    raw = "|".join(part.strip().lower() for part in parts if part)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def write_json(path: Path, payload: dict) -> None:
    """Atomically write JSON using a randomized temporary file and os.replace."""
    tmp = path.parent / f"{path.name}.{os.getpid()}.{random.randrange(10**9)}.tmp"
    tmp.write_text(json.dumps(redact_obj(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text using a randomized temporary file and os.replace."""
    tmp = path.parent / f"{path.name}.{os.getpid()}.{random.randrange(10**9)}.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def read_json(path: Path, fallback: Any) -> Any:
    """Read JSON from path, returning fallback on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def safe_status_payload() -> dict:
    """Load and redact safe-status JSON from known locations.

    Rejects symlinks.
    """
    candidates = [
        SAFE_STATUS_FILE,
        MEMORY_DIR / "runtime" / "safe_status.json",
        MEMORY_DIR / "reports" / "safe_status.json",
    ]
    for path in candidates:
        try:
            if path.exists() and path.is_file() and os.access(path, os.R_OK) and not path.is_symlink():
                payload = json.loads(path.read_text(encoding="utf-8"))
                return redact_obj(payload) if isinstance(payload, dict) else {}
        except Exception:
            continue
    return {}


def safe_run(command: list[str], timeout: int = 20) -> tuple[int, str, str]:
    """Run a subprocess safely, capturing bytes and decoding with replacement.

    Returns (returncode, stdout, stderr).
    """
    try:
        completed = subprocess.run(command, check=False, capture_output=True, timeout=timeout)
        stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        return completed.returncode, redact(stdout.strip()), redact(stderr.strip())
    except FileNotFoundError:
        return 127, "", f"missing command: {shlex.join(command)}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {shlex.join(command)}"
    except Exception as exc:
        return 1, "", f"{exc.__class__.__name__}: {exc}"


def probe_cert_expiry(hostname: str | None, port: int = 443, timeout: int = 5) -> dict:
    """Probe TLS certificate expiry for a hostname."""
    if not hostname:
        return {"error": "no hostname"}
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                not_after = cert.get("notAfter")
                if not_after:
                    expiry_ts = ssl.cert_time_to_seconds(not_after)
                    days_remaining = int((expiry_ts - time.time()) / 86400)
                    return {
                        "hostname": hostname,
                        "expiry_iso": dt.datetime.fromtimestamp(expiry_ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "days_remaining": days_remaining,
                        "ok": days_remaining > 14,
                    }
        return {"error": "missing notAfter"}
    except Exception as exc:
        return {"error": str(exc)}


def safe_http_probe(name: str, url: str, timeout: int = 5) -> dict:
    """Probe an HTTP(S) endpoint and record latency (monotonic) plus TLS cert info."""
    started = time.monotonic()
    parsed = urllib.parse.urlparse(url)
    cert_info: dict[str, Any] = {}
    if parsed.hostname and url.startswith("https://"):
        cert_info = probe_cert_expiry(parsed.hostname, parsed.port or 443, timeout=timeout)
    request = urllib.request.Request(url, headers={"User-Agent": "w7sh-server-agent/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
        status = getattr(response, "status", None)
        ok = 200 <= int(status or 0) < 400
        return {
            "name": name,
            "url": url,
            "reachable": ok,
            "status_code": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "body_preview": redact(body[:160]),
            "source": "least-privilege-http",
            "cert": cert_info,
        }
    except urllib.error.HTTPError as exc:
        return {
            "name": name,
            "url": url,
            "reachable": False,
            "status_code": exc.code,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "body_preview": redact(exc.read(4096).decode("utf-8", errors="replace")[:160]),
            "source": "least-privilege-http",
            "cert": cert_info,
        }
    except Exception as exc:
        return {
            "name": name,
            "url": url,
            "reachable": False,
            "status_code": None,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "error": exc.__class__.__name__,
            "source": "least-privilege-http",
            "cert": cert_info,
        }


def ensure_memory() -> None:
    """Create required directories with secure permissions and seed memory files."""
    for path in [MEMORY_DIR, MEMORY_DIR / "reports", MEMORY_DIR / "runbooks", MEMORY_DIR / "queue", MEMORY_DIR / "runtime", LOG_DIR]:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    for name in ["activity_log.md", "decisions.md", "project_inventory.md"]:
        target = MEMORY_DIR / name
        if not target.exists():
            target.write_text(f"# {name}\n\nCreated by W7SH server agent on {now().isoformat()}.\n", encoding="utf-8")
    approval_queue = MEMORY_DIR / "queue" / APPROVAL_QUEUE_JSON
    if not approval_queue.exists():
        write_json(approval_queue, {
            "schema_version": SCHEMA_VERSION,
            "updated_at": now().isoformat(),
            "enabled": False,
            "items": [],
            "safety": {
                "dangerous_operations_enabled": False,
                "executes_production_mutations": False,
                "note": "Queue is read/write state only until a dedicated gated executor is enabled.",
            },
        })


def read_memory_context() -> dict[str, str]:
    """Read sampled context from memory files."""
    context: dict[str, str] = {}
    for name in ["activity_log.md", "decisions.md", "project_inventory.md"]:
        path = MEMORY_DIR / name
        try:
            context[name] = path.read_text(encoding="utf-8", errors="replace")[-6000:]
        except Exception as exc:
            context[name] = f"unreadable:{exc.__class__.__name__}"
    report_files = sorted((MEMORY_DIR / "reports").glob("*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[:5]
    context["latest_reports"] = "\n".join(path.name for path in report_files)
    return context


def service_health() -> list[str]:
    """Collect systemd, Docker, pg_isready, and HTTPS health lines."""
    lines = ["## Health Watcher"]
    code, output, _err = safe_run(["systemctl", "list-units", "--type=service", "--state=running,failed", "--no-pager", "--plain", "--full"], timeout=20)
    if code == 0:
        interesting = [line for line in output.splitlines() if re.search(r"\b(?:w7sh|gamebot|moviebot|admin|docker|postgres|nginx|caddy)\b", line, re.I)]
        lines.extend(f"- {line}" for line in interesting[:40])
        if not interesting:
            lines.append("- No matching W7SH service names found in visible systemd unit list.")
    else:
        lines.append(f"- systemctl unavailable: {output}")

    for command in (["pg_isready"], ["docker", "ps", "--format", "{{.Names}} {{.Status}}"]):
        code, output, _err = safe_run(command, timeout=10)
        label = command[0]
        if code == 0 and output:
            lines.append(f"- {label}: available")
            for line in output.splitlines()[:20]:
                lines.append(f"  - {line}")
        else:
            lines.append(f"- {label}: unavailable or not permitted")
    for name, url in SAFE_HTTP_HEALTH_ENDPOINTS.items():
        result = safe_http_probe(name, url)
        if result["reachable"]:
            lines.append(f"- {name} HTTPS health: reachable status={result['status_code']} latency_ms={result['latency_ms']}")
        else:
            detail = result.get("error") or result.get("status_code") or "unavailable"
            lines.append(f"- {name} HTTPS health: unavailable detail={detail}")
    return lines


def service_health_summary() -> dict:
    """Return structured service health summary."""
    safe_status = safe_status_payload()
    units: dict[str, dict[str, str | int | None]] = {}
    for unit in WATCHED_SYSTEMD_UNITS:
        code, output, _err = safe_run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts", "-p", "Result"], timeout=8)
        data: dict[str, str | int | None] = {"name": unit, "visible": code == 0}
        for line in output.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                data[key] = int(value) if key == "NRestarts" and value.isdigit() else value
        units[unit] = data

    containers: dict[str, dict[str, str | int | None]] = {}
    collector_containers = safe_status.get("containers") if isinstance(safe_status.get("containers"), dict) else {}
    for container in WATCHED_CONTAINERS:
        code, output, _err = safe_run([
            "docker",
            "inspect",
            "--format",
            "{{.Name}}|{{.RestartCount}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            container,
        ], timeout=12)
        if code == 0 and output:
            line = output.strip()
            name, restart, status, health = (line.split("|") + ["", "", "", ""])[:4]
            containers[name.lstrip("/")] = {
                "name": name.lstrip("/"),
                "visible": True,
                "restart_count": int(restart) if restart.isdigit() else None,
                "status": status or "unknown",
                "health": health or "unknown",
            }
        else:
            collected = collector_containers.get(container, {}) if isinstance(collector_containers, dict) else {}
            containers[container] = {
                "name": container,
                "visible": bool(collected),
                "status": str(collected.get("status", "unavailable")) if isinstance(collected, dict) else "unavailable",
                "health": str(collected.get("health", "unknown")) if isinstance(collected, dict) else "unknown",
                "restart_count": collected.get("restart_count") if isinstance(collected, dict) and isinstance(collected.get("restart_count"), int) else None,
                "source": "safe-status-collector" if collected else "direct-docker-unavailable",
            }

    http_endpoints = {name: safe_http_probe(name, url) for name, url in SAFE_HTTP_HEALTH_ENDPOINTS.items()}
    if isinstance(safe_status.get("http_endpoints"), dict):
        for name, data in safe_status["http_endpoints"].items():
            if isinstance(data, dict):
                http_endpoints[str(name)] = redact_obj(data)

    return {
        "units": units,
        "containers": containers,
        "http_endpoints": http_endpoints,
        "source": "direct-safe-commands-with-collector-fallback",
        "visibility": "direct" if any(item.get("source") != "safe-status-collector" and item.get("visible") for item in containers.values()) else "collector" if any(item.get("visible") for item in containers.values()) else "limited",
    }


def resource_usage_summary() -> dict:
    """Return structured resource usage including disk inodes, swap, and zombies."""
    safe_status = safe_status_payload()
    usage: dict[str, Any] = {"cpu": "unavailable", "memory": "unavailable", "disk": "unavailable", "load": "unavailable", "source": "safe-local-commands"}
    if isinstance(safe_status.get("resources"), dict):
        usage.update(redact_obj(safe_status["resources"]))
        usage["source"] = f"{usage.get('source')}; safe-status-collector"

    code, output, _err = safe_run(["sh", "-c", "awk '{print $1\",""$2\",""$3}' /proc/loadavg"], timeout=5)
    if code == 0 and output:
        usage["load"] = output

    code, output, _err = safe_run(["df", "-h", "/"], timeout=5)
    if code == 0:
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) >= 2:
            parts = re.split(r"\s+", lines[1])
            if len(parts) >= 5:
                usage["disk"] = {"filesystem": parts[0], "size": parts[1], "used": parts[2], "available": parts[3], "use_percent": parts[4]}

    code, output, _err = safe_run(["df", "-i", "/"], timeout=5)
    if code == 0:
        lines = [line for line in output.splitlines() if line.strip()]
        if len(lines) >= 2:
            parts = re.split(r"\s+", lines[1])
            if len(parts) >= 5:
                usage["disk_inodes"] = {"filesystem": parts[0], "total": parts[1], "used": parts[2], "available": parts[3], "use_percent": parts[4]}

    code, output, _err = safe_run(["sh", "-c", "awk '/MemTotal|MemAvailable/ {print $1 $2}' /proc/meminfo"], timeout=5)
    if code == 0 and output:
        values: dict[str, int] = {}
        for line in output.splitlines():
            if line.startswith("MemTotal:"):
                values["total_kb"] = int(line.replace("MemTotal:", ""))
            if line.startswith("MemAvailable:"):
                values["available_kb"] = int(line.replace("MemAvailable:", ""))
        if values.get("total_kb"):
            used = values["total_kb"] - values.get("available_kb", 0)
            usage["memory"] = {"total_kb": values["total_kb"], "available_kb": values.get("available_kb"), "used_percent": round((used / values["total_kb"]) * 100, 2)}

    code, output, _err = safe_run(["sh", "-c", "awk '/SwapTotal|SwapFree/ {print $1 $2}' /proc/meminfo"], timeout=5)
    if code == 0 and output:
        swap_values: dict[str, int] = {}
        for line in output.splitlines():
            if line.startswith("SwapTotal:"):
                swap_values["total_kb"] = int(line.replace("SwapTotal:", ""))
            if line.startswith("SwapFree:"):
                swap_values["free_kb"] = int(line.replace("SwapFree:", ""))
        if swap_values.get("total_kb"):
            used_kb = swap_values["total_kb"] - swap_values.get("free_kb", 0)
            usage["swap"] = {"total_kb": swap_values["total_kb"], "free_kb": swap_values.get("free_kb"), "used_percent": round((used_kb / swap_values["total_kb"]) * 100, 2)}

    code, output, _err = safe_run(["ps", "-p", str(os.getpid()), "-o", "%cpu=,%mem="], timeout=5)
    if code == 0 and output:
        parts = output.strip().split()
        if len(parts) >= 2:
            usage["cpu"] = {"agent_cpu_percent": parts[0], "agent_mem_percent": parts[1]}

    code, output, _err = safe_run(["sh", "-c", "ps aux | awk '$8==\"Z\" {print $0}'"], timeout=5)
    if code == 0:
        zombie_lines = [line for line in output.splitlines() if line.strip()]
        usage["zombies"] = {"count": len(zombie_lines), "processes": zombie_lines[:10]}

    return usage


def restart_count_watch() -> list[str]:
    """Watch systemd units and Docker containers for restarts."""
    lines = ["## Restart / Runtime Watcher"]
    for unit in WATCHED_SYSTEMD_UNITS:
        code, output, _err = safe_run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts", "-p", "Result"], timeout=8)
        if code == 0 and output:
            summary = " ".join(part.strip() for part in output.splitlines() if part.strip())
            lines.append(f"- systemd {unit}: {summary}")
        else:
            lines.append(f"- systemd {unit}: unavailable")

    for container in WATCHED_CONTAINERS:
        code, output, _err = safe_run([
            "docker",
            "inspect",
            "--format",
            "{{.Name}} restart={{.RestartCount}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            container,
        ], timeout=12)
        if code == 0 and output:
            lines.append(f"- container {output.strip().lstrip('/')}")
        else:
            lines.append(f"- container {container}: unavailable or not permitted")
    return lines


def db_health_watch() -> list[str]:
    """Watch database health."""
    lines = ["## DB Health Watcher"]
    code, output, _err = safe_run(["pg_isready"], timeout=10)
    if code == 0:
        lines.append(f"- host PostgreSQL readiness: {output or 'ready'}")
    else:
        lines.append("- host PostgreSQL readiness: unavailable or not ready")
    for target in ["/health", "/ops/freshness"]:
        code, output, _err = safe_run(["curl", "-fsS", "--max-time", "4", f"http://127.0.0.1:8000{target}"], timeout=7)
        if code == 0:
            lines.append(f"- gamebot local {target}: reachable")
        else:
            lines.append(f"- gamebot local {target}: unavailable")
    return lines


def db_health_summary() -> dict:
    """Return structured DB health summary."""
    safe_status = safe_status_payload()
    code, output, _err = safe_run(["pg_isready"], timeout=10)
    endpoints: dict[str, str] = {}
    for target in ["/health", "/ops/freshness"]:
        curl_code, _curl_output, _curl_err = safe_run(["curl", "-fsS", "--max-time", "4", f"http://127.0.0.1:8000{target}"], timeout=7)
        endpoints[target] = "reachable" if curl_code == 0 else "unavailable"
    collector_db = safe_status.get("db_health") if isinstance(safe_status.get("db_health"), dict) else {}
    if code != 0 and collector_db:
        return {
            "postgres": str(collector_db.get("postgres", collector_db.get("status", "unknown"))),
            "postgres_detail": "",
            "gamebot_local_endpoints": endpoints,
            "source": "safe-status-collector",
        }
    return {
        "postgres": "ready" if code == 0 else "unavailable_or_not_ready",
        "postgres_detail": output if code == 0 else "",
        "gamebot_local_endpoints": endpoints,
        "source": "pg_isready",
    }


def freshness_watch() -> list[str]:
    """Check freshness of runtime paths and latest report."""
    lines = ["## Freshness Watcher"]
    candidates = [Path("/root/infra/gamebot"), Path("/root/infra/moviebot"), Path("/srv/w7sh")]
    visible = []
    for path in candidates:
        try:
            if path.exists() and os.access(path, os.R_OK):
                visible.append(path)
        except PermissionError:
            continue
    if not visible:
        lines.append("- Runtime app directories are not readable by the safe agent; using service/log signals only.")
    for path in visible:
        lines.append(f"- readable runtime path: {path}")
    reports = sorted((MEMORY_DIR / "reports").glob("server_agent_watch_*.md"), key=lambda item: item.stat().st_mtime, reverse=True)
    if reports:
        age_seconds = int(time.time() - reports[0].stat().st_mtime)
        lines.append(f"- latest server-agent watch report: {reports[0].name} age_seconds={age_seconds}")
    else:
        lines.append("- latest server-agent watch report: missing")
    return lines


def log_triage() -> list[str]:
    """Triage recent journal entries and collapse similar lines."""
    lines = ["## Log Triage"]
    code, output, _err = safe_run(["journalctl", "--since", "30 minutes ago", "--priority", "warning", "--no-pager", "--output", "short-iso"], timeout=25)
    if code != 0:
        lines.append(f"- journal read unavailable: {output or _err}")
        return lines
    patterns: dict[str, int] = {}
    for line in output.splitlines()[-300:]:
        compact = re.sub(r"\b[0-9a-f]{12,}\b", "<id>", line)
        compact = re.sub(r"\d+", "<n>", compact)
        key = compact[:180]
        patterns[key] = patterns.get(key, 0) + 1
    if not patterns:
        lines.append("- No warning-or-higher journal entries visible in the last 30 minutes.")
        return lines
    for key, count in sorted(patterns.items(), key=lambda item: item[1], reverse=True)[:12]:
        lines.append(f"- count={count}: `{key}`")
    return lines


def _walk_git_dirs(root: Path, max_depth: int = 7) -> list[Path]:
    """Bounded-depth .git directory discovery without following symlinks."""
    results: list[Path] = []
    if not root.exists() or not os.access(root, os.R_OK):
        return results
    _scan_dirs([root], 0, max_depth, results)
    return results


def _scan_dirs(dirs: list[Path], depth: int, max_depth: int, results: list[Path]) -> None:
    """Recursive helper for _walk_git_dirs."""
    if depth >= max_depth:
        return
    for d in dirs:
        try:
            with os.scandir(d) as it:
                for entry in it:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name == ".git":
                            results.append(Path(entry.path))
                        else:
                            _scan_dirs([Path(entry.path)], depth + 1, max_depth, results)
        except (PermissionError, OSError):
            continue


def repo_hygiene() -> list[str]:
    """Check git repo hygiene without following symlinks."""
    lines = ["## Repo Hygiene Watcher"]
    repos: set[Path] = set()
    for root in REPO_CANDIDATES:
        repos.update(path.parent for path in _walk_git_dirs(root))
    if not repos:
        lines.append("- No readable git workspaces found for the safe agent.")
        return lines
    for repo in sorted(repos)[:20]:
        code_branch, branch, _ = safe_run(["git", "-C", str(repo), "branch", "--show-current"], timeout=8)
        code_rev, rev, _ = safe_run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], timeout=8)
        code_status, status, _ = safe_run(["git", "-C", str(repo), "status", "--short"], timeout=8)
        dirty = "dirty" if status.strip() else "clean"
        lines.append(f"- {repo}: branch={branch if code_branch == 0 else 'unknown'} commit={rev if code_rev == 0 else 'unknown'} status={dirty}")
    return lines


def repo_hygiene_summary() -> dict:
    """Return structured repo hygiene summary."""
    repos: list[dict[str, str]] = []
    for root in REPO_CANDIDATES:
        for git_dir in _walk_git_dirs(root):
            repo = git_dir.parent
            code_branch, branch, _ = safe_run(["git", "-C", str(repo), "branch", "--show-current"], timeout=8)
            code_rev, rev, _ = safe_run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], timeout=8)
            _code_status, status, _ = safe_run(["git", "-C", str(repo), "status", "--short"], timeout=8)
            repos.append({
                "path": str(repo),
                "branch": branch if code_branch == 0 and branch else "unknown",
                "commit": rev if code_rev == 0 and rev else "unknown",
                "status": "dirty" if status.strip() else "clean",
            })
    unique = {item["path"]: item for item in repos}
    return {
        "repos": list(unique.values())[:30],
        "dirty_count": sum(1 for item in unique.values() if item["status"] == "dirty"),
        "clean_count": sum(1 for item in unique.values() if item["status"] == "clean"),
        "visibility": "visible" if unique else "none",
    }


def deployed_commit_watch() -> list[str]:
    """Watch deployed commit visibility."""
    lines = ["## Deployed Commit Visibility Watcher"]
    safe_status = safe_status_payload()
    manifest_repos = safe_status.get("repositories") if isinstance(safe_status.get("repositories"), list) else []
    if manifest_repos:
        for repo in manifest_repos[:20]:
            if not isinstance(repo, dict):
                continue
            lines.append(
                "- manifest {name}: branch={branch} commit={commit} status={status}".format(
                    name=repo.get("name", repo.get("path", "unknown")),
                    branch=repo.get("branch", "unknown"),
                    commit=repo.get("commit", "unknown"),
                    status=repo.get("status", "unknown"),
                )
            )
        return lines
    paths = [
        Path("/tmp/github-export/w7sh-infra-clean"),
        Path("/tmp/github-export/w7sh-gamebot-clean"),
        Path("/tmp/github-export/w7sh-moviebot-clean"),
        Path("/tmp/github-export/w7sh-admin-clean"),
        Path("/tmp/github-export/w7sh-website-clean"),
    ]
    visible = False
    for repo in paths:
        if not repo.exists():
            lines.append(f"- {repo.name}: missing")
            continue
        visible = True
        code_branch, branch, _ = safe_run(["git", "-C", str(repo), "branch", "--show-current"], timeout=8)
        code_rev, rev, _ = safe_run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], timeout=8)
        code_status, status, _ = safe_run(["git", "-C", str(repo), "status", "--short"], timeout=8)
        dirty = "dirty" if status.strip() else "clean"
        lines.append(f"- {repo.name}: branch={branch if code_branch == 0 else 'unknown'} commit={rev if code_rev == 0 else 'unknown'} status={dirty}")
    if not visible:
        lines.append("- clean export repos are not visible to the server agent.")
    return lines


def local_ollama_status() -> dict:
    """Check local Ollama runtime status."""
    enabled = os.environ.get("OLLAMA_ENABLED", "1").lower() in {"1", "true", "yes", "on"}
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:latest")
    if not enabled:
        return {"enabled": False, "available": False, "model": model, "fallback_mode": True}
    start = time.monotonic()
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
        return {
            "enabled": True,
            "available": True,
            "model": model,
            "loaded": model in models,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "fallback_mode": False,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "available": False,
            "model": model,
            "error": type(exc).__name__,
            "fallback_mode": True,
        }


def model_training_watch() -> list[str]:
    """Watch model / training status."""
    lines = ["## Model / Training Watcher"]
    ollama = local_ollama_status()
    lines.append(f"- local AI runtime: {'available' if ollama.get('available') else 'fallback'}")
    lines.append(f"- OLLAMA_MODEL: {ollama.get('model', 'unknown')}")
    lines.append(f"- OLLAMA latency: {ollama.get('latency_ms', 'unavailable')} ms")
    lines.append(f"- fallback mode: {ollama.get('fallback_mode')}")
    for name in ["OLLAMA_ENABLED", "OLLAMA_URL", "OLLAMA_MODEL", "MOVIELENS_MODEL_PATH"]:
        lines.append(f"- {name}: {'configured' if os.environ.get(name) else 'not configured'}")
    lines.append("- No training worker control action was attempted.")
    return lines


def model_training_summary() -> dict:
    """Return structured model/training summary."""
    ollama = local_ollama_status()
    return {
        "local_ai_runtime": "available" if ollama.get("available") else "fallback",
        "ollama": ollama,
        "ollama_model": ollama.get("model", "unknown"),
        "fallback_mode": bool(ollama.get("fallback_mode")),
        "movielens_model_path": "configured" if os.environ.get("MOVIELENS_MODEL_PATH") else "not_configured",
        "training_controls": "disabled_read_only_status",
    }


def approval_queue_status() -> dict:
    """Return approval queue status."""
    path = MEMORY_DIR / "queue" / APPROVAL_QUEUE_JSON
    queue = read_json(path, {"enabled": False, "items": []})
    items = queue.get("items") if isinstance(queue, dict) else []
    if not isinstance(items, list):
        items = []
    return {
        "enabled": bool(queue.get("enabled")) if isinstance(queue, dict) else False,
        "dangerous_operations_enabled": bool(queue.get("safety", {}).get("dangerous_operations_enabled")) if isinstance(queue, dict) else False,
        "queued": len([item for item in items if isinstance(item, dict) and item.get("status") == "queued"]),
        "total": len(items),
        "path": str(path),
    }


def detect_bug_findings(previous_sections: list[list[str]]) -> list[dict[str, str]]:
    """Detect bug signals with per-match service attribution."""
    findings: list[dict[str, str]] = []
    joined = "\n".join("\n".join(section) for section in previous_sections)
    code, journal, _err = safe_run(["journalctl", "--since", "90 minutes ago", "--priority", "warning", "--no-pager", "--output", "short-iso"], timeout=25)
    if code != 0:
        journal = ""
    scan_text = joined + "\n" + journal

    for pattern_str, symptom, cause, severity in BUG_MARKERS:
        pattern = re.compile(pattern_str, flags=re.I)
        matches = list(pattern.finditer(scan_text))
        if not matches:
            continue
        service_counts: dict[str, int] = {}
        for match in matches:
            start = max(0, match.start() - 200)
            end = min(len(scan_text), match.end() + 200)
            context = scan_text[start:end]
            svc = "gamebot" if re.search(r"gamebot|telegram_gamebot|/app/handlers|free|upcoming|callback", context, re.I) else "unknown"
            service_counts[svc] = service_counts.get(svc, 0) + 1
        for svc, count in service_counts.items():
            findings.append({
                "service": svc,
                "symptom": f"{symptom} count={count}",
                "cause": cause,
                "severity": severity,
                "auto": "no",
                "approval": "yes",
            })

    if "container restart/count checks unavailable" in joined or "visibility': 'limited" in joined:
        findings.append({
            "service": "server-agent",
            "symptom": "container restart/count checks unavailable",
            "cause": "safe agent lacks Docker visibility or Docker is unavailable",
            "severity": "medium",
            "auto": "no",
            "approval": "yes",
        })
    if "gamebot local /health: unavailable" in joined:
        findings.append({
            "service": "gamebot",
            "symptom": "local health endpoint unavailable from host",
            "cause": "API not host-published or service unhealthy",
            "severity": "medium",
            "auto": "no",
            "approval": "yes",
        })
    return findings


def bug_regression_watch(previous_sections: list[list[str]]) -> list[str]:
    """Format bug/regression findings into report lines."""
    lines = ["## Bug / Regression Watcher"]
    findings = detect_bug_findings(previous_sections)

    if not findings:
        lines.append("- service=all symptom=no_new_high_confidence_bug_signals likely_root_cause=none severity=info safe_auto_patch=no needs_approval=no")
        return lines

    seen: set[tuple[str, str]] = set()
    for finding in findings[:20]:
        key = (finding["service"], finding["symptom"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            "- service={service} symptom={symptom} likely_root_cause={cause} "
            "severity={severity} safe_auto_patch={auto} needs_approval={approval}".format(**finding)
        )
    return lines


def bullet_text(line: str) -> str:
    """Strip bullet prefix from a line."""
    return re.sub(r"^\s*-\s*", "", line).strip()


def field_value(line: str, key: str) -> str:
    """Extract a key=value field from a line, respecting subsequent keys as terminators."""
    keys = ["service", "symptom", "likely_root_cause", "severity", "safe_auto_patch", "needs_approval", "source"]
    next_keys = "|".join(item for item in keys if item != key)
    match = re.search(rf"{key}=([\s\S]*?)(?=\s(?:{next_keys})=|$)", line)
    return match.group(1).strip() if match else ""


def classify_item(kind: str, text: str, service: str) -> str:
    """Classify backlog item by category."""
    lowered = text.lower()
    if "secret" in lowered or "credential" in lowered:
        return "security"
    if "db" in lowered or "database" in lowered or "postgres" in lowered or "integrityerror" in lowered:
        return "db"
    if "training" in lowered or "model" in lowered or "openai" in lowered:
        return "model_training"
    if "sync" in lowered or "freshness" in lowered:
        return "sync"
    if "repo" in lowered or "commit" in lowered or "deploy" in lowered:
        return "repo_hygiene"
    if "docker" in lowered or "container" in lowered or service == "server-agent":
        return "observability"
    return "feature" if kind == "feature" else "runtime"


def item_service(text: str) -> str:
    """Determine service from explicit field or heuristics."""
    explicit = field_value(text, "service")
    if explicit:
        return explicit
    lowered = text.lower()
    if "gamebot" in lowered:
        return "gamebot"
    if "moviebot" in lowered:
        return "moviebot"
    if "server-agent" in lowered or "server agent" in lowered:
        return "server-agent"
    if "shared memory" in lowered or "sync" in lowered:
        return "shared-memory"
    if "repo" in lowered or "github" in lowered:
        return "repo"
    if "db" in lowered or "postgres" in lowered:
        return "database"
    return "infra"


def item_severity(text: str) -> str:
    """Determine severity from explicit field or heuristics."""
    explicit = field_value(text, "severity").lower()
    if explicit in {"critical", "high", "medium", "low", "info"}:
        return explicit
    lowered = text.lower()
    if "traceback" in lowered or "integrityerror" in lowered or "database is locked" in lowered or "credential" in lowered:
        return "high"
    if "unavailable" in lowered or "dirty" in lowered or "permission" in lowered or "not permitted" in lowered:
        return "medium"
    return "low"


def canonical_issue_family(kind: str, service: str, category: str, symptom: str, root_cause: str) -> str:
    """Compute canonical issue family, stripping count from symptom for stable IDs."""
    clean_symptom = re.sub(r"\bcount=\d+", "", symptom).strip()
    text = f"{clean_symptom} {root_cause}".lower()
    if category == "observability" and ("docker" in text or "container" in text or "permission grant" in text):
        return "server-agent|observability|container-health-visibility"
    if category == "db" and ("pg_isready" in text or "postgres" in text or "db health" in text):
        return "server-agent|observability|db-health-visibility"
    if service == "gamebot" and "local health endpoint unavailable" in text:
        return "server-agent|observability|gamebot-health-probe-vantage"
    return f"{kind}|{service}|{category}|{clean_symptom}|{root_cause}"


def make_backlog_item(kind: str, text: str, source: str, created_at: str | None = None) -> dict:
    """Create a structured backlog item."""
    service = item_service(text)
    severity = item_severity(text)
    symptom = field_value(text, "symptom") or re.sub(r"\s*source=.*$", "", text).strip()
    root_cause = field_value(text, "likely_root_cause") or "Needs operator review from the source report."
    category = classify_item(kind, text, service)
    safe_auto_patch = field_value(text, "safe_auto_patch") == "yes"
    needs_approval = field_value(text, "needs_approval") == "yes" or not safe_auto_patch
    risky = re.search(r"restart|db cutover|credential|secret|dns|firewall|broadcast|notification|destructive", text, re.I)
    risk = "dangerous" if risky else "safe_auto_apply" if safe_auto_patch else "approval_required" if needs_approval else "read_only"
    family = canonical_issue_family(kind, service, category, symptom, root_cause)
    item_id = stable_id(family)
    now_iso = now().isoformat()
    return {
        "id": item_id,
        "family": family,
        "created_at": created_at or now_iso,
        "updated_at": now_iso,
        "kind": kind,
        "service": service,
        "title": symptom if service in {"infra", "repo", "database"} else f"{service}: {symptom}",
        "severity": severity,
        "category": category,
        "status": "open",
        "active": True,
        "root_cause": root_cause,
        "fix_plan": "Review the source evidence, approve a scoped implementation, and validate with no-send/no-destructive tests.",
        "report_link": source,
        "validation_status": "pending",
        "rollback_link": "",
        "safe_auto_patch": safe_auto_patch,
        "needs_approval": needs_approval,
        "risk": risk,
        "last_seen_at": now_iso,
        "seen_count": 1,
    }


def current_items_from_sections(sections: list[list[str]], report_name: str) -> list[dict]:
    """Extract current backlog items from bug/regression and feature sections."""
    items: list[dict] = []
    for section in sections:
        mode = ""
        for line in section:
            if line.startswith("### Potential Bugs"):
                mode = "bug"
                continue
            if line.startswith("### Potential Features"):
                mode = "feature"
                continue
            if line.startswith("- service="):
                mode = "bug"
            if not mode or not line.startswith("- "):
                continue
            text = bullet_text(line)
            if text.startswith("No new ") or "no_new_high_confidence_bug_signals" in text:
                continue
            items.append(make_backlog_item(mode, text, report_name))
    deduped: dict[str, dict] = {}
    for item in items:
        deduped[item["id"]] = item
    return list(deduped.values())


def legacy_backlog_items() -> list[dict]:
    """Load legacy markdown backlog items."""
    backlog = MEMORY_DIR / "reports" / BUG_FEATURE_BACKLOG
    if not backlog.exists():
        return []
    items = []
    for line in backlog.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^- (\d{4}-\d{2}-\d{2}) \[(\w+)\] (.+)$", line)
        if not match:
            continue
        date, kind, body = match.groups()
        source = field_value(body, "source") or BUG_FEATURE_BACKLOG
        items.append(make_backlog_item(kind if kind in {"bug", "feature"} else "risk", body, source, created_at=date))
    return items


def update_structured_backlog(current_items: list[dict]) -> dict:
    """Update structured backlog with file locking and without downgrading verified items."""
    path = MEMORY_DIR / "reports" / BACKLOG_JSON
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with os.fdopen(fd, "r+", encoding="utf-8", closefd=False) as f:
            f.seek(0)
            try:
                existing = json.load(f)
            except Exception:
                existing = {}
            by_id: dict[str, dict] = {}
            for item in legacy_backlog_items():
                by_id[item["id"]] = item
            for item in existing.get("items", []) if isinstance(existing, dict) else []:
                if isinstance(item, dict) and item.get("id"):
                    by_id[str(item["id"])] = item

            current_ids = {item["id"] for item in current_items}
            now_iso = now().isoformat()
            for item in current_items:
                previous = by_id.get(item["id"], {})
                merged = {**item}
                merged["created_at"] = previous.get("created_at", item["created_at"])
                merged["seen_count"] = int(previous.get("seen_count", 0)) + 1
                previous_status = previous.get("status")
                merged["status"] = previous_status if previous_status in {"acknowledged", "in_progress", "deferred", "blocked"} else "open"
                merged["active"] = merged["status"] in ACTIVE_BACKLOG_STATES
                merged["validation_status"] = "failing_or_unverified"
                by_id[item["id"]] = merged

            for item_id, item in list(by_id.items()):
                if item_id in current_ids:
                    continue
                if item.get("status") in TERMINAL_BACKLOG_STATES or item.get("kind") == "feature":
                    item["active"] = item.get("status") in ACTIVE_BACKLOG_STATES
                    continue
                if item.get("status") == "verified":
                    item["active"] = False
                    continue
                if item.get("status") in {"open", "acknowledged", "in_progress"}:
                    item["status"] = "acknowledged"
                    item["active"] = True
                    item["validation_status"] = "not_seen_recently_unverified"
                    item["updated_at"] = now_iso

            items = sorted(by_id.values(), key=lambda item: (item.get("active") is not True, item.get("severity", ""), item.get("updated_at", "")))
            payload = {
                "schema_version": SCHEMA_VERSION,
                "updated_at": now_iso,
                "active_states": sorted(ACTIVE_BACKLOG_STATES),
                "terminal_states": sorted(TERMINAL_BACKLOG_STATES),
                "resolution_rule": "Items are marked verified only after explicit validation evidence; signal absence becomes acknowledged/not_seen_recently_unverified.",
                "items": items,
                "active_items": [item for item in items if item.get("active")],
                "counts": backlog_counts(items),
            }
            f.seek(0)
            f.truncate()
            json.dump(redact_obj(payload), f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return payload


def backlog_counts(items: list[dict]) -> dict:
    """Compute backlog count aggregations."""
    active = [item for item in items if item.get("active")]
    return {
        "total": len(items),
        "active": len(active),
        "bugs": sum(1 for item in active if item.get("kind") == "bug"),
        "features": sum(1 for item in active if item.get("kind") == "feature"),
        "awaiting_approval": sum(1 for item in active if item.get("needs_approval")),
        "by_status": count_strings(item.get("status", "unknown") for item in items),
        "by_severity": count_strings(item.get("severity", "unknown") for item in active),
        "by_service": count_strings(item.get("service", "unknown") for item in active),
        "by_category": count_strings(item.get("category", "unknown") for item in active),
    }


def count_strings(values) -> dict[str, int]:
    """Count occurrences of string values."""
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def bug_feature_watch(previous_sections: list[list[str]]) -> list[str]:
    """Watch for bug/feature opportunities from aggregated signals."""
    lines = ["## Bug / Feature Opportunity Watcher"]
    bugs: list[str] = []
    features: list[str] = []
    joined = "\n".join("\n".join(section) for section in previous_sections)

    for needle, finding in BUG_SIGNAL_RULES:
        if needle in joined and finding not in bugs:
            bugs.append(finding)
    for needle, finding in FEATURE_SIGNAL_RULES:
        if needle in joined and finding not in features:
            features.append(finding)

    if not bugs:
        bugs.append("No new high-confidence bug signals detected in this cycle.")
    if not features:
        features.append("No new feature opportunities detected beyond existing watcher coverage.")

    lines.append("### Potential Bugs / Risks")
    lines.extend(f"- {item}" for item in bugs[:12])
    lines.append("### Potential Features / Improvements")
    lines.extend(f"- {item}" for item in features[:12])
    return lines


def update_bug_feature_backlog(section: list[str], report: Path) -> None:
    """Append new bug/feature lines to the legacy markdown backlog."""
    backlog = MEMORY_DIR / "reports" / BUG_FEATURE_BACKLOG
    existing = backlog.read_text(encoding="utf-8", errors="replace") if backlog.exists() else ""
    known = {line.strip().lower() for line in existing.splitlines() if line.strip().startswith("- ")}
    additions: list[str] = []
    mode = ""
    for line in section:
        if line.startswith("### Potential Bugs"):
            mode = "bug"
            continue
        if line.startswith("### Potential Features"):
            mode = "feature"
            continue
        if line.startswith("- service="):
            mode = "bug"
        if not mode or not line.startswith("- "):
            continue
        item = bullet_text(line)
        if item.startswith("No new "):
            continue
        entry = f"- {now().date().isoformat()} [{mode}] {item} source={report.name}"
        if entry.lower() not in known and item.lower() not in " ".join(known):
            additions.append(entry)
            known.add(entry.lower())

    if not backlog.exists():
        atomic_write_text(
            backlog,
            "# W7SH Server Agent Bug / Feature Backlog\n\n"
            "Rolling report-only backlog generated by the safe server-side watcher. "
            "Entries are proposals or risks, not approvals to change production.\n\n",
        )
    if additions:
        with backlog.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(additions) + "\n")


def write_markdown_backlog(payload: dict) -> None:
    """Render structured backlog to markdown atomically."""
    backlog = MEMORY_DIR / "reports" / BUG_FEATURE_BACKLOG
    items = payload.get("items", []) if isinstance(payload, dict) else []
    counts = payload.get("counts", {}) if isinstance(payload, dict) else {}
    lines = [
        "# W7SH Server Agent Bug / Feature Backlog",
        "",
        "Rolling backlog generated by the safe server-side watcher. Items include explicit resolution state; active views should exclude fixed, verified, and closed items.",
        "",
        "## Counts",
        f"- total={counts.get('total', 0)} active={counts.get('active', 0)} bugs={counts.get('bugs', 0)} features={counts.get('features', 0)} awaiting_approval={counts.get('awaiting_approval', 0)}",
        "",
        "## Active Items",
    ]
    active = [item for item in items if item.get("active")]
    if not active:
        lines.append("- none")
    for item in active:
        lines.append(
            "- id={id} status={status} service={service} severity={severity} category={category} "
            "kind={kind} title={title} root_cause={root_cause} fix_plan={fix_plan} "
            "validation_status={validation_status} rollback_link={rollback_link} report_link={report_link} "
            "safe_auto_patch={safe_auto_patch} needs_approval={needs_approval}".format(
                id=item.get("id", ""),
                status=item.get("status", "open"),
                service=item.get("service", "unknown"),
                severity=item.get("severity", "info"),
                category=item.get("category", "unknown"),
                kind=item.get("kind", "unknown"),
                title=item.get("title", ""),
                root_cause=item.get("root_cause", ""),
                fix_plan=item.get("fix_plan", ""),
                validation_status=item.get("validation_status", "pending"),
                rollback_link=item.get("rollback_link", ""),
                report_link=item.get("report_link", ""),
                safe_auto_patch="yes" if item.get("safe_auto_patch") else "no",
                needs_approval="yes" if item.get("needs_approval") else "no",
            )
        )
    lines.extend(["", "## Resolved / Inactive Items"])
    inactive = [item for item in items if not item.get("active")]
    if not inactive:
        lines.append("- none")
    for item in inactive[:80]:
        lines.append(
            "- id={id} status={status} service={service} severity={severity} category={category} kind={kind} "
            "title={title} validation_status={validation_status} report_link={report_link}".format(
                id=item.get("id", ""),
                status=item.get("status", "verified"),
                service=item.get("service", "unknown"),
                severity=item.get("severity", "info"),
                category=item.get("category", "unknown"),
                kind=item.get("kind", "unknown"),
                title=item.get("title", ""),
                validation_status=item.get("validation_status", ""),
                report_link=item.get("report_link", ""),
            )
        )
    atomic_write_text(backlog, "\n".join(redact(line) for line in lines) + "\n")


def write_report(sections: list[list[str]], context: dict[str, str]) -> Path:
    """Write a markdown report atomically."""
    report = MEMORY_DIR / "reports" / f"{REPORT_PREFIX}_{stamp()}.md"
    content = [
        f"# W7SH Server Agent Watch - {now().isoformat()}",
        "",
        "## Memory Read Before Work",
        f"- activity_log.md: {len(context.get('activity_log.md', ''))} chars sampled",
        f"- decisions.md: {len(context.get('decisions.md', ''))} chars sampled",
        f"- project_inventory.md: {len(context.get('project_inventory.md', ''))} chars sampled",
        "- latest reports:",
    ]
    latest = context.get("latest_reports") or "(none)"
    content.extend(f"  - {line}" for line in latest.splitlines())
    content.append("")
    for section in sections:
        content.extend(section)
        content.append("")
    content.extend([
        "## Safety",
        "- Read-only checks only.",
        "- No DNS, firewall, credential, broadcast, notification, destructive DB, or public exposure changes attempted.",
        "- Secrets were redacted from command output before writing.",
    ])
    atomic_write_text(report, "\n".join(content) + "\n")
    return report


def latest_report_path(report: Path) -> str:
    """Return relative path to report from memory dir if possible."""
    try:
        return str(report.relative_to(MEMORY_DIR))
    except ValueError:
        return str(report)


def section_has(sections: list[list[str]], heading: str) -> bool:
    """Check if any section starts with the given heading."""
    return any(section and section[0] == heading for section in sections)


def warning_summary(sections: list[list[str]]) -> list[str]:
    """Extract warning/error lines from sections."""
    warnings: list[str] = []
    for section in sections:
        for line in section[1:]:
            if re.search(r"failed|traceback|error|unavailable|not permitted|dirty|locked|integrityerror", line, re.I):
                warnings.append(bullet_text(line))
    return warnings[:25]


def sync_status(report: Path) -> dict:
    """Return shared-memory sync status."""
    age = int(time.time() - report.stat().st_mtime) if report.exists() else None
    return {
        "memory_dir": str(MEMORY_DIR),
        "reports_dir": str(MEMORY_DIR / "reports"),
        "latest_report": report.name,
        "latest_report_age_seconds": age,
        "readable": os.access(MEMORY_DIR, os.R_OK),
        "writable": os.access(MEMORY_DIR, os.W_OK),
    }


def verify_redaction_succeeded() -> bool:
    """Verify that the redaction pipeline strips a canary secret."""
    canary = "CANARY_SECRET_VALUE_12345"
    test_payload = {"api_key": canary, "nested": {"token": canary}}
    redacted = redact_obj(test_payload)
    return canary not in json.dumps(redacted)


def write_snapshot(report: Path, sections: list[list[str]], backlog_payload: dict) -> Path:
    """Write the JSON snapshot with degraded-state awareness."""
    service_summary = service_health_summary()
    unit = service_summary.get("units", {}).get("w7sh-server-agent.service", {})
    status = "running" if unit.get("ActiveState") == "active" and unit.get("SubState") == "running" else "degraded"
    active_items = backlog_payload.get("active_items", []) if isinstance(backlog_payload, dict) else []
    bug_count = sum(1 for item in active_items if item.get("kind") == "bug")
    feature_count = sum(1 for item in active_items if item.get("kind") == "feature")
    errors_present = bool(warning_summary(sections))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now().isoformat(),
        "agent": {
            "name": "w7sh-server-agent",
            "status": status,
            "active_state": unit.get("ActiveState", "unknown"),
            "sub_state": unit.get("SubState", "unknown"),
            "result": unit.get("Result", "unknown"),
            "restart_count": unit.get("NRestarts"),
            "last_heartbeat": now().isoformat(),
            "last_report_path": latest_report_path(report),
            "last_watch_cycle_result": "degraded" if errors_present else "success",
            "current_tasks": [
                "health check",
                "log scan",
                "restart count check",
                "DB check",
                "sync freshness check",
                "repo hygiene check",
                "model/training status check",
                "bug/regression watcher",
                "backlog update",
                "JSON snapshot generation",
            ],
        },
        "service_health": service_summary,
        "restart_counts": {
            "units": {name: data.get("NRestarts") for name, data in service_summary.get("units", {}).items()},
            "containers": {name: data.get("restart_count") for name, data in service_summary.get("containers", {}).items()},
        },
        "db_health": db_health_summary(),
        "repo_hygiene": repo_hygiene_summary(),
        "backlog": {
            "bug_counts": {"active": bug_count, "total": sum(1 for item in backlog_payload.get("items", []) if item.get("kind") == "bug")},
            "feature_counts": {"active": feature_count, "total": sum(1 for item in backlog_payload.get("items", []) if item.get("kind") == "feature")},
            "counts": backlog_payload.get("counts", {}),
            "active_item_ids": [item.get("id") for item in active_items],
            "path": f"reports/{BACKLOG_JSON}",
        },
        "model_training": model_training_summary(),
        "shared_memory_sync": sync_status(report),
        "resources": resource_usage_summary(),
        "approval_queue": approval_queue_status(),
        "watchers": {
            "health": "active" if section_has(sections, "## Health Watcher") else "missing",
            "log_scan": "active" if section_has(sections, "## Log Triage") else "missing",
            "restart_counts": "active" if section_has(sections, "## Restart / Runtime Watcher") else "missing",
            "db": "active" if section_has(sections, "## DB Health Watcher") else "missing",
            "sync_freshness": "active" if section_has(sections, "## Freshness Watcher") else "missing",
            "repo_hygiene": "active" if section_has(sections, "## Repo Hygiene Watcher") else "missing",
            "model_training": "active" if section_has(sections, "## Model / Training Watcher") else "missing",
            "bug_regression": "active" if section_has(sections, "## Bug / Regression Watcher") else "missing",
        },
        "errors_warnings": warning_summary(sections),
        "safety": {
            "read_only_cycle": True,
            "secrets_redacted": verify_redaction_succeeded(),
            "public_exposure_changed": False,
            "dns_firewall_changed": False,
            "broadcasts_sent": False,
            "destructive_actions": False,
        },
    }
    snapshot = MEMORY_DIR / "reports" / SNAPSHOT_JSON
    write_json(snapshot, payload)
    return snapshot


def write_heartbeat() -> None:
    """Write a heartbeat timestamp every cycle."""
    heartbeat = MEMORY_DIR / "runtime" / HEARTBEAT_JSON
    write_json(heartbeat, {"timestamp": now().isoformat(), "pid": os.getpid()})


def log_structured(event: str, **kwargs: Any) -> None:
    """Append a JSON Lines structured log entry."""
    if not LOG_DIR.exists():
        return
    payload: dict[str, Any] = {
        "timestamp": now().isoformat(),
        "event": event,
        "pid": os.getpid(),
    }
    payload.update(kwargs)
    line = json.dumps(payload, sort_keys=True, default=str) + "\n"
    try:
        with (LOG_DIR / "server-agent.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:
        pass


def append_activity(report: Path, snapshot: Path | None = None) -> None:
    """Append a completion line to the activity log."""
    suffix = f"; snapshot={snapshot.name}" if snapshot else ""
    line = f"- {now().isoformat()} server-agent: completed safe watch cycle; report={report.name}{suffix}\n"
    with (MEMORY_DIR / "activity_log.md").open("a", encoding="utf-8") as handle:
        handle.write(line)


def cycle() -> Path:
    """Execute one full watch cycle."""
    ensure_memory()
    context = read_memory_context()
    sections = [
        service_health(),
        restart_count_watch(),
        freshness_watch(),
        log_triage(),
        db_health_watch(),
        repo_hygiene(),
        deployed_commit_watch(),
        model_training_watch(),
    ]
    sections.append(bug_regression_watch(sections))
    sections.append(bug_feature_watch(sections))
    sections.append(["## Safe Maintenance Helper", "- No automatic fixes applied. Findings are report-only unless explicitly approved."])
    report = write_report(sections, context)
    current_items = current_items_from_sections([sections[-3], sections[-2]], report.name)
    backlog_payload = update_structured_backlog(current_items)
    write_markdown_backlog(backlog_payload)
    snapshot = write_snapshot(report, sections, backlog_payload)
    append_activity(report, snapshot)
    write_heartbeat()
    log_structured("cycle_complete", report=str(report), snapshot=str(snapshot))
    return report


def main() -> int:
    """Main loop with exception recovery and degraded snapshots."""
    if "--help" in sys.argv:
        print("usage: w7sh-server-agent [--oneshot]", file=sys.stderr)
        return 0
    if "--oneshot" in sys.argv:
        os.environ["W7SH_AGENT_ONESHOT"] = "1"
    ensure_memory()
    while True:
        try:
            report = cycle()
            log_line = f"{now().isoformat()} wrote {report}\n"
            with (LOG_DIR / "server-agent.log").open("a", encoding="utf-8") as handle:
                handle.write(log_line)
        except Exception as exc:
            tb = traceback.format_exc()
            error_msg = f"{now().isoformat()} ERROR: {exc}\n{tb}\n"
            try:
                with (LOG_DIR / "server-agent.log").open("a", encoding="utf-8") as handle:
                    handle.write(error_msg)
            except Exception:
                pass
            log_structured("cycle_error", error=str(exc), traceback=tb)
            try:
                degraded = {
                    "schema_version": SCHEMA_VERSION,
                    "timestamp": now().isoformat(),
                    "agent": {
                        "name": "w7sh-server-agent",
                        "status": "degraded",
                        "last_watch_cycle_result": "degraded",
                        "error": str(exc),
                    },
                    "errors_warnings": [str(exc)],
                }
                write_json(MEMORY_DIR / "reports" / SNAPSHOT_JSON, degraded)
            except Exception:
                pass
        if os.environ.get("W7SH_AGENT_ONESHOT") == "1":
            return 0
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
