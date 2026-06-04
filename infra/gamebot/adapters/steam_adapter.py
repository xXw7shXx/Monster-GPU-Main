import httpx
from loguru import logger
from typing import List
from core.schemas import GameObject
from core.config import settings

class SteamAdapter:
    def __init__(self):
        self.featured_url = "https://store.steampowered.com/api/featuredcategories"

    async def fetch(self) -> List[GameObject]:
        logger.info("[Steam] Fetching specials and releases...")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.featured_url, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                games = []

                # Fetch Specials
                specials = data.get("specials", {}).get("items", [])
                for item in specials:
                    if item.get("discount_percent", 0) > 0:
                        games.append(GameObject(
                            external_id=f"STEAM-{item['id']}",
                            title=item["name"],
                            original_price=item.get("original_price") or 0,
                            current_price=item.get("final_price") or 0,
                            store_link=f"https://store.steampowered.com/app/{item['id']}/",
                            image_url=item.get("large_capsule_image") or item.get("header_image"),
                            source_name="steam",
                            game_type="free" if item.get("discount_percent") == 100 else "special"
                        ))

                # Fetch New Releases
                new_releases = data.get("new_releases", {}).get("items", [])
                for item in new_releases:
                    games.append(GameObject(
                        external_id=f"STEAM-{item['id']}",
                        title=item["name"],
                        original_price=item.get("original_price") or 0,
                        current_price=item.get("final_price") or 0,
                        store_link=f"https://store.steampowered.com/app/{item['id']}/",
                        image_url=item.get("large_capsule_image"),
                        source_name="steam",
                        game_type="upcoming"
                    ))

                return games
            except Exception as e:
                logger.error(f"[Steam] fetch failed: {e.__class__.__name__}")
                raise
