#!/usr/bin/env python3
"""Validate PostgreSQL driver availability without opening DB connections."""

from __future__ import annotations

import argparse
import importlib
import sys


def import_status(module_name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"
    version = getattr(module, "__version__", "unknown")
    return True, str(version)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate PostgreSQL driver imports and SQLAlchemy dialect loading."
    )
    parser.add_argument(
        "--no-engine-check",
        action="store_true",
        help="Only import modules; do not instantiate SQLAlchemy engines.",
    )
    parser.add_argument(
        "--allow-psycopg3",
        action="store_true",
        help="Accept psycopg v3 if psycopg2 is unavailable.",
    )
    args = parser.parse_args()

    failures: list[str] = []

    sqlalchemy_ok, sqlalchemy_info = import_status("sqlalchemy")
    print(f"sqlalchemy={'ok' if sqlalchemy_ok else 'missing'} info={sqlalchemy_info}")
    if not sqlalchemy_ok:
        failures.append("sqlalchemy")

    asyncpg_ok, asyncpg_info = import_status("asyncpg")
    print(f"asyncpg={'ok' if asyncpg_ok else 'missing'} info={asyncpg_info}")
    if not asyncpg_ok:
        failures.append("asyncpg")

    psycopg2_ok, psycopg2_info = import_status("psycopg2")
    print(f"psycopg2={'ok' if psycopg2_ok else 'missing'} info={psycopg2_info}")

    psycopg_ok = False
    psycopg_info = "not_checked"
    if args.allow_psycopg3:
        psycopg_ok, psycopg_info = import_status("psycopg")
        print(f"psycopg={'ok' if psycopg_ok else 'missing'} info={psycopg_info}")

    if not psycopg2_ok and not (args.allow_psycopg3 and psycopg_ok):
        failures.append("sync_postgres_driver")

    if sqlalchemy_ok and not args.no_engine_check:
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.ext.asyncio import create_async_engine

            sync_url = "postgresql+psycopg2://HOST/DBNAME"
            if not psycopg2_ok and args.allow_psycopg3 and psycopg_ok:
                sync_url = "postgresql+psycopg://example.invalid:5432/gamebot_driver_check"
            sync_engine = create_engine(sync_url, pool_pre_ping=True)
            sync_engine.dispose()
            print("sync_sqlalchemy_dialect=ok")
        except Exception as exc:
            print(f"sync_sqlalchemy_dialect=fail info={type(exc).__name__}:{exc}")
            failures.append("sync_sqlalchemy_dialect")

        try:
            async_engine = create_async_engine(
                "postgresql+asyncpg://HOST/DBNAME",
                pool_pre_ping=True,
            )
            try:
                import asyncio

                asyncio.run(async_engine.dispose())
            except TypeError:
                async_engine.sync_engine.dispose()
            print("async_sqlalchemy_dialect=ok")
        except Exception as exc:
            print(f"async_sqlalchemy_dialect=fail info={type(exc).__name__}:{exc}")
            failures.append("async_sqlalchemy_dialect")

    if failures:
        print(f"status=fail failures={','.join(failures)}")
        return 2

    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
