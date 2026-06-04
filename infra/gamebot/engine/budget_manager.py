from sqlalchemy import select
from datetime import datetime, timedelta
from core.database import AsyncSessionLocal, APILimit
from loguru import logger
import httpx
from core.config import settings

class OpenCriticBudgetManager:
    def __init__(self, daily_limit=20, monthly_limit=500):
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.service_name = 'opencritic'

    async def can_call(self, is_high_priority=False) -> bool:
        """
        Credit Guard: 
        - If monthly limit > 90% used, enter 'Queue Mode' (only high priority).
        - If monthly limit > 98% used, stop all calls.
        """
        async with AsyncSessionLocal() as session:
            stmt = select(APILimit).where(APILimit.service_name == self.service_name)
            result = await session.execute(stmt)
            limit = result.scalar_one_or_none()
            
            now = datetime.utcnow()
            
            if not limit:
                limit = APILimit(service_name=self.service_name, reset_at=now + timedelta(days=30), call_count=0)
                session.add(limit)
                await session.commit()
            
            if now > limit.reset_at:
                limit.call_count = 0
                limit.reset_at = now + timedelta(days=30)
                await session.commit()
                
            if limit.call_count >= self.monthly_limit * 0.98:
                logger.error("[Credit Guard] OpenCritic monthly quota exhausted!")
                return False
                
            if limit.call_count >= self.monthly_limit * 0.90 and not is_high_priority:
                logger.warning("[Credit Guard] Entering Queue Mode (High Priority Only).")
                return False

            return limit.call_count < self.monthly_limit

    async def _increment(self):
        async with AsyncSessionLocal() as session:
            stmt = select(APILimit).where(APILimit.service_name == self.service_name)
            result = await session.execute(stmt)
            limit = result.scalar_one_or_none()
            if limit:
                limit.call_count += 1
                await session.commit()

    async def fetch_score(self, game_title: str, is_high_priority=False):
        if not await self.can_call(is_high_priority):
            return None

        headers = {
            "X-RapidAPI-Key": settings.OPENCRITIC_API_KEY,
            "X-RapidAPI-Host": settings.OPENCRITIC_HOST
        }

        async with httpx.AsyncClient() as client:
            try:
                # 1. Search for game
                search_url = f"https://{settings.OPENCRITIC_HOST}/game/search"
                response = await client.get(search_url, headers=headers, params={"criteria": game_title}, timeout=5.0)
                await self._increment()
                response.raise_for_status()
                results = response.json()
                
                if not results: return None
                game_id = results[0]['id']
                
                # 2. Get details
                detail_url = f"https://{settings.OPENCRITIC_HOST}/game/{game_id}"
                response = await client.get(detail_url, headers=headers, timeout=5.0)
                await self._increment()
                response.raise_for_status()
                details = response.json()
                
                return {
                    "score": int(details.get("topCriticScore", -1)),
                    "tier": details.get("tier"),
                    "id": game_id
                }
            except Exception as e:
                logger.error(f"[OpenCritic] Lazy load failed for {game_title}: {e}")
                return None
