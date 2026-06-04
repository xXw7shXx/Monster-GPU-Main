from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.schema import Base  # noqa: E402
from database.url import (  # noqa: E402
    database_dialect_name,
    derive_sync_database_url,
    redacted_url,
)


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _x_args() -> dict[str, str]:
    return context.get_x_argument(as_dictionary=True)


def _migration_database_url() -> str:
    x_args = _x_args()
    if x_args.get("database_url_env"):
        env_name = x_args["database_url_env"]
        value = os.environ.get(env_name)
        if not value:
            raise RuntimeError(f"database URL env var is not set: {env_name}")
        return value

    if x_args.get("database_url"):
        return x_args["database_url"]

    return os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///bot_data.db"


def _sync_url() -> str:
    x_args = _x_args()
    explicit_sync_url = None

    if x_args.get("sync_database_url_env"):
        env_name = x_args["sync_database_url_env"]
        explicit_sync_url = os.environ.get(env_name)
        if not explicit_sync_url:
            raise RuntimeError(f"sync database URL env var is not set: {env_name}")
    elif x_args.get("sync_database_url"):
        explicit_sync_url = x_args["sync_database_url"]
    elif not (x_args.get("database_url_env") or x_args.get("database_url")):
        explicit_sync_url = os.environ.get("SYNC_DATABASE_URL")

    return derive_sync_database_url(_migration_database_url(), explicit_sync_url)


def _dialect_name(url: str) -> str:
    return database_dialect_name(url)


def _configure_context(connection=None, url: str | None = None) -> None:
    target_url = url or str(connection.engine.url)
    dialect = _dialect_name(target_url)
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"} if connection is None else None,
        render_as_batch=dialect == "sqlite",
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    url = _sync_url()
    try:
        _configure_context(url=url)
        with context.begin_transaction():
            context.run_migrations()
    except Exception as exc:
        safe_url = redacted_url(url)
        raise RuntimeError(f"Alembic offline migration setup failed for {safe_url}: {exc}") from exc


def run_migrations_online() -> None:
    url = _sync_url()
    try:
        connectable = create_engine(url, poolclass=pool.NullPool)
        with connectable.connect() as connection:
            _configure_context(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    except Exception as exc:
        safe_url = redacted_url(url)
        raise RuntimeError(f"Alembic online migration setup failed for {safe_url}: {exc}") from exc


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
