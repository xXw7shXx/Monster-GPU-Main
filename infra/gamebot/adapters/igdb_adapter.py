import httpx
from loguru import logger
from datetime import datetime, timedelta
from typing import List
from core.schemas import GameObject
from core.config import settings

class IGDBAdapter:
    def __init__(self):
        self.base_url = "https://api.igdb.com/v4/games"
        self.oauth_url = "https://id.twitch.tv/oauth2/token"
        self.token = None
        self.token_expiry = datetime.utcnow()

    async def _get_token(self) -> str:
        if self.token and datetime.utcnow() < self.token_expiry:
            return self.token

        payload = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "client_secret": settings.TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.oauth_url, data=payload)
                response.raise_for_status()
                data = response.json()
                self.token = data["access_token"]
                self.token_expiry = datetime.utcnow() + timedelta(seconds=data["expires_in"] - 60)
                return self.token
            except Exception as e:
                logger.error(f"[IGDB] OAuth token request failed: {e.__class__.__name__}")
                raise

    async def fetch(self) -> List[GameObject]:
        logger.info("[IGDB] Fetching upcoming games...")
        token = await self._get_token()
        headers = {
            "Client-ID": settings.TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {token}"
        }

        now = int(datetime.utcnow().timestamp())
        next_month = int((datetime.utcnow() + timedelta(days=30)).timestamp())

        query = (
            f"fields name, first_release_date, platforms.name, cover.url, summary; "
            f"where first_release_date >= {now} & first_release_date <= {next_month}; "
            f"sort first_release_date asc; "
            f"limit 50;"
        )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.base_url, headers=headers, data=query, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                games = []
                for g in data:
                    platforms = ", ".join([p['name'] for p in g.get('platforms', [])])
                    release_date = datetime.fromtimestamp(g.get('first_release_date')) if g.get('first_release_date') else None
                    image_url = g.get('cover', {}).get('url', '').replace('t_thumb', 't_cover_big')
                    if image_url and image_url.startswith('//'):
                        image_url = 'https:' + image_url

                    games.append(GameObject(
                        external_id=f"IGDB-{g['id']}",
                        title=g['name'],
                        platforms=platforms,
                        release_date=release_date,
                        image_url=image_url,
                        source_name="igdb",
                        game_type="upcoming"
                    ))
                return games
            except Exception as e:
                logger.error(f"[IGDB] fetch failed: {e.__class__.__name__}")
                raise
