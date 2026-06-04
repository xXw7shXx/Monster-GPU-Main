import httpx
from typing import Optional
from loguru import logger


class SteamEnricher:
    def __init__(self):
        self.store_url = "https://store.steampowered.com/api/storesearch"
        self.app_url = "https://store.steampowered.com/api/appdetails"

    async def enrich(self, title: str) -> Optional[dict]:
        """Fetch metadata from Steam Store API by title."""
        try:
            # Search for app by title
            async with httpx.AsyncClient() as client:
                search_resp = await client.get(
                    self.store_url,
                    params={"term": title, "cc": "US", "l": "en", "v": "1"},
                    timeout=10.0,
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()

            items = search_data.get("items", [])
            if not items:
                return None

            appid = items[0].get("id")
            if not appid:
                return None

            # Fetch app details
            async with httpx.AsyncClient() as client:
                detail_resp = await client.get(
                    self.app_url,
                    params={"appids": appid, "cc": "US", "l": "en"},
                    timeout=10.0,
                )
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()

            app_data = detail_data.get(str(appid), {})
            if not app_data.get("success"):
                return None

            data = app_data["data"]
            genres = [g.get("description") for g in data.get("genres", []) if g.get("description")]
            tags = []
            developers = data.get("developers", [])
            screenshots = [ss.get("path_full") for ss in data.get("screenshots", [])[:5] if ss.get("path_full")]

            return {
                "description": data.get("short_description", data.get("about_the_game", "")),
                "genres": ", ".join(genres),
                "tags": ", ".join(tags),
                "developers": ", ".join(developers),
                "screenshots": screenshots,
                "cover": data.get("header_image"),
                "source": "steam",
            }

        except Exception as e:
            logger.warning(f"[Steam Enricher] Failed for '{title}': {e.__class__.__name__}: {e}")
            return None
