import os
import requests
import logging
from datetime import datetime, timedelta
from database.db import get_session
from database.models import OAuthToken

class IGDBService:
    def __init__(self):
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.oauth_url = "https://id.twitch.tv/oauth2/token"
        self.base_url = "https://api.igdb.com/v4/games"

    def get_token(self):
        session = get_session()
        token_record = session.query(OAuthToken).filter_by(service_name='twitch').first()
        
        # Check if token exists and is not expired (with 1 min buffer)
        if token_record and token_record.expires_at > datetime.utcnow() + timedelta(minutes=1):
            token = token_record.access_token
            session.close()
            return token
        
        # Refresh token
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        
        try:
            response = requests.post(self.oauth_url, data=payload)
            response.raise_for_status()
            data = response.json()
            
            token = data["access_token"]
            expires_in = data["expires_in"]
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            if token_record:
                token_record.access_token = token
                token_record.expires_at = expires_at
            else:
                token_record = OAuthToken(
                    service_name='twitch',
                    access_token=token,
                    expires_at=expires_at
                )
                session.add(token_record)
            
            session.commit()
            return token
        except Exception as e:
            logging.error(f"Failed to fetch Twitch token: {e}")
            return None
        finally:
            session.close()

    def fetch_upcoming_games(self):
        token = self.get_token()
        if not token:
            return []

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}"
        }

        # Apicalypse query for games releasing in the next 30 days
        now = int(datetime.utcnow().timestamp())
        next_month = int((datetime.utcnow() + timedelta(days=30)).timestamp())
        
        query = (
            f"fields name, first_release_date, platforms.name, cover.url, summary; "
            f"where first_release_date >= {now} & first_release_date <= {next_month}; "
            f"sort first_release_date asc; "
            f"limit 50;"
        )

        try:
            response = requests.post(self.base_url, headers=headers, data=query)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Error fetching IGDB upcoming games: {e}")
            return []

igdb_service = IGDBService()
