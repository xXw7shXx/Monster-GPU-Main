#!/usr/bin/env python3
"""Validate gamebot DB URL derivation without printing secrets."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.url import (  # noqa: E402
    database_name,
    database_dialect_name,
    derive_async_database_url,
    derive_sync_database_url,
    redacted_url,
    resolve_database_urls,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate safe DB URL derivation.")
    parser.add_argument("--database-url", help="DATABASE_URL value. If omitted, env/default is used.")
    parser.add_argument("--database-url-env", help="Read DATABASE_URL from this env var name.")
    parser.add_argument("--async-database-url", help="Optional explicit async URL override.")
    parser.add_argument("--sync-database-url", help="Optional explicit sync URL override.")
    parser.add_argument("--expect-mode", choices=("sqlite", "postgresql"))
    parser.add_argument("--show-redacted", action="store_true", help="Print redacted URLs only.")
    args = parser.parse_args()

    env = dict(os.environ)
    source = None

    if args.database_url_env:
        if args.database_url_env not in env or not env[args.database_url_env]:
            print(f"status=fail reason=env_var_unset env_var={args.database_url_env}")
            return 2
        env["DATABASE_URL"] = env[args.database_url_env]
        source = f"env:{args.database_url_env}"

    if args.database_url:
        env["DATABASE_URL"] = args.database_url
        source = "cli"

    if args.async_database_url:
        env["ASYNC_DATABASE_URL"] = args.async_database_url
    if args.sync_database_url:
        env["SYNC_DATABASE_URL"] = args.sync_database_url

    resolved = resolve_database_urls(env)
    if source is not None:
        resolved = resolved.__class__(
            raw_source=source,
            mode=database_dialect_name(env["DATABASE_URL"]),
            database_url=env["DATABASE_URL"],
            async_database_url=derive_async_database_url(env["DATABASE_URL"], env.get("ASYNC_DATABASE_URL")),
            sync_database_url=derive_sync_database_url(env["DATABASE_URL"], env.get("SYNC_DATABASE_URL")),
        )

    if args.expect_mode and resolved.mode != args.expect_mode:
        print(f"status=fail expected_mode={args.expect_mode} actual_mode={resolved.mode}")
        return 2

    print("status=ok")
    print(f"source={resolved.raw_source}")
    print(f"mode={resolved.mode}")
    print(f"database_name={database_name(resolved.database_url) or '<none>'}")
    print(f"async_scheme={resolved.async_database_url.split(':', 1)[0]}")
    print(f"sync_scheme={resolved.sync_database_url.split(':', 1)[0]}")
    if args.show_redacted:
        print(f"database_url={redacted_url(resolved.database_url)}")
        print(f"async_database_url={redacted_url(resolved.async_database_url)}")
        print(f"sync_database_url={redacted_url(resolved.sync_database_url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
