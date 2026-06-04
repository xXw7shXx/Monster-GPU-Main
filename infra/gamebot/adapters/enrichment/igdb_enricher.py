import httpx
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from core.config import settings


class IGDBEnricher:
    def __init__(self):
        self.base_url = "https://api.igdb.com/v4"
        self.oauth_url = "https://id.twitch.tv/oauth2/token"
        self.token: Optional[str] = None
        self.token_expiry = datetime.utcnow()

    async def _get_token(self) -> str:
        if self.token and datetime.utcnow() < self.token_expiry:
            return self.token
        payload = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "client_secret": settings.TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.oauth_url, data=payload)
            resp.raise_for_status()
            data = resp.json()
            self.token = data["access_token"]
            self.token_expiry = datetime.utcnow() + timedelta(seconds=data["expires_in"] - 60)
            return self.token

    async def enrich(self, title: str, platform_type: Optional[str] = None) -> Optional[dict]:
        try:
            token = await self._get_token()
            headers = {"Client-ID": settings.TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}

            search_body = f'fields game; search "{title.replace(chr(34), chr(92)+chr(34))}"; limit 1;'
            async with httpx.AsyncClient() as client:
                search_resp = await client.post(
                    f"{self.base_url}/search",
                    headers=headers,
                    data=search_body,
                    timeout=10.0,
                )
                search_resp.raise_for_status()
                search_results = search_resp.json()

            if not search_results:
                return None

            game_id = search_results[0].get("game")
            if not game_id:
                return None

            game_body = (
                f"fields name, summary, genres.name, themes.name, keywords.name, "
                f"involved_companies.company.name, cover.url, screenshots.url; "
                f"where id = {game_id};"
            )
            async with httpx.AsyncClient() as client:
                game_resp = await client.post(
                    f"{self.base_url}/games",
                    headers=headers,
                    data=game_body,
                    timeout=10.0,
                )
                game_resp.raise_for_status()
                games = game_resp.json()

            if not games:
                return None

            g = games[0]
            genres = [gn.get("name") for gn in g.get("genres", []) if gn.get("name")]
            themes = [th.get("name") for th in g.get("themes", []) if th.get("name")]
            keywords = [kw.get("name") for kw in g.get("keywords", []) if kw.get("name")]
            companies = []
            for ic in g.get("involved_companies", []):
                c = ic.get("company", {})
                if c.get("name"):
                    companies.append(c["name"])

            screenshots = []
            for ss in g.get("screenshots", []):
                if ss.get("url"):
                    screenshots.append(ss["url"].replace("t_thumb", "t_screenshot_big"))

            cover = None
            if g.get("cover", {}).get("url"):
                cover = g["cover"]["url"].replace("t_thumb", "t_cover_big")

            return {
                "description": g.get("summary", ""),
                "genres": ", ".join(genres),
                "tags": ", ".join(themes + keywords),
                "developers": ", ".join(companies),
                "screenshots": screenshots[:5],
                "cover": cover,
                "source": "igdb",
            }

        except Exception as e:
            logger.warning(f"[IGDB Enricher] Failed for '{title}': {e.__class__.__name__}: {e}")
            return None
