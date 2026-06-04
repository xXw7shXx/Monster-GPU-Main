"""Canonical SQLAlchemy metadata for gamebot database readiness.

This module is intentionally limited to table/model declarations. It does not
import runtime settings, create engines, open sessions, or read environment
secrets.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = sa.Column(sa.Integer, primary_key=True)
    telegram_id = sa.Column(sa.BigInteger, unique=True, nullable=True)
    tiktok_id = sa.Column(sa.String, unique=True, nullable=True)
    username = sa.Column(sa.String, nullable=True)
    platform = sa.Column(sa.String, nullable=True, default="telegram", server_default="telegram")
    created_at = sa.Column(
        sa.DateTime,
        nullable=False,
        default=datetime.utcnow,
        server_default=sa.func.now(),
    )

    preferences = relationship(
        "Preferences",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    activity_logs = relationship("ActivityLog", back_populates="user")


class Preferences(Base):
    __tablename__ = "preferences"

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(
        sa.Integer,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    language = sa.Column(sa.String, nullable=True, default="ar", server_default="ar")
    notify_daily_releases = sa.Column(sa.Boolean, nullable=True, default=True)
    notify_free_games = sa.Column(sa.Boolean, nullable=True, default=True)
    notify_leaving_games = sa.Column(sa.Boolean, nullable=True, default=True)
    platform_pc = sa.Column(sa.Boolean, nullable=True, default=True)
    platform_ps = sa.Column(sa.Boolean, nullable=True, default=True)
    platform_xbox = sa.Column(sa.Boolean, nullable=True, default=True)
    platform_switch = sa.Column(sa.Boolean, nullable=True, default=True)
    platform_mobile = sa.Column(sa.Boolean, nullable=True, default=True)
    favorite_platforms = sa.Column(sa.Text, nullable=True)
    favorite_sources = sa.Column(sa.Text, nullable=True)
    favorite_genres = sa.Column(sa.Text, nullable=True)
    liked_game_ids = sa.Column(sa.Text, nullable=True)
    disliked_game_ids = sa.Column(sa.Text, nullable=True)
    watchlist_game_ids = sa.Column(sa.Text, nullable=True)
    intent_history = sa.Column(sa.Text, nullable=True)

    user = relationship("User", back_populates="preferences")


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        sa.Index("idx_activity_logs_timestamp", "timestamp"),
        sa.Index("idx_activity_logs_event_type", "event_type"),
        sa.Index("idx_activity_logs_platform", "platform"),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    bot_id = sa.Column(sa.String, nullable=True, default="gamebot", server_default="gamebot")
    platform = sa.Column(sa.String, nullable=False)
    event_type = sa.Column(sa.String, nullable=False)
    event_name = sa.Column(sa.String, nullable=True)
    timestamp = sa.Column(sa.DateTime, nullable=True, default=datetime.utcnow, server_default=sa.func.now())

    user = relationship("User", back_populates="activity_logs")


class APICache(Base):
    __tablename__ = "api_cache"

    id = sa.Column(sa.Integer, primary_key=True)
    endpoint = sa.Column(sa.String, nullable=False)
    query_params = sa.Column(sa.Text, nullable=False)
    response_data = sa.Column(sa.Text, nullable=False)
    timestamp = sa.Column(sa.BigInteger, nullable=False)


class GameCache(Base):
    __tablename__ = "game_cache_v2"
    __table_args__ = (
        sa.Index("idx_game_type", "game_type"),
        sa.Index("idx_release_date", "release_date"),
        sa.Index("idx_title", "title"),
        sa.Index("idx_ltf", "is_limited_time"),
        sa.Index("idx_status", "status"),
        sa.Index("idx_expiry", "expiry_date"),
        sa.Index("idx_platform_type", "platform_type"),
        sa.Index("idx_game_free_lookup", "game_type", "current_price", "status"),
        sa.Index("idx_game_upcoming_lookup", "game_type", "status", "release_date"),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    external_id = sa.Column(sa.String, unique=True, nullable=False)
    title = sa.Column(sa.String, nullable=False)
    platforms = sa.Column(sa.Text, nullable=True)
    original_price = sa.Column(sa.Integer, nullable=True, default=0)
    current_price = sa.Column(sa.Integer, nullable=True, default=0)
    release_date = sa.Column(sa.DateTime, nullable=True)
    expiry_date = sa.Column(sa.DateTime, nullable=True)
    store_link = sa.Column(sa.String, nullable=True)
    image_url = sa.Column(sa.String, nullable=True)
    thumbnail_url = sa.Column(sa.String, nullable=True)
    trailer_url = sa.Column(sa.String, nullable=True)
    source_name = sa.Column(sa.String, nullable=False)
    game_type = sa.Column(sa.String, nullable=False)
    platform_type = sa.Column(sa.String, nullable=True, default="PC", server_default="PC")
    monetization_tags = sa.Column(sa.Text, nullable=True)
    is_limited_time = sa.Column(sa.Boolean, nullable=True, default=False)
    status = sa.Column(sa.String, nullable=True, default="active", server_default="active")
    critic_score = sa.Column(sa.Integer, nullable=True)
    critic_tier = sa.Column(sa.String, nullable=True)
    last_score_sync = sa.Column(sa.DateTime, nullable=True)
    last_updated = sa.Column(
        sa.DateTime,
        nullable=True,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=sa.func.now(),
    )
    hype_score = sa.Column(sa.Integer, nullable=True, default=0, server_default="0")
    cost_per_deal = sa.Column(sa.Float, nullable=True, default=0.0, server_default="0")
    click_count = sa.Column(sa.Integer, nullable=True, default=0, server_default="0")
    vibe_tag = sa.Column(sa.Text, nullable=True)
    description = sa.Column(sa.Text, nullable=True)
    genres = sa.Column(sa.Text, nullable=True)
    tags = sa.Column(sa.Text, nullable=True)
    developers = sa.Column(sa.Text, nullable=True)
    screenshots = sa.Column(sa.JSON, nullable=True)
    enriched_at = sa.Column(sa.DateTime, nullable=True)
    enriched_source = sa.Column(sa.String(16), nullable=True)


class APILimit(Base):
    __tablename__ = "api_limits_v2"

    id = sa.Column(sa.Integer, primary_key=True)
    service_name = sa.Column(sa.String, unique=True, nullable=False)
    call_count = sa.Column(sa.Integer, nullable=True, default=0, server_default="0")
    reset_at = sa.Column(sa.DateTime, nullable=False)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens_v2"

    id = sa.Column(sa.Integer, primary_key=True)
    service_name = sa.Column(sa.String, unique=True, nullable=False)
    access_token = sa.Column(sa.String, nullable=False)
    expires_at = sa.Column(sa.DateTime, nullable=False)


class NotifiedDeal(Base):
    __tablename__ = "notified_deals"

    id = sa.Column(sa.Integer, primary_key=True)
    deal_id = sa.Column(sa.String, unique=True, nullable=False)
    platform = sa.Column(sa.String, nullable=False)
    timestamp = sa.Column(sa.DateTime, nullable=True, default=datetime.utcnow, server_default=sa.func.now())


class SyncHistory(Base):
    __tablename__ = "sync_history"
    __table_args__ = (
        sa.Index("idx_sync_history_timestamp", "timestamp"),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    source_name = sa.Column(sa.String, nullable=False)
    timestamp = sa.Column(sa.DateTime, nullable=True, default=datetime.utcnow, server_default=sa.func.now())
    status = sa.Column(sa.String, nullable=False)
    error_message = sa.Column(sa.Text, nullable=True)
    items_synced = sa.Column(sa.Integer, nullable=True, default=0, server_default="0")


class MaintenanceLog(Base):
    __tablename__ = "maintenance_logs"

    id = sa.Column(sa.Integer, primary_key=True)
    action_type = sa.Column(sa.String, nullable=False)
    timestamp = sa.Column(sa.DateTime, nullable=True, default=datetime.utcnow, server_default=sa.func.now())
    rows_affected = sa.Column(sa.Integer, nullable=True, default=0, server_default="0")
    db_size_before = sa.Column(sa.Float, nullable=True)
    db_size_after = sa.Column(sa.Float, nullable=True)
    status = sa.Column(sa.String, nullable=True, default="Success", server_default="Success")


class ContentQueue(Base):
    __tablename__ = "content_queue"

    id = sa.Column(sa.Integer, primary_key=True)
    game_id = sa.Column(sa.Integer, sa.ForeignKey("game_cache_v2.id", ondelete="SET NULL"), nullable=True)
    title = sa.Column(sa.String, nullable=False)
    vibe_tag = sa.Column(sa.String, nullable=True)
    tiktok_script = sa.Column(sa.Text, nullable=True)
    telegram_caption = sa.Column(sa.Text, nullable=True)
    trend_priority = sa.Column(sa.Integer, nullable=True, default=5, server_default="5")
    status = sa.Column(sa.String, nullable=True, default="pending", server_default="pending")
    created_at = sa.Column(sa.DateTime, nullable=True, default=datetime.utcnow, server_default=sa.func.now())

    game = relationship("GameCache")


class GameEmbedding(Base):
    __tablename__ = "game_embeddings"
    __table_args__ = (
        sa.Index("idx_game_embeddings_vector", "embedding", postgresql_using="ivfflat", postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    game_id = sa.Column(sa.Integer, sa.ForeignKey("game_cache_v2.id", ondelete="CASCADE"), nullable=False, unique=True)
    embedding = sa.Column(sa.dialects.postgresql.ARRAY(sa.Float), nullable=False)
    model_version = sa.Column(sa.String(32), nullable=False, default="all-MiniLM-L6-v2")
    text_hash = sa.Column(sa.String(64), nullable=False)
    generated_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow, server_default=sa.func.now())


class UserTasteProfile(Base):
    __tablename__ = "user_taste_profiles"

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    taste_embedding = sa.Column(sa.dialects.postgresql.ARRAY(sa.Float), nullable=True)
    liked_embedding = sa.Column(sa.dialects.postgresql.ARRAY(sa.Float), nullable=True)
    disliked_embedding = sa.Column(sa.dialects.postgresql.ARRAY(sa.Float), nullable=True)
    history_json = sa.Column(sa.JSON, nullable=False, default=lambda: [])
    updated_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=sa.func.now())


class RecommendationHistory(Base):
    __tablename__ = "recommendation_history"
    __table_args__ = (
        sa.Index("idx_rec_hist_user_time", "user_id", "recommended_at"),
        sa.Index("idx_rec_hist_user_game", "user_id", "game_id"),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    game_id = sa.Column(sa.Integer, sa.ForeignKey("game_cache_v2.id", ondelete="CASCADE"), nullable=False)
    reason = sa.Column(sa.Text, nullable=True)
    channel = sa.Column(sa.String(16), nullable=False, default="telegram")
    source = sa.Column(sa.String(16), nullable=False, default="fast")
    recommended_at = sa.Column(sa.DateTime, nullable=False, default=datetime.utcnow, server_default=sa.func.now())
