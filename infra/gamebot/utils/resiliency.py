import logging
import httpx
import asyncio
from datetime import datetime
from database.db import get_session
from database.models import User, GameCache, SyncHistory
import os

logger = logging.getLogger(__name__)

# Simple Circuit Breaker Implementation
class CircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "CLOSED" # CLOSED, OPEN, HALF-OPEN

    def __call__(self, func):
        async def wrapper(*args, **kwargs):
            if self.state == "OPEN":
                if (datetime.now() - self.last_failure_time).total_seconds() > self.recovery_timeout:
                    self.state = "HALF-OPEN"
                else:
                    logger.warning(f"Circuit Breaker OPEN for {func.__name__}. Skipping call.")
                    return None

            try:
                result = await func(*args, **kwargs)
                self.reset()
                return result
            except Exception as e:
                self.record_failure()
                logger.error(f"Circuit Breaker failure in {func.__name__}: {e}")
                return None
        return wrapper

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.now()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"

    def reset(self):
        self.failures = 0
        self.state = "CLOSED"

# Shared Circuit Breakers
rawg_breaker = CircuitBreaker()
steam_breaker = CircuitBreaker()

async def send_heartbeat(bot_name: str, api_key: str):
    """
    Sends a 1-minute heartbeat to the Super Admin Dashboard.
    Includes live user counts and system health.
    """
    url = "https://admin.w7sh.us/api/heartbeat"
    session = get_session()
    try:
        total_users = session.query(User).count()
        total_games = session.query(GameCache).count()
        last_sync = session.query(SyncHistory).order_by(SyncHistory.timestamp.desc()).first()
        
        payload = {
            "bot_name": bot_name,
            "status": "Healthy",
            "users": total_users,
            "inventory_size": total_games,
            "last_sync": last_sync.timestamp.isoformat() if last_sync else None,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url, 
                json=payload, 
                headers={"X-API-KEY": api_key}
            )
            if response.status_code != 200:
                logger.error(f"Heartbeat failed: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending heartbeat: {e}")
    finally:
        session.close()
