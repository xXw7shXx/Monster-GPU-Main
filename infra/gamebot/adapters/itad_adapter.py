import httpx
from loguru import logger
from typing import List
from core.schemas import GameObject
from core.config import settings
import re

class ITADAdapter:
    def __init__(self):
        self.url = "https://api.isthereanydeal.com/deals/v2"

    async def fetch(self) -> List[GameObject]:
        logger.info("[ITAD] Fetching 100% discount deals...")

        params = {
            "key": settings.ITAD_API_KEY,
            "country": "US",
            "sort": "cut:desc",
            "limit": 50
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.url, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json().get("list", [])

                games = []
                for item in data:
                    deal_info = item.get("deal", {})
                    if deal_info.get("cut") == 100:
                        title = item.get("title")
                        # Generate a clean ID
                        clean_id = "".join(filter(str.isalnum, title.lower()))

                        games.append(GameObject(
                            external_id=f"ITAD-{clean_id}",
                            title=title,
                            platforms=deal_info.get("shop", {}).get("name", "PC"),
                            original_price=int(deal_info.get("regular", {}).get("amount", 0.0) * 100),
                            current_price=0,
                            store_link=deal_info.get("url"),
                            source_name="itad",
                            game_type="free"
                        ))
                return games
            except Exception as e:
                logger.error(f"[ITAD] fetch failed: {e.__class__.__name__}")
                raise
