from loguru import logger
from datetime import datetime
from typing import List, Optional
from core.schemas import GameObject
from core.database import AsyncSessionLocal, GameCache, NotifiedDeal
from sqlalchemy import select, update

class FlashDealEngine:
    def __init__(self, quality_threshold=70):
        self.quality_threshold = quality_threshold

    def is_flash_freebie(self, game: GameObject) -> bool:
        """
        Detects if a game is a Limited-Time Freebie (LTF).
        - Price must be 0.
        - Must be tagged as limited-time or derived from specific sources (Epic/Steam Specials).
        - Excludes inherently Free-to-Play games if possible (checking original price > 0).
        """
        # Rule: Price drop to 0 and original price was > 0 (Premium going Free)
        if game.current_price == 0 and game.original_price > 0:
            return True
        
        # Rule: Specific sources known for LTF
        if game.source_name in ['epic', 'steam'] and game.game_type == 'free':
            return True
            
        return False

    async def rank_and_filter(self, games: List[GameObject]) -> List[GameObject]:
        """
        Quality Guard: Only allow high-profile freebies or those meeting score thresholds.
        """
        high_priority = []
        for g in games:
            # 1. Automatic pass for very high profile stores OR non-mobile freebies
            # We want to be inclusive of PC/Console freebies as requested.
            if g.source_name == 'epic' or g.platform_type != 'Mobile':
                high_priority.append(g)
                continue
                
            # 2. Score threshold check (primarily for Mobile/Indie sources)
            if g.critic_score and g.critic_score >= self.quality_threshold:
                high_priority.append(g)
                continue
            
            # 3. Default to logging but skipping lower quality assets to avoid spam
            logger.debug(f"[Quality Guard] Skipping low-tier freebie: {g.title} (Score: {g.critic_score or 'N/A'})")
            
        return high_priority

    async def process_potential_freebies(self, games: List[GameObject]) -> List[GameObject]:
        """
        Main entry point for detection and ranking.
        """
        freebies = [g for g in games if self.is_flash_freebie(g)]
        if not freebies:
            return []
            
        ranked = await self.rank_and_filter(freebies)
        return ranked

    async def cleanup_expired_deals(self):
        """
        Hourly Task: Checks for deals where expiry_date < now.
        """
        logger.info("[Deal Engine] Running hourly cleanup for expired deals...")
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            try:
                stmt = update(GameCache).where(
                    GameCache.status == 'active',
                    GameCache.expiry_date != None,
                    GameCache.expiry_date < now
                ).values(status='expired')
                
                result = await session.execute(stmt)
                await session.commit()
                logger.info(f"[Cleanup] Marked {result.rowcount} deals as expired.")
            except Exception as e:
                logger.error(f"[Cleanup] Failed: {e}")
                await session.rollback()

deal_engine = FlashDealEngine()
