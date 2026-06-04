import os
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import datetime
import uvicorn
from services.api import app as api_app

# Fix for asyncio ProactorEventLoop shutdown errors on Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import TELEGRAM_BOT_TOKEN, LOG_FILE, LOG_DIR, ADMIN_IDS
from database.db import init_db
from handlers.commands import (
    start_command,
    free_command,
    free_callback,
    upcoming_command,
    leaving_command,
    language_command,
    search_command,
    stats_command,
    mobile_command,
    help_command,
    recommend_command,
    feedback_callback,
    game_callback,
    quick_callback,
    natural_language_message,
    profile_command,
    watchlist_command,
    reset_preferences_command,
)
from handlers.settings import settings_command, settings_callback
from handlers.admin import announce_command
from jobs.notifier import daily_releases_job, free_games_job, sync_job
from utils.middleware import rate_limit

# Setup Professional Logging
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

async def post_init(application: Application) -> None:
    """Sets the bot commands for the menu button."""
    commands = [
        ("start", "Start the bot | ابدأ البوت"),
        ("upcoming", "Upcoming releases | الإصدارات القادمة"),
        ("free", "Free games | الألعاب المجانية"),
        ("mobile", "Mobile games | ألعاب الجوال"),
        ("recommend", "Recommendations | الترشيحات"),
        ("search", "Search game | البحث عن لعبة"),
        ("profile", "Profile | ملف التفضيلات"),
        ("watchlist", "Saved games | الألعاب المحفوظة"),
        ("leaving", "Leaving services | ألعاب مغادرة"),
        ("settings", "Settings | الإعدادات"),
        ("language", "Language | اللغة"),
        ("help", "Help | المساعدة"),
        ("stats", "Statistics | الإحصائيات")
    ]
    await application.bot.set_my_commands(commands)

async def run_api():
    config = uvicorn.Config(api_app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    init_db()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("language", language_command))
    application.add_handler(CommandHandler("free", free_command))
    application.add_handler(CommandHandler("mobile", mobile_command))
    application.add_handler(CommandHandler("recommend", recommend_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("watchlist", watchlist_command))
    application.add_handler(CommandHandler("resetpreferences", reset_preferences_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("upcoming", upcoming_command))
    application.add_handler(CommandHandler("leaving", leaving_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("announce", announce_command))
    
    application.add_handler(CallbackQueryHandler(free_callback, pattern=r"^free\|"))
    application.add_handler(CallbackQueryHandler(feedback_callback, pattern=r"^fb\|"))
    application.add_handler(CallbackQueryHandler(game_callback, pattern=r"^game\|"))
    application.add_handler(CallbackQueryHandler(quick_callback, pattern=r"^quick\|"))
    application.add_handler(CallbackQueryHandler(settings_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, natural_language_message))
    application.add_error_handler(error_handler)

    # Jobs
    job_queue = application.job_queue
    notifications_disabled = os.getenv("DISABLE_NOTIFICATION_JOBS", "").lower() in {"1", "true", "yes", "on"}
    if notifications_disabled:
        logger.warning("Outbound notification jobs disabled via DISABLE_NOTIFICATION_JOBS")
    else:
        logger.info("Outbound notification jobs enabled; scheduling daily/free jobs")
        job_queue.run_daily(daily_releases_job, time=datetime.time(hour=10, minute=0, tzinfo=datetime.timezone.utc))
        job_queue.run_repeating(free_games_job, interval=21600, first=21600)
    job_queue.run_repeating(sync_job, interval=600, first=5)

    logger.info("Bot and API are starting...")
    
    from services import api
    api.bot_app = application
    
    loop = asyncio.get_event_loop()
    loop.create_task(run_api())
    application.run_polling()

if __name__ == "__main__":
    main()
