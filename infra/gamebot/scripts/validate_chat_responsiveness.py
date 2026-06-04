#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace


tmp_db = Path(tempfile.gettempdir()) / "gamebot_chat_responsiveness_validation.db"
if tmp_db.exists():
    tmp_db.unlink()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_db}"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "validation-token")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.db import get_session, init_db  # noqa: E402
from database.models import GameCache  # noqa: E402
from handlers.commands import (  # noqa: E402
    free_callback,
    free_command,
    mobile_command,
    natural_language_message,
    search_command,
    start_command,
    upcoming_command,
)
from handlers.settings import settings_callback  # noqa: E402
from utils.middleware import user_rates  # noqa: E402


class FakeBot:
    def __init__(self):
        self.actions = []

    async def send_chat_action(self, chat_id, action):
        self.actions.append((chat_id, action))


class FakeMessage:
    def __init__(self, text: str = "", fail_photo: bool = False):
        self.text = text
        self.fail_photo = fail_photo
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(("text", text, kwargs))

    async def reply_photo(self, photo, caption=None, **kwargs):
        if self.fail_photo:
            raise RuntimeError("simulated invalid telegram image")
        self.replies.append(("photo", caption or "", kwargs))


class FakeCallbackQuery:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answered = False
        self.edits = []

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(("text", text, kwargs))

    async def edit_message_reply_markup(self, **kwargs):
        self.edits.append(("markup", "", kwargs))


def fake_update(user_id: int, text: str = "", *, fail_photo: bool = False, callback_data: str | None = None):
    message = FakeMessage(text=text, fail_photo=fail_photo)
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, username=f"user{user_id}", language_code="en"),
        effective_chat=SimpleNamespace(id=user_id + 1000),
        message=message,
        callback_query=None,
    )
    if callback_data is not None:
        update.callback_query = FakeCallbackQuery(callback_data, message)
    return update


def context(args=None):
    return SimpleNamespace(args=args or [], bot=FakeBot())


def seed_data():
    init_db()
    session = get_session()
    session.add_all(
        [
            GameCache(
                external_id="validation-free",
                title="Validation Free Game",
                platforms="PC",
                original_price=1999,
                current_price=0,
                expiry_date=datetime.utcnow() + timedelta(days=2),
                store_link="https://example.com/free",
                image_url="https://example.com/free.jpg",
                source_name="Epic Games Store",
                game_type="free",
                platform_type="PC",
                status="active",
            ),
            GameCache(
                external_id="validation-upcoming",
                title="Validation Upcoming Game",
                platforms="PC, Xbox",
                release_date=datetime.utcnow() + timedelta(days=3),
                image_url="https://example.com/not-an-image",
                source_name="RAWG",
                game_type="upcoming",
                platform_type="PC",
                status="active",
            ),
            GameCache(
                external_id="validation-mobile",
                title="Validation Mobile Game",
                platforms="Android, iOS",
                image_url="https://example.com/mobile.jpg",
                source_name="MiniReview",
                game_type="upcoming",
                platform_type="Mobile",
                status="active",
            ),
        ]
    )
    session.commit()
    session.close()


async def run_checks():
    seed_data()

    update = fake_update(9101, "/start")
    await start_command(update, context())
    assert update.message.replies, "/start produced no reply"

    update = fake_update(9101, callback_data="set_lang_ar")
    await settings_callback(update, context())
    assert update.callback_query.answered and update.callback_query.edits, "language/settings callback produced no edit"

    update = fake_update(9102, "Validation Upcoming", fail_photo=True)
    await natural_language_message(update, context())
    assert update.message.replies, "plain text/natural language produced no reply"

    update = fake_update(9103, "/search", fail_photo=True)
    await search_command(update, context(["Validation"]))
    assert any(kind == "text" for kind, _, _ in update.message.replies), "/search did not fall back to text"

    update = fake_update(9104, "/free", fail_photo=True)
    await free_command(update, context())
    assert len(update.message.replies) >= 2, "/free produced too few replies"

    update = fake_update(9105, callback_data="free|legacy")
    await free_callback(update, context())
    assert update.message.replies, "stale free callback produced no recovery reply"

    update = fake_update(9106, "/upcoming", fail_photo=True)
    await upcoming_command(update, context())
    assert any(kind == "text" for kind, _, _ in update.message.replies), "/upcoming did not fall back to text"

    update = fake_update(9107, "/mobile", fail_photo=True)
    await mobile_command(update, context())
    assert update.message.replies, "/mobile produced no reply"

    user_rates.clear()


if __name__ == "__main__":
    asyncio.run(run_checks())
    print("chat_responsiveness_validation=ok")
