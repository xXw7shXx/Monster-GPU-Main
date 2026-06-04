import asyncio
from loguru import logger
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update

from core.database import AsyncSessionLocal, GameCache, SyncHistory, ContentQueue
from core.schemas import GameObject
from adapters.itad_adapter import ITADAdapter
from adapters.epic_adapter import EpicAdapter
from adapters.igdb_adapter import IGDBAdapter
from adapters.rawg_adapter import RAWGAdapter
from adapters.steam_adapter import SteamAdapter
from adapters.minireview_adapter import MiniReviewAdapter
from engine.budget_manager import OpenCriticBudgetManager
from engine.deal_engine import deal_engine
from engine.bi_engine import bi_engine
from engine.content_drafter import content_drafter
from engine.enrichment_pipeline import EnrichmentPipeline
from utils.normalization import normalizer
from utils.media_worker import media_worker
from database.db import get_session


def _to_db_datetime(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value

def _safe_error(exc: Exception) -> str:
    return exc.__class__.__name__

class GlobalSyncManager:
    def __init__(self):
        # Priority 1 (Free-to-Keep)
        self.itad = ITADAdapter()
        self.epic = EpicAdapter()
        # Priority 2 (Upcoming & Specials & Mobile)
        self.igdb = IGDBAdapter()
        self.rawg = RAWGAdapter()
        self.steam = SteamAdapter()
        self.minireview = MiniReviewAdapter()
        # Priority 3 (Lazy Scores)
        self.oc_budget = OpenCriticBudgetManager()

    async def _upsert_games(self, session, games: list[GameObject]):
        if not games:
            return
        count = 0
        now = datetime.utcnow()
        deduped_games = {}

        for g in games:
            if not getattr(g, 'external_id', None):
                logger.warning(f"Skipping game without external_id: {g.title}")
                continue

            previous = deduped_games.get(g.external_id)
            if previous and previous.game_type == 'free' and g.game_type != 'free':
                continue
            deduped_games[g.external_id] = g

        for g in deduped_games.values():
            should_commit = False

            # SECURITY: Apply Jitter to avoid bot detection
            await bi_engine.apply_jitter()

            stmt = select(GameCache).where(GameCache.external_id == g.external_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            title_to_use = g.title
            if not existing:
                existing_title = await normalizer.find_existing_game(g.title)
                if existing_title:
                    title_to_use = existing_title
                    stmt = select(GameCache).where(GameCache.title == title_to_use)
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()

            data_dict = g.model_dump()
            for datetime_key in ('release_date', 'expiry_date', 'last_score_sync', 'last_updated'):
                if datetime_key in data_dict:
                    data_dict[datetime_key] = _to_db_datetime(data_dict[datetime_key])
            data_dict['title'] = title_to_use

            # MEDIA OPTIMIZATION: Generate thumbnail for Telegram
            if g.image_url:
                data_dict['thumbnail_url'] = await media_worker.optimize_image(g.image_url, g.external_id)

            # BI: Calculate Cost and Hype
            data_dict['cost_per_deal'] = bi_engine.calculate_cost_per_deal(g.source_name)

            if deal_engine.is_flash_freebie(g):
                data_dict['is_limited_time'] = True
                data_dict['status'] = 'active'

            if existing:
                if existing.status != 'active':
                    existing.status = 'active'
                    should_commit = True

                if g.game_type == 'upcoming' and existing.last_updated and existing.last_updated > now - timedelta(hours=24):
                    if should_commit:
                        await session.commit()
                        count += 1
                    continue

                if existing.game_type == 'free' and g.game_type != 'free':
                    if should_commit:
                        await session.commit()
                        count += 1
                    continue

                for k, v in data_dict.items():
                    if k in {'id', 'external_id'}:
                        continue
                    if getattr(existing, k, None) != v:
                        setattr(existing, k, v)
                        should_commit = True
            else:
                new_game = GameCache(**data_dict)
                session.add(new_game)
                should_commit = True

            if should_commit:
                await session.commit()
                count += 1

        logger.debug(f"Upserted {count} records with shortened external_id transactions.")

    async def fetch_priority_1(self):
        """ Fetch Critical 'Free-to-Keep' Deals """
        logger.info("[Priority 1] Fetching Free Deals...")
        results = await asyncio.gather(
            self.itad.fetch(),
            self.epic.fetch(),
            return_exceptions=True
        )
        return {'itad': results[0], 'epic': results[1]}

    async def fetch_priority_2(self):
        """ Fetch High 'Upcoming, Specials' (Mobile moved to dedicated service) """
        logger.info("[Priority 2] Fetching Upcoming & Specials...")
        results = await asyncio.gather(
            self.igdb.fetch(),
            self.rawg.fetch(),
            self.steam.fetch(),
            return_exceptions=True
        )
        return {'igdb': results[0], 'rawg': results[1], 'steam': results[2]}

    async def fetch_priority_3_lazy(self, session):
        """ Fetch Background Review Scores and Generate AI Content (v2.3 Intelligence) """
        logger.info("[Priority 3] Agentic Intelligence & Dynamic Budgeting...")
        now = datetime.utcnow()
        stmt = select(GameCache).where(
            GameCache.game_type == 'upcoming',
            GameCache.release_date >= now,
            GameCache.release_date <= now + timedelta(days=14),
            GameCache.critic_score.is_(None)
        ).limit(10)
        
        result = await session.execute(stmt)
        candidates = result.scalars().all()
        
        for game in candidates:
            # 📉 DYNAMIC BUDGETING: Skip low-quality asset flips
            if content_drafter.is_asset_flip(game):
                logger.info(f"[Budget] Skipping low-quality title: {game.title}")
                game.critic_score = -1 # Flag as skipped
                continue

            if not await self.oc_budget.can_call():
                break
            
            score_data = await self.oc_budget.fetch_score(game.title)
            if score_data:
                game.critic_score = score_data['score']
                game.critic_tier = score_data['tier']
                game.last_score_sync = now
                
                # 🧠 AGENTIC INTELLIGENCE: Draft content with Vibe & Trend analysis
                if game.critic_score >= 75:
                    logger.info(f"[Agentic] Analyzing Vibe/Trend for: {game.title}")
                    drafts = await content_drafter.generate_drafts(game)
                    
                    new_draft = ContentQueue(
                        game_id=game.id,
                        title=game.title,
                        vibe_tag=drafts.get('vibe'),
                        tiktok_script=drafts.get('tiktok'),
                        telegram_caption=drafts.get('telegram'),
                        trend_priority=drafts.get('priority', 5),
                        status='pending'
                    )
                    session.add(new_draft)
                    logger.success(f"[Intelligence] {drafts.get('vibe')} detected! {game.title} queued.")
                
                logger.success(f"Score synced for {game.title}: {game.critic_score}")
                await asyncio.sleep(1)
        await session.commit()


    async def run_sync_cycle(self):
        logger.info("=== Starting Global 2.3 Sync Cycle ===")
        async with AsyncSessionLocal() as session:
            try:
                p1_res, p2_res = await asyncio.gather(
                    self.fetch_priority_1(),
                    self.fetch_priority_2(),
                    return_exceptions=True
                )

                source_results = {}
                if isinstance(p1_res, Exception):
                    logger.error(f"[Sync] priority 1 fetch failed: {_safe_error(p1_res)}")
                else:
                    source_results.update(p1_res)
                if isinstance(p2_res, Exception):
                    logger.error(f"[Sync] priority 2 fetch failed: {_safe_error(p2_res)}")
                else:
                    source_results.update(p2_res)

                all_incoming = []
                for source in ['epic', 'itad', 'igdb', 'rawg', 'steam']:
                    res = source_results.get(source)
                    if isinstance(res, Exception):
                        error_type = _safe_error(res)
                        session.add(SyncHistory(source_name=source, status='Error', error_message=error_type, items_synced=0))
                        logger.error(f"[Adapter Failure] {source} failed: {error_type}")
                        continue

                    items = res if isinstance(res, list) else []
                    all_incoming.extend(items)
                    session.add(SyncHistory(source_name=source, status='Success', items_synced=len(items)))

                await session.commit()

                if all_incoming:
                    try:
                        await self._upsert_games(session, all_incoming)

                        flash_freebies = await deal_engine.process_potential_freebies(all_incoming)
                        if flash_freebies:
                            logger.warning(f"[FLASH ALERT] {len(flash_freebies)} urgent deals detected!")
                    except Exception as exc:
                        await session.rollback()
                        logger.exception(f"Sync cache upsert failed: {_safe_error(exc)}")

                try:
                    await self.fetch_priority_3_lazy(session)
                except Exception as exc:
                    await session.rollback()
                    logger.error(f"Lazy sync enrichment failed: {_safe_error(exc)}")

                try:
                    enrich_session = get_session()
                    pipeline = EnrichmentPipeline(enrich_session)
                    await pipeline.enrich_batch(limit=20)
                    enrich_session.close()
                except Exception as e:
                    logger.warning(f"[Sync] Post-sync enrichment failed: {e}")

                logger.info("=== Sync Cycle 2.3 Complete ===")
            except Exception as e:
                logger.exception(f"Sync Engine Failure: {_safe_error(e)}")
                await session.rollback()
