from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


GENRE_SYNONYMS = {
    "action": {"action", "combat", "shooter", "fps", "fight", "اكشن", "أكشن", "قتال", "تصويب"},
    "adventure": {"adventure", "quest", "open world", "exploration", "مغامرة", "استكشاف", "عالم مفتوح"},
    "rpg": {"rpg", "role playing", "jrpg", "soulslike", "تقمص", "ار بي جي"},
    "strategy": {"strategy", "tactics", "4x", "city builder", "استراتيجية", "تكتيك"},
    "sports": {"sports", "football", "soccer", "racing", "رياضة", "كرة", "سباق"},
    "puzzle": {"puzzle", "logic", "cozy", "ألغاز", "لغز", "هادئة"},
    "horror": {"horror", "scary", "survival", "رعب", "مخيف", "بقاء"},
    "indie": {"indie", "small", "hidden gem", "اندie", "مستقلة"},
    "family": {"family", "kids", "children", "عائلية", "أطفال"},
}

PLATFORM_SYNONYMS = {
    "pc": {"pc", "steam", "epic", "windows", "كمبيوتر", "بي سي"},
    "mobile": {"mobile", "ios", "android", "phone", "جوال", "موبايل", "اندرويد", "ايفون"},
    "playstation": {"playstation", "ps5", "ps4", "بلايستيشن"},
    "xbox": {"xbox", "game pass", "اكس بوكس", "قيم باس"},
    "switch": {"switch", "nintendo", "نينتندو", "سويتش"},
}

SOURCE_SYNONYMS = {
    "epic": {"epic", "epic games", "ايبك"},
    "steam": {"steam", "ستيم"},
    "gog": {"gog"},
    "itad": {"itad", "isthereanydeal", "deals", "خصومات"},
}


@dataclass
class GameIntent:
    intent: str = "recommend"
    query: str | None = None
    similar_to: str | None = None
    genres: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    max_price: float | None = None
    free_only: bool = False
    mobile_only: bool = False
    ending_soon: bool = False
    sort: str = "recommended"
    needs_clarification: bool = False
    clarification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "query": self.query,
            "similar_to": self.similar_to,
            "genres": self.genres,
            "platforms": self.platforms,
            "sources": self.sources,
            "max_price": self.max_price,
            "free_only": self.free_only,
            "mobile_only": self.mobile_only,
            "ending_soon": self.ending_soon,
            "sort": self.sort,
            "needs_clarification": self.needs_clarification,
            "clarification": self.clarification,
        }


def _contains(text: str, term: str) -> bool:
    return re.search(r"\b" + re.escape(term.lower()) + r"\b", text) is not None or term.lower() in text


def _find_matches(text: str, mapping: dict[str, set[str]]) -> list[str]:
    found: list[str] = []
    for canonical, aliases in mapping.items():
        if any(_contains(text, alias) for alias in aliases):
            found.append(canonical)
    return found


def parse_intent(text: str) -> GameIntent:
    raw = (text or "").strip()
    lower = raw.lower()
    result = GameIntent()
    if not raw:
        result.needs_clarification = True
        result.clarification = "Tell me a platform, genre, store, or budget and I will recommend games."
        return result

    if lower.startswith("/search") or lower.startswith("search ") or "find " in lower or "ابحث" in lower or "دور" in lower:
        result.intent = "search"
        result.query = re.sub(r"^/?search\s*", "", raw, flags=re.I).strip() or None
    if lower.startswith("/similar") or "more like" in lower or "similar to" in lower or "like " in lower or "يشبه" in lower or "مشابه" in lower or "مثل " in lower or "زي " in lower:
        result.intent = "similar"
    if "free" in lower or "مجاني" in lower or "مجانية" in lower:
        result.intent = "free"
        result.free_only = True
        result.max_price = 0
    if "mobile" in lower or "android" in lower or "ios" in lower or "phone" in lower or "جوال" in lower or "موبايل" in lower or "اندرويد" in lower or "ايفون" in lower:
        result.intent = "mobile"
        result.mobile_only = True
        if "mobile" not in result.platforms:
            result.platforms.append("mobile")
    if "upcoming" in lower or "release" in lower or "coming" in lower or "قادمة" in lower or "تصدر" in lower:
        result.intent = "upcoming"
        result.sort = "release_date"
    if result.intent == "recommend" and ("recommend" in lower or "suggest" in lower or "what should i play" in lower or "رشح" in lower or "اقترح" in lower or "ابي" in lower or "أبغى" in lower or "ابغى" in lower):
        result.intent = "recommend"
    if "top" in lower or "best" in lower or "highest" in lower or "أفضل" in lower:
        result.sort = "quality"
    if "new" in lower or "latest" in lower or "جديد" in lower:
        result.sort = "fresh"
    if "ending soon" in lower or "expires soon" in lower or "before it ends" in lower or "ينتهي" in lower or "قبل ينتهي" in lower:
        result.ending_soon = True
        result.sort = "ending_soon"

    like_match = re.search(r"(?:like|similar to|more like)\s+([a-z0-9 '\-:]+?)(?:\s+but|\s+and|$)", lower, re.I)
    ar_like_match = re.search(r"(?:يشبه|مشابه(?: ل)?|مثل|زي)\s+([^،.!؟]+)", raw, re.I)
    if like_match:
        result.similar_to = like_match.group(1).strip(" .?!")
        result.intent = "similar"
    if ar_like_match:
        result.similar_to = ar_like_match.group(1).strip(" .?!؟،")
        result.intent = "similar"

    result.genres = _find_matches(lower, GENRE_SYNONYMS)
    found_platforms = _find_matches(lower, PLATFORM_SYNONYMS)
    result.platforms = list(dict.fromkeys(result.platforms + found_platforms))
    result.sources = _find_matches(lower, SOURCE_SYNONYMS)

    price_match = re.search(r"(?:under|below|less than|max)\s*\$?(\d{1,3})", lower)
    if price_match:
        result.max_price = float(price_match.group(1))
    if result.intent == "search" and not result.query:
        result.query = re.sub(r"^(search|find|ابحث|دور)\s*", "", raw, flags=re.I).strip() or None
    if result.intent == "recommend" and not result.genres and not result.platforms and result.max_price is None:
        result.needs_clarification = True
        result.clarification = "Try: free PC strategy, new mobile games, best RPG, more like Hades, or ألعاب مجانية للكمبيوتر."
    return result
