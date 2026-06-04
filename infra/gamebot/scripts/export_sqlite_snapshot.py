#!/usr/bin/env python3
"""Create a consistent SQLite snapshot for gamebot migration."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SOURCE = "/mnt/data/gamer_alert/db/bot_data.db"
DEFAULT_BACKUP_DIR = "/root/backups/gamebot_postgres_cutover"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create read-only SQLite backup snapshot.")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--label", default="snapshot")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        print(f"status=fail reason=source_missing source={source}")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(args.backup_dir) / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"bot_data_{args.label}_{stamp}.db"

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    print("status=ok")
    print(f"snapshot_path={target}")
    print(f"snapshot_size={target.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
