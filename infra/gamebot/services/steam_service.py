import os
import requests
import logging
from typing import List
from dataclasses import dataclass
from datetime import datetime

class SteamService:
    def __init__(self):
        self.api_key = os.getenv("STEAM_API_KEY")
        # Featured categories is public and provides specials/top sellers
        self.featured_url = "https://store.steampowered.com/api/featuredcategories"
        # StoreService requires API Key
        self.store_service_url = "https://api.steampowered.com/IStoreService/GetAppList/v1/"

    def fetch_specials(self):
        """
        Fetches current Steam specials (Price cuts, featured deals).
        """
        try:
            response = requests.get(self.featured_url)
            response.raise_for_status()
            data = response.json()
            
            specials = data.get("specials", {}).get("items", [])
            normalized_specials = []
            
            for item in specials:
                # Check for significant discount or free weekend
                if item.get("discount_percent", 0) > 0:
                    normalized_specials.append({
                        "external_id": f"STEAM-{item['id']}",
                        "title": item["name"],
                        "original_price": item.get("original_price", 0), # in cents already
                        "current_price": item.get("final_price", 0),
                        "store_link": f"https://store.steampowered.com/app/{item['id']}/",
                        "image_url": item.get("large_capsule_image") or item.get("header_image"),
                        "source_name": "steam",
                        "game_type": "special"
                    })
            return normalized_specials
        except Exception as e:
            logging.error(f"Error fetching Steam specials: {e}")
            return []

    def fetch_new_releases(self):
        """
        Fetches new releases from Steam featured categories.
        """
        try:
            response = requests.get(self.featured_url)
            response.raise_for_status()
            data = response.json()
            
            new_items = data.get("new_releases", {}).get("items", [])
            normalized_new = []
            
            for item in new_items:
                normalized_new.append({
                    "external_id": f"STEAM-{item['id']}",
                    "title": item["name"],
                    "original_price": item.get("original_price", 0),
                    "current_price": item.get("final_price", 0),
                    "store_link": f"https://store.steampowered.com/app/{item['id']}/",
                    "image_url": item.get("large_capsule_image"),
                    "source_name": "steam",
                    "game_type": "upcoming" # Mapped to upcoming if very new
                })
            return normalized_new
        except Exception as e:
            logging.error(f"Error fetching Steam new releases: {e}")
            return []

steam_service = SteamService()
