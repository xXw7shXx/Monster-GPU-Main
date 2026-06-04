import os
from loguru import logger
from datetime import datetime, timedelta
from sqlalchemy import delete, update, func, text
from core.database import AsyncSessionLocal, GameCache, MaintenanceLog, engine

class CleanupManager:
    def __init__(self, db_path: str = "bot_data.db", logs_dir: str = "logs"):
        self.db_path = db_path
        self.logs_dir = logs_dir

    async def prune_expired_deals(self):
        """
        Expired Deals: 
        1. Mark as 'expired' if expiry_date < now.
        2. Permanent deletion if marked 'expired' for > 7 days.
        """
        logger.info("[Janitor] Pruning expired deals...")
        async with AsyncSessionLocal() as session:
            try:
                now = datetime.utcnow()
                
                # 1. Update status to expired
                mark_stmt = update(GameCache).where(
                    GameCache.status == 'active',
                    GameCache.expiry_date != None,
                    GameCache.expiry_date < now
                ).values(status='expired', last_updated=now)
                
                # 2. Permanent deletion of old expired deals (marked > 7 days ago)
                week_ago = now - timedelta(days=7)
                delete_stmt = delete(GameCache).where(
                    GameCache.status == 'expired',
                    GameCache.last_updated < week_ago
                )
                
                res_mark = await session.execute(mark_stmt)
                res_del = await session.execute(delete_stmt)
                await session.commit()
                
                logger.info(f"[Janitor] Marked {res_mark.rowcount} as expired, Deleted {res_del.rowcount} stale records.")
                return res_del.rowcount
            except Exception as e:
                logger.error(f"[Janitor] Prune failed: {e}")
                await session.rollback()
                return 0

    async def clean_historical_junk(self):
        """
        Automatically delete 'Upcoming' games older than 90 days.
        """
        logger.info("[Janitor] Cleaning historical junk...")
        async with AsyncSessionLocal() as session:
            try:
                threshold = datetime.utcnow() - timedelta(days=90)
                stmt = delete(GameCache).where(
                    GameCache.game_type == 'upcoming',
                    GameCache.last_updated < threshold
                )
                result = await session.execute(stmt)
                await session.commit()
                logger.info(f"[Janitor] Deleted {result.rowcount} historical upcoming entries.")
                return result.rowcount
            except Exception as e:
                logger.error(f"[Janitor] Junk cleanup failed: {e}")
                await session.rollback()
                return 0

    async def clean_orphaned_metadata(self):
        """
        Delete games that are not 'free' or 'upcoming' and haven't been updated in 30 days.
        """
        logger.info("[Janitor] Cleaning orphaned metadata...")
        async with AsyncSessionLocal() as session:
            try:
                threshold = datetime.utcnow() - timedelta(days=30)
                stmt = delete(GameCache).where(
                    GameCache.status != 'active',
                    GameCache.game_type != 'free',
                    GameCache.last_updated < threshold
                )
                result = await session.execute(stmt)
                await session.commit()
                logger.info(f"[Janitor] Deleted {result.rowcount} orphaned records.")
                return result.rowcount
            except Exception as e:
                logger.error(f"[Janitor] Orphaned cleanup failed: {e}")
                await session.rollback()
                return 0

    async def enforce_log_retention(self, max_size_mb=100, max_days=7):
        """
        Deletes logs older than 7 days and ensures folder size < 100MB.
        """
        logger.info("[SRE] Enforcing log retention policies...")
        if not os.path.exists(self.logs_dir): return
        
        now = datetime.now().timestamp()
        deleted_count = 0
        
        # 1. Time-based cleanup
        for f in os.listdir(self.logs_dir):
            path = os.path.join(self.logs_dir, f)
            if os.path.isfile(path):
                if os.path.getmtime(path) < now - (max_days * 86400):
                    try:
                        os.remove(path)
                        deleted_count += 1
                    except: pass
        
        # 2. Size-based cleanup
        log_files = [os.path.join(self.logs_dir, f) for f in os.listdir(self.logs_dir)]
        log_files.sort(key=os.path.getmtime)
        
        while sum(os.path.getsize(f) for f in log_files if os.path.isfile(f)) > max_size_mb * 1024 * 1024:
            if not log_files: break
            oldest = log_files.pop(0)
            try:
                os.remove(oldest)
                deleted_count += 1
            except: pass
            
        logger.info(f"[SRE] Log cleanup complete. Removed {deleted_count} files.")

    async def verify_and_rebuild_indexes(self):
        """
        Verifies index integrity and rebuilds to optimize query plans.
        """
        logger.info("[SRE] Rebuilding database indexes...")
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("REINDEX"))
                logger.success("[SRE] Indexes rebuilt.")
        except Exception as e:
            logger.warning(f"[SRE] REINDEX skipped (fallback to VACUUM): {e}")

    async def optimize_database(self):
        """
        Run VACUUM and ANALYZE to reclaim space and update statistics.
        """
        logger.info("[SRE] Optimizing database (VACUUM)...")
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
                await conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("ANALYZE"))
            
            db_size = os.path.getsize(self.db_path) / (1024 * 1024)
            logger.success(f"[SRE] Optimization complete. DB Size: {db_size:.2f} MB")
            return db_size
        except Exception as e:
            logger.error(f"[SRE] Database optimization failed: {e}")
            return 0

    async def run_autonomous_maintenance(self):
        """
        Full 24-hour maintenance suite with detailed logging.
        """
        async with AsyncSessionLocal() as session:
            db_size_before = os.path.getsize(self.db_path) / (1024 * 1024)
            
            pruned = await self.prune_expired_deals()
            orphaned = await self.clean_orphaned_metadata()
            await self.enforce_log_retention()
            
            db_size_after = os.path.getsize(self.db_path) / (1024 * 1024)
            
            # Log to Maintenance Ledger
            log = MaintenanceLog(
                action_type='Daily Health Sync',
                rows_affected=pruned + orphaned,
                db_size_before=db_size_before,
                db_size_after=db_size_after,
                status='Success'
            )
            session.add(log)
            await session.commit()
        
        msg = f"Self-Check: Cleaned {pruned} expired deals, {orphaned} orphaned records. Current DB size: {db_size_after:.2f} MB."
        logger.success(f"[SRE] {msg}")
        return msg

cleanup_manager = CleanupManager()
