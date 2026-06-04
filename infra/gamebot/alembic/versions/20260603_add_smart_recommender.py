"""Add smart recommender tables and enrichment columns.

Revision ID: 20260603_add_smart_recommender
Revises: pg_gamebot_baseline_20260506
Create Date: 2026-06-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '20260603_add_smart_recommender'
down_revision: Union[str, None] = '20260507_gamebot_ai_profile'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column('game_cache_v2', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('game_cache_v2', sa.Column('genres', sa.Text(), nullable=True))
    op.add_column('game_cache_v2', sa.Column('tags', sa.Text(), nullable=True))
    op.add_column('game_cache_v2', sa.Column('developers', sa.Text(), nullable=True))
    op.add_column('game_cache_v2', sa.Column('screenshots', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('game_cache_v2', sa.Column('enriched_at', sa.DateTime(), nullable=True))
    op.add_column('game_cache_v2', sa.Column('enriched_source', sa.String(length=16), nullable=True))

    op.execute("""
        CREATE TABLE game_embeddings (
            id SERIAL PRIMARY KEY,
            game_id INTEGER NOT NULL REFERENCES game_cache_v2(id) ON DELETE CASCADE,
            embedding vector(384) NOT NULL,
            model_version VARCHAR(32) NOT NULL DEFAULT 'all-MiniLM-L6-v2',
            text_hash VARCHAR(64) NOT NULL,
            generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(game_id, model_version)
        )
    """)
    op.execute("CREATE INDEX idx_game_embeddings_vector ON game_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")

    op.execute("""
        CREATE TABLE user_taste_profiles (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            taste_embedding vector(384),
            liked_embedding vector(384),
            disliked_embedding vector(384),
            history_json JSONB NOT NULL DEFAULT '[]',
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            UNIQUE(user_id)
        )
    """)

    op.execute("""
        CREATE TABLE recommendation_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_id INTEGER NOT NULL REFERENCES game_cache_v2(id) ON DELETE CASCADE,
            reason TEXT,
            channel VARCHAR(16) NOT NULL DEFAULT 'telegram',
            source VARCHAR(16) NOT NULL DEFAULT 'fast',
            recommended_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_rec_hist_user_time ON recommendation_history(user_id, recommended_at DESC)")
    op.execute("CREATE INDEX idx_rec_hist_user_game ON recommendation_history(user_id, game_id)")


def downgrade() -> None:
    op.drop_index('idx_rec_hist_user_game', table_name='recommendation_history')
    op.drop_index('idx_rec_hist_user_time', table_name='recommendation_history')
    op.execute("DROP TABLE IF EXISTS recommendation_history")
    op.execute("DROP TABLE IF EXISTS user_taste_profiles")
    op.execute("DROP TABLE IF EXISTS game_embeddings")
    op.drop_column('game_cache_v2', 'enriched_source')
    op.drop_column('game_cache_v2', 'enriched_at')
    op.drop_column('game_cache_v2', 'screenshots')
    op.drop_column('game_cache_v2', 'developers')
    op.drop_column('game_cache_v2', 'tags')
    op.drop_column('game_cache_v2', 'genres')
    op.drop_column('game_cache_v2', 'description')
