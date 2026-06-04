from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.intent_parser import parse_intent
from utils.language import infer_language
from utils.localization import get_string


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label: str) -> None:
    if not value:
        raise AssertionError(label)


def main() -> None:
    free_pc = parse_intent("free PC strategy ending soon")
    assert_equal(free_pc.intent, "free", "free intent")
    assert_true(free_pc.free_only, "free_only flag")
    assert_true(free_pc.ending_soon, "ending soon flag")
    assert_true("pc" in free_pc.platforms, "pc platform")
    assert_true("strategy" in free_pc.genres, "strategy genre")

    mobile = parse_intent("new mobile games for android")
    assert_equal(mobile.intent, "mobile", "mobile intent")
    assert_true(mobile.mobile_only, "mobile_only flag")
    assert_true("mobile" in mobile.platforms, "mobile platform")

    similar = parse_intent("more like Hades")
    assert_equal(similar.intent, "similar", "similar intent")
    assert_equal(similar.similar_to, "hades", "similar title")

    arabic = parse_intent("أبغى ألعاب مجانية للكمبيوتر")
    assert_equal(arabic.intent, "free", "arabic free intent")
    assert_equal(infer_language("ألعاب مجانية"), "ar", "arabic language inference")

    for lang in ("en", "ar"):
        for key in (
            "welcome",
            "start_hint",
            "help_text",
            "menu_mobile",
            "profile_summary",
            "watchlist_empty",
            "more_like_this",
            "higher_rated",
            "ending_soon",
        ):
            assert_true(get_string(lang, key) != key, f"localized key {lang}:{key}")

    callbacks = [
        "quick|mobile",
        "quick|profile",
        "game|similar|123",
        "game|quality|0",
        "game|ending|0",
        "fb|watchlist|123",
    ]
    for callback in callbacks:
        assert_true(1 <= len(callback.encode("utf-8")) <= 64, f"callback size {callback}")


if __name__ == "__main__":
    main()
