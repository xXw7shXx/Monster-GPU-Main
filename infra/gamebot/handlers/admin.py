from telegram import Update
from telegram.ext import ContextTypes
from database.db import get_session
from database.models import User
from services.announcement_service import load_announcement_template
from config import ADMIN_IDS, LOGO_PATH
import asyncio
import logging

async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text(
            "<b>Usage:</b> /announce [template_id] [key=value ...]\n\n"
            "<b>Available Templates:</b>\n"
            "- new_feature\n"
            "- maintenance\n"
            "- advertisement",
            parse_mode="HTML"
        )
        return

    template_id = context.args[0]
    kwargs = {}
    for arg in context.args[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kwargs[k] = v

    session = get_session()
    users = session.query(User).all()
    
    count = 0
    await update.message.reply_text(f"📢 Starting broadcast to {len(users)} users...")
    
    for user in users:
        lang = user.preferences.language if user.preferences else 'en'
        text = load_announcement_template(template_id, lang, **kwargs)
        
        if not text:
            continue
            
        try:
            # For advertisement, we might want to send with logo
            if template_id == "advertisement" and LOGO_PATH.exists():
                with open(LOGO_PATH, 'rb') as photo:
                    await context.bot.send_photo(chat_id=user.telegram_id, photo=photo, caption=text, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="HTML")
            count += 1
            # Avoid hitting rate limits
            await asyncio.sleep(0.05) 
        except Exception as e:
            logging.error(f"Failed to send message to {user.telegram_id}: {e}")

    session.close()
    await update.message.reply_text(f"✅ Broadcast complete. Sent to {count} users.")
