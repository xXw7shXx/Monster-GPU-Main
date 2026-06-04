import time
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter
# user_id -> [timestamps]
user_rates = {}

def rate_limit(limit=5, period=10):
    """
    Rate limit decorator.
    :param limit: Maximum number of requests allowed in the period.
    :param period: Time period in seconds.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if not update.effective_user:
                return await func(update, context, *args, **kwargs)
                
            user_id = update.effective_user.id
            now = time.time()
            
            # Initialize or clean up old timestamps
            user_timestamps = user_rates.get(user_id, [])
            user_timestamps = [t for t in user_timestamps if now - t < period]
            
            if len(user_timestamps) >= limit:
                logger.warning(f"User {user_id} rate limited on {func.__name__}")
                # Optional: Send a message to the user
                # await update.message.reply_text("⚠️ Slow down! You are sending commands too fast.")
                return
                
            user_timestamps.append(now)
            user_rates[user_id] = user_timestamps
            
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator
