import httpx
from loguru import logger
from typing import List
from core.schemas import GameObject

class EpicAdapter:
    def __init__(self):
        self.url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"

    async def fetch(self) -> List[GameObject]:
        logger.info("[Epic] Fetching free games...")

        params = {"locale": "en-US", "country": "US", "allowCountries": "US"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.url, params=params, timeout=10.0)
                response.raise_for_status()
                elements = response.json().get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])

                games = []
                for element in elements:
                    promotions = element.get("promotions")
                    if not promotions: continue

                    upcoming = promotions.get("upcomingPromotionalOffers", [])
                    current = promotions.get("promotionalOffers", [])

                    is_free = False
                    expiry = None

                    if current:
                        for promo in current:
                            for offer in promo.get("promotionalOffers", []):
                                if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                                    is_free = True
                                    expiry_str = offer.get("endDate")
                                    if expiry_str:
                                        try:
                                            expiry = __import__('datetime').datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
                                        except: pass
                                    break

                    if is_free:
                        image_url = None
                        for img in element.get("keyImages", []):
                            if img.get("type") in ["Thumbnail", "OfferImageWide", "DieselStoreFrontWide"]:
                                image_url = img.get("url")
                                break

                        slug = element.get("urlSlug") or element.get("catalogNs", {}).get("mappings", [{}])[0].get("pageSlug")
                        link = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://www.epicgames.com/store/en-US/free-games"

                        games.append(GameObject(
                            external_id=f"EPIC-{element['id']}",
                            title=element.get("title"),
                            platforms="PC",
                            original_price=element.get("price", {}).get("totalPrice", {}).get("originalPrice", 0),
                            current_price=0,
                            expiry_date=expiry,
                            store_link=link,
                            image_url=image_url,
                            source_name="epic",
                            game_type="free"
                        ))
                return games
            except Exception as e:
                logger.error(f"[Epic] fetch failed: {e.__class__.__name__}")
                raise
