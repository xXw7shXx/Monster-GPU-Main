"""Database URL helpers for safe SQLite/PostgreSQL readiness checks.

This module deliberately avoids importing application settings. It only parses
and derives URLs passed by callers or present in the process environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///bot_data.db"


@dataclass(frozen=True)
class DatabaseUrlResolution:
    raw_source: str
    mode: str
    database_url: str
    async_database_url: str
    sync_database_url: str


def _normalize_scheme(url: str) -> str:
    return urlsplit(url).scheme.lower()


def is_sqlite_url(url: str | None) -> bool:
    return bool(url) and _normalize_scheme(url).startswith("sqlite")


def is_postgres_url(url: str | None) -> bool:
    if not url:
        return False
    scheme = _normalize_scheme(url)
    return scheme == "postgres" or scheme.startswith("postgresql")


def database_dialect_name(url: str | None) -> str:
    if is_sqlite_url(url):
        return "sqlite"
    if is_postgres_url(url):
        return "postgresql"
    return "unknown"


def _replace_scheme(url: str, scheme: str) -> str:
    current_scheme = url.split(":", 1)[0]
    return f"{scheme}{url[len(current_scheme):]}"


def derive_sync_database_url(database_url: str, explicit_sync_url: str | None = None) -> str:
    """Return a sync SQLAlchemy-compatible URL without logging credentials."""

    if explicit_sync_url:
        return explicit_sync_url

    scheme = _normalize_scheme(database_url)
    if scheme == "sqlite+aiosqlite":
        return _replace_scheme(database_url, "sqlite")
    if scheme == "sqlite":
        return database_url
    if scheme in {"postgres", "postgresql", "postgresql+asyncpg"}:
        return _replace_scheme(database_url, "postgresql+psycopg2")
    if scheme in {"postgresql+psycopg2", "postgresql+psycopg"}:
        return database_url
    return database_url


def derive_async_database_url(database_url: str, explicit_async_url: str | None = None) -> str:
    """Return an async SQLAlchemy-compatible URL without logging credentials."""

    if explicit_async_url:
        return explicit_async_url

    scheme = _normalize_scheme(database_url)
    if scheme == "sqlite":
        return _replace_scheme(database_url, "sqlite+aiosqlite")
    if scheme == "sqlite+aiosqlite":
        return database_url
    if scheme in {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}:
        return _replace_scheme(database_url, "postgresql+asyncpg")
    if scheme == "postgresql+asyncpg":
        return database_url
    return database_url


def resolve_database_urls(env: Mapping[str, str] | None = None) -> DatabaseUrlResolution:
    source_env = os.environ if env is None else env
    raw = source_env.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    raw_source = "env:DATABASE_URL" if source_env.get("DATABASE_URL") else "default"
    async_url = derive_async_database_url(raw, source_env.get("ASYNC_DATABASE_URL"))
    sync_url = derive_sync_database_url(raw, source_env.get("SYNC_DATABASE_URL"))
    return DatabaseUrlResolution(
        raw_source=raw_source,
        mode=database_dialect_name(raw),
        database_url=raw,
        async_database_url=async_url,
        sync_database_url=sync_url,
    )


def redacted_url(url: str | None) -> str:
    """Redact credential material while preserving enough shape for debugging."""

    if not url:
        return "<unset>"

    parts = urlsplit(url)
    if parts.scheme.startswith("sqlite"):
        return url

    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"<credentials>@{host}{port}" if parts.username or parts.password else f"{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def database_name(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme.startswith("sqlite"):
        return sqlite_path_from_url(url)
    return parts.path.lstrip("/")


def sqlite_path_from_url(url: str) -> str:
    """Resolve a SQLAlchemy SQLite URL into a filesystem path string."""

    clean = url.split("?", 1)[0]
    for prefix in ("sqlite+aiosqlite:////", "sqlite:////"):
        if clean.startswith(prefix):
            return "/" + clean[len(prefix):]
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if clean.startswith(prefix):
            return clean[len(prefix):]
    raise ValueError("Unsupported SQLite URL format")
