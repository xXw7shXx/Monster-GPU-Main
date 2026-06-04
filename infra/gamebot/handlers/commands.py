from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from database.db import get_session
from database.models import User, Preferences, GameCache
from services.deal_orchestrator import DealOrchestrator, format_deal_message
from services.game_api import get_upcoming_releases, format_release_message, search_game, format_search_message
from services.subscription_tracker import get_games_leaving_soon, format_leaving_message
from utils.localization import get_string
from utils.language import apply_language_defaults, infer_language, user_language
from config import LOGO_PATH, ADMIN_IDS
from datetime import datetime, timedelta
from html import escape
from types import SimpleNamespace
from typing import Optional
import asyncio
import json
import logging
from utils.middleware import rate_limit
from utils.analytics import log_tg_event
from sqlalchemy import or_
from ai.intent_parser import parse_intent
from ai.response_builder import recommendation_intro, safe_reason
from recommender.ranker import profile_summary, recommend_games, record_feedback, similar_games


def _ensure_user(session, update: Update, text: str | None = None) -> User:
    user = session.query(User).filter_by(telegram_id=update.effective_user.id).first()
    if user:
        if not user.preferences:
            prefs = Preferences(user=user)
            apply_language_defaults(prefs, infer_language(text, getattr(update.effective_user, "language_code", None), default="en"))
            session.add(prefs)
            session.flush()
        return user
    user = User(telegram_id=update.effective_user.id, username=update.effective_user.username)
    prefs = Preferences(user=user)
    apply_language_defaults(prefs, infer_language(text, getattr(update.effective_user, "language_code", None), default="en"))
    session.add(user)
    session.add(prefs)
    session.flush()
    return user


def _start_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_string(lang, "menu_recommend"), callback_data="quick|recommend"),
            InlineKeyboardButton(get_string(lang, "menu_free"), callback_data="quick|free"),
        ],
        [
            InlineKeyboardButton(get_string(lang, "menu_mobile"), callback_data="quick|mobile"),
            InlineKeyboardButton(get_string(lang, "menu_upcoming"), callback_data="quick|upcoming"),
        ],
        [
            InlineKeyboardButton(get_string(lang, "menu_profile"), callback_data="quick|profile"),
            InlineKeyboardButton(get_string(lang, "menu_settings"), callback_data="quick|settings"),
            InlineKeyboardButton(get_string(lang, "menu_help"), callback_data="quick|help"),
        ],
    ])

@rate_limit(limit=5, period=10)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    session = get_session()
    try:
        user = _ensure_user(session, update, update.message.text if update.message else None)
        lang = user_language(user, telegram_language_code=getattr(update.effective_user, "language_code", None))
        session.commit()
    finally:
        session.close()

    log_tg_event(user_id, 'command', '/start')
    welcome_text = f"{get_string(lang, 'welcome')}\n\n<i>{get_string(lang, 'start_hint')}</i>"
    keyboard = _start_keyboard(lang)
    
    if LOGO_PATH.exists():
        with open(LOGO_PATH, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=welcome_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=keyboard)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    log_tg_event(user_id, 'command', '/language')
    from handlers.settings import build_language_keyboard
    session = get_session()
    try:
        user = _ensure_user(session, update)
        lang = user_language(user)
        session.commit()
    finally:
        session.close()
    
    text = get_string(lang, 'change_language')
    keyboard = build_language_keyboard(lang)
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        user = _ensure_user(session, update)
        lang = user_language(user)
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(get_string(lang, "help_text"), parse_mode="HTML", reply_markup=_start_keyboard(lang))


FREE_PAGE_SIZE = 3
FREE_CALLBACK_PREFIX = "free"
FREE_SOURCE_LABELS = {
    "epic": "Epic Games Store",
    "epic games store": "Epic Games Store",
    "itad": "IsThereAnyDeal",
    "isthereanydeal": "IsThereAnyDeal",
    "steam": "Steam",
    "gog": "GOG",
    "rawg": "RAWG",
    "igdb": "IGDB",
}
FREE_SOURCE_CODES = {
    "epic": ("epic", "epic games store"),
    "itad": ("itad", "isthereanydeal"),
    "steam": ("steam",),
    "gog": ("gog",),
    "rawg": ("rawg",),
    "igdb": ("igdb",),
}
FREE_PLATFORM_CODES = {
    "pc": ("pc", "windows", "steam", "epic", "gog"),
    "mobile": ("mobile", "android", "ios"),
    "console": ("console", "playstation", "xbox", "switch", "nintendo"),
}


def _free_cache_row_to_deal(game: GameCache) -> SimpleNamespace:
    expiry_date = game.expiry_date.strftime("%Y-%m-%d") if game.expiry_date else None
    return SimpleNamespace(
        title=game.title,
        platform=game.platforms or game.platform_type or "PC",
        original_price=float(game.original_price or 0),
        current_price=float(game.current_price or 0),
        expiry_date=expiry_date,
        store_link=game.store_link or "",
        image_url=game.image_url,
        source=getattr(game, "source_name", None) or getattr(game, "source", None),
        is_upcoming=False,
        platform_type=game.platform_type or "PC",
        monetization_tags=game.monetization_tags,
    )


def _free_game_snapshot(game: GameCache) -> SimpleNamespace:
    return SimpleNamespace(
        id=game.id,
        title=game.title,
        platforms=game.platforms,
        original_price=game.original_price,
        current_price=game.current_price,
        expiry_date=game.expiry_date,
        store_link=game.store_link,
        image_url=game.image_url,
        source_name=game.source_name,
        game_type=game.game_type,
        platform_type=game.platform_type,
        monetization_tags=game.monetization_tags,
        status=game.status,
        last_updated=game.last_updated,
    )


def _normalize_free_token(value: Optional[str]) -> str:
    if not value:
        return "all"
    normalized = value.strip().lower()
    return normalized or "all"


def _parse_free_command_filters(args):
    token = _normalize_free_token(args[0]) if args else "all"
    if token == "all":
        return "all", "all"
    if token in FREE_SOURCE_CODES:
        return "all", token
    return token, "all"


def _source_code_for_game(game) -> str:
    source = (getattr(game, "source_name", None) or getattr(game, "source", "") or "").lower()
    for code, aliases in FREE_SOURCE_CODES.items():
        if any(alias in source for alias in aliases):
            return code
    return source.replace(" ", "_")[:24] or "unknown"


def _source_label_for_game(game) -> str:
    source = getattr(game, "source_name", None) or getattr(game, "source", None) or ""
    source_lower = source.lower()
    for key, label in FREE_SOURCE_LABELS.items():
        if key in source_lower:
            return label
    return source or "Unknown source"


def _platform_label_for_game(game) -> str:
    return getattr(game, "platforms", None) or getattr(game, "platform_type", None) or "PC"


def _is_valid_url(url: Optional[str]) -> bool:
    return bool(url and url.startswith(("https://", "http://")))


async def _reply_media_or_text(reply_target, text: str, image: Optional[str] = None, *, parse_mode: str = "HTML", reply_markup=None, label: str = "message"):
    if image and _is_valid_url(image):
        try:
            await reply_target.reply_photo(photo=image, caption=text, parse_mode=parse_mode, reply_markup=reply_markup)
            return
        except Exception as exc:
            logging.warning("%s photo fallback: %s", label, type(exc).__name__)
    await reply_target.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True)


def _format_free_price(value) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        return "N/A"
    if amount <= 0:
        return "N/A"
    if amount > 100:
        amount = amount / 100
    return f"${amount:.2f}"


def _format_free_expiry(value) -> str:
    if not value:
        return "Unknown"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value).split("T")[0]


def _free_filter_text(lang: str, platform_filter: str, source_filter: str) -> str:
    platform = "all" if platform_filter == "all" else platform_filter.upper()
    source = "all" if source_filter == "all" else source_filter.upper()
    if lang == "ar":
        platform = "كل المنصات" if platform_filter == "all" else platform
        source = "كل المصادر" if source_filter == "all" else source
    else:
        platform = "all platforms" if platform_filter == "all" else platform
        source = "all sources" if source_filter == "all" else source
    return f"{platform}, {source}"


def _query_free_games():
    session = get_session()
    try:
        games = session.query(GameCache).filter(
            GameCache.game_type == 'free',
            GameCache.current_price == 0,
            GameCache.status == 'active'
        ).all()
        snapshots = [_free_game_snapshot(game) for game in games]
        snapshots.sort(key=lambda game: (
            getattr(game, "expiry_date", None) is None,
            getattr(game, "expiry_date", None) or datetime.max,
            (getattr(game, "title", "") or "").lower(),
        ))
        return snapshots
    finally:
        session.close()


def _matches_source(game, source_filter: str) -> bool:
    if source_filter == "all":
        return True
    text = f"{getattr(game, 'source_name', '')} {getattr(game, 'platforms', '')}".lower()
    aliases = FREE_SOURCE_CODES.get(source_filter, (source_filter,))
    return any(alias in text for alias in aliases)


def _matches_platform(game, platform_filter: str) -> bool:
    if platform_filter == "all":
        return True
    text = f"{getattr(game, 'platforms', '')} {getattr(game, 'platform_type', '')} {getattr(game, 'source_name', '')}".lower()
    aliases = FREE_PLATFORM_CODES.get(platform_filter, (platform_filter,))
    return any(alias in text for alias in aliases)


def _apply_free_filters(games, platform_filter: str, source_filter: str):
    return [
        game for game in games
        if _matches_platform(game, platform_filter) and _matches_source(game, source_filter)
    ]


def _available_source_codes(games):
    codes = []
    for game in games:
        code = _source_code_for_game(game)
        if code != "unknown" and code not in codes:
            codes.append(code)
    return codes[:3]


def _available_platform_codes(games):
    available = []
    for code in ("pc", "mobile", "console"):
        if any(_matches_platform(game, code) for game in games) and code not in available:
            available.append(code)
    return available


def _build_free_header(lang: str, total: int, page: int, total_pages: int, platform_filter: str, source_filter: str) -> str:
    title = escape(get_string(lang, "free_title"))
    page_status = escape(get_string(lang, "free_page_status").format(
        total=total,
        page=page + 1,
        total_pages=total_pages,
    ))
    filters = escape(_free_filter_text(lang, platform_filter, source_filter))
    return f"🎁 <b>{title}</b>\n{page_status}\n{escape(get_string(lang, 'free_filter_hint'))}: {filters}"


def _format_free_game_card(game, lang: str, index: int, total: int) -> str:
    title = escape(getattr(game, "title", None) or "Untitled")
    platform = escape(_platform_label_for_game(game))
    source = escape(_source_label_for_game(game))
    value = escape(_format_free_price(getattr(game, "original_price", None)))
    expiry = escape(_format_free_expiry(getattr(game, "expiry_date", None)))
    monetization = getattr(game, "monetization_tags", None)
    monetization_text = f" | {escape(monetization)}" if monetization else ""
    return (
        f"🎁 <b>{index}/{total} {title}</b>\n"
        f"🕹️ <b>{escape(get_string(lang, 'free_platform'))}:</b> {platform}{monetization_text}\n"
        f"🏷️ <b>{escape(get_string(lang, 'free_source'))}:</b> {source}\n"
        f"💰 <b>{escape(get_string(lang, 'value'))}:</b> <s>{value}</s> → {escape(get_string(lang, 'free'))}\n"
        f"⏳ <b>{escape(get_string(lang, 'free_expires'))}:</b> {expiry}"
    )


def _build_free_game_buttons(game, lang: str):
    rows = []
    if _is_valid_url(getattr(game, "store_link", None)):
        rows.append([InlineKeyboardButton(get_string(lang, "free_open"), url=game.store_link)])
    rows.extend([
        [
            InlineKeyboardButton(get_string(lang, "like"), callback_data=f"fb|like|{game.id}"),
            InlineKeyboardButton(get_string(lang, "watchlist"), callback_data=f"fb|watchlist|{game.id}"),
            InlineKeyboardButton(get_string(lang, "dislike"), callback_data=f"fb|dislike|{game.id}"),
        ],
        [
            InlineKeyboardButton(get_string(lang, "more_like_this"), callback_data=f"game|similar|{game.id}"),
            InlineKeyboardButton(get_string(lang, "higher_rated"), callback_data="game|quality|0"),
            InlineKeyboardButton(get_string(lang, "next_pick"), callback_data="game|next|0"),
        ],
    ])
    return InlineKeyboardMarkup(rows)


def _build_free_navigation_keyboard(page: int, total_pages: int, platform_filter: str, source_filter: str, source_codes, platform_codes, lang: str):
    rows = []
    filter_row = []
    if platform_filter != "all" or source_filter != "all":
        filter_row.append(InlineKeyboardButton(get_string(lang, "free_all"), callback_data="free|p|0|all|all"))
    for source in source_codes:
        if source != source_filter:
            filter_row.append(InlineKeyboardButton(source.upper(), callback_data=f"free|p|0|all|{source}"))
    if filter_row:
        rows.append(filter_row[:4])

    platform_row = []
    for platform in platform_codes:
        if platform != platform_filter:
            platform_row.append(InlineKeyboardButton(platform.upper(), callback_data=f"free|p|0|{platform}|all"))
    if platform_row:
        rows.append(platform_row[:3])

    nav_row = []
    safe_platform = platform_filter if platform_filter else "all"
    safe_source = source_filter if source_filter else "all"
    if page > 0:
        nav_row.append(InlineKeyboardButton(get_string(lang, "free_previous"), callback_data=f"free|p|{page - 1}|{safe_platform}|{safe_source}"))
    nav_row.append(InlineKeyboardButton(get_string(lang, "free_refresh"), callback_data=f"free|p|{page}|{safe_platform}|{safe_source}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(get_string(lang, "free_next"), callback_data=f"free|p|{page + 1}|{safe_platform}|{safe_source}"))
    if nav_row:
        rows.append(nav_row)

    return InlineKeyboardMarkup(rows) if rows else None


async def _send_free_page(reply_target, lang: str, page: int = 0, platform_filter: str = "all", source_filter: str = "all"):
    all_games = _query_free_games()
    available_sources = _available_source_codes(all_games)
    available_platforms = _available_platform_codes(all_games)
    filtered_games = _apply_free_filters(all_games, platform_filter, source_filter)

    if not filtered_games:
        if platform_filter != "all" or source_filter != "all":
            text = get_string(lang, "free_empty_filtered")
        else:
            text = get_string(lang, "free_empty")
        keyboard = _build_free_navigation_keyboard(0, 1, platform_filter, source_filter, available_sources, available_platforms, lang)
        await reply_target.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
        return {"total": 0, "cards": 0, "page": 0, "total_pages": 0}

    total = len(filtered_games)
    total_pages = max(1, (total + FREE_PAGE_SIZE - 1) // FREE_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * FREE_PAGE_SIZE
    page_games = filtered_games[start:start + FREE_PAGE_SIZE]

    header = _build_free_header(lang, total, page, total_pages, platform_filter, source_filter)
    await reply_target.reply_text(header, parse_mode="HTML")

    for offset, game in enumerate(page_games, start=start + 1):
        text = _format_free_game_card(game, lang, offset, total)
        keyboard = _build_free_game_buttons(game, lang)
        image = getattr(game, "image_url", None)
        if image:
            try:
                await reply_target.reply_photo(photo=image, caption=text, parse_mode="HTML", reply_markup=keyboard)
                continue
            except Exception as exc:
                logging.warning("free card photo fallback: %s", type(exc).__name__)
        await reply_target.reply_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

    keyboard = _build_free_navigation_keyboard(page, total_pages, platform_filter, source_filter, available_sources, available_platforms, lang)
    if keyboard:
        await reply_target.reply_text(get_string(lang, "free_controls"), reply_markup=keyboard, parse_mode="HTML")

    return {"total": total, "cards": len(page_games), "page": page, "total_pages": total_pages}


@rate_limit(limit=5, period=10)
async def free_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    log_tg_event(user_id, 'command', '/free')

    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        lang = user.preferences.language if user and user.preferences else 'en'
    finally:
        session.close()

    platform_filter, source_filter = _parse_free_command_filters(context.args)
    try:
        await _send_free_page(update.message, lang, page=0, platform_filter=platform_filter, source_filter=source_filter)
    except Exception as exc:
        logging.exception("free_command failed: %s", type(exc).__name__)
        await update.message.reply_text(get_string(lang, "free_error"), parse_mode="HTML")


async def free_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id if update.effective_user else None

    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first() if user_id else None
        lang = user.preferences.language if user and user.preferences else 'en'
    finally:
        session.close()

    try:
        parts = (query.data or "").split("|")
        if len(parts) != 5 or parts[0] != FREE_CALLBACK_PREFIX or parts[1] != "p":
            logging.warning("ignored stale free callback shape")
            await query.message.reply_text(get_string(lang, "stale_button"), parse_mode="HTML")
            await _send_free_page(query.message, lang, page=0, platform_filter="all", source_filter="all")
            return
        page = int(parts[2])
        platform_filter = _normalize_free_token(parts[3])
        source_filter = _normalize_free_token(parts[4])
        if platform_filter not in FREE_PLATFORM_CODES and platform_filter != "all":
            platform_filter = "all"
        if source_filter not in FREE_SOURCE_CODES and source_filter != "all":
            source_filter = "all"
        await _send_free_page(query.message, lang, page=page, platform_filter=platform_filter, source_filter=source_filter)
    except Exception as exc:
        logging.exception("free_callback failed: %s", type(exc).__name__)
        await query.message.reply_text(get_string(lang, "free_error"), parse_mode="HTML")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    query = " ".join(context.args) if context.args else "N/A"
    log_tg_event(user_id, 'command', f'/search {query[:40]}')
    
    session = get_session()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    lang = user.preferences.language if user else 'en'
    session.close()

    if not context.args:
        await update.message.reply_text(get_string(lang, 'search_usage'), parse_mode="HTML")
        return

    query_term = " ".join(context.args)

    # Offload the synchronous database query to a thread
    try:
        cached_game = await asyncio.to_thread(_get_game_from_db_by_title, query_term)
    except Exception as e:
        logging.error("Error fetching game from DB: %s", e.__class__.__name__)
        await update.message.reply_text(get_string(lang, 'db_error'))
        return
    
    if not cached_game:
        await update.message.reply_text(get_string(lang, 'not_found'), parse_mode="HTML")
        return

    game_data = {
        "name": cached_game.title,
        "released": cached_game.release_date.strftime('%Y-%m-%d') if cached_game.release_date else 'Unknown',
        "platforms": [{"platform": {"name": p}} for p in (cached_game.platforms or "").split(", ")],
        "background_image": cached_game.image_url
    }
    
    text, image = format_search_message(game_data, lang)
    keyboard = _build_free_game_buttons(cached_game, lang)
    await _reply_media_or_text(update.message, text, image, reply_markup=keyboard, label="search")


def _format_recommendation_card(item, lang: str, index: int) -> tuple[str, Optional[str], InlineKeyboardMarkup | None]:
    game = item["game"]
    title = escape(game.title or "Untitled")
    platforms = escape(game.platforms or game.platform_type or "Unknown")
    source = escape(game.source_name or "Unknown")
    reason = escape(safe_reason(item.get("reason"), lang))
    score = item.get("score", 0)
    price = _format_free_price(game.current_price)
    text = (
        f"🎯 <b>{index}. {title}</b>\n"
        f"🕹️ <b>{escape(get_string(lang, 'platform'))}:</b> {platforms}\n"
        f"🏷️ <b>{escape(get_string(lang, 'free_source'))}:</b> {source}\n"
        f"💰 <b>{escape(get_string(lang, 'value'))}:</b> {escape(price)}\n"
        f"✨ <b>{escape(get_string(lang, 'why_this'))}:</b> {reason}\n"
        f"📈 <b>Score:</b> <code>{score}</code>"
    )
    rows = [[
        InlineKeyboardButton(get_string(lang, "like"), callback_data=f"fb|like|{game.id}"),
        InlineKeyboardButton(get_string(lang, "watchlist"), callback_data=f"fb|watchlist|{game.id}"),
        InlineKeyboardButton(get_string(lang, "dislike"), callback_data=f"fb|dislike|{game.id}"),
    ], [
        InlineKeyboardButton(get_string(lang, "more_like_this"), callback_data=f"game|similar|{game.id}"),
        InlineKeyboardButton(get_string(lang, "higher_rated"), callback_data="game|quality|0"),
        InlineKeyboardButton(get_string(lang, "ending_soon"), callback_data="game|ending|0"),
    ]]
    if _is_valid_url(game.store_link):
        rows.insert(0, [InlineKeyboardButton(get_string(lang, "free_open"), url=game.store_link)])
    return text, game.image_url, InlineKeyboardMarkup(rows)


@rate_limit(limit=5, period=10)
async def recommend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    text = " ".join(context.args) if context.args else ""
    log_tg_event(user_id, 'command', f'/recommend {text[:40]}')
    intent = parse_intent(text or "recommend games")
    session = get_session()
    try:
        user = _ensure_user(session, update, text)
        lang = user_language(user, text, getattr(update.effective_user, "language_code", None))
        if intent.intent == "similar" and intent.similar_to:
            results = similar_games(session, user, intent.similar_to, limit=5)
        else:
            results = recommend_games(session, user, intent.to_dict(), limit=5)
        session.commit()
    except Exception as exc:
        session.rollback()
        logging.exception("recommend_command failed: %s", type(exc).__name__)
        await update.message.reply_text(get_string('en', "recommend_error"), parse_mode="HTML")
        return
    finally:
        session.close()

    if intent.clarification and not results:
        await update.message.reply_text(escape(intent.clarification), parse_mode="HTML")
        return
    if not results:
        await update.message.reply_text(get_string(lang, "recommend_empty"), parse_mode="HTML")
        return
    await update.message.reply_text(recommendation_intro(intent.to_dict(), len(results), lang), parse_mode="HTML")
    for index, item in enumerate(results, start=1):
        card, image, keyboard = _format_recommendation_card(item, lang, index)
        if image:
            try:
                await update.message.reply_photo(photo=image, caption=card, parse_mode="HTML", reply_markup=keyboard)
                continue
            except Exception:
                logging.warning("recommendation photo fallback")
        await update.message.reply_text(card, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)


async def _send_recommendations(reply_target, context: ContextTypes.DEFAULT_TYPE, intent: dict, telegram_id: int | None, lang: str):
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first() if telegram_id else None
        if intent.get("intent") == "similar" and intent.get("similar_to"):
            results = similar_games(session, user, str(intent["similar_to"]), limit=5)
        else:
            results = recommend_games(session, user, intent, limit=5)
        session.commit()
    except Exception as exc:
        session.rollback()
        logging.exception("send recommendations failed: %s", type(exc).__name__)
        await reply_target.reply_text(get_string(lang, "recommend_error"), parse_mode="HTML")
        return
    finally:
        session.close()
    if not results:
        await reply_target.reply_text(get_string(lang, "recommend_empty"), parse_mode="HTML")
        return
    await reply_target.reply_text(recommendation_intro(intent, len(results), lang), parse_mode="HTML")
    for index, item in enumerate(results, start=1):
        card, image, keyboard = _format_recommendation_card(item, lang, index)
        if image:
            try:
                await reply_target.reply_photo(photo=image, caption=card, parse_mode="HTML", reply_markup=keyboard)
                continue
            except Exception:
                logging.warning("recommendation photo fallback")
        await reply_target.reply_text(card, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)


async def _send_profile(reply_target, telegram_id: int | None, lang: str):
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first() if telegram_id else None
        summary = profile_summary(user.preferences if user and user.preferences else None)
    finally:
        session.close()
    if not any([summary["platforms"], summary["sources"], summary["genres"], summary["likes"], summary["watchlist"], summary["dislikes"]]):
        await reply_target.reply_text(get_string(lang, "profile_empty"), parse_mode="HTML")
        return
    from utils.localization import format_string
    await reply_target.reply_text(
        format_string(
            lang,
            "profile_summary",
            platforms=", ".join(summary["platforms"][:5]) or "-",
            sources=", ".join(summary["sources"][:5]) or "-",
            genres=", ".join(summary["genres"][:5]) or "-",
            likes=summary["likes"],
            watchlist=summary["watchlist"],
            dislikes=summary["dislikes"],
        ),
        parse_mode="HTML",
    )


async def natural_language_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    try:
        intent = parse_intent(text)
    except Exception as exc:
        logging.warning("intent parser fallback: %s", type(exc).__name__)
        session = get_session()
        try:
            user = _ensure_user(session, update, text)
            lang = user_language(user)
            session.commit()
        finally:
            session.close()
        if text.strip():
            context.args = text.split()
            await search_command(update, context)
        else:
            await update.message.reply_text(get_string(lang, "recommend_prompt"), parse_mode="HTML")
        return
    if intent.intent == "search" and intent.query:
        context.args = intent.query.split()
        await search_command(update, context)
        return
    if intent.intent == "free":
        context.args = intent.platforms[:1] or intent.sources[:1]
        await free_command(update, context)
        return
    if intent.intent == "upcoming":
        await upcoming_command(update, context)
        return
    if intent.intent == "mobile":
        await mobile_command(update, context)
        return
    context.args = text.split()
    await recommend_command(update, context)


async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split("|")
    if len(parts) != 3:
        return
    feedback, game_id_raw = parts[1], parts[2]
    if feedback not in {"like", "dislike", "watchlist"} or not game_id_raw.isdigit():
        return
    user_id = update.effective_user.id if update.effective_user else None
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first() if user_id else None
        lang = user.preferences.language if user and user.preferences else 'en'
        record_feedback(session, user, int(game_id_raw), feedback)
        session.commit()
        await query.message.reply_text(get_string(lang, f"feedback_{feedback}"), parse_mode="HTML")
    except Exception as exc:
        session.rollback()
        logging.exception("feedback_callback failed: %s", type(exc).__name__)
    finally:
        session.close()


async def game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = (query.data or "").split("|")
    if len(parts) != 3:
        return
    action, raw_id = parts[1], parts[2]
    user_id = update.effective_user.id if update.effective_user else None
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first() if user_id else None
        lang = user_language(user) if user else 'en'
        game = session.get(GameCache, int(raw_id)) if raw_id.isdigit() and int(raw_id) else None
        if action == "similar" and game:
            intent = {"intent": "similar", "similar_to": game.title}
            results = similar_games(session, user, game.title, limit=5)
        elif action == "quality":
            intent = {"intent": "recommend", "sort": "quality", "genres": [], "platforms": [], "sources": []}
            results = recommend_games(session, user, intent, limit=5)
        elif action == "ending":
            intent = {"intent": "free", "free_only": True, "ending_soon": True, "sort": "ending_soon", "genres": [], "platforms": [], "sources": []}
            results = recommend_games(session, user, intent, limit=5)
        else:
            intent = {"intent": "recommend", "sort": "recommended", "genres": [], "platforms": [], "sources": []}
            results = recommend_games(session, user, intent, limit=5)
        session.commit()
    except Exception as exc:
        session.rollback()
        logging.exception("game_callback failed: %s", type(exc).__name__)
        await query.message.reply_text(get_string('en', "recommend_error"), parse_mode="HTML")
        return
    finally:
        session.close()
    if not results:
        await query.message.reply_text(get_string(lang, "recommend_empty"), parse_mode="HTML")
        return
    await query.message.reply_text(recommendation_intro(intent, len(results), lang), parse_mode="HTML")
    for index, item in enumerate(results, start=1):
        card, image, keyboard = _format_recommendation_card(item, lang, index)
        if image:
            try:
                await query.message.reply_photo(photo=image, caption=card, parse_mode="HTML", reply_markup=keyboard)
                continue
            except Exception:
                logging.warning("game callback photo fallback")
        await query.message.reply_text(card, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)


async def quick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = (query.data or "").split("|")[-1]
    user_id = update.effective_user.id if update.effective_user else None
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first() if user_id else None
        lang = user.preferences.language if user and user.preferences else 'en'
    finally:
        session.close()
    if action == "free":
        await _send_free_page(query.message, lang, page=0)
    elif action == "mobile":
        context.args = ["mobile"]
        await query.message.reply_text(get_string(lang, "quick_mobile"), parse_mode="HTML")
        await _send_recommendations(query.message, context, {"intent": "mobile", "mobile_only": True, "platforms": ["mobile"], "sort": "recommended"}, user_id, lang)
    elif action == "upcoming":
        await query.message.reply_text(get_string(lang, "quick_upcoming"), parse_mode="HTML")
    elif action == "profile":
        await _send_profile(query.message, user_id, lang)
    elif action == "help":
        await query.message.reply_text(get_string(lang, "help_text"), parse_mode="HTML", reply_markup=_start_keyboard(lang))
    elif action == "settings":
        await query.message.reply_text(get_string(lang, "quick_settings"), parse_mode="HTML")
    else:
        await query.message.reply_text(get_string(lang, "recommend_prompt"), parse_mode="HTML")


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        user = _ensure_user(session, update)
        lang = user_language(user)
        session.commit()
    finally:
        session.close()
    await _send_profile(update.message, update.effective_user.id, lang)


async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        user = _ensure_user(session, update)
        lang = user_language(user)
        prefs = user.preferences
        try:
            ids = [int(item) for item in json.loads(prefs.watchlist_game_ids or "[]") if str(item).isdigit()]
        except Exception:
            ids = []
        games = session.query(GameCache).filter(GameCache.id.in_(ids), GameCache.status == "active").limit(10).all() if ids else []
        session.commit()
    finally:
        session.close()
    if not games:
        await update.message.reply_text(get_string(lang, "watchlist_empty"), parse_mode="HTML")
        return
    await update.message.reply_text(get_string(lang, "watchlist_title"), parse_mode="HTML")
    for index, game in enumerate(games, start=1):
        card, image, keyboard = _format_recommendation_card({"game": game, "score": 0, "reason": "saved by you"}, lang, index)
        if image:
            try:
                await update.message.reply_photo(photo=image, caption=card, parse_mode="HTML", reply_markup=keyboard)
                continue
            except Exception:
                logging.warning("watchlist photo fallback")
        await update.message.reply_text(card, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)


async def reset_preferences_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_session()
    try:
        user = _ensure_user(session, update)
        lang = user_language(user)
        prefs = user.preferences
        prefs.favorite_platforms = None
        prefs.favorite_sources = None
        prefs.favorite_genres = None
        prefs.liked_game_ids = None
        prefs.disliked_game_ids = None
        prefs.watchlist_game_ids = None
        prefs.intent_history = None
        session.commit()
    finally:
        session.close()
    await update.message.reply_text(get_string(lang, "preferences_reset"), parse_mode="HTML")

# --- Helper function for synchronous database calls ---
def _get_game_from_db_by_title(query_term: str) -> Optional[GameCache]:
    """Synchronously searches for a game in the database by title."""
    session = get_session()
    try:
        cached_game = session.query(GameCache).filter(
            GameCache.title.ilike(f"%{query_term}%")
        ).first()
        return cached_game
    finally:
        session.close()

@rate_limit(limit=5, period=10)
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    log_tg_event(user_id, 'command', '/stats')
    if user_id not in ADMIN_IDS:
        return

    session = get_session()
    total_users = session.query(User).count()
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = session.query(User).filter(User.created_at >= today).count()
    
    ar = session.query(Preferences).filter_by(language='ar').count()
    en = session.query(Preferences).filter_by(language='en').count()
    
    session.close()
    
    stats_text = (
        "📊 <b>Enterprise Analytics</b>\n\n"
        f"👥 <b>Growth:</b>\n"
        f"├ Total Users: <code>{total_users}</code>\n"
        f"└ New Today: <code>{new_today}</code>\n\n"
        f"🌐 <b>Language:</b>\n"
        f"├ Arabic: <code>{ar}</code>\n"
        f"└ English: <code>{en}</code>"
    )
    
    await update.message.reply_text(stats_text, parse_mode="HTML")

@rate_limit(limit=5, period=10)
async def upcoming_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    log_tg_event(user_id, 'command', '/upcoming')
    session = get_session()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    lang = user.preferences.language if user else 'en'

    now = datetime.utcnow()
    cached_games = session.query(GameCache).filter(
        GameCache.game_type == 'upcoming',
        GameCache.release_date >= now,
        GameCache.status == 'active'
    ).order_by(GameCache.release_date.asc()).limit(5).all()
    
    session.close()

    if not cached_games:
        await update.message.reply_text(get_string(lang, 'no_upcoming'))
        return
        
    await update.message.reply_text(get_string(lang, 'upcoming_releases'), parse_mode="HTML")
    for game in cached_games:
        game_data = {
            "name": game.title,
            "released": game.release_date.strftime('%Y-%m-%d') if game.release_date else 'Unknown',
            "platforms": [{"platform": {"name": p}} for p in (game.platforms or "").split(", ")],
            "background_image": game.image_url
        }
        text, image = format_release_message(game_data, lang)
        keyboard = _build_free_game_buttons(game, lang)
        await _reply_media_or_text(update.message, text, image, reply_markup=keyboard, label="upcoming")

@rate_limit(limit=5, period=10)
async def mobile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    log_tg_event(user_id, 'command', '/mobile')
    session = get_session()
    try:
        user = _ensure_user(session, update)
        lang = user_language(user)
        intent = {"intent": "mobile", "mobile_only": True, "platforms": ["mobile"], "sources": [], "genres": [], "sort": "recommended"}
        results = recommend_games(session, user, intent, limit=5)
        session.commit()
    except Exception as exc:
        session.rollback()
        logging.exception("mobile_command failed: %s", type(exc).__name__)
        await update.message.reply_text(get_string('en', "recommend_error"), parse_mode="HTML")
        return
    finally:
        session.close()

    if not results:
        await update.message.reply_text(get_string(lang, 'no_mobile_games'), parse_mode="HTML")
        return

    await update.message.reply_text(get_string(lang, 'mobile_hot'), parse_mode="HTML")
    for index, item in enumerate(results, start=1):
        card, image, keyboard = _format_recommendation_card(item, lang, index)
        if image:
            try:
                await update.message.reply_photo(photo=image, caption=card, parse_mode="HTML", reply_markup=keyboard)
                continue
            except Exception:
                logging.warning("mobile photo fallback")
        await update.message.reply_text(card, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

@rate_limit(limit=5, period=10)
async def leaving_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    user_id = update.effective_user.id
    log_tg_event(user_id, 'command', '/leaving')
    session = get_session()
    user = session.query(User).filter_by(telegram_id=user_id).first()
    lang = user.preferences.language if user else 'en'
    session.close()

    games = get_games_leaving_soon()
    if not games:
        await update.message.reply_text(get_string(lang, 'no_leaving'))
        return
        
    await update.message.reply_text(get_string(lang, 'leaving_soon'), parse_mode="HTML")
    for game in games:
        text, image = format_leaving_message(game, lang)
        await _reply_media_or_text(update.message, text, image, label="leaving")
