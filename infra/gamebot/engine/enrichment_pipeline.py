import asyncio
from datetime import datetime, timedelta
from typing import List
from loguru import logger
from sqlalchemy.orm import Session

from database.schema import GameCache
from adapters.enrichment.igdb_enricher import IGDBEnricher
from adapters.enrichment.steam_enricher import SteamEnricher


class EnrichmentPipeline:
    def __init__(self, session: Session):
        self.session = session
        self.igdb = IGDBEnricher()
        self.steam = SteamEnricher()

    async def enrich_game(self, game: GameCache) -> bool:
        """Enrich a single game. Returns True if successful."""
        if game.enriched_at and (datetime.utcnow() - game.enriched_at) < timedelta(days=7):
            return True  # skip recently enriched

        # Try IGDB first
        data = await self.igdb.enrich(game.title, game.platform_type)
        if not data:
            data = await self.steam.enrich(game.title)

        if not data:
            logger.debug(f"[Enrichment] No data found for '{game.title}'")
            return False

        game.description = data.get("description")
        game.genres = data.get("genres")
        game.tags = data.get("tags")
        game.developers = data.get("developers")
        game.screenshots = data.get("screenshots")
        game.enriched_at = datetime.utcnow()
        game.enriched_source = data.get("source")
        self.session.flush()
        logger.info(f"[Enrichment] Enriched '{game.title}' from {data['source']}")
        return True

    async def enrich_batch(self, limit: int = 100) -> int:
        """Enrich up to `limit` unenriched or stale games. Returns count enriched."""
        cutoff = datetime.utcnow() - timedelta(days=7)
        games = (
            self.session.query(GameCache)
            .filter(
                (GameCache.enriched_at == None) | (GameCache.enriched_at < cutoff)
            )
            .order_by(GameCache.enriched_at.asc().nullsfirst())
            .limit(limit)
            .all()
        )

        enriched = 0
        for game in games:
            try:
                success = await self.enrich_game(game)
                if success:
                    enriched += 1
                await asyncio.sleep(0.3)  # rate limit respect
            except Exception as e:
                logger.error(f"[Enrichment] Error enriching '{game.title}': {e}")
                continue

        self.session.commit()
        logger.info(f"[Enrichment] Batch complete: {enriched}/{len(games)} games enriched")
        return enriched

    async def backfill_all(self, batch_size: int = 50) -> int:
        """Backfill all games in batches."""
        total = 0
        while True:
            count = await self.enrich_batch(limit=batch_size)
            total += count
            if count == 0:
                break
            await asyncio.sleep(2)  # pause between batches
        logger.info(f"[Enrichment] Backfill complete: {total} games enriched")
        return total
