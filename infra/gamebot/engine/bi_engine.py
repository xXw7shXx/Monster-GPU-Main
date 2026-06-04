import random
import asyncio
from loguru import logger
from core.schemas import GameObject

class BIEngine:
    def __init__(self):
        # Simulation of API costs in cents
        self.source_costs = {
            "igdb": 0.05,
            "rawg": 0.02,
            "itad": 0.01,
            "steam": 0.00,
            "opencritic": 0.10,
            "minireview": 0.05
        }

    def predict_hype_cycle(self, igdb_hype: int, critic_score: int) -> int:
        """
        Cross-references hype and scores to predict the 'Hype Cycle' rating (0-100).
        """
        score = critic_score or 50 # Default middle
        hype = igdb_hype or 0
        # Formula: Weighted average of hype and critic reception
        return int((hype * 0.4) + (score * 0.6))

    def calculate_cost_per_deal(self, source: str) -> float:
        """
        Tracks API credit usage per successful discovery.
        """
        return self.source_costs.get(source.lower(), 0.01)

    async def apply_jitter(self):
        """
        Security: Mimic human behavior to avoid IP flagging.
        """
        jitter = random.uniform(2, 5)
        logger.debug(f"[Security] Applying jitter: {jitter:.2f}s")
        await asyncio.sleep(jitter)

bi_engine = BIEngine()
