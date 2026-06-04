import os
import requests
import logging
from datetime import datetime, timedelta
from database.db import get_session
from database.models import APILimit, GameCache

class BudgetManager:
    def __init__(self, daily_limit=50):
        self.daily_limit = daily_limit
        self.service_name = 'opencritic'

    def can_call(self) -> bool:
        session = get_session()
        limit = session.query(APILimit).filter_by(service_name=self.service_name).first()
        
        now = datetime.utcnow()
        
        if not limit:
            limit = APILimit(service_name=self.service_name, reset_at=now + timedelta(days=1), call_count=0)
            session.add(limit)
            session.commit()
        
        if now > limit.reset_at:
            limit.call_count = 0
            limit.reset_at = now + timedelta(days=1)
            session.commit()
            
        result = limit.call_count < self.daily_limit
        session.close()
        return result

    def increment(self):
        session = get_session()
        limit = session.query(APILimit).filter_by(service_name=self.service_name).first()
        if limit:
            limit.call_count += 1
            session.commit()
        session.close()

class OpenCriticService:
    def __init__(self):
        self.api_key = os.getenv("OPENCRITIC_API_KEY")
        self.host = os.getenv("OPENCRITIC_HOST")
        self.budget_manager = BudgetManager(daily_limit=20) # Conservative limit

    def fetch_game_score(self, game_title: str):
        """
        Lazy-loads a score for a specific game title.
        """
        if not self.api_key or not self.budget_manager.can_call():
            return None

        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.host
        }

        try:
            # 1. Search for game to get ID
            search_url = f"https://{self.host}/game/search"
            response = requests.get(search_url, headers=headers, params={"criteria": game_title})
            self.budget_manager.increment()
            response.raise_for_status()
            results = response.json()
            
            if not results:
                return None
            
            game_id = results[0]['id']
            
            # 2. Get game details
            if not self.budget_manager.can_call(): return None
            
            detail_url = f"https://{self.host}/game/{game_id}"
            response = requests.get(detail_url, headers=headers)
            self.budget_manager.increment()
            response.raise_for_status()
            details = response.json()
            
            return {
                "score": int(details.get("topCriticScore", -1)),
                "tier": details.get("tier"),
                "id": game_id
            }
        except Exception as e:
            logging.error(f"Error fetching OpenCritic score for {game_title}: {e}")
            return None

opencritic_service = OpenCriticService()
