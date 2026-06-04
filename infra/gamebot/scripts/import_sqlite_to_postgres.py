#!/usr/bin/env python3
"""Import a gamebot SQLite snapshot into a clean PostgreSQL target."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from typing import Any

import sqlalchemy as sa

from database.schema import Base
from database.url import derive_sync_database_url


IMPORT_TABLES = [
    "users",
    "preferences",
    "game_cache_v2",
    "activity_logs",
    "api_cache",
    "api_limits_v2",
    "maintenance_logs",
    "notified_deals",
    "sync_history",
    "content_queue",
]

BOOLEAN_COLUMNS = {
    "notify_daily_releases",
    "notify_free_games",
    "notify_leaving_games",
    "platform_pc",
    "platform_ps",
    "platform_xbox",
    "platform_switch",
    "platform_mobile",
    "is_limited_time",
}

DATETIME_COLUMNS = {
    "created_at",
    "timestamp",
    "release_date",
    "expiry_date",
    "last_score_sync",
    "last_updated",
    "reset_at",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import gamebot SQLite snapshot into PostgreSQL.")
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--database-url-env", default="GAMEBOT_PG_TARGET_URL")
    parser.add_argument("--backfill-timestamp")
    parser.add_argument("--allow-nonempty", action="store_true")
    return parser.parse_args()


def parse_datetime(value: Any, fallback: datetime | None = None) -> datetime | None:
    if value in (None, ""):
        return fallback
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return fallback
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return fallback


def normalize_api_cache_timestamp(value: Any, backfill: datetime) -> int:
    if value in (None, ""):
        return int(backfill.timestamp())
    try:
        return int(float(value))
    except (TypeError, ValueError):
        parsed = parse_datetime(value, backfill)
        return int((parsed or backfill).timestamp())


def normalize_value(table_name: str, column_name: str, value: Any, backfill: datetime) -> Any:
    if column_name in BOOLEAN_COLUMNS and value is not None:
        return bool(value)
    if table_name == "api_cache" and column_name == "timestamp":
        return normalize_api_cache_timestamp(value, backfill)
    if column_name in DATETIME_COLUMNS:
        fallback = backfill if table_name == "users" and column_name == "created_at" else None
        return parse_datetime(value, fallback)
    return value


def sqlite_rows(conn: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cur.fetchone() is None:
        return []
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f'SELECT * FROM "{table_name}"')
    return list(cur.fetchall())


def main() -> int:
    args = parse_args()
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"status=fail reason=sqlite_missing path={sqlite_path}")
        return 2

    raw_url = os.environ.get(args.database_url_env)
    if not raw_url:
        print(f"status=fail reason=env_unset env={args.database_url_env}")
        return 2

    backfill = parse_datetime(args.backfill_timestamp) if args.backfill_timestamp else datetime.now(timezone.utc).replace(tzinfo=None)
    engine = sa.create_engine(derive_sync_database_url(raw_url), future=True)
    sqlite_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    sqlite_conn.row_factory = sqlite3.Row

    imported: dict[str, int] = {}
    backfilled_users_created_at = 0

    try:
        with engine.begin() as pg:
            for table_name in IMPORT_TABLES:
                table = Base.metadata.tables[table_name]
                existing = pg.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
                if existing and not args.allow_nonempty:
                    print(f"status=fail reason=target_not_empty table={table_name} rows={existing}")
                    return 2

            for table_name in IMPORT_TABLES:
                table = Base.metadata.tables[table_name]
                target_columns = set(table.columns.keys())
                rows = sqlite_rows(sqlite_conn, table_name)
                payloads = []
                for row in rows:
                    payload = {}
                    for column_name in row.keys():
                        if column_name not in target_columns:
                            continue
                        value = row[column_name]
                        if table_name == "users" and column_name == "created_at" and value in (None, ""):
                            backfilled_users_created_at += 1
                        payload[column_name] = normalize_value(table_name, column_name, value, backfill)
                    payloads.append(payload)
                if payloads:
                    pg.execute(table.insert(), payloads)
                imported[table_name] = len(payloads)

            for table_name in IMPORT_TABLES + ["oauth_tokens_v2"]:
                table = Base.metadata.tables.get(table_name)
                if table is None or "id" not in table.columns:
                    continue
                pg.execute(
                    sa.text(
                        "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                        "GREATEST(COALESCE((SELECT MAX(id) FROM "
                        + table_name
                        + "), 0), 1), "
                        "COALESCE((SELECT MAX(id) FROM "
                        + table_name
                        + "), 0) > 0)"
                    ),
                    {"table_name": table_name},
                )

        print("status=ok")
        print(f"sqlite_snapshot={sqlite_path}")
        for table_name in IMPORT_TABLES:
            print(f"imported.{table_name}={imported.get(table_name, 0)}")
        print("skipped.oauth_tokens_v2=credential_bearing")
        print(f"backfilled.users_created_at={backfilled_users_created_at}")
        return 0
    finally:
        sqlite_conn.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
