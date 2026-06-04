import asyncio
import time
from loguru import logger
from engine.sync_manager import GlobalSyncManager
from core.database import init_db, SyncHistory

async def run_service():
    logger.info("[MiniReview Service] Starting Mobile Scraper Service...")
    sync_manager = GlobalSyncManager()
    
    # Initialize DB (Postgres or SQLite based on DATABASE_URL)
    await init_db()
    
    while True:
        try:
            logger.info("[MiniReview] Starting periodic fetch...")
            # We only want to trigger MiniReview specifically here
            games = await sync_manager.minireview.fetch()
            
            from core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                if isinstance(games, list) and games:
                    logger.success(f"[MiniReview] Fetched {len(games)} mobile games.")
                    await sync_manager._upsert_games(session, games)
                    session.add(SyncHistory(source_name='minireview', status='Success', items_synced=len(games)))
                    logger.success("[MiniReview] Sync complete.")
                elif isinstance(games, list) and not games:
                    logger.warning("[MiniReview] No games fetched. site structure might have changed.")
                    session.add(SyncHistory(source_name='minireview', status='Success', items_synced=0))
                else:
                    logger.error("[MiniReview] Failed to fetch.")
                    session.add(SyncHistory(source_name='minireview', status='Error', error_message="Failed to fetch", items_synced=0))
                await session.commit()
                
        except Exception as e:
            logger.error(f"[MiniReview Service] Loop Failure: {e}")
            from core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                session.add(SyncHistory(source_name='minireview', status='Error', error_message=str(e), items_synced=0))
                await session.commit()
        
        # Sync every 4 hours
        logger.info("[MiniReview Service] Sleeping for 4 hours...")
        await asyncio.sleep(14400)

if __name__ == "__main__":
    try:
        asyncio.run(run_service())
    except KeyboardInterrupt:
        logger.info("[MiniReview Service] Shutting down...")
