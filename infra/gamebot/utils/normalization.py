from rapidfuzz import fuzz, process
from loguru import logger
from sqlalchemy import select
from core.database import AsyncSessionLocal, GameCache

class NormalizationLayer:
    def __init__(self, threshold=90):
        self.threshold = threshold

    async def find_existing_game(self, title: str):
        """
        Uses fuzzy matching to find if a game already exists under a variant name.
        """
        async with AsyncSessionLocal() as session:
            # Fetch all active titles for matching (In production, use a limited set or specialized search)
            stmt = select(GameCache.title).where(GameCache.status == 'active')
            result = await session.execute(stmt)
            existing_titles = result.scalars().all()
            
            if not existing_titles:
                return None
            
            # Find best match
            match = process.extractOne(title, existing_titles, scorer=fuzz.token_sort_ratio)
            
            if match and match[1] >= self.threshold:
                logger.info(f"[Fuzzy] Matched '{title}' to existing '{match[0]}' ({match[1]}%)")
                return match[0]
            
            return None

    def normalize_title(self, title: str) -> str:
        """
        Removes common variants and cleans string.
        """
        t = title.strip()
        # Convert Roman numerals to digits for common ones
        t = t.replace(" VI", " 6").replace(" V", " 5").replace(" IV", " 4")
        return t

normalizer = NormalizationLayer()
