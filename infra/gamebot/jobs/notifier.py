from telegram.ext import ContextTypes
from database.db import get_session
from database.models import User
from services.free_games import get_free_games, format_free_game_message
from services.game_api import get_upcoming_releases, format_release_message
from utils.localization import get_string

from services.sync_service import sync_service
from engine.sync_manager import GlobalSyncManager

sync_manager = GlobalSyncManager()

async def sync_job(context: ContextTypes.DEFAULT_TYPE):
    await sync_manager.run_sync_cycle()

async def daily_releases_job(context: ContextTypes.DEFAULT_TYPE):
    games = get_upcoming_releases(days_ahead=1)
    if not games:
        return
        
    session = get_session()
    users = session.query(User).all()
    
    for user in users:
        if not user.preferences.notify_daily_releases:
            continue
            
        lang = user.preferences.language
        message = get_string(lang, 'upcoming_releases') + "\n\n"
        
        try:
            await context.bot.send_message(chat_id=user.telegram_id, text=message, parse_mode="HTML")
            for game in games[:3]:
                text, image = format_release_message(game, lang)
                if image:
                    await context.bot.send_photo(chat_id=user.telegram_id, photo=image, caption=text, parse_mode="HTML")
                else:
                    await context.bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
        except Exception as e:
            print(f"Failed to send to {user.telegram_id}: {e}")
                
    session.close()

from services.deal_orchestrator import fetch_deals, format_deal_message
from services.tiktok_api import tiktok_service
import re

async def free_games_job(context: ContextTypes.DEFAULT_TYPE):
    deals = fetch_deals()
    if not deals:
        return
        
    session = get_session()
    users = session.query(User).all()
    
    for deal in deals:
        text_en, image = format_deal_message(deal, 'en')
        text_ar, _ = format_deal_message(deal, 'ar')
        
        # Clean HTML for TikTok
        clean_text_en = re.sub('<[^<]+?>', '', text_en)
        clean_text_ar = re.sub('<[^<]+?>', '', text_ar)

        for user in users:
            if not user.preferences.notify_free_games:
                continue
            
            lang = user.preferences.language
            text = text_ar if lang == 'ar' else text_en
            clean_text = clean_text_ar if lang == 'ar' else clean_text_en

            try:
                # Send to Telegram
                if user.telegram_id:
                    if image:
                        await context.bot.send_photo(chat_id=user.telegram_id, photo=image, caption=text, parse_mode="HTML")
                    else:
                        await context.bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
                
                # Send to TikTok
                if user.tiktok_id:
                    if image:
                        await tiktok_service.send_photo(user.tiktok_id, image, clean_text)
                    else:
                        await tiktok_service.send_message(user.tiktok_id, clean_text)
                        
            except Exception as e:
                print(f"Failed to notify user {user.id}: {e}")
                
    session.close()
