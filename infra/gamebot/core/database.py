"""Async SQLAlchemy engine/session setup for gamebot."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from database.schema import (
    APICache,
    APILimit,
    ActivityLog,
    Base,
    ContentQueue,
    GameCache,
    MaintenanceLog,
    NotifiedDeal,
    OAuthToken,
    Preferences,
    SyncHistory,
    User,
)
from database.url import database_dialect_name, derive_async_database_url


ASYNC_DATABASE_URL = derive_async_database_url(settings.DATABASE_URL, os.getenv("ASYNC_DATABASE_URL"))
DATABASE_DIALECT = database_dialect_name(ASYNC_DATABASE_URL)

engine_kwargs = {"echo": False}
if DATABASE_DIALECT == "postgresql":
    engine_kwargs.update(
        {
            "pool_size": int(os.getenv("ASYNC_DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("ASYNC_DB_MAX_OVERFLOW", "10")),
            "pool_pre_ping": True,
        }
    )

engine = create_async_engine(ASYNC_DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
