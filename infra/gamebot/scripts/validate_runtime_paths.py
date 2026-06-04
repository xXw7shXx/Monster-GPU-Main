#!/usr/bin/env python3
"""Validate gamebot DB-backed runtime paths against a staging DB."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeReplyTarget:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.photos: list[str] = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(str(text))
        return SimpleNamespace()

    async def reply_photo(self, photo=None, caption=None, **kwargs):
        self.photos.append(str(caption or ""))
        return SimpleNamespace()


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Validate mocked gamebot runtime paths.")
    parser.add_argument("--analytics-write", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("status=fail reason=database_url_unset")
        return 2

    from sqlalchemy import func, select

    from database.db import get_session
    from database.models import ActivityLog, GameCache, User
    from handlers import commands
    from services import ops_api
    from core.database import AsyncSessionLocal

    errors: list[str] = []

    free_target = FakeReplyTarget()
    free_result = await commands._send_free_page(free_target, "en", page=0, platform_filter="all", source_filter="all")
    print(f"free.total={free_result['total']}")
    print(f"free.cards={free_result['cards']}")
    print(f"free.messages={len(free_target.texts) + len(free_target.photos)}")
    if free_result["total"] <= 0 or free_result["cards"] <= 0:
        errors.append("free_empty")

    session = get_session()
    try:
        upcoming = session.query(GameCache).filter(
            GameCache.game_type == "upcoming",
            GameCache.status == "active",
        ).order_by(GameCache.release_date.asc()).limit(5).all()
        print(f"upcoming.rows={len(upcoming)}")
        if not upcoming:
            errors.append("upcoming_empty")

        search_seed = session.query(GameCache.title).filter(GameCache.title.isnot(None)).first()
        search_term = (search_seed[0].split()[0] if search_seed and search_seed[0] else "")
    finally:
        session.close()

    if search_term:
        found = commands._get_game_from_db_by_title(search_term)
        print("search.found=" + ("true" if found else "false"))
        if not found:
            errors.append("search_not_found")
    else:
        print("search.found=false")
        errors.append("search_seed_missing")

    if args.analytics_write:
        session = get_session()
        try:
            user = session.query(User).order_by(User.id.asc()).first()
            if user:
                before = session.query(func.count(ActivityLog.id)).scalar()
                log = ActivityLog(user_id=user.id, bot_id="gamebot", platform="staging", event_type="validation", event_name="postgres_readiness")
                session.add(log)
                session.commit()
                after = session.query(func.count(ActivityLog.id)).scalar()
                print(f"analytics.before={before}")
                print(f"analytics.after={after}")
                if after != before + 1:
                    errors.append("analytics_write_count")
            else:
                print("analytics.skipped=no_user")
                errors.append("analytics_no_user")
        except Exception as exc:
            session.rollback()
            print(f"analytics.error={type(exc).__name__}")
            errors.append("analytics_write_error")
        finally:
            session.close()

    dashboard = await ops_api.get_ops_dashboard(api_key="validation")
    users = await ops_api.get_users_list(api_key="validation")
    queue = await ops_api.get_content_queue(api_key="validation")
    print(f"ops.dashboard_status={dashboard.get('system_health', {}).get('status', 'missing')}")
    print(f"ops.users={len(users)}")
    print(f"ops.content_queue={len(queue)}")
    if not users:
        errors.append("ops_users_empty")

    async with AsyncSessionLocal() as async_session:
        active_count = (await async_session.execute(select(func.count(GameCache.id)).where(GameCache.status == "active"))).scalar_one()
        print(f"async.active_rows={active_count}")
        if active_count <= 0:
            errors.append("async_active_empty")

    if errors:
        print("status=fail")
        for error in errors:
            print(f"error={error}")
        return 2
    print("status=ok")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
