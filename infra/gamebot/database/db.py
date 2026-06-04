"""Sync SQLAlchemy engine/session setup for gamebot.

Supports current SQLite rollback mode and future PostgreSQL cutover mode without
printing credential-bearing database URLs.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.models import Base
from database.url import database_dialect_name, derive_sync_database_url


load_dotenv()

RAW_DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///bot_data.db"
DATABASE_URL = derive_sync_database_url(RAW_DATABASE_URL, os.getenv("SYNC_DATABASE_URL"))
DATABASE_DIALECT = database_dialect_name(DATABASE_URL)

engine_kwargs = {"echo": False, "future": True}
if DATABASE_DIALECT == "sqlite":
    if "?" not in DATABASE_URL:
        DATABASE_URL = f"{DATABASE_URL}?cache=shared"
    elif "cache=" not in DATABASE_URL:
        DATABASE_URL = f"{DATABASE_URL}&cache=shared"
    engine_kwargs["connect_args"] = {"check_same_thread": False, "uri": True}
elif DATABASE_DIALECT == "postgresql":
    engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),
        }
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_DIALECT != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
