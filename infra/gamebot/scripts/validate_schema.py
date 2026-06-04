#!/usr/bin/env python3
"""Read-only schema validator for gamebot SQLite/PostgreSQL targets."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.url import (  # noqa: E402
    database_dialect_name,
    derive_sync_database_url,
    redacted_url,
    resolve_database_urls,
    sqlite_path_from_url,
)


REQUIRED_TABLES = {
    "users": {"id", "telegram_id", "tiktok_id", "username", "platform", "created_at"},
    "preferences": {
        "id",
        "user_id",
        "language",
        "notify_daily_releases",
        "notify_free_games",
        "notify_leaving_games",
        "platform_pc",
        "platform_ps",
        "platform_xbox",
        "platform_switch",
        "platform_mobile",
        "favorite_platforms",
        "favorite_sources",
        "favorite_genres",
        "liked_game_ids",
        "disliked_game_ids",
        "watchlist_game_ids",
        "intent_history",
    },
    "activity_logs": {"id", "user_id", "platform", "event_type", "event_name", "timestamp"},
    "api_cache": {"id", "endpoint", "query_params", "response_data", "timestamp"},
    "api_limits_v2": {"id", "service_name", "call_count", "reset_at"},
    "game_cache_v2": {
        "id",
        "external_id",
        "title",
        "platforms",
        "original_price",
        "current_price",
        "release_date",
        "expiry_date",
        "store_link",
        "image_url",
        "source_name",
        "game_type",
        "platform_type",
        "monetization_tags",
        "is_limited_time",
        "status",
        "critic_score",
        "critic_tier",
        "last_score_sync",
        "last_updated",
        "thumbnail_url",
        "hype_score",
        "cost_per_deal",
        "click_count",
        "vibe_tag",
    },
    "maintenance_logs": {"id", "action_type", "timestamp", "rows_affected", "db_size_before", "db_size_after", "status"},
    "notified_deals": {"id", "deal_id", "platform", "timestamp"},
    "oauth_tokens_v2": {"id", "service_name", "access_token", "expires_at"},
    "sync_history": {"id", "source_name", "timestamp", "status", "error_message", "items_synced"},
    "content_queue": {"id", "game_id", "title", "tiktok_script", "telegram_caption", "status", "created_at"},
    "alembic_version": {"version_num"},
}

OPTIONAL_COLUMNS = {
    "activity_logs": {"bot_id"},
    "game_cache_v2": {"trailer_url"},
    "content_queue": {"vibe_tag", "trend_priority"},
}

REQUIRED_UNIQUES = {
    "users": (("telegram_id",), ("tiktok_id",)),
    "game_cache_v2": (("external_id",),),
    "api_limits_v2": (("service_name",),),
    "notified_deals": (("deal_id",),),
    "oauth_tokens_v2": (("service_name",),),
}

POSTGRES_ONLY_UNIQUES = {
    "preferences": (("user_id",),),
}

REQUIRED_FKS = {
    "preferences": (("user_id", "users", "id"),),
    "activity_logs": (("user_id", "users", "id"),),
    "content_queue": (("game_id", "game_cache_v2", "id"),),
}

SQLITE_REQUIRED_INDEXES = {
    "game_cache_v2": {
        "idx_game_type",
        "idx_release_date",
        "idx_title",
        "idx_ltf",
        "idx_status",
        "idx_expiry",
        "idx_platform_type",
    },
}

POSTGRES_REQUIRED_INDEXES = {
    **SQLITE_REQUIRED_INDEXES,
    "game_cache_v2": SQLITE_REQUIRED_INDEXES["game_cache_v2"]
    | {"idx_game_free_lookup", "idx_game_upcoming_lookup"},
    "activity_logs": {"idx_activity_logs_timestamp", "idx_activity_logs_event_type", "idx_activity_logs_platform"},
    "sync_history": {"idx_sync_history_timestamp"},
}


class ValidationResult:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def _sorted_tuple(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


def _sqlite_connect_readonly(url: str):
    path = sqlite_path_from_url(url)
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True), str(db_path)


def validate_sqlite(url: str) -> tuple[ValidationResult, str]:
    result = ValidationResult()
    conn, target = _sqlite_connect_readonly(url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        for table, required_columns in REQUIRED_TABLES.items():
            if table not in tables:
                result.error(f"missing_table:{table}")
                continue
            cur.execute(f"PRAGMA table_info({table})")
            columns = {row[1] for row in cur.fetchall()}
            missing = required_columns - columns
            if missing:
                result.error(f"missing_columns:{table}:{','.join(sorted(missing))}")
            optional_missing = OPTIONAL_COLUMNS.get(table, set()) - columns
            if optional_missing:
                result.warn(f"optional_columns_missing:{table}:{','.join(sorted(optional_missing))}")

        for table, expected_uniques in REQUIRED_UNIQUES.items():
            if table not in tables:
                continue
            cur.execute(f"PRAGMA index_list({table})")
            unique_indexes = [row[1] for row in cur.fetchall() if row[2]]
            unique_columns = set()
            for index_name in unique_indexes:
                cur.execute(f"PRAGMA index_info({index_name})")
                unique_columns.add(tuple(row[2] for row in cur.fetchall()))
            for expected in expected_uniques:
                if expected not in unique_columns:
                    result.error(f"missing_unique:{table}:{','.join(expected)}")

        for table, expected_fks in REQUIRED_FKS.items():
            if table not in tables:
                continue
            cur.execute(f"PRAGMA foreign_key_list({table})")
            fks = {(row[3], row[2], row[4]) for row in cur.fetchall()}
            for expected in expected_fks:
                if expected not in fks:
                    result.error(f"missing_fk:{table}:{expected[0]}->{expected[1]}.{expected[2]}")

        for table, expected_indexes in SQLITE_REQUIRED_INDEXES.items():
            if table not in tables:
                continue
            cur.execute(f"PRAGMA index_list({table})")
            indexes = {row[1] for row in cur.fetchall()}
            for expected in expected_indexes:
                if expected not in indexes:
                    result.error(f"missing_index:{table}:{expected}")
    finally:
        conn.close()
    return result, target


def _postgres_connect(url: str):
    sync_url = derive_sync_database_url(url)
    parts = urlsplit(sync_url)
    driverless = urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))
    try:
        import psycopg2  # type: ignore

        return psycopg2.connect(driverless)
    except ImportError:
        try:
            import psycopg  # type: ignore

            return psycopg.connect(driverless)
        except ImportError as exc:
            raise RuntimeError("postgres_driver_missing: install psycopg2-binary or psycopg[binary]") from exc


def validate_postgres(url: str, schema: str) -> tuple[ValidationResult, str]:
    result = ValidationResult()
    conn = _postgres_connect(url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            """,
            (schema,),
        )
        tables = {row[0] for row in cur.fetchall()}
        for table, required_columns in REQUIRED_TABLES.items():
            if table not in tables:
                result.error(f"missing_table:{table}")
                continue
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            columns = {row[0] for row in cur.fetchall()}
            missing = required_columns - columns
            if missing:
                result.error(f"missing_columns:{table}:{','.join(sorted(missing))}")
            optional_missing = OPTIONAL_COLUMNS.get(table, set()) - columns
            if optional_missing:
                result.warn(f"optional_columns_missing:{table}:{','.join(sorted(optional_missing))}")

        expected_uniques = {**REQUIRED_UNIQUES}
        for table, values in POSTGRES_ONLY_UNIQUES.items():
            expected_uniques[table] = expected_uniques.get(table, tuple()) + values
        for table, expected_sets in expected_uniques.items():
            if table not in tables:
                continue
            cur.execute(
                """
                SELECT array_agg(a.attname ORDER BY cols.ordinality)
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN unnest(c.conkey) WITH ORDINALITY AS cols(attnum, ordinality) ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = cols.attnum
                WHERE n.nspname = %s
                  AND t.relname = %s
                  AND c.contype = 'u'
                GROUP BY c.oid
                """,
                (schema, table),
            )
            unique_columns = {tuple(row[0]) for row in cur.fetchall()}
            for expected in expected_sets:
                if expected not in unique_columns:
                    result.error(f"missing_unique:{table}:{','.join(expected)}")

        for table, expected_fks in REQUIRED_FKS.items():
            if table not in tables:
                continue
            cur.execute(
                """
                SELECT kcu.column_name, ccu.table_name, ccu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.table_schema = %s
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'FOREIGN KEY'
                """,
                (schema, table),
            )
            fks = {(row[0], row[1], row[2]) for row in cur.fetchall()}
            for expected in expected_fks:
                if expected not in fks:
                    result.error(f"missing_fk:{table}:{expected[0]}->{expected[1]}.{expected[2]}")

        for table, expected_indexes in POSTGRES_REQUIRED_INDEXES.items():
            if table not in tables:
                continue
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = %s AND tablename = %s
                """,
                (schema, table),
            )
            indexes = {row[0] for row in cur.fetchall()}
            for expected in expected_indexes:
                if expected not in indexes:
                    result.error(f"missing_index:{table}:{expected}")
    finally:
        conn.close()
    return result, schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate gamebot DB schema without changing data.")
    parser.add_argument("--database-url", help="DATABASE_URL value. If omitted, env/default is used.")
    parser.add_argument("--database-url-env", help="Read DATABASE_URL from this env var name.")
    parser.add_argument("--expect-mode", choices=("sqlite", "postgresql"))
    parser.add_argument("--schema", default="public", help="PostgreSQL schema name.")
    parser.add_argument("--show-redacted", action="store_true", help="Print redacted URL only.")
    args = parser.parse_args()

    env = dict(os.environ)
    if args.database_url_env:
        if args.database_url_env not in env or not env[args.database_url_env]:
            print(f"status=skip reason=env_var_unset env_var={args.database_url_env}")
            return 0
        env["DATABASE_URL"] = env[args.database_url_env]
    if args.database_url:
        env["DATABASE_URL"] = args.database_url

    resolved = resolve_database_urls(env)
    mode = database_dialect_name(resolved.database_url)
    if args.expect_mode and mode != args.expect_mode:
        print(f"status=fail expected_mode={args.expect_mode} actual_mode={mode}")
        return 2

    try:
        if mode == "sqlite":
            result, target = validate_sqlite(resolved.sync_database_url)
        elif mode == "postgresql":
            result, target = validate_postgres(resolved.sync_database_url, args.schema)
        else:
            print(f"status=fail reason=unsupported_mode mode={mode}")
            return 2
    except Exception as exc:
        print(f"status=fail reason={type(exc).__name__}:{exc}")
        return 2

    print("status=ok" if result.ok else "status=fail")
    print(f"mode={mode}")
    print(f"target={target}")
    if args.show_redacted:
        print(f"database_url={redacted_url(resolved.database_url)}")
    print(f"errors={len(result.errors)}")
    for error in result.errors:
        print(f"error={error}")
    print(f"warnings={len(result.warnings)}")
    for warning in result.warnings:
        print(f"warning={warning}")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
