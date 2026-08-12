"""Add odds_snapshots table and game_version column to matches.

Revision ID: 002_add_odds_snapshots_and_game_version
Revises: 001_initial_schema
Create Date: 2026-08-11 16:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_odds_snapshots_game_ver"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add game_version column to core.matches
    op.add_column(
        "matches",
        sa.Column("game_version", sa.String(length=50), nullable=True),
        schema="core",
    )

    # 2. Create core.odds_snapshots table
    op.create_table(
        "odds_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.String(length=255), nullable=False),
        sa.Column("market_type", sa.String(length=50), nullable=False),
        sa.Column("line_value", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.Column("odds_value", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.matches.match_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )

    # 3. Create composite index on (match_id, market_type, polled_at)
    op.create_index(
        "idx_odds_snapshots_match_market_polled",
        "odds_snapshots",
        ["match_id", "market_type", "polled_at"],
        unique=False,
        schema="core",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_odds_snapshots_match_market_polled",
        table_name="odds_snapshots",
        schema="core",
    )
    op.drop_table("odds_snapshots", schema="core")
    op.drop_column("matches", "game_version", schema="core")
