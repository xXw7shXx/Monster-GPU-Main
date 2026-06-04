from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import or_

from database.models import GameCache, Preferences, User


def _loads(raw: str | None, fallback):
    try:
        return json.loads(raw or "")
    except Exception:
        return fallback


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _tokens(value: str | None) -> set[str]:
    return {part.strip().lower() for part in (value or "").replace("/", ",").split(",") if part.strip()}


def _game_text(game: GameCache) -> str:
    return " ".join(
        str(part or "")
        for part in [
            game.title,
            game.platforms,
            game.platform_type,
            game.source_name,
            game.monetization_tags,
            game.vibe_tag,
            game.critic_tier,
        ]
    ).lower()


def game_traits(game: GameCache) -> set[str]:
    text = _game_text(game)
    traits = _tokens(game.platform_type) | _tokens(game.platforms) | _tokens(game.source_name)
    aliases = {
        "action": ["action", "combat", "shooter", "fps", "fight"],
        "adventure": ["adventure", "quest", "open world", "exploration"],
        "rpg": ["rpg", "role", "jrpg", "soulslike"],
        "strategy": ["strategy", "tactics", "4x", "city builder"],
        "sports": ["sports", "football", "soccer", "racing"],
        "puzzle": ["puzzle", "logic", "cozy"],
        "horror": ["horror", "scary", "survival"],
        "indie": ["indie", "hidden gem"],
        "family": ["family", "kids", "children"],
    }
    for trait, words in aliases.items():
        if any(word in text for word in words):
            traits.add(trait)
    return traits


def _profile_set(prefs: Preferences | None, field: str) -> set[str]:
    return {str(item).lower() for item in _loads(getattr(prefs, field, None), [])}


def update_profile_from_intent(session, user: User | None, intent: dict[str, Any]) -> None:
    if not user or not user.preferences:
        return
    prefs = user.preferences
    platforms = _profile_set(prefs, "favorite_platforms")
    sources = _profile_set(prefs, "favorite_sources")
    genres = _profile_set(prefs, "favorite_genres")
    history = _loads(getattr(prefs, "intent_history", None), [])

    platforms.update(str(item).lower() for item in intent.get("platforms") or [])
    sources.update(str(item).lower() for item in intent.get("sources") or [])
    genres.update(str(item).lower() for item in intent.get("genres") or [])
    history = ([{"at": datetime.utcnow().isoformat(), "intent": intent}] + history)[:20]

    prefs.favorite_platforms = _dumps(sorted(platforms))
    prefs.favorite_sources = _dumps(sorted(sources))
    prefs.favorite_genres = _dumps(sorted(genres))
    prefs.intent_history = _dumps(history)
    session.flush()


def record_feedback(session, user: User | None, game_id: int, feedback: str) -> None:
    if not user or not user.preferences:
        return
    prefs = user.preferences
    liked = set(int(item) for item in _loads(getattr(prefs, "liked_game_ids", None), []) if str(item).isdigit())
    disliked = set(int(item) for item in _loads(getattr(prefs, "disliked_game_ids", None), []) if str(item).isdigit())
    watchlist = set(int(item) for item in _loads(getattr(prefs, "watchlist_game_ids", None), []) if str(item).isdigit())
    if feedback == "like":
        liked.add(game_id)
        disliked.discard(game_id)
    elif feedback == "dislike":
        disliked.add(game_id)
        liked.discard(game_id)
    elif feedback == "watchlist":
        watchlist.add(game_id)
    prefs.liked_game_ids = _dumps(sorted(liked))
    prefs.disliked_game_ids = _dumps(sorted(disliked))
    prefs.watchlist_game_ids = _dumps(sorted(watchlist))
    game = session.query(GameCache).filter(GameCache.id == game_id).first()
    if game and feedback in {"like", "watchlist"}:
        platforms = _profile_set(prefs, "favorite_platforms")
        sources = _profile_set(prefs, "favorite_sources")
        genres = _profile_set(prefs, "favorite_genres")
        platforms.update(_tokens(game.platform_type) | _tokens(game.platforms))
        sources.update(_tokens(game.source_name))
        genres.update(game_traits(game))
        prefs.favorite_platforms = _dumps(sorted(platforms))
        prefs.favorite_sources = _dumps(sorted(sources))
        prefs.favorite_genres = _dumps(sorted(genres))
    session.flush()


def score_game(game: GameCache, intent: dict[str, Any], prefs: Preferences | None = None) -> tuple[float, str]:
    score = 0.0
    reasons: list[str] = []
    platforms = _tokens(game.platform_type) | _tokens(game.platforms)
    source = _tokens(game.source_name)
    title_text = _game_text(game)
    requested_platforms = {str(item).lower() for item in intent.get("platforms") or []}
    requested_sources = {str(item).lower() for item in intent.get("sources") or []}
    requested_genres = {str(item).lower() for item in intent.get("genres") or []}

    if intent.get("free_only") and (game.current_price or 0) == 0:
        score += 45
        reasons.append("free now")
    if intent.get("mobile_only"):
        if "mobile" in platforms or "android" in title_text or "ios" in title_text:
            score += 35
            reasons.append("mobile match")
        else:
            score -= 35
    if requested_platforms:
        if requested_platforms & platforms:
            score += 28
            reasons.append("platform match")
        else:
            score -= 20
    if requested_sources:
        if requested_sources & source:
            score += 18
            reasons.append("store match")
        else:
            score -= 10
    for genre in requested_genres:
        if genre in title_text:
            score += 20
            reasons.append(f"{genre} signal")
    if intent.get("max_price") is not None:
        price = float(game.current_price or 0)
        if price > 100:
            price = price / 100
        if price <= float(intent["max_price"]):
            score += 18
            reasons.append("budget fit")
        else:
            score -= 16

    if prefs:
        liked_ids = set(int(item) for item in _loads(getattr(prefs, "liked_game_ids", None), []) if str(item).isdigit())
        disliked_ids = set(int(item) for item in _loads(getattr(prefs, "disliked_game_ids", None), []) if str(item).isdigit())
        if game.id in liked_ids:
            score += 8
        if game.id in disliked_ids:
            score -= 45
        if _profile_set(prefs, "favorite_platforms") & platforms:
            score += 10
            reasons.append("learned platform")
        if _profile_set(prefs, "favorite_sources") & source:
            score += 6
            reasons.append("learned store")

    if game.critic_score:
        score += min(game.critic_score, 100) / 5
        if game.critic_score >= 80:
            reasons.append("strong critic score")
    if game.hype_score:
        score += min(game.hype_score, 100) / 10
    if game.expiry_date:
        days = max(0, (game.expiry_date - datetime.utcnow()).days)
        score += max(0, 14 - days)
        if days <= 3:
            reasons.append("ending soon")
        if intent.get("ending_soon") and days <= 7:
            score += 25
    if game.last_updated:
        age_days = max(0, (datetime.utcnow() - game.last_updated).days)
        score += max(0, 10 - age_days)

    if not reasons:
        reasons.append("balanced freshness and quality")
    return round(score, 3), ", ".join(dict.fromkeys(reasons))


def recommend_games(session, user: User | None, intent: dict[str, Any], limit: int = 5):
    if user:
        update_profile_from_intent(session, user, intent)
    query = session.query(GameCache).filter(GameCache.status == "active")
    if intent.get("intent") == "free" or intent.get("free_only"):
        query = query.filter(GameCache.game_type == "free", GameCache.current_price == 0)
    elif intent.get("intent") == "mobile" or intent.get("mobile_only"):
        query = query.filter(or_(GameCache.platform_type.ilike("%mobile%"), GameCache.platforms.ilike("%android%"), GameCache.platforms.ilike("%ios%")))
    elif intent.get("intent") == "upcoming":
        query = query.filter(GameCache.game_type == "upcoming")
    sort = intent.get("sort")
    if sort == "quality":
        query = query.order_by(GameCache.critic_score.desc().nullslast(), GameCache.hype_score.desc().nullslast())
    elif sort == "release_date":
        query = query.order_by(GameCache.release_date.asc().nullslast(), GameCache.last_updated.desc())
    elif sort == "ending_soon":
        query = query.order_by(GameCache.expiry_date.asc().nullslast(), GameCache.last_updated.desc())
    else:
        query = query.order_by(GameCache.last_updated.desc())
    candidates = query.limit(150).all()
    ranked = sorted(
        ((score_game(game, intent, user.preferences if user else None), game) for game in candidates),
        key=lambda item: item[0][0],
        reverse=True,
    )
    return [{"game": game, "score": score, "reason": reason} for (score, reason), game in ranked[:limit]]


def similar_games(session, user: User | None, title: str, limit: int = 5):
    base = session.query(GameCache).filter(GameCache.title.ilike(f"%{title}%"), GameCache.status == "active").order_by(GameCache.critic_score.desc().nullslast()).first()
    if not base:
        return []
    intent = {
        "intent": "similar",
        "similar_to": base.title,
        "platforms": list(_tokens(base.platform_type) | _tokens(base.platforms)),
        "sources": list(_tokens(base.source_name)),
        "genres": list(game_traits(base)),
        "free_only": base.current_price == 0,
        "sort": "recommended",
        "allow_repeat": False,
    }
    results = [item for item in recommend_games(session, user, intent, limit=limit + 3) if item["game"].id != base.id]
    return results[:limit]


def profile_summary(prefs: Preferences | None) -> dict[str, Any]:
    return {
        "platforms": sorted(_profile_set(prefs, "favorite_platforms")),
        "sources": sorted(_profile_set(prefs, "favorite_sources")),
        "genres": sorted(_profile_set(prefs, "favorite_genres")),
        "likes": len(_profile_set(prefs, "liked_game_ids")),
        "dislikes": len(_profile_set(prefs, "disliked_game_ids")),
        "watchlist": len(_profile_set(prefs, "watchlist_game_ids")),
    }
