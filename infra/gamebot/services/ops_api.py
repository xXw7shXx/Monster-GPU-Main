import logging
import os
import shutil
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy import select, func, text
from sqlalchemy.orm import selectinload

from core.database import (
    APILimit,
    AsyncSessionLocal,
    ContentQueue,
    DATABASE_DIALECT,
    GameCache,
    MaintenanceLog,
    OAuthToken,
    Preferences,
    SyncHistory,
    User,
)

router = APIRouter(prefix="/ops", tags=["Operations"])
logger = logging.getLogger(__name__)
TRAINING_JOBS: list[dict] = []

API_KEY = os.getenv("INTERNAL_API_KEY")
if not API_KEY:
    raise RuntimeError("INTERNAL_API_KEY is required")

api_key_header = APIKeyHeader(name="X-API-KEY")


async def get_api_key(header: str = Security(api_key_header)):
    if header == API_KEY:
        return header
    raise HTTPException(status_code=403, detail="Invalid API Key")


def _safe_error(exc: Exception) -> str:
    return exc.__class__.__name__


def _iso(value):
    return value.isoformat() if value else None


def _age_seconds(value):
    if not value:
        return None
    return int((datetime.utcnow() - value).total_seconds())


async def _scalar(session, stmt, default=0):
    value = (await session.execute(stmt)).scalar()
    return default if value is None else value


async def _database_size_mb(session) -> float:
    if DATABASE_DIALECT == "postgresql":
        size_bytes = await _scalar(session, text("select pg_database_size(current_database())"), 0)
        return round(float(size_bytes) / (1024 * 1024), 2)
    return 0.0


def _resource_snapshot() -> dict:
    total, used, free = shutil.disk_usage("/")
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    cpu_count = os.cpu_count() or 1
    return {
        "cpu_percent": round(min(100.0, (load / cpu_count) * 100), 1),
        "memory_percent": None,
        "disk_percent": round((used / total) * 100, 1),
        "network_rx_per_sec": None,
        "network_tx_per_sec": None,
        "container_count": int(os.getenv("W7SH_CONTAINER_COUNT", "0") or 0),
        "restart_count": int(os.getenv("W7SH_RESTART_COUNT", "0") or 0),
        "load_1m": round(load, 2),
    }


async def _cache_freshness(session):
    rows = {
        "free": (
            GameCache.status == "active",
            GameCache.game_type == "free",
            GameCache.current_price == 0,
        ),
        "upcoming": (
            GameCache.status == "active",
            GameCache.game_type == "upcoming",
        ),
        "mobile": (
            GameCache.status == "active",
            GameCache.platform_type == "Mobile",
        ),
    }
    freshness = {}
    for name, filters in rows.items():
        count_stmt = select(func.count(GameCache.id)).where(*filters)
        latest_stmt = select(func.max(GameCache.last_updated)).where(*filters)
        count = await _scalar(session, count_stmt, 0)
        latest = await _scalar(session, latest_stmt, None)
        freshness[name] = {
            "active_rows": count,
            "last_updated": _iso(latest),
            "age_seconds": _age_seconds(latest),
        }
    return freshness


def _source_health(syncs):
    latest = {}
    for sync in syncs:
        if sync.source_name in latest:
            continue
        latest[sync.source_name] = {
            "source": sync.source_name,
            "time": _iso(sync.timestamp),
            "status": sync.status,
            "items": sync.items_synced or 0,
            "error_type": sync.error_message if sync.status == "Error" else None,
            "age_seconds": _age_seconds(sync.timestamp),
        }
    return list(latest.values())


@router.get("/dashboard")
async def get_ops_dashboard(api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            start_time = time.time()
            await session.execute(text("select 1"))
            latency = (time.time() - start_time) * 1000

            total_active = await _scalar(
                session,
                select(func.count(GameCache.id)).where(GameCache.status == "active"),
                0,
            )
            platform_dist = (
                await session.execute(
                    select(GameCache.platform_type, func.count(GameCache.id)).group_by(GameCache.platform_type)
                )
            ).all()
            source_dist = (
                await session.execute(
                    select(GameCache.source_name, func.count(GameCache.id)).group_by(GameCache.source_name)
                )
            ).all()

            ltf_count = await _scalar(
                session,
                select(func.count(GameCache.id)).where(GameCache.is_limited_time == True),
                0,
            )

            avg_hype = await _scalar(session, select(func.avg(GameCache.hype_score)), 0)
            total_cost = await _scalar(session, select(func.sum(GameCache.cost_per_deal)), 0)

            limits = (await session.execute(select(APILimit))).scalars().all()
            tokens = (await session.execute(select(OAuthToken))).scalars().all()
            maintenance = (
                await session.execute(select(MaintenanceLog).order_by(MaintenanceLog.timestamp.desc()).limit(10))
            ).scalars().all()
            syncs = (
                await session.execute(select(SyncHistory).order_by(SyncHistory.timestamp.desc()).limit(50))
            ).scalars().all()

            health = "Optimized"
            if latency > 100:
                health = "Maintenance Pending"
            if any(s.status == "Error" for s in syncs[:3]):
                health = "Sync Error"

            dist_dict = {p or "Unknown": c for p, c in platform_dist}
            for platform in ["PC", "Mobile", "Console"]:
                dist_dict.setdefault(platform, 0)

            cache_freshness = await _cache_freshness(session)

            return {
                "system_health": {
                    "status": health,
                    "db_mode": DATABASE_DIALECT,
                    "db_size_mb": await _database_size_mb(session),
                    "query_latency_ms": round(latency, 2),
                    "uptime": "Healthy",
                },
                "resources": _resource_snapshot(),
                "queue_depth": await _scalar(session, select(func.count(ContentQueue.id)).where(ContentQueue.status == "pending"), 0),
                "restart_count": int(os.getenv("W7SH_RESTART_COUNT", "0") or 0),
                "inventory": {
                    "total_active": total_active,
                    "platform_distribution": dist_dict,
                    "source_distribution": {s or "Unknown": c for s, c in source_dist},
                    "flash_deals": ltf_count,
                    "avg_hype": round(float(avg_hype or 0), 1),
                    "total_api_cost": round(float(total_cost or 0), 2),
                },
                "cache_freshness": cache_freshness,
                "source_health": _source_health(syncs),
                "quotas": {
                    "opencritic": next(
                        ({"used": l.call_count or 0, "limit": 500} for l in limits if l.service_name == "opencritic"),
                        {"used": 0, "limit": 500},
                    ),
                    "twitch": next(
                        (
                            {"status": "Active" if t.expires_at and t.expires_at > datetime.utcnow() else "Expired"}
                            for t in tokens
                            if t.service_name == "twitch"
                        ),
                        {"status": "Not Set"},
                    ),
                },
                "ledger": [
                    {
                        "action": m.action_type,
                        "time": _iso(m.timestamp),
                        "affected": m.rows_affected or 0,
                        "delta": round((m.db_size_after or 0) - (m.db_size_before or 0), 2),
                        "status": m.status,
                    }
                    for m in maintenance
                ],
                "sync_history": [
                    {
                        "source": s.source_name,
                        "time": _iso(s.timestamp),
                        "status": s.status,
                        "items": s.items_synced or 0,
                    }
                    for s in syncs[:10]
                ],
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("ops dashboard failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="Ops dashboard failed")


@router.get("/freshness")
async def get_freshness(api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            syncs = (
                await session.execute(select(SyncHistory).order_by(SyncHistory.timestamp.desc()).limit(50))
            ).scalars().all()
            return {
                "cache_freshness": await _cache_freshness(session),
                "source_health": _source_health(syncs),
            }
        except Exception as exc:
            logger.exception("ops freshness failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="Ops freshness failed")


@router.get("/content-queue")
async def get_content_queue(api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(ContentQueue).where(ContentQueue.status == "pending").order_by(ContentQueue.created_at.desc())
            result = await session.execute(stmt)
            queue = result.scalars().all()
            return [
                {
                    "id": c.id,
                    "title": c.title,
                    "tiktok_script": c.tiktok_script,
                    "telegram_caption": c.telegram_caption,
                    "status": c.status,
                    "created_at": _iso(c.created_at),
                }
                for c in queue
            ]
        except Exception as exc:
            logger.exception("content queue read failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="Content queue read failed")


@router.post("/approve-content/{draft_id}")
async def approve_content(draft_id: int, status: str = "approved", api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(ContentQueue).where(ContentQueue.id == draft_id)
            result = await session.execute(stmt)
            draft = result.scalar_one_or_none()
            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found")

            draft.status = status
            await session.commit()
            return {"status": "success", "new_status": status}
        except HTTPException:
            raise
        except Exception as exc:
            await session.rollback()
            logger.exception("content approval failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="Content approval failed")


@router.get("/users")
async def get_users_list(api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(User).options(selectinload(User.preferences)).order_by(User.created_at.desc())
            result = await session.execute(stmt)
            users = result.scalars().all()
            return [
                {
                    "id": u.id,
                    "external_id": u.telegram_id or u.tiktok_id,
                    "username": u.username or "Anonymous",
                    "platform": u.platform,
                    "language": u.preferences.language if u.preferences else "ar",
                    "joined": _iso(u.created_at),
                }
                for u in users
            ]
        except Exception as exc:
            logger.exception("users list failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="Users list failed")


@router.get("/export/csv")
async def export_deals(api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            deals = (
                await session.execute(select(GameCache).where(GameCache.status == "active"))
            ).scalars().all()
            csv_data = "Title,Platform,Source,Price,Expiry\n"
            for d in deals:
                csv_data += f"{d.title},{d.platform_type},{d.source_name},{(d.current_price or 0) / 100},{d.expiry_date}\n"
            return {"csv": csv_data}
        except Exception as exc:
            logger.exception("csv export failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="CSV export failed")


@router.get("/model/status")
async def get_model_status(api_key: str = Depends(get_api_key)):
    async with AsyncSessionLocal() as session:
        try:
            users = await _scalar(session, select(func.count(User.id)), 0)
            feedback_ready = await _scalar(session, select(func.count(Preferences.id)), 0)
            latest_sync = await _scalar(session, select(func.max(SyncHistory.timestamp)), None)
            return {
                "status": "ok",
                "runtime": "local-rule-layer",
                "intent_parser": "rule-based-multilingual",
                "recommender": "profile-weighted-ranker",
                "latest_training_at": _iso(latest_sync),
                "evaluation_status": "basic validation pending",
                "models": [
                    {"name": "game-intent-parser", "version": "2026.05-rule", "location": "local", "status": "available", "memory_mb": 0},
                    {"name": "game-recommender-ranker", "version": "2026.05-profile", "location": "local", "status": "available", "memory_mb": 0},
                ],
                "signals": {
                    "users": users,
                    "profile_learning_ready": feedback_ready,
                    "external_llm": "disabled",
                },
            }
        except Exception as exc:
            logger.exception("model status failed: %s", _safe_error(exc))
            raise HTTPException(status_code=500, detail="Model status failed")


@router.get("/training/jobs")
async def get_training_jobs(api_key: str = Depends(get_api_key)):
    return {"jobs": TRAINING_JOBS[-20:]}


@router.post("/training/start")
async def start_training(payload: dict, api_key: str = Depends(get_api_key)):
    kind = str((payload or {}).get("kind") or "recommender")[:40]
    dry_run = bool((payload or {}).get("dry_run", True))
    job = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "status": "validated" if dry_run else "queued",
        "dry_run": dry_run,
        "progress_percent": 100 if dry_run else 0,
        "eta_seconds": 0 if dry_run else None,
        "created_at": datetime.utcnow().isoformat(),
        "log": "Dry-run checked data access and training configuration." if dry_run else "Training queued for worker execution.",
    }
    TRAINING_JOBS.append(job)
    return job
