"""gamebot ai profile fields

Revision ID: 20260507_gamebot_ai_profile
Revises: pg_gamebot_baseline_20260506
Create Date: 2026-05-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_gamebot_ai_profile"
down_revision: Union[str, Sequence[str], None] = "pg_gamebot_baseline_20260506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("favorite_platforms", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("favorite_sources", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("favorite_genres", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("liked_game_ids", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("disliked_game_ids", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("watchlist_game_ids", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("intent_history", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("preferences", schema=None) as batch_op:
        batch_op.drop_column("intent_history")
        batch_op.drop_column("watchlist_game_ids")
        batch_op.drop_column("disliked_game_ids")
        batch_op.drop_column("liked_game_ids")
        batch_op.drop_column("favorite_genres")
        batch_op.drop_column("favorite_sources")
        batch_op.drop_column("favorite_platforms")
