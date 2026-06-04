import os
import requests
import logging
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
from database.db import get_session
from database.models import NotifiedDeal
from utils.localization import get_string

@dataclass
class GameDeal:
    title: str
    platform: str
    original_price: float
    current_price: float
    expiry_date: Optional[str]
    store_link: str
    image_url: Optional[str]
    source: str
    is_upcoming: bool = False
    platform_type: str = "PC"
    monetization_tags: Optional[str] = None

class GameSource:
    def fetch_deals(self) -> List[GameDeal]:
        raise NotImplementedError

class ITADSource(GameSource):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.isthereanydeal.com/deals/v2"

    def fetch_deals(self) -> List[GameDeal]:
        if not self.api_key:
            return []
        
        params = {
            "key": self.api_key,
            "country": "US",
            "sort": "cut:desc",
            "limit": 50
        }
        
        try:
            response = requests.get(self.url, params=params)
            response.raise_for_status()
            data = response.json().get("list", [])
            
            deals = []
            for item in data:
                deal_info = item.get("deal", {})
                if deal_info.get("cut") == 100:
                    deals.append(GameDeal(
                        title=item.get("title"),
                        platform=deal_info.get("shop", {}).get("name", "PC"),
                        original_price=deal_info.get("regular", {}).get("amount", 0.0),
                        current_price=0.0,
                        expiry_date=deal_info.get("expiry"),
                        store_link=deal_info.get("url"),
                        image_url=None,
                        source="ITAD"
                    ))
            return deals
        except Exception as e:
            logging.error(f"Error fetching ITAD deals: {e}")
            return []

class EpicGamesSource(GameSource):
    def __init__(self):
        self.url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"

    def fetch_deals(self) -> List[GameDeal]:
        params = {"locale": "en-US", "country": "US", "allowCountries": "US"}
        try:
            response = requests.get(self.url, params=params)
            response.raise_for_status()
            elements = response.json().get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
            
            deals = []
            for element in elements:
                promotions = element.get("promotions")
                if not promotions:
                    continue
                
                upcoming = promotions.get("upcomingPromotionalOffers", [])
                current = promotions.get("promotionalOffers", [])
                
                is_free = False
                is_upcoming = False
                expiry = None

                if current:
                    for promo in current:
                        for offer in promo.get("promotionalOffers", []):
                            if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                                is_free = True
                                expiry = offer.get("endDate")
                                break
                
                if not is_free and upcoming:
                    for promo in upcoming:
                        for offer in promo.get("promotionalOffers", []):
                            if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                                is_upcoming = True
                                expiry = offer.get("startDate")
                                break

                if is_free or is_upcoming:
                    image_url = None
                    for img in element.get("keyImages", []):
                        if img.get("type") in ["Thumbnail", "OfferImageWide", "DieselStoreFrontWide"]:
                            image_url = img.get("url")
                            break

                    slug = element.get("urlSlug") or element.get("catalogNs", {}).get("mappings", [{}])[0].get("pageSlug")
                    link = f"https://store.epicgames.com/en-US/p/{slug}" if slug else "https://www.epicgames.com/store/en-US/free-games"

                    deals.append(GameDeal(
                        title=element.get("title"),
                        platform="Epic Games Store",
                        original_price=element.get("price", {}).get("totalPrice", {}).get("originalPrice", 0) / 100,
                        current_price=0.0,
                        expiry_date=expiry,
                        store_link=link,
                        image_url=image_url,
                        source="Epic Games Store",
                        is_upcoming=is_upcoming
                    ))
            return deals
        except Exception as e:
            logging.error(f"Error fetching Epic Games deals: {e}")
            return []

class GamerPowerSource(GameSource):
    def __init__(self):
        self.url = "https://www.gamerpower.com/api/giveaways"

    def fetch_deals(self) -> List[GameDeal]:
        try:
            response = requests.get(self.url, params={"type": "game"})
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("status") == 0:
                return []
            
            deals = []
            for item in data:
                worth = item.get("worth", "0").replace("$", "").strip()
                try:
                    orig_price = float(worth) if worth and worth != "N/A" else 0.0
                except:
                    orig_price = 0.0

                deals.append(GameDeal(
                    title=item.get("title"),
                    platform=item.get("platforms"),
                    original_price=orig_price,
                    current_price=0.0,
                    expiry_date=item.get("end_date"),
                    store_link=item.get("open_giveaway_url"),
                    image_url=item.get("image"),
                    source="GamerPower"
                ))
            return deals
        except Exception as e:
            logging.error(f"Error fetching GamerPower deals: {e}")
            return []

class DealOrchestrator:
    def __init__(self):
        self.sources = [
            ITADSource(os.getenv("ITAD_API_KEY")),
            EpicGamesSource(),
            GamerPowerSource()
        ]

    def fetch_all_deals(self) -> List[GameDeal]:
        all_deals = []
        for source in self.sources:
            try:
                deals = source.fetch_deals()
                all_deals.extend(deals)
            except Exception as e:
                logging.error(f"Source {source.__class__.__name__} failed: {e}")
        
        merged_deals = {}
        for deal in all_deals:
            key = "".join(filter(str.isalnum, deal.title.lower()))
            if not key: continue

            if key not in merged_deals:
                merged_deals[key] = deal
            else:
                if deal.platform.lower() not in merged_deals[key].platform.lower():
                    merged_deals[key].platform += f", {deal.platform}"
                
                if deal.source == "Epic Games Store":
                    merged_deals[key].store_link = deal.store_link
                    merged_deals[key].image_url = deal.image_url
                
                if deal.original_price > merged_deals[key].original_price:
                    merged_deals[key].original_price = deal.original_price

        return list(merged_deals.values())

    def get_new_deals(self) -> List[GameDeal]:
        deals = self.fetch_all_deals()
        session = get_session()
        new_deals = []
        for deal in deals:
            key = "".join(filter(str.isalnum, deal.title.lower()))
            exists = session.query(NotifiedDeal).filter_by(deal_id=key).first()
            if not exists:
                new_deals.append(deal)
                notified = NotifiedDeal(deal_id=key, platform=deal.platform)
                session.add(notified)
        session.commit()
        session.close()
        return new_deals

def format_deal_message(deal: GameDeal, lang='en'):
    platform_str = get_string(lang, 'platform')
    value_str = get_string(lang, 'value')
    free_str = get_string(lang, 'free')
    end_date_str = get_string(lang, 'end_date')
    claim_str = get_string(lang, 'claim_here')
    upcoming_str = f" ({get_string(lang, 'coming_in')}...)" if deal.is_upcoming else ""
    price_text = f"${deal.original_price:.2f}" if deal.original_price > 0 else "N/A"
    
    # Monetization Label (e.g., [Ads/IAP])
    monetization_label = f" 🏷️ <i>[{deal.monetization_tags}]</i>" if deal.monetization_tags else ""
    
    # Platform Icon
    platform_icon = "📱" if deal.platform_type == "Mobile" else "💻"
    
    text = (
        f"🎁 <b>{deal.title}{upcoming_str}</b>\n"
        f"{platform_icon} {platform_str}: {deal.platform}{monetization_label}\n"
        f"💰 {value_str}: <s>{price_text}</s> -> {free_str}\n"
        f"📅 {end_date_str}: {deal.expiry_date or 'Unknown'}\n"
        f"🔗 <a href='{deal.store_link}'>{claim_str}</a>"
    )
    return text, deal.image_url

def format_flash_alert(deal: GameDeal, lang='en'):
    """
    High-Impact template for Limited-Time Freebies.
    """
    claim_str = get_string(lang, 'claim_here')
    platform_icon = "📱" if deal.platform_type == "Mobile" else "💻"
    
    # Calculate time remaining if expiry exists
    timer_text = ""
    if deal.expiry_date:
        try:
            # Handle string or datetime
            expiry = deal.expiry_date
            if isinstance(expiry, str):
                expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
            
            remaining = expiry - datetime.utcnow()
            if remaining.total_seconds() > 0:
                hours = int(remaining.total_seconds() // 3600)
                timer_text = f"\n⏱️ <b>Ends in: {hours} hours!</b>"
        except: pass

    text = (
        f"🚨 <b>FLASH FREEBIE ALERT</b> 🚨\n\n"
        f"🔥 <b>{deal.title}</b> is currently <b>FREE</b>!\n"
        f"{platform_icon} Platform: {deal.platform}\n"
        f"💵 Value: <s>${deal.original_price:.2f}</s>\n"
        f"{timer_text}\n\n"
        f"⚡ <a href='{deal.store_link}'>{claim_str.upper()} NOW</a> ⚡"
    )
    return text, deal.image_url

def fetch_deals():
    orchestrator = DealOrchestrator()
    return orchestrator.get_new_deals()
