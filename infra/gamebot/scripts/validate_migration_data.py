#!/usr/bin/env python3
"""Validate gamebot PostgreSQL migrated data without printing secrets."""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import sqlalchemy as sa

from database.schema import Base
from database.url import derive_sync_database_url


MIGRATED_TABLES = [
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


def sqlite_count(conn: sqlite3.Connection, table_name: str) -> int:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if cur.fetchone() is None:
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate migrated gamebot PostgreSQL data.")
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--database-url-env", default="GAMEBOT_PG_TARGET_URL")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    raw_url = os.environ.get(args.database_url_env)
    if not sqlite_path.exists():
        print(f"status=fail reason=sqlite_missing path={sqlite_path}")
        return 2
    if not raw_url:
        print(f"status=fail reason=env_unset env={args.database_url_env}")
        return 2

    errors: list[str] = []
    sqlite_conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    engine = sa.create_engine(derive_sync_database_url(raw_url), future=True)
    try:
        with engine.connect() as conn:
            for table_name in MIGRATED_TABLES:
                table = Base.metadata.tables[table_name]
                src = sqlite_count(sqlite_conn, table_name)
                dst = conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
                print(f"count.{table_name}.sqlite={src}")
                print(f"count.{table_name}.postgres={dst}")
                if src != dst:
                    errors.append(f"count_mismatch:{table_name}:{src}!={dst}")

            oauth_table = Base.metadata.tables["oauth_tokens_v2"]
            oauth_count = conn.execute(sa.select(sa.func.count()).select_from(oauth_table)).scalar_one()
            print(f"count.oauth_tokens_v2.postgres={oauth_count}")
            if oauth_count != 0:
                errors.append("oauth_tokens_not_empty")

            duplicate_external = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM (SELECT external_id FROM game_cache_v2 "
                    "GROUP BY external_id HAVING COUNT(*) > 1) d"
                )
            ).scalar_one()
            null_external = conn.execute(
                sa.text("SELECT COUNT(*) FROM game_cache_v2 WHERE external_id IS NULL OR btrim(external_id) = ''")
            ).scalar_one()
            active_free = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM game_cache_v2 "
                    "WHERE game_type = 'free' AND current_price = 0 AND status = 'active'"
                )
            ).scalar_one()
            active_upcoming = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM game_cache_v2 "
                    "WHERE game_type = 'upcoming' AND status = 'active'"
                )
            ).scalar_one()
            active_mobile = conn.execute(
                sa.text("SELECT COUNT(*) FROM game_cache_v2 WHERE platform_type = 'Mobile' AND status = 'active'")
            ).scalar_one()
            users_created_at_null = conn.execute(sa.text("SELECT COUNT(*) FROM users WHERE created_at IS NULL")).scalar_one()
            pref_orphans = conn.execute(
                sa.text("SELECT COUNT(*) FROM preferences p LEFT JOIN users u ON u.id=p.user_id WHERE u.id IS NULL")
            ).scalar_one()
            activity_orphans = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM activity_logs a LEFT JOIN users u ON u.id=a.user_id "
                    "WHERE a.user_id IS NOT NULL AND u.id IS NULL"
                )
            ).scalar_one()
            queue_orphans = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM content_queue c LEFT JOIN game_cache_v2 g ON g.id=c.game_id "
                    "WHERE c.game_id IS NOT NULL AND g.id IS NULL"
                )
            ).scalar_one()

            checks = {
                "duplicate_external_id_groups": duplicate_external,
                "null_empty_external_id": null_external,
                "active_free_rows": active_free,
                "active_upcoming_rows": active_upcoming,
                "active_mobile_rows": active_mobile,
                "users_created_at_null": users_created_at_null,
                "preferences_orphans": pref_orphans,
                "activity_orphans": activity_orphans,
                "content_queue_orphans": queue_orphans,
            }
            for key, value in checks.items():
                print(f"check.{key}={value}")

            if duplicate_external:
                errors.append("duplicate_external_id")
            if null_external:
                errors.append("null_external_id")
            if active_free <= 0:
                errors.append("no_active_free_rows")
            if users_created_at_null:
                errors.append("users_created_at_null")
            if pref_orphans or activity_orphans or queue_orphans:
                errors.append("fk_orphans")

        if errors:
            print("status=fail")
            for error in errors:
                print(f"error={error}")
            return 2
        print("status=ok")
        return 0
    finally:
        sqlite_conn.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
