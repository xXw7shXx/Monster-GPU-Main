import asyncio
import os
from loguru import logger
from engine.sync_manager import GlobalSyncManager
from core.database import init_db

async def run_handshake():
    logger.info("Starting Handshake Test...")
    # 1. Initialize DB
    await init_db()
    
    # 2. Trigger Sync Manager
    manager = GlobalSyncManager()
    logger.info("Attempting Manual Sync (ITAD/Steam Priorities)...")
    await manager.run_sync_cycle()
    logger.info("Handshake Complete.")

if __name__ == "__main__":
    asyncio.run(run_handshake())
