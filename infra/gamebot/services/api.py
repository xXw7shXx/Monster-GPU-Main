from fastapi import FastAPI, HTTPException, Security, Depends, BackgroundTasks, Request
from fastapi.security.api_key import APIKeyHeader
from database.db import get_session
from database.models import User, Preferences, ActivityLog, GameCache
from sqlalchemy import func, text
from datetime import datetime, timedelta
import os
import asyncio
import logging
from services.tiktok_api import tiktok_service
from services.deal_orchestrator import DealOrchestrator, GameDeal, format_deal_message
from services.game_api import get_upcoming_releases, format_release_message, search_game, format_search_message
from utils.localization import get_string
from utils.analytics import log_tt_event
from config import ADMIN_IDS

from services.ops_api import router as ops_router

app = FastAPI(title="GameBot Internal API")

app.include_router(ops_router)

# We'll use a global to store the bot instance if needed
bot_app = None

API_KEY = os.getenv("INTERNAL_API_KEY")
if not API_KEY:
    raise RuntimeError("INTERNAL_API_KEY is required for GameBot API")
api_key_header = APIKeyHeader(name="X-API-KEY")

async def get_api_key(header: str = Security(api_key_header)):
    if header == API_KEY:
        return header
    raise HTTPException(status_code=403, detail="Could not validate credentials")

@app.get("/health")
async def health():
    session = get_session()
    try:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "service": "gamebot", "database": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="unhealthy")
    finally:
        session.close()

@app.get("/analytics", dependencies=[Depends(get_api_key)])
async def get_analytics():
    session = get_session()
    try:
        # Engagement Metrics (Last 24h vs Last 7d)
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)

        # Interactions by platform
        tg_interactions = session.query(ActivityLog).filter(ActivityLog.platform == 'telegram', ActivityLog.timestamp >= week_ago).count()
        tt_interactions = session.query(ActivityLog).filter(ActivityLog.platform == 'tiktok', ActivityLog.timestamp >= week_ago).count()

        # Command usage (Top 5)
        top_commands = session.query(
            ActivityLog.event_name, func.count(ActivityLog.id).label('count')
        ).filter(ActivityLog.event_type == 'command').group_by(ActivityLog.event_name).order_by(func.count(ActivityLog.id).desc()).limit(5).all()

        # Growth trend (Last 7 days)
        growth_trend = []
        for i in range(7):
            date = (now - timedelta(days=i)).date()
            start_of_day = datetime.combine(date, datetime.min.time())
            end_of_day = datetime.combine(date, datetime.max.time())
            count = session.query(User).filter(User.created_at >= start_of_day, User.created_at <= end_of_day).count()
            growth_trend.append({"date": date.isoformat(), "new_users": count})

        # Recent TikTok interactions
        recent_tiktok = session.query(User).filter(User.tiktok_id.isnot(None)).order_by(User.created_at.desc()).limit(5).all()

        return {
            "bot_info": {
                "tiktok_client_key": "configured" if os.getenv("TIKTOK_CLIENT_KEY") else "missing",
                "tiktok_status": "configured" if os.getenv("TIKTOK_ACCESS_TOKEN") else "missing_token"
            },
            "engagement": {
                "telegram": tg_interactions,
                "tiktok": tt_interactions
            },
            "top_commands": [{"command": c[0], "count": c[1]} for c in top_commands],
            "growth_trend": growth_trend[::-1],
            "recent_tiktok_users": [{
                "id": u.tiktok_id,
                "username": u.username or "Anonymous",
                "joined": u.created_at.isoformat() if u.created_at else None
            } for u in recent_tiktok]
        }
    except Exception as e:
        logging.error(f"Error in /analytics: {e}")
        return {"status": "error", "detail": str(e)}
    finally:
        session.close()

@app.post("/tiktok/webhook")
async def tiktok_webhook(request: Request):
    """ Webhook for TikTok Business Messaging API. """
    data = await request.json()
    if data.get("event") == "verification":
        return {"challenge": data.get("challenge")}
    if data.get("event") == "message":
        sender_id = data["data"]["sender_id"]
        content = data["data"]["content"].strip()
        asyncio.create_task(handle_tiktok_message(sender_id, content))
    return {"status": "ok"}

async def handle_tiktok_message(sender_id: str, content: str):
    session = get_session()
    user = session.query(User).filter_by(tiktok_id=sender_id).first()
    if not user:
        user = User(tiktok_id=sender_id, platform='tiktok')
        prefs = Preferences(user=user)
        session.add(user)
        session.add(prefs)
        session.commit()

    log_tt_event(sender_id, 'message', content[:50])
    lang = user.preferences.language
    session.close()
    command = content.split()[0].lower() if content else ""

    if command in ["/start", "start", "ابدأ"]:
        log_tt_event(sender_id, 'command', '/start')
        await tiktok_service.send_message(sender_id, get_string(lang, 'welcome'))
    elif command in ["/free", "free", "مجاني"]:
        log_tt_event(sender_id, 'command', '/free')
        session = get_session()
        cached_deals = session.query(GameCache).filter(GameCache.game_type == 'free', GameCache.current_price == 0, GameCache.status == 'active').limit(3).all()
        session.close()

        if not cached_deals:
            await tiktok_service.send_message(sender_id, get_string(lang, 'no_free_games'))
        else:
            for game in cached_deals:
                deal = GameDeal(
                    title=game.title,
                    platform=game.platforms or "N/A",
                    original_price=game.original_price / 100,
                    current_price=game.current_price / 100,
                    expiry_date=game.expiry_date.strftime('%Y-%m-%d') if game.expiry_date else None,
                    store_link=game.store_link or "N/A",
                    image_url=game.image_url,
                    source=game.source_name,
                    platform_type=game.platform_type,
                    monetization_tags=game.monetization_tags
                )
                text, image = format_deal_message(deal, lang)
                import re
                clean_text = re.sub('<[^<]+?>', '', text)
                if image:
                    await tiktok_service.send_photo(sender_id, image, clean_text)
                else:
                    await tiktok_service.send_message(sender_id, clean_text)

    elif command in ["/upcoming", "upcoming", "قادم"]:
        log_tt_event(sender_id, 'command', '/upcoming')
        session = get_session()
        now = datetime.utcnow()
        cached_games = session.query(GameCache).filter(
            GameCache.game_type == 'upcoming',
            GameCache.release_date >= now
        ).order_by(GameCache.release_date.asc()).limit(3).all()
        session.close()

        if not cached_games:
            await tiktok_service.send_message(sender_id, get_string(lang, 'no_upcoming'))
        else:
            for game in cached_games:
                game_data = {
                    "name": game.title,
                    "released": game.release_date.strftime('%Y-%m-%d') if game.release_date else 'Unknown',
                    "platforms": [{"platform": {"name": p}} for p in (game.platforms or "").split(", ")],
                    "background_image": game.image_url,
                    "critic_score": game.critic_score,
                    "critic_tier": game.critic_tier,
                    "platform_type": game.platform_type
                }
                text, image = format_release_message(game_data, lang)
                import re
                clean_text = re.sub('<[^<]+?>', '', text)
                if image:
                    await tiktok_service.send_photo(sender_id, image, clean_text)
                else:
                    await tiktok_service.send_message(sender_id, clean_text)
    elif command in ["/search", "search", "بحث"]:
        log_tt_event(sender_id, 'command', '/search')
        query = " ".join(content.split()[1:])
        if not query:
            await tiktok_service.send_message(sender_id, "Usage: search [game name]")
            return
        game = await search_game(query)
        if not game:
            await tiktok_service.send_message(sender_id, get_string(lang, 'not_found'))
        else:
            text, image = format_search_message(game, lang)
            import re
            clean_text = re.sub('<[^<]+?>', '', text)
            await tiktok_service.send_photo(sender_id, image, clean_text)
    else:
        await tiktok_service.send_message(sender_id, "Unknown command. Try: start, free, upcoming, search")

@app.get("/stats", dependencies=[Depends(get_api_key)])
async def get_stats():
    session = get_session()
    try:
        total_users = session.query(User).count()
        tg_users = session.query(User).filter(User.telegram_id.isnot(None)).count()
        tt_users = session.query(User).filter(User.tiktok_id.isnot(None)).count()
        ar_users = session.query(User).join(User.preferences).filter_by(language='ar').count()
        en_users = session.query(User).join(User.preferences).filter_by(language='en').count()
        return {
            "total_users": total_users,
            "telegram_users": tg_users,
            "tiktok_users": tt_users,
            "languages": {"ar": ar_users, "en": en_users},
            "status": "online"
        }
    except Exception as e:
        logging.error("Error in /stats: %s", e.__class__.__name__)
        return {"total_users": 0, "status": "error", "detail": "stats unavailable"}
    finally:
        session.close()

@app.get("/users", dependencies=[Depends(get_api_key)])
async def get_users():
    session = get_session()
    try:
        users = session.query(User).all()
        result = []
        for user in users:
            prefs = user.preferences
            result.append({
                "telegram_id": user.telegram_id,
                "tiktok_id": user.tiktok_id,
                "username": user.username or "N/A",
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "preferences": {
                    "language": prefs.language if prefs else "ar",
                    "notify_free": prefs.notify_free_games if prefs else True,
                    "notify_daily": prefs.notify_daily_releases if prefs else True,
                    "notify_leaving": prefs.notify_leaving_games if prefs else True
                }
            })
        return result
    except Exception as e:
        logging.error("Error in /users: %s", e.__class__.__name__)
        raise HTTPException(status_code=500, detail="users unavailable")
    finally:
        session.close()

async def perform_broadcast(message: str, image_url: str = None, target_lang: str = None):
    session = get_session()
    try:
        query = session.query(User)
        if target_lang:
            query = query.join(User.preferences).filter_by(language=target_lang)
        users = query.all()
        count = 0
        import re
        clean_message = re.sub('<[^<]+?>', '', message)
        for user in users:
            try:
                if user.telegram_id and bot_app:
                    if image_url:
                        await bot_app.bot.send_photo(chat_id=user.telegram_id, photo=image_url, caption=message, parse_mode="HTML")
                    else:
                        await bot_app.bot.send_message(chat_id=user.telegram_id, text=message, parse_mode="HTML")
                    from utils.analytics import log_tg_event
                    log_tg_event(user.telegram_id, 'broadcast', 'global_announce')
                if user.tiktok_id:
                    if image_url:
                        await tiktok_service.send_photo(user.tiktok_id, image_url, clean_message)
                    else:
                        await tiktok_service.send_message(user.tiktok_id, clean_message)
                    from utils.analytics import log_tt_event
                    log_tt_event(user.tiktok_id, 'broadcast', 'global_announce')
                count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logging.error(f"Failed to send broadcast to user {user.id}: {e.__class__.__name__}")
        logging.info(f"Broadcast finished. Sent to {count} users.")
    finally:
        session.close()

@app.post("/announce", dependencies=[Depends(get_api_key)])
async def trigger_announce(background_tasks: BackgroundTasks, data: dict):
    message = data.get("message")
    image_url = data.get("image_url")
    target_lang = data.get("target_lang")
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    background_tasks.add_task(perform_broadcast, message, image_url, target_lang)
    return {"status": "success", "message": "Broadcast queued for all platforms"}
