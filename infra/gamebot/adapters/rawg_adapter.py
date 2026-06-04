import httpx
from loguru import logger
from typing import List
from datetime import datetime
from core.schemas import GameObject
from core.config import settings

class RAWGAdapter:
    def __init__(self):
        self.url = "https://api.rawg.io/api/games"

    async def fetch(self) -> List[GameObject]:
        logger.info("[RAWG] Fetching upcoming games...")

        now = datetime.now()
        start_date = now.strftime('%Y-%m-%d')
        end_date = (now + __import__('datetime').timedelta(days=30)).strftime('%Y-%m-%d')

        params = {
            "key": settings.RAWG_API_KEY,
            "dates": f"{start_date},{end_date}",
            "ordering": "-added",
            "page_size": 20
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.url, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json().get("results")
                if data is None:
                    return []

                games = []
                for g in data:
                    if not g: continue
                    platforms_list = g.get('platforms') or []
                    platforms = ", ".join([p.get('platform', {}).get('name', 'N/A') for p in platforms_list if p])
                    release_date = datetime.strptime(g['released'], '%Y-%m-%d') if g.get('released') else None

                    games.append(GameObject(
                        external_id=f"RAWG-{g['id']}",
                        title=g['name'],
                        platforms=platforms,
                        release_date=release_date,
                        image_url=g.get('background_image'),
                        source_name="rawg",
                        game_type="upcoming"
                    ))
                return games
            except Exception as e:
                logger.error(f"[RAWG] fetch failed: {e.__class__.__name__}")
                raise
