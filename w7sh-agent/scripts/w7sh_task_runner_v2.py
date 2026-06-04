#!/usr/bin/env python3
"""
W7SH Task Runner v4.0 — Secure Distributed Execution Agent

Security hardening applied:
  - No shell=True anywhere; all subprocess calls use list arguments
  - Default-deny approval system with recursive multi-action evaluation
  - Path traversal protection via validate_path()
  - SQL injection fix: psycopg2 exclusively with allowlists / parameterization
  - Size limits enforced on all inputs and outputs
  - Sanitized subprocess environments (secrets stripped)
  - Secure screenshot handling (tempdir only, approval for desktop)
  - Service management restricted to read-only without approval
  - Task orphaning fix: broad try/except always calls finish_task()
  - Input validation helpers (int, enum, URL with private-IP blocking)
  - opencode sandboxed with sanitized env and marker stripping
  - Database connection with exponential backoff and pool limit
  - Structured JSON logging with task context
  - Metrics tracking exposed via HTTP endpoint
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import ipaddress
import json
import logging
import logging.handlers
import os
import pathlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
import psycopg2.extras

# =============================================================================
# CONFIG
# =============================================================================

_DOTENV_PATH = Path.home() / "w7sh-agent" / ".env"


def _load_env_file(path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ."""
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
    except Exception:
        pass


_load_env_file(_DOTENV_PATH)

HUB_DB_URL = os.environ.get("HUB_DB_URL", "")
NODE_NAME = os.environ.get("NODE_NAME", os.environ.get("HOSTNAME", "unknown"))
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "opencode")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "15"))
WORKSPACE = os.path.realpath(os.path.expanduser(os.environ.get("WORKSPACE", "~/GitHub")))
MAX_OUTPUT = 8000
MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5 MiB
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))

APPROVED_ACTIONS: Set[str] = {
    "ping",
    "system_info",
    "health_check",
    "docker_ps",
    "docker_stats",
    "process_list",
    "process_monitor",
    "file_list",
}

ALLOWED_DB_NAMES: Set[str] = {
    "w7sh_hub",
    "gamebot_prod_20260506_160159",
    "moviebot_prod_20260506_205152",
    "n8n",
}

running = True
_db_pool: List[psycopg2.extensions.connection] = []
_db_pool_lock = threading.Lock()
_db_pool_max = 3

# =============================================================================
# STRUCTURED LOGGING
# =============================================================================


class JSONFormatter(logging.Formatter):
    """Emit log records as JSON with required fields."""

    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "level": record.levelname,
            "node": getattr(record, "node", NODE_NAME),
            "task_id": getattr(record, "task_id", None),
            "action_type": getattr(record, "action_type", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


_logger = logging.getLogger("w7sh_runner")
_logger.setLevel(logging.DEBUG)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.DEBUG)
_console_handler.setFormatter(JSONFormatter())
_logger.addHandler(_console_handler)

_log_dir = Path.home() / "w7sh-agent" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_file_handler = logging.handlers.RotatingFileHandler(
    _log_dir / "task-runner-v2.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(JSONFormatter())
_logger.addHandler(_file_handler)


def log(msg: str, *, task_id: Optional[int] = None, action_type: Optional[str] = None, level: int = logging.INFO) -> None:
    extra: Dict[str, Any] = {"node": NODE_NAME}
    if task_id is not None:
        extra["task_id"] = task_id
    if action_type is not None:
        extra["action_type"] = action_type
    _logger.log(level, msg, extra=extra)


# =============================================================================
# METRICS
# =============================================================================


@dataclass
class Metrics:
    tasks_processed: int = 0
    tasks_failed: int = 0
    tasks_cancelled: int = 0
    total_latency_ms: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, status: str, latency_ms: float) -> None:
        with self.lock:
            self.tasks_processed += 1
            if status == "failed":
                self.tasks_failed += 1
            elif status == "cancelled":
                self.tasks_cancelled += 1
            self.total_latency_ms += latency_ms

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            avg = (self.total_latency_ms / self.tasks_processed) if self.tasks_processed else 0.0
            return {
                "tasks_processed": self.tasks_processed,
                "tasks_failed": self.tasks_failed,
                "tasks_cancelled": self.tasks_cancelled,
                "avg_latency_ms": round(avg, 2),
            }


METRICS = Metrics()


class MetricsHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to expose metrics as JSON."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/metrics":
            body = json.dumps(METRICS.to_dict()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # suppress default access logging


def start_metrics_server(port: int = METRICS_PORT) -> threading.Thread:
    """Start a background thread serving metrics on /metrics."""
    server = HTTPServer(("127.0.0.1", port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log("Metrics server started on http://127.0.0.1:{}/metrics".format(port))
    return thread


# =============================================================================
# SECURITY
# =============================================================================

_SECRET_PATTERNS = [
    re.compile(r"(password[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(secret[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(token[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(postgresql://[^:]+:)([^@]+)(@)", re.IGNORECASE),
    re.compile(r"(AWS_ACCESS_KEY_ID[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(AWS_SECRET_ACCESS_KEY[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(PRIVATE_KEY[:=]\s*)\S+", re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    """Scrub known secret patterns from text."""
    if not isinstance(text, str):
        text = str(text)
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "***REDACTED***" + (m.group(3) if len(m.groups()) > 2 else ""), text)
    return text


def _is_private_ip(host: str) -> bool:
    """Return True if host resolves to a private/link-local IP."""
    try:
        addr = socket.getaddrinfo(host, None)[0][4][0]
        ip = ipaddress.ip_address(addr)
        return ip.is_private or ip.is_loopback or str(ip) == "169.254.169.254"
    except Exception:
        # If resolution fails, do regex-based fallback for literal IPs
        for blocked in ("10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                        "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                        "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
                        "192.168.", "169.254.169.254", "127.", "0.0.0.0", "::1"):
            if host.startswith(blocked):
                return True
        return False


def validate_url(url: str) -> str:
    """Validate URL and reject private IP targets."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL scheme")
    # Extract host
    match = re.match(r"https?://([^/:]+)", url)
    if not match:
        raise ValueError("Could not parse URL host")
    host = match.group(1)
    if _is_private_ip(host):
        raise ValueError("Private IP ranges are not allowed")
    return url


def validate_int(param: Any, minimum: int, maximum: int) -> int:
    """Coerce param to int and enforce bounds."""
    try:
        value = int(param)
    except (TypeError, ValueError) as exc:
        raise ValueError("Expected integer, got {}".format(type(param).__name__)) from exc
    if value < minimum or value > maximum:
        raise ValueError("Value {} out of bounds [{} , {}]".format(value, minimum, maximum))
    return value


def validate_enum(param: Any, allowed: Set[str]) -> str:
    """Ensure param is a string in the allowed set."""
    value = str(param) if param is not None else ""
    if value not in allowed:
        raise ValueError("Invalid value '{}'; allowed: {}".format(value, ", ".join(sorted(allowed))))
    return value


def validate_path(path: str) -> Path:
    """Resolve path, enforce WORKSPACE containment, reject symlinks and traversal."""
    if not isinstance(path, str):
        raise ValueError("Path must be a string")
    if ".." in path:
        raise ValueError("Path traversal ('..') not allowed")
    # Reject symlinks on the original path before resolution
    expanded = os.path.expanduser(path)
    if os.path.islink(expanded):
        raise ValueError("Symlinks are not allowed")
    resolved = Path(os.path.realpath(expanded))
    # Allow tempfile directory and WORKSPACE (resolve roots too for macOS /private/var)
    allowed_roots = {Path(os.path.realpath(WORKSPACE)), Path(os.path.realpath(tempfile.gettempdir()))}
    in_allowed = any(
        str(resolved).startswith(str(root) + os.sep) or resolved == root
        for root in allowed_roots
    )
    if not in_allowed:
        raise ValueError("Path {} is outside allowed directories".format(resolved))
    return resolved


def build_sanitized_env() -> Dict[str, str]:
    """Return a subprocess-safe env dict with secrets removed."""
    denylist = {
        "HUB_DB_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "PRIVATE_KEY",
        "GITHUB_TOKEN",
        "DOCKER_TOKEN",
        "OPENAI_API_KEY",
    }
    env = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper in denylist or "SECRET" in upper or "PASSWORD" in upper or "TOKEN" in upper:
            continue
        env[key] = value
    # HOME is needed by many tools; keep it but ensure it's safe
    if "HOME" not in env:
        env["HOME"] = str(Path.home())
    return env


# =============================================================================
# DB (connection pool + retry)
# =============================================================================


def _connect_with_backoff(max_wait: int = 60) -> psycopg2.extensions.connection:
    """Connect to Postgres with exponential backoff."""
    wait = 1.0
    total = 0.0
    last_exc: Optional[Exception] = None
    while total < max_wait:
        try:
            conn = psycopg2.connect(
                HUB_DB_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            conn.autocommit = True
            return conn
        except Exception as exc:
            last_exc = exc
            log("DB connection failed, retrying in {}s: {}".format(wait, exc), level=logging.WARNING)
            time.sleep(wait)
            total += wait
            wait = min(wait * 2, max_wait - total)
    raise ConnectionError("Could not connect to database after {}s: {}".format(total, last_exc))


def get_db() -> psycopg2.extensions.connection:
    """Return a healthy connection from the pool, creating one if needed."""
    global _db_pool
    with _db_pool_lock:
        for conn in list(_db_pool):
            try:
                if not conn.closed:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                    return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                _db_pool.remove(conn)
        if len(_db_pool) >= _db_pool_max:
            raise ConnectionError("DB connection pool exhausted (max={})".format(_db_pool_max))
        new_conn = _connect_with_backoff()
        _db_pool.append(new_conn)
        return new_conn


def db_exec(query: str, params: Optional[Tuple[Any, ...]] = None, fetch: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Execute a query using a pooled connection."""
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(query, params)
        if fetch:
            return cur.fetchall()
        return None


# =============================================================================
# SUBPROCESS HELPERS
# =============================================================================


def run_cmd(cmd_list: List[str], timeout: int = 60, cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run a subprocess with shell=False, sanitized env, and timeout."""
    if not isinstance(cmd_list, list):
        raise TypeError("cmd_list must be a list of strings")
    actual_cwd = cwd or WORKSPACE
    if not os.path.isdir(actual_cwd):
        actual_cwd = str(Path.home())
    env = build_sanitized_env()
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=actual_cwd,
            env=env,
            shell=False,
        )
        out = (result.stdout or "") + (result.stderr or "")
        return {
            "exit": result.returncode,
            "out": redact_secrets(out.strip()[:MAX_OUTPUT]),
            "cmd": str(cmd_list)[:200],
        }
    except subprocess.TimeoutExpired:
        return {
            "exit": -1,
            "out": "TIMEOUT ({}s)".format(timeout),
            "cmd": str(cmd_list)[:200],
        }
    except Exception as exc:
        return {
            "exit": -1,
            "out": redact_secrets(str(exc)),
            "cmd": str(cmd_list)[:200],
        }


# =============================================================================
# APPROVAL SYSTEM
# =============================================================================


def is_dangerous(action_type: str, params: Dict[str, Any]) -> bool:
    """
    Default-deny: only APPROVED_ACTIONS are safe.
    Recursive evaluation for action_multi.
    """
    if action_type == "multi":
        actions = params.get("actions", [])
        if not isinstance(actions, list):
            return True
        for sub in actions:
            if not isinstance(sub, dict):
                return True
            sub_type = sub.get("type", "shell")
            sub_params = sub.get("params", {})
            if is_dangerous(sub_type, sub_params):
                return True
        return False
    return action_type not in APPROVED_ACTIONS


def request_approval(task_id: int, action: str, reason: str, command: str = "") -> None:
    db_exec(
        """
        INSERT INTO approval_queue (task_id, node, action, reason, command, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
        """,
        (task_id, NODE_NAME, action[:500], reason[:1000], command[:500]),
    )
    db_exec("UPDATE task_queue SET status = 'needs_approval' WHERE id = %s", (task_id,))
    log("APPROVAL REQUESTED: {} - {}".format(task_id, action[:80]), task_id=task_id)


def wait_for_approval(task_id: int, timeout: int = 600) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        rows = db_exec(
            "SELECT status FROM approval_queue WHERE task_id = %s ORDER BY created_at DESC LIMIT 1",
            (task_id,),
            fetch=True,
        )
        if rows:
            status = rows[0]["status"]
            if status == "approved":
                return True
            if status == "denied":
                return False
        time.sleep(5)
    return False


# =============================================================================
# ACTION HANDLERS
# =============================================================================


def action_shell(params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a shell command via list (no shell=True)."""
    cmd = params.get("command", params.get("cmd", ""))
    if isinstance(cmd, str):
        # If caller passes a string, we must NOT use shell=True.
        # We try a simple split; complex commands should be passed as list by the caller.
        cmd_list = cmd.split()
    elif isinstance(cmd, list):
        cmd_list = [str(c) for c in cmd]
    else:
        return {"ok": False, "result": "Error: No command provided."}
    if not cmd_list:
        return {"ok": False, "result": "Error: No command provided."}
    timeout = validate_int(params.get("timeout", 60), 1, 300)
    cwd = params.get("cwd", None)
    r = run_cmd(cmd_list, timeout=timeout, cwd=cwd)
    if r["exit"] == 0:
        return {"ok": True, "result": r["out"].strip()[:MAX_OUTPUT] or "Command completed. (no output)"}
    return {"ok": False, "result": "Command failed (exit {}):\n{}".format(r["exit"], r["out"][:MAX_OUTPUT])}


def action_docker_ps(params: Dict[str, Any]) -> Dict[str, Any]:
    fmt = params.get("format", "{{.Names}}\t{{.Status}}\t{{.Ports}}")
    r = run_cmd(["docker", "ps", "--format", fmt])
    if r["exit"] != 0:
        return {"ok": False, "result": "Docker error: {}".format(r["out"][:200])}
    if not r["out"].strip():
        return {"ok": True, "result": "No containers running."}
    lines = r["out"].strip().split("\n")
    parts = ["Running Containers:", "-" * 40]
    for line in lines:
        cols = line.split("\t")
        name = cols[0].strip() if len(cols) > 0 else "?"
        status = cols[1].strip() if len(cols) > 1 else "?"
        if "(healthy)" in status:
            parts.append("  {}: HEALTHY".format(name))
        elif "(unhealthy)" in status:
            parts.append("  {}: UNHEALTHY".format(name))
        else:
            parts.append("  {}: {}".format(name, status))
    return {"ok": True, "result": "\n".join(parts)}


def action_docker_logs(params: Dict[str, Any]) -> Dict[str, Any]:
    container = str(params.get("container", ""))
    if not container:
        return {"ok": False, "result": "Error: No container specified."}
    lines = validate_int(params.get("lines", 50), 1, 5000)
    r = run_cmd(["docker", "logs", "--tail", str(lines), container])
    if r["exit"] != 0 and not r["out"]:
        return {"ok": False, "result": "Error reading logs for {}.".format(container)}
    return {
        "ok": True,
        "result": "Logs: {} (last {} lines)\n---\n{}".format(
            container, lines, r["out"].strip()[:MAX_OUTPUT - 100]
        ),
    }


def action_docker_stats(params: Dict[str, Any]) -> Dict[str, Any]:
    r = run_cmd([
        "docker", "stats", "--no-stream",
        "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}",
    ])
    if r["exit"] != 0:
        return {"ok": False, "result": "Docker stats error: {}".format(r["out"][:200])}
    return {"ok": True, "result": "Container Resource Usage:\n{}".format(r["out"][:MAX_OUTPUT])}


def action_docker_restart(params: Dict[str, Any]) -> Dict[str, Any]:
    container = str(params.get("container", ""))
    if not container:
        return {"ok": False, "result": "Error: No container specified."}
    r = run_cmd(["docker", "restart", container], timeout=30)
    if r["exit"] == 0:
        return {"ok": True, "result": "Container {} restarted successfully.".format(container)}
    return {"ok": False, "result": "Failed to restart {}: {}".format(container, r["out"][:200])}


def action_docker_compose(params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = str(params.get("command", "ps"))
    project_dir = str(params.get("dir", "."))
    service = str(params.get("service", ""))
    args = str(params.get("args", ""))
    cmd_list = ["docker", "compose", cmd]
    if service:
        cmd_list.append(service)
    if args:
        cmd_list.extend(args.split())
    r = run_cmd(cmd_list, cwd=project_dir, timeout=120)
    if r["exit"] == 0:
        return {"ok": True, "result": r["out"].strip()[:MAX_OUTPUT] or "Docker Compose command completed."}
    return {"ok": False, "result": "Docker Compose failed (exit {}):\n{}".format(r["exit"], r["out"][:MAX_OUTPUT])}


def action_file_read(params: Dict[str, Any]) -> Dict[str, Any]:
    path = str(params.get("path", ""))
    if not path:
        return {"ok": False, "result": "Error: No file path provided."}
    try:
        resolved = validate_path(path)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}
    lines = validate_int(params.get("lines", 100), 1, 10000)
    offset = validate_int(params.get("offset", 1), 1, 100000)
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        start = offset - 1
        end = start + lines
        selected = all_lines[start:end]
        out = "".join(selected)
        if not out:
            return {"ok": True, "result": "File {} is empty or offset beyond end.".format(resolved)}
        return {"ok": True, "result": "File: {}\n---\n{}".format(resolved, out[:MAX_OUTPUT - 100])}
    except Exception as exc:
        return {"ok": False, "result": "Could not read {}: {}".format(resolved, exc)}


def action_file_write(params: Dict[str, Any]) -> Dict[str, Any]:
    path = str(params.get("path", ""))
    content = params.get("content", "")
    mode = validate_enum(params.get("mode", "w"), {"w", "a"})
    if not path:
        return {"ok": False, "result": "Error: No file path provided."}
    try:
        resolved = validate_path(path)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}
    if not isinstance(content, str):
        return {"ok": False, "result": "Error: content must be a string"}
    if len(content.encode("utf-8")) > MAX_CONTENT_SIZE:
        return {"ok": False, "result": "Error: content exceeds {} bytes".format(MAX_CONTENT_SIZE)}
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, mode, encoding="utf-8") as fh:
            fh.write(content)
        return {"ok": True, "result": "Wrote {} chars to {}".format(len(content), resolved)}
    except Exception as exc:
        return {"ok": False, "result": "Write error: {}".format(exc)}


def action_file_list(params: Dict[str, Any]) -> Dict[str, Any]:
    path = str(params.get("path", "."))
    try:
        resolved = validate_path(path)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}
    try:
        entries = []
        for entry in sorted(resolved.iterdir(), key=lambda e: e.name):
            prefix = "d" if entry.is_dir() else "f"
            entries.append("{} {}".format(prefix, entry.name))
        return {"ok": True, "result": "Directory: {}\n{}".format(resolved, "\n".join(entries)[:MAX_OUTPUT])}
    except Exception as exc:
        return {"ok": False, "result": "Could not list {}: {}".format(resolved, exc)}


def action_file_upload(params: Dict[str, Any]) -> Dict[str, Any]:
    path = str(params.get("path", ""))
    if not path:
        return {"ok": False, "result": "Error: No file path."}
    try:
        resolved = validate_path(path)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}
    try:
        size = resolved.stat().st_size
        if size > MAX_CONTENT_SIZE:
            return {"ok": False, "result": "Error: file exceeds {} bytes".format(MAX_CONTENT_SIZE)}
        with open(resolved, "rb") as fh:
            data = fh.read()
        encoded = base64.b64encode(data).decode()
        checksum = hashlib.md5(data).hexdigest()
        return {
            "ok": True,
            "result": json.dumps({
                "action": "file_upload",
                "filename": resolved.name,
                "size": size,
                "checksum": checksum,
                "data_base64": encoded,
            }),
        }
    except Exception as exc:
        return {"ok": False, "result": "Error reading file: {}".format(exc)}


def action_db_query(params: Dict[str, Any]) -> Dict[str, Any]:
    query = str(params.get("query", "")).strip()
    database = str(params.get("database", "w7sh_hub"))
    if not query:
        return {"ok": False, "result": "Error: No query provided."}
    if database not in ALLOWED_DB_NAMES:
        return {"ok": False, "result": "Error: Database '{}' not in allowlist.".format(database)}
    # Only SELECT allowed unless explicitly parameterized and whitelisted
    upper = query.upper()
    if not upper.startswith("SELECT"):
        return {"ok": False, "result": "Error: Only SELECT queries are allowed."}
    # Reject obvious injection patterns inside the query string itself
    dangerous = {";", "--", "/*", "*/", "@@", "CHAR(", "CONCAT(", "0x"}
    if any(d in query for d in dangerous):
        return {"ok": False, "result": "Error: Query contains forbidden patterns."}
    host = str(params.get("host", "100.74.48.94"))
    port = validate_int(params.get("port", 5432), 1, 65535)
    user = str(params.get("user", "w7sh-agent"))
    db_url = "postgresql://{}@{}:{}/{}".format(user, host, port, database)
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        conn.close()
        if cols:
            header = " | ".join(cols[:8])
            separator = "-+-".join(["-" * len(c) for c in cols[:8]])
            lines = [header, separator]
            for row in (rows or [])[:50]:
                lines.append(" | ".join(str(v)[:40] if v is not None else "NULL" for v in row[:8]))
            return {
                "ok": True,
                "result": "Query on {} ({} rows):\n{}".format(database, len(rows or []), "\n".join(lines)[:MAX_OUTPUT]),
            }
        return {"ok": True, "result": "Query on {}: OK (no rows returned)".format(database)}
    except Exception as exc:
        return {"ok": False, "result": "Query error: {}".format(str(exc)[:500])}


def action_git(params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = str(params.get("command", "status"))
    repo = str(params.get("repo", params.get("dir", WORKSPACE)))
    try:
        resolved = validate_path(repo)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}
    r = run_cmd(["git", "-C", str(resolved), *cmd.split()], timeout=60)
    repo_name = resolved.name
    if r["exit"] == 0:
        return {"ok": True, "result": "Git {} on {}:\n{}".format(cmd, repo_name, r["out"].strip()[:MAX_OUTPUT])}
    return {"ok": False, "result": "Git error on {}:\n{}".format(repo_name, r["out"][:MAX_OUTPUT])}


def action_git_clone(params: Dict[str, Any]) -> Dict[str, Any]:
    url = str(params.get("url", ""))
    dest = str(params.get("dest", ""))
    branch = str(params.get("branch", ""))
    if not url:
        return {"ok": False, "result": "Error: No repository URL."}
    try:
        validate_url(url)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}
    cmd_list = ["git", "clone"]
    if branch:
        cmd_list.extend(["-b", branch])
    cmd_list.append(url)
    if dest:
        try:
            dest_path = validate_path(dest)
            cmd_list.append(str(dest_path))
        except ValueError as exc:
            return {"ok": False, "result": str(exc)}
    r = run_cmd(cmd_list, timeout=120)
    repo_name = url.split("/")[-1].replace(".git", "")
    if r["exit"] == 0:
        return {"ok": True, "result": "Cloned {} successfully.".format(repo_name)}
    return {"ok": False, "result": "Clone failed for {}:\n{}".format(repo_name, r["out"][:MAX_OUTPUT])}


def action_system_info(params: Dict[str, Any]) -> Dict[str, Any]:
    results: List[str] = []
    results.append("System Info: {}".format(NODE_NAME))
    results.append("=" * 35)
    if sys.platform != "win32":
        r = run_cmd(["uname", "-a"])
        results.append("OS: {}".format(r["out"][:80]))
        r = run_cmd(["uptime"])
        results.append("Uptime: {}".format(r["out"][:60]))
        r = run_cmd(["free", "-h"])
        for line in r["out"].splitlines():
            if line.startswith("Mem"):
                parts = line.split()
                if len(parts) >= 3:
                    results.append("Memory: {}/{}".format(parts[2], parts[1]))
                break
        r = run_cmd(["df", "-h", "/"])
        parts = r["out"].splitlines()[-1].split()
        if len(parts) >= 5:
            results.append("Disk: {}/{} ({})".format(parts[2], parts[1], parts[4]))
        r = run_cmd(["nproc"])
        results.append("CPUs: {}".format(r["out"].strip()))
        r = run_cmd(["cat", "/proc/loadavg"])
        loads = r["out"].split()[:3]
        if loads:
            results.append("Load: {}".format(" ".join(loads)))
    else:
        r = run_cmd(["cmd", "/c", "ver"])
        results.append("OS: {}".format(r["out"][:80]))
    # Docker count
    if sys.platform != "win32":
        r = run_cmd(["docker", "ps", "--format", "{{.Names}}"])
        count = len([l for l in r["out"].strip().split("\n") if l.strip()])
        if count:
            results.append("Docker containers: {}".format(count))
    return {"ok": True, "result": "\n".join(results)}


def action_health_check(params: Dict[str, Any]) -> Dict[str, Any]:
    target = str(params.get("target", ""))
    url = str(params.get("url", ""))
    results: List[str] = ["Health Check Results", "-" * 25]
    if url:
        try:
            validate_url(url)
        except ValueError as exc:
            return {"ok": False, "result": str(exc)}
        r = run_cmd([
            "curl", "-sSf", "-o", "/dev/null",
            "-w", "%{http_code}", "--max-time", "5", url,
        ])
        code = r["out"].strip()
        if code in ("200", "301", "302"):
            results.append("  OK  {} -> HTTP {}".format(url[:40], code))
        else:
            results.append("  FAIL  {} -> HTTP {}".format(url[:40], code or "ERR"))
    if target == "docker":
        r = run_cmd(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"])
        lines = [l for l in r["out"].split("\n") if l.strip()]
        for line in lines:
            cols = line.split("\t")
            name = cols[0] if cols else "?"
            status = cols[1] if len(cols) > 1 else "?"
            icon = "OK" if "healthy" in status.lower() else "WARN" if "unhealthy" in status.lower() else "---"
            results.append("  [{}] {}: {}".format(icon, name, status))
    if target == "services":
        services = params.get("services", [])
        for svc in services:
            r = run_cmd(["systemctl", "is-active", str(svc)])
            st = r["out"].strip()
            icon = "OK" if st == "active" else "FAIL"
            results.append("  [{}] {}: {}".format(icon, svc, st))
    if target == "ports":
        r = run_cmd(["ss", "-tlnp"])
        listening = [l for l in r["out"].split("\n") if "LISTEN" in l][:20]
        results.append("Listening ports:\n{}".format("\n".join(listening)[:2000]))
    if len(results) == 2:
        results.append("No targets specified.")
    return {"ok": True, "result": "\n".join(results)}


def action_screenshot(params: Dict[str, Any]) -> Dict[str, Any]:
    url = str(params.get("url", ""))
    width = validate_int(params.get("width", 1280), 100, 7680)
    height = validate_int(params.get("height", 800), 100, 4320)
    desktop = bool(params.get("desktop", False))

    # Restrict output to tempdir + runner subdir
    tmp_root = Path(tempfile.gettempdir()) / "w7sh_screenshots"
    tmp_root.mkdir(parents=True, exist_ok=True)
    fd, output_path = tempfile.mkstemp(suffix=".png", dir=tmp_root)
    os.close(fd)
    out_path = Path(output_path)

    if desktop:
        if sys.platform == "win32":
            r = run_cmd([
                "powershell", "-NoProfile", "-Command",
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$bmp = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); "
                "$g = [System.Drawing.Graphics]::FromImage($bmp); "
                "$g.CopyFromScreen([System.Drawing.Point]::Empty, [System.Drawing.Point]::Empty, $bmp.Size); "
                "$bmp.Save('{}'); $g.Dispose(); $bmp.Dispose()".format(out_path),
            ], timeout=15)
        elif sys.platform == "darwin":
            r = run_cmd(["screencapture", "-x", str(out_path)], timeout=10)
        else:
            for tool in (["import", "-window", "root", str(out_path)],
                         ["scrot", str(out_path)]):
                r = run_cmd(list(tool), timeout=10)
                if out_path.exists() and out_path.stat().st_size > 100:
                    break
        if out_path.exists() and out_path.stat().st_size > 100:
            size = out_path.stat().st_size
            with open(out_path, "rb") as fh:
                img_b64 = base64.b64encode(fh.read()).decode()
            return {
                "ok": True,
                "result": json.dumps({
                    "action": "screenshot",
                    "path": str(out_path),
                    "size": size,
                    "type": "desktop",
                    "node": NODE_NAME,
                    "image_base64": img_b64,
                }),
            }
        return {"ok": False, "result": "Desktop screenshot failed: {}".format(r["out"][:200])}

    if not url:
        return {"ok": False, "result": "Error: No URL for screenshot. Use {\"desktop\":true} for desktop capture."}

    try:
        validate_url(url)
    except ValueError as exc:
        return {"ok": False, "result": str(exc)}

    # Headless browser screenshot via list args
    browser_cmd: Optional[List[str]] = None
    if sys.platform != "win32":
        for candidate in ["chromium-browser", "google-chrome", "chromium", "firefox"]:
            r = run_cmd(["which", candidate], timeout=5)
            if r["exit"] == 0 and r["out"].strip():
                browser = r["out"].strip().split("\n")[0]
                browser_cmd = [
                    browser, "--headless", "--disable-gpu",
                    "--screenshot={}".format(out_path),
                    "--window-size={},{}".format(width, height),
                    url,
                ]
                break
    else:
        for b in ["chrome", "firefox", "msedge"]:
            r = run_cmd(["where", b], timeout=5)
            if r["exit"] == 0:
                browser = r["out"].strip().split("\n")[0]
                browser_cmd = [
                    browser, "--headless", "--disable-gpu",
                    "--screenshot={}".format(out_path),
                    "--window-size={},{}".format(width, height),
                    url,
                ]
                break

    if browser_cmd:
        r = run_cmd(browser_cmd, timeout=30)
    else:
        # Fallback to curl saving HTML
        html_path = out_path.with_suffix(".html")
        r = run_cmd(["curl", "-sSf", "-L", "-o", str(html_path), "--max-time", "15", url], timeout=20)
        if r["exit"] == 0:
            return {"ok": True, "result": "No headless browser. Saved HTML to {}.".format(html_path)}
        return {"ok": False, "result": "No browser and curl failed."}

    if out_path.exists() and out_path.stat().st_size > 100:
        size = out_path.stat().st_size
        with open(out_path, "rb") as fh:
            img_b64 = base64.b64encode(fh.read()).decode()
        return {
            "ok": True,
            "result": json.dumps({
                "action": "screenshot",
                "path": str(out_path),
                "size": size,
                "url": url,
                "node": NODE_NAME,
                "image_base64": img_b64,
            }),
        }
    return {"ok": False, "result": "Screenshot failed: {}".format(r.get("out", "unknown")[:200])}


def action_network_diagnostic(params: Dict[str, Any]) -> Dict[str, Any]:
    host = str(params.get("host", "google.com"))
    results: List[str] = ["Network Diagnostic: {}".format(host), "=" * 35]
    r = run_cmd(["ping", "-c", "3", "-W", "3", host], timeout=15)
    if r["exit"] != 0 and sys.platform == "win32":
        r = run_cmd(["ping", "-n", "3", host], timeout=15)
    ping_lines = [l for l in r["out"].split("\n") if "avg" in l.lower() or "packets" in l.lower() or "min" in l.lower()]
    if ping_lines:
        results.append("Ping: {}".format(ping_lines[0].strip()))
    else:
        results.append("Ping: {}".format(r["out"][:100]))
    r = run_cmd(["traceroute", "-m", "10", "-w", "2", host], timeout=30)
    if r["exit"] != 0 and sys.platform == "win32":
        r = run_cmd(["tracert", "-h", "10", host], timeout=30)
    results.append("\nTraceroute (first 10 hops):")
    for line in r["out"].split("\n")[:10]:
        if line.strip():
            results.append("  {}".format(line.strip()[:60]))
    port = str(params.get("port", "443"))
    r = run_cmd(["curl", "-sSf", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5", "https://{}:{}".format(host, port)], timeout=10)
    results.append("\nPort {} test: {}".format(port, r["out"][:100]))
    return {"ok": True, "result": "\n".join(results)}


def action_log_analysis(params: Dict[str, Any]) -> Dict[str, Any]:
    path = str(params.get("path", ""))
    container = str(params.get("container", ""))
    pattern = str(params.get("pattern", "error|warning|fail|exception|traceback"))
    lines = validate_int(params.get("lines", 200), 1, 5000)
    if container:
        r = run_cmd(["docker", "logs", "--tail", str(lines), container])
        log_content = r["out"]
        source = "container:{}".format(container)
    elif path:
        try:
            resolved = validate_path(path)
        except ValueError as exc:
            return {"ok": False, "result": str(exc)}
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            log_content = "".join(fh.readlines()[-lines:])
        source = str(resolved)
    else:
        return {"ok": False, "result": "Error: Specify container or path."}
    if not log_content.strip():
        return {"ok": True, "result": "No log content from {}.".format(source)}
    try:
        matches = re.findall(".*(?:{}).*".format(re.escape(pattern)), log_content, re.IGNORECASE)
    except Exception:
        matches = []
    total_lines = len(log_content.split("\n"))
    error_count = len(matches)
    results = [
        "Log Analysis: {}".format(source),
        "=" * 35,
        "Total lines scanned: {}".format(total_lines),
        "Pattern: {}".format(pattern),
        "Matches: {}".format(error_count),
        "",
        "Last {} matches:".format(min(20, len(matches))),
    ]
    for m in matches[-20:]:
        results.append("  {}".format(m.strip()[:80]))
    return {"ok": True, "result": "\n".join(results)}


def action_process_monitor(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("name", ""))
    cpu_threshold = float(params.get("cpu_threshold", 90))
    mem_threshold = float(params.get("mem_threshold", 80))
    results: List[str] = ["Process Monitor", "-" * 25]
    if name:
        r = run_cmd(["ps", "aux"])
        lines = [l for l in r["out"].split("\n") if name in l and "grep" not in l]
    else:
        r = run_cmd(["ps", "aux", "--sort=-%mem"])
        lines = r["out"].split("\n")[1:21]
    alerts: List[str] = []
    for line in lines[:20]:
        parts = line.split(None, 10)
        if len(parts) >= 6:
            try:
                cpu = float(parts[2])
                mem = float(parts[3])
                cmd = parts[10] if len(parts) > 10 else parts[-1]
                icon = "[ALERT]" if cpu > cpu_threshold or mem > mem_threshold else "[OK]"
                results.append("  {} {} CPU:{}% MEM:{}%".format(icon, cmd[:30], cpu, mem))
                if cpu > cpu_threshold or mem > mem_threshold:
                    alerts.append("{}: CPU={}% MEM={}%".format(cmd[:30], cpu, mem))
            except Exception:
                pass
    if alerts:
        results.append("\nThreshold alerts (>{}% CPU or >{}% MEM):".format(cpu_threshold, mem_threshold))
        for a in alerts:
            results.append("  !!! {}".format(a))
    return {"ok": True, "result": "\n".join(results)}


def action_service(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("name", ""))
    action_type = str(params.get("action", "status"))
    if not name:
        return {"ok": False, "result": "Error: No service name."}
    read_only = {"status", "is-active"}
    if action_type not in read_only:
        return {"ok": False, "result": "Error: action_type '{}' requires approval.".format(action_type)}
    if sys.platform == "win32":
        if action_type == "status":
            r = run_cmd(["sc", "query", name])
        else:
            r = run_cmd(["sc", action_type, name], timeout=30)
    else:
        r = run_cmd(["systemctl", action_type, name], timeout=30)
    if r["exit"] == 0:
        out = r["out"].strip()
        return {"ok": True, "result": "Service {} ({}): {}".format(name, action_type, out) if out else "Service {}: {} completed.".format(name, action_type)}
    return {"ok": False, "result": "Service {} ({}) failed: {}".format(name, action_type, r["out"][:200])}


def action_npm(params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = str(params.get("command", "list"))
    project_dir = str(params.get("dir", "."))
    r = run_cmd(["npm", *cmd.split()], cwd=project_dir, timeout=120)
    if r["exit"] == 0:
        return {"ok": True, "result": r["out"].strip()[:MAX_OUTPUT] or "npm {} completed.".format(cmd)}
    return {"ok": False, "result": "npm {} failed:\n{}".format(cmd, r["out"][:MAX_OUTPUT])}


def action_pip(params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = str(params.get("command", "list"))
    r = run_cmd(["pip", *cmd.split()], timeout=120)
    if r["exit"] == 0:
        return {"ok": True, "result": r["out"].strip()[:MAX_OUTPUT] or "pip {} completed.".format(cmd)}
    return {"ok": False, "result": "pip {} failed:\n{}".format(cmd, r["out"][:MAX_OUTPUT])}


def action_ping(params: Dict[str, Any]) -> Dict[str, Any]:
    host = str(params.get("host", "google.com"))
    count = validate_int(params.get("count", 3), 1, 20)
    r = run_cmd(["ping", "-c", str(count), host], timeout=15)
    if r["exit"] != 0 and sys.platform == "win32":
        r = run_cmd(["ping", "-n", str(count), host], timeout=15)
    out = r["out"].strip()
    lines = out.split("\n")
    summary = [l for l in lines if "avg" in l.lower() or "packets" in l.lower() or "min" in l.lower()]
    if summary:
        return {"ok": True, "result": "Ping {}:\n{}".format(host, "\n".join(summary))}
    return {"ok": True, "result": "Ping {}:\n{}".format(host, out[:500])}


def action_process_list(params: Dict[str, Any]) -> Dict[str, Any]:
    filter_name = str(params.get("filter", ""))
    if sys.platform == "win32":
        if filter_name:
            r = run_cmd(["tasklist", "/FI", "IMAGENAME eq {}".format(filter_name)])
        else:
            r = run_cmd(["tasklist", "/FO", "TABLE"])
    else:
        if filter_name:
            r = run_cmd(["ps", "aux"])
            lines = [l for l in r["out"].split("\n") if filter_name in l and "grep" not in l]
            r = {"exit": 0, "out": "\n".join(lines), "cmd": "ps aux filter"}
        else:
            r = run_cmd(["ps", "aux", "--sort=-%mem"])
    return {"ok": True, "result": "Processes{}:\n{}".format(" ({})".format(filter_name) if filter_name else "", r["out"][:MAX_OUTPUT])}


def action_opencode(params: Dict[str, Any]) -> Dict[str, Any]:
    prompt = str(params.get("prompt", ""))
    cwd = str(params.get("cwd", WORKSPACE))
    timeout = validate_int(params.get("timeout", 300), 1, 600)
    if not prompt:
        return {"ok": False, "result": "Error: No prompt provided."}
    full_prompt = (
        "You are executing a task on the {} node.\n\n"
        "Task: {}\n\n"
        "Execute this task. Be concise.\n"
        "Do NOT push to git without approval.\n"
        "When done, summarize in 3-5 sentences.\n"
        "If dangerous, say NEEDS_APPROVAL: <what> | <why> and STOP.\n"
        "When finished, say TASK_COMPLETE: <summary>\n"
    ).format(NODE_NAME, prompt)
    env = build_sanitized_env()
    try:
        result = subprocess.run(
            [OPENCODE_BIN, "--prompt", full_prompt, "--non-interactive"],
            capture_output=True, text=True, timeout=timeout,
            cwd=cwd, env=env, shell=False,
        )
        output = redact_secrets((result.stdout or "") + (result.stderr or ""))
        # Strip markers
        output = output.replace("TASK_COMPLETE:", "").replace("NEEDS_APPROVAL:", "")
        return {"ok": True, "result": output[:MAX_OUTPUT]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "Timeout: AI session exceeded {}s".format(timeout)}
    except FileNotFoundError:
        return {"ok": False, "result": "Error: opencode not found at '{}'".format(OPENCODE_BIN)}
    except Exception as exc:
        return {"ok": False, "result": "Error: {}".format(exc)}


def action_multi(params: Dict[str, Any]) -> Dict[str, Any]:
    actions = params.get("actions", [])
    if not isinstance(actions, list) or not actions:
        return {"ok": False, "result": "Error: No actions provided."}
    results: List[str] = []
    stop_on_fail = bool(params.get("stop_on_fail", True))
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            results.append("Step {} SKIPPED (invalid action descriptor)".format(i + 1))
            if stop_on_fail:
                break
            continue
        sub_type = action.get("type", "shell")
        sub_params = action.get("params", {})
        depends = action.get("depends_on")
        if depends is not None:
            try:
                depends = int(depends)
            except (TypeError, ValueError):
                depends = None
        if depends is not None and 0 <= depends < len(results):
            prev_raw = results[depends]
            # prev_raw contains json.dumps of {"ok": bool, ...} with lowercase booleans
            if '"ok": false' in prev_raw:
                results.append("Step {} SKIPPED (dependency {} failed)".format(i + 1, depends))
                continue
        sub_result = execute_action(sub_type, sub_params)
        results.append("Step {} ({}):\n{}".format(i + 1, sub_type, json.dumps(sub_result)))
        if stop_on_fail and not sub_result.get("ok"):
            results.append("Pipeline stopped at step {} due to error.".format(i + 1))
            break
    return {"ok": True, "result": "\n".join(results)}


def action_close_browsers(params: Dict[str, Any]) -> Dict[str, Any]:
    browsers = ["chrome", "firefox", "msedge", "edge", "opera", "brave", "iexplore"]
    if sys.platform == "win32":
        for b in browsers:
            run_cmd(["taskkill", "/F", "/IM", "{}.exe".format(b), "/T"])
        time.sleep(2)
        check = run_cmd(["tasklist"])
        remaining = [l.strip() for l in check["out"].split("\n") if any(b in l.lower() for b in browsers)]
        if remaining:
            return {"ok": False, "result": "Some browsers still running:\n{}".format("\n".join(remaining[:10]))}
        return {"ok": True, "result": "All browsers closed successfully."}
    else:
        for b in browsers:
            run_cmd(["pkill", "-f", b])
        time.sleep(2)
        check = run_cmd(["ps", "aux"])
        count = len([l for l in check["out"].split("\n") if any(b in l.lower() for b in browsers) and "grep" not in l])
        if count > 0:
            return {"ok": False, "result": "Some browser processes still running ({} remaining).".format(count)}
        return {"ok": True, "result": "All browsers closed successfully."}


ACTION_MAP: Dict[str, Any] = {
    "shell": action_shell,
    "docker_ps": action_docker_ps,
    "docker_logs": action_docker_logs,
    "docker_stats": action_docker_stats,
    "docker_restart": action_docker_restart,
    "docker_compose": action_docker_compose,
    "file_read": action_file_read,
    "file_write": action_file_write,
    "file_list": action_file_list,
    "file_upload": action_file_upload,
    "db_query": action_db_query,
    "git": action_git,
    "git_clone": action_git_clone,
    "system_info": action_system_info,
    "health_check": action_health_check,
    "screenshot": action_screenshot,
    "network_diagnostic": action_network_diagnostic,
    "log_analysis": action_log_analysis,
    "process_monitor": action_process_monitor,
    "service": action_service,
    "npm": action_npm,
    "pip": action_pip,
    "ping": action_ping,
    "process_list": action_process_list,
    "close_browsers": action_close_browsers,
    "opencode": action_opencode,
    "multi": action_multi,
}


# =============================================================================
# ORCHESTRATION
# =============================================================================


def execute_action(action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch to the correct handler. Always returns {"ok": bool, "result": str}."""
    handler = ACTION_MAP.get(action_type)
    if not handler:
        available = ", ".join(sorted(ACTION_MAP.keys()))
        return {"ok": False, "result": "Error: Unknown action '{}'. Available: {}".format(action_type, available)}
    try:
        return handler(params)
    except Exception as exc:
        return {"ok": False, "result": "Error: {}".format(str(exc)[:300])}


def claim_task() -> Optional[Dict[str, Any]]:
    tasks = db_exec(
        "SELECT * FROM task_queue WHERE assigned_node = %s AND status = 'pending' ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
        (NODE_NAME,),
        fetch=True,
    )
    if not tasks:
        return None
    task = tasks[0]
    db_exec("UPDATE task_queue SET status = 'in_progress', started_at = NOW() WHERE id = %s", (task["id"],))
    return task


def finish_task(task_id: int, status: str, output: str) -> None:
    max_len = MAX_OUTPUT
    if '"image_base64"' in output or '"data_base64"' in output:
        max_len = 8000000
    safe_output = output[:max_len]
    db_exec(
        "UPDATE task_queue SET status = %s, output = %s, completed_at = NOW() WHERE id = %s",
        (status, safe_output, task_id),
    )
    db_exec(
        """
        INSERT INTO shared_memory (key, context_value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET context_value = %s, last_updated = NOW()
        """,
        ("task_result:{}".format(task_id), safe_output[:2000], safe_output[:2000]),
    )
    log("Task {} {}: {}".format(task_id, status, output[:100]), task_id=task_id)


def process_task(task: Dict[str, Any]) -> None:
    task_id = task["id"]
    intent = task["intent"]
    start_time = time.time()
    log("Processing task {}: {}".format(task_id, str(intent)[:80]), task_id=task_id)

    # Size limit on intent
    if len(str(intent).encode("utf-8")) > MAX_CONTENT_SIZE:
        finish_task(task_id, "failed", "Error: task intent exceeds max content size")
        METRICS.record("failed", (time.time() - start_time) * 1000)
        return

    try:
        task_data = json.loads(intent)
    except (json.JSONDecodeError, TypeError):
        task_data = {"type": "opencode", "params": {"prompt": str(intent)}}

    if isinstance(task_data, str):
        task_data = {"type": "opencode", "params": {"prompt": task_data}}

    action_type = task_data.get("type", "shell")
    params = task_data.get("params", {})
    description = task_data.get("description", str(intent)[:200])

    try:
        if is_dangerous(action_type, params):
            cmd_summary = json.dumps({
                "type": action_type,
                "params": {k: (v[:50] if isinstance(v, str) else v) for k, v in params.items()},
            })[:300]
            request_approval(task_id, "Execute {}".format(action_type), description, cmd_summary)
            approved = wait_for_approval(task_id, timeout=600)
            if not approved:
                finish_task(task_id, "cancelled", "Denied by operator: {}".format(description))
                METRICS.record("cancelled", (time.time() - start_time) * 1000)
                return
            db_exec("UPDATE task_queue SET status = 'in_progress' WHERE id = %s", (task_id,))

        result = execute_action(action_type, params)
        final_status = "completed" if result.get("ok") else "failed"
        result_text = redact_secrets(str(result.get("result", "")))
        finish_task(task_id, final_status, result_text)
        METRICS.record(final_status, (time.time() - start_time) * 1000)
    except Exception as exc:
        log("UNHANDLED EXCEPTION in process_task: {}".format(exc), task_id=task_id, level=logging.ERROR)
        try:
            finish_task(task_id, "failed", "Unhandled error: {}".format(redact_secrets(str(exc)))[:MAX_OUTPUT])
            METRICS.record("failed", (time.time() - start_time) * 1000)
        except Exception:
            pass


def poll_loop() -> None:
    log("W7SH Task Runner v4.0 started -- node={} interval={}s workspace={}".format(NODE_NAME, POLL_INTERVAL, WORKSPACE))
    db_exec(
        """
        INSERT INTO shared_memory (key, context_value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET context_value = %s, last_updated = NOW()
        """,
        (
            "runner_status:{}".format(NODE_NAME),
            json.dumps({
                "version": "4.0",
                "node": NODE_NAME,
                "status": "alive",
                "workspace": WORKSPACE,
                "pid": os.getpid(),
                "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "actions": list(ACTION_MAP.keys()),
            }),
            json.dumps({
                "version": "4.0",
                "node": NODE_NAME,
                "status": "alive",
                "workspace": WORKSPACE,
                "pid": os.getpid(),
                "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "actions": list(ACTION_MAP.keys()),
            }),
        ),
    )
    while running:
        try:
            task = claim_task()
            if task:
                process_task(task)
            else:
                time.sleep(POLL_INTERVAL)
        except Exception as exc:
            log("POLL ERROR: {}\n{}".format(exc, traceback.format_exc()), level=logging.ERROR)
            time.sleep(POLL_INTERVAL)


def shutdown(signum: int, frame: Any) -> None:
    global running
    running = False
    log("SHUTDOWN")


if __name__ == "__main__":
    if not HUB_DB_URL:
        print("FATAL: HUB_DB_URL env var required", file=sys.stderr)
        sys.exit(1)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    start_metrics_server()
    poll_loop()
