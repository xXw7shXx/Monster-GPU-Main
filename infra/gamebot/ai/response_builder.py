from __future__ import annotations

from typing import Any

from utils.localization import get_string


def recommendation_intro(intent: dict[str, Any], count: int, lang: str) -> str:
    if count <= 0:
        return get_string(lang, "recommend_empty")
    if intent.get("intent") == "free":
        return get_string(lang, "free_recommend_intro")
    if intent.get("intent") == "mobile":
        return get_string(lang, "mobile_recommend_intro")
    if intent.get("intent") == "upcoming":
        return get_string(lang, "upcoming_recommend_intro")
    if intent.get("sort") == "quality":
        return get_string(lang, "quality_recommend_intro")
    if intent.get("similar_to"):
        return get_string(lang, "similar_recommend_intro")
    return get_string(lang, "recommend_title")


def safe_reason(reason: str | None, lang: str) -> str:
    return reason or get_string(lang, "balanced_reason")
