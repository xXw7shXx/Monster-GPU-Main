from __future__ import annotations

import re


ARABIC_RE = re.compile(r"[\u0600-\u06ff]")


def infer_language(text: str | None = None, telegram_language_code: str | None = None, default: str = "en") -> str:
    if text and ARABIC_RE.search(text):
        return "ar"
    if telegram_language_code and telegram_language_code.lower().startswith("ar"):
        return "ar"
    return default


def apply_language_defaults(prefs, lang: str) -> None:
    prefs.language = "ar" if lang == "ar" else "en"


def user_language(user, text: str | None = None, telegram_language_code: str | None = None) -> str:
    if text and ARABIC_RE.search(text):
        return "ar"
    prefs = getattr(user, "preferences", None)
    if prefs and getattr(prefs, "language", None) in {"ar", "en"}:
        return prefs.language
    return infer_language(text, telegram_language_code, default="en")
