import asyncio
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from engine.cleanup_manager import cleanup_manager
from core.database import init_db

async def run_daily_maintenance():
    """
    Triggers the autonomous 24-hour maintenance suite.
    """
    logger.info("=== Starting Autonomous Daily Maintenance ===")
    status_msg = await cleanup_manager.run_autonomous_maintenance()
    logger.success(f"[SRE] Maintenance Result: {status_msg}")

async def run_weekly_optimization():
    """
    Sundays at 3:00 AM: Deep DB Reconstruction.
    """
    logger.info("=== Starting Weekly Sunday Optimization (3:00 AM) ===")
    await cleanup_manager.verify_and_rebuild_indexes()
    await cleanup_manager.optimize_database()
    logger.success("[SRE] Weekly optimization suite finished.")

async def main():
    logger.info("Initializing Autonomous Maintenance Service...")
    await init_db()
    
    scheduler = AsyncIOScheduler()
    
    # 1. Daily Health Sync (Every 24 hours)
    scheduler.add_job(run_daily_maintenance, 'interval', hours=24, next_run_time=None)
    
    # 2. Weekly Sunday Optimization (3:00 AM)
    scheduler.add_job(run_weekly_optimization, 'cron', day_of_week='sun', hour=3, minute=0)
    
    # Start scheduler
    scheduler.start()
    
    # Trigger initial health check on service start
    await run_daily_maintenance()
    
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Maintenance Service shutting down...")

if __name__ == "__main__":
    logger.add("logs/maintenance_service.log", rotation="50 MB", retention="7 days", level="INFO")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
