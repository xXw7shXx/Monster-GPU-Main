import asyncio
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.database import init_db
from engine.sync_manager import GlobalSyncManager
from engine.deal_engine import deal_engine

async def scheduled_sync():
    manager = GlobalSyncManager()
    await manager.run_sync_cycle()

async def main():
    # Initialize Database
    logger.info("Initializing Database...")
    await init_db()
    
    # Initialize Sync Engine
    logger.info("Initializing Global Sync Engine...")
    scheduler = AsyncIOScheduler()
    
    # Ingestion Cycle (10 mins)
    scheduler.add_job(scheduled_sync, 'interval', minutes=10, next_run_time=None)
    
    scheduler.start()
    
    # Trigger first run
    await scheduled_sync()
    
    # Keep main thread alive
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down gracefully...")

if __name__ == "__main__":
    # Configure Loguru: Main App Rotation
    logger.add("logs/enterprise_engine.log", rotation="50 MB", retention="5 days", level="INFO")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
