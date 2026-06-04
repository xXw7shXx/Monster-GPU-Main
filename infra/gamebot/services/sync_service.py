import logging
from datetime import datetime, timedelta
from database.db import get_session
from database.models import GameCache
from services.igdb_service import igdb_service
from services.deal_orchestrator import DealOrchestrator
from services.game_api import get_upcoming_releases
import os

from services.steam_service import steam_service
from services.opencritic_service import opencritic_service

class SyncService:
    def __init__(self):
        self.deal_orchestrator = DealOrchestrator()

    def upsert_game(self, session, external_id, data):
        game = session.query(GameCache).filter_by(external_id=external_id).first()
        if game:
            for key, value in data.items():
                setattr(game, key, value)
        else:
            game = GameCache(external_id=external_id, **data)
            session.add(game)
        return game

    def sync_steam(self, session):
        logging.info("Syncing Steam specials and releases...")
        specials = steam_service.fetch_specials()
        for s in specials:
            self.upsert_game(session, s["external_id"], s)
        
        new_releases = steam_service.fetch_new_releases()
        for r in new_releases:
            self.upsert_game(session, r["external_id"], r)

    def sync_opencritic_scores(self, session):
        """
        Tiered Fetching: Lazy-load scores for high-profile upcoming games or trending deals.
        """
        logging.info("Lazy-loading OpenCritic scores for high-profile games...")
        
        # Define high-profile criteria: upcoming in next 14 days or recent high-interaction titles
        now = datetime.utcnow()
        candidates = session.query(GameCache).filter(
            GameCache.game_type == 'upcoming',
            GameCache.release_date >= now,
            GameCache.release_date <= now + timedelta(days=14),
            GameCache.critic_score == None # Haven't fetched yet
        ).limit(5).all() # Small batches to preserve quota

        for game in candidates:
            # Quota Check: Never fetch more than once per week
            if game.last_score_sync and game.last_score_sync > now - timedelta(days=7):
                continue
                
            score_data = opencritic_service.fetch_game_score(game.title)
            if score_data:
                game.critic_score = score_data["score"]
                game.critic_tier = score_data["tier"]
                game.last_score_sync = now
                logging.info(f"Updated score for {game.title}: {game.critic_score} ({game.critic_tier})")
            
            # Throttle slightly between candidates
            import time
            time.sleep(1)

    def run_sync(self):
        logging.info("Starting 10-minute Database-First Sync...")
        session = get_session()
        try:
            self.sync_igdb(session)
            self.sync_rawg(session)
            self.sync_deals(session)
            self.sync_steam(session)
            session.commit()
            
            # Post-sync: Lazy-load scores
            self.sync_opencritic_scores(session)
            session.commit()
            
            logging.info("Sync complete.")
        except Exception as e:
            logging.error(f"Sync failed: {e}")
            session.rollback()
        finally:
            session.close()

    def sync_igdb(self, session):
        logging.info("Syncing IGDB upcoming games...")
        games = igdb_service.fetch_upcoming_games() or []
        for g in games:
            # Data Normalization
            platforms = ", ".join([p['name'] for p in g.get('platforms', [])])
            release_date = datetime.fromtimestamp(g.get('first_release_date')) if g.get('first_release_date') else None
            image_url = g.get('cover', {}).get('url', '').replace('t_thumb', 't_cover_big')
            if image_url and image_url.startswith('//'):
                image_url = 'https:' + image_url

            self.upsert_game(session, f"IGDB-{g['id']}", {
                "title": g['name'],
                "platforms": platforms,
                "release_date": release_date,
                "image_url": image_url,
                "source_name": "igdb",
                "game_type": "upcoming"
            })

    def sync_rawg(self, session):
        logging.info("Syncing RAWG upcoming games...")
        games = get_upcoming_releases(days_ahead=30)
        for g in games:
            platforms = ", ".join([p['platform']['name'] for p in g.get('platforms', [])])
            release_date = datetime.strptime(g['released'], '%Y-%m-%d') if g.get('released') else None
            
            self.upsert_game(session, f"RAWG-{g['id']}", {
                "title": g['name'],
                "platforms": platforms,
                "release_date": release_date,
                "image_url": g.get('background_image'),
                "source_name": "rawg",
                "game_type": "upcoming"
            })

    def sync_deals(self, session):
        logging.info("Syncing ITAD and Epic deals...")
        # Fetch all deals (manual command logic but for sync)
        deals = self.deal_orchestrator.fetch_all_deals()
        for d in deals:
            # Normalize title for ID
            normalized_title = "".join(filter(str.isalnum, d.title.lower()))
            expiry = None
            if d.expiry_date:
                try:
                    # Try common ISO formats
                    expiry = datetime.fromisoformat(d.expiry_date.replace('Z', '+00:00'))
                except:
                    pass

            self.upsert_game(session, f"DEAL-{normalized_title}", {
                "title": d.title,
                "platforms": d.platform,
                "original_price": int(d.original_price * 100),
                "current_price": int(d.current_price * 100),
                "expiry_date": expiry,
                "store_link": d.store_link,
                "image_url": d.image_url,
                "source_name": d.source.lower(),
                "game_type": "free"
            })

sync_service = SyncService()
