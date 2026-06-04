"""PostgreSQL gamebot clean baseline schema.

Revision ID: pg_gamebot_baseline_20260506
Revises:
Create Date: 2026-05-06

This branch is intended for clean gamebot PostgreSQL targets only. Do not run it
against the stale shared media_bots public schema.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "pg_gamebot_baseline_20260506"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = ("postgres_gamebot_baseline",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("tiktok_id", sa.String(), nullable=True, unique=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=True, server_default="telegram"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "game_cache_v2",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(), nullable=False, unique=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("platforms", sa.Text(), nullable=True),
        sa.Column("original_price", sa.Integer(), nullable=True),
        sa.Column("current_price", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.DateTime(), nullable=True),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("store_link", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("trailer_url", sa.String(), nullable=True),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("game_type", sa.String(), nullable=False),
        sa.Column("platform_type", sa.String(), nullable=True, server_default="PC"),
        sa.Column("monetization_tags", sa.Text(), nullable=True),
        sa.Column("is_limited_time", sa.Boolean(), nullable=True),
        sa.Column("status", sa.String(), nullable=True, server_default="active"),
        sa.Column("critic_score", sa.Integer(), nullable=True),
        sa.Column("critic_tier", sa.String(), nullable=True),
        sa.Column("last_score_sync", sa.DateTime(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("hype_score", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("cost_per_deal", sa.Float(), nullable=True, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("vibe_tag", sa.Text(), nullable=True),
    )

    op.create_table(
        "preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("language", sa.String(), nullable=True, server_default="ar"),
        sa.Column("notify_daily_releases", sa.Boolean(), nullable=True),
        sa.Column("notify_free_games", sa.Boolean(), nullable=True),
        sa.Column("notify_leaving_games", sa.Boolean(), nullable=True),
        sa.Column("platform_pc", sa.Boolean(), nullable=True),
        sa.Column("platform_ps", sa.Boolean(), nullable=True),
        sa.Column("platform_xbox", sa.Boolean(), nullable=True),
        sa.Column("platform_switch", sa.Boolean(), nullable=True),
        sa.Column("platform_mobile", sa.Boolean(), nullable=True),
    )

    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bot_id", sa.String(), nullable=True, server_default="gamebot"),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_name", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )

    op.create_table(
        "api_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("query_params", sa.Text(), nullable=False),
        sa.Column("response_data", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
    )

    op.create_table(
        "api_limits_v2",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_name", sa.String(), nullable=False, unique=True),
        sa.Column("call_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("reset_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "maintenance_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("rows_affected", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("db_size_before", sa.Float(), nullable=True),
        sa.Column("db_size_after", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=True, server_default="Success"),
    )

    op.create_table(
        "notified_deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.String(), nullable=False, unique=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )

    op.create_table(
        "oauth_tokens_v2",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_name", sa.String(), nullable=False, unique=True),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sync_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("items_synced", sa.Integer(), nullable=True, server_default="0"),
    )

    op.create_table(
        "content_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("game_cache_v2.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("vibe_tag", sa.String(), nullable=True),
        sa.Column("tiktok_script", sa.Text(), nullable=True),
        sa.Column("telegram_caption", sa.Text(), nullable=True),
        sa.Column("trend_priority", sa.Integer(), nullable=True, server_default="5"),
        sa.Column("status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )

    op.create_index("idx_game_type", "game_cache_v2", ["game_type"])
    op.create_index("idx_release_date", "game_cache_v2", ["release_date"])
    op.create_index("idx_title", "game_cache_v2", ["title"])
    op.create_index("idx_ltf", "game_cache_v2", ["is_limited_time"])
    op.create_index("idx_status", "game_cache_v2", ["status"])
    op.create_index("idx_expiry", "game_cache_v2", ["expiry_date"])
    op.create_index("idx_platform_type", "game_cache_v2", ["platform_type"])
    op.create_index("idx_game_free_lookup", "game_cache_v2", ["game_type", "current_price", "status"])
    op.create_index("idx_game_upcoming_lookup", "game_cache_v2", ["game_type", "status", "release_date"])
    op.create_index("idx_activity_logs_timestamp", "activity_logs", ["timestamp"])
    op.create_index("idx_activity_logs_event_type", "activity_logs", ["event_type"])
    op.create_index("idx_activity_logs_platform", "activity_logs", ["platform"])
    op.create_index("idx_sync_history_timestamp", "sync_history", ["timestamp"])


def downgrade() -> None:
    op.drop_index("idx_sync_history_timestamp", table_name="sync_history")
    op.drop_index("idx_activity_logs_platform", table_name="activity_logs")
    op.drop_index("idx_activity_logs_event_type", table_name="activity_logs")
    op.drop_index("idx_activity_logs_timestamp", table_name="activity_logs")
    op.drop_index("idx_game_upcoming_lookup", table_name="game_cache_v2")
    op.drop_index("idx_game_free_lookup", table_name="game_cache_v2")
    op.drop_index("idx_platform_type", table_name="game_cache_v2")
    op.drop_index("idx_expiry", table_name="game_cache_v2")
    op.drop_index("idx_status", table_name="game_cache_v2")
    op.drop_index("idx_ltf", table_name="game_cache_v2")
    op.drop_index("idx_title", table_name="game_cache_v2")
    op.drop_index("idx_release_date", table_name="game_cache_v2")
    op.drop_index("idx_game_type", table_name="game_cache_v2")
    op.drop_table("content_queue")
    op.drop_table("sync_history")
    op.drop_table("oauth_tokens_v2")
    op.drop_table("notified_deals")
    op.drop_table("maintenance_logs")
    op.drop_table("api_limits_v2")
    op.drop_table("api_cache")
    op.drop_table("activity_logs")
    op.drop_table("preferences")
    op.drop_table("game_cache_v2")
    op.drop_table("users")
