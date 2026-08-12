"""Initial database schema creation across core and market namespaces.

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-08-11 15:35:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMAS = [
    "core",
    "fifa_goals_ou",
    "fifa_asian_handicap",
    "fifa_money_line",
    "ebasket_ou",
    "ebasket_money_line",
]


def upgrade() -> None:
    # 1. Create schemas
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # 2. Create core.matches table
    op.create_table(
        "matches",
        sa.Column("match_id", sa.String(length=255), nullable=False),
        sa.Column("sport", sa.String(length=50), nullable=False),
        sa.Column("league", sa.String(length=100), nullable=False),
        sa.Column("home_player", sa.String(length=100), nullable=True),
        sa.Column("away_player", sa.String(length=100), nullable=True),
        sa.Column("home_team", sa.String(length=100), nullable=False),
        sa.Column("away_team", sa.String(length=100), nullable=False),
        sa.Column("match_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("match_id"),
        schema="core",
    )
    op.create_index(
        "ix_core_matches_league", "matches", ["league"], unique=False, schema="core"
    )
    op.create_index(
        "ix_core_matches_match_start_time",
        "matches",
        ["match_start_time"],
        unique=False,
        schema="core",
    )

    # 3. Create core.odds table
    op.create_table(
        "odds",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.String(length=255), nullable=False),
        sa.Column("market_type", sa.String(length=50), nullable=False),
        sa.Column("line_value", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("odds_open", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("odds_close", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("odds_snapshot_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.matches.match_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        "idx_odds_match_market",
        "odds",
        ["match_id", "market_type"],
        unique=False,
        schema="core",
    )

    # 4. Create core.results table
    op.create_table(
        "results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.String(length=255), nullable=False),
        sa.Column("final_home_score", sa.Integer(), nullable=False),
        sa.Column("final_away_score", sa.Integer(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settlement_source", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"], ["core.matches.match_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )

    # 5. Create market-specific tables in each market schema
    market_schemas = [s for s in SCHEMAS if s != "core"]
    for m_schema in market_schemas:
        # features
        op.create_table(
            "features",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("match_id", sa.String(length=255), nullable=False),
            sa.Column(
                "feature_vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False
            ),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["match_id"], ["core.matches.match_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            schema=m_schema,
        )

        # model_scores
        op.create_table(
            "model_scores",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("match_id", sa.String(length=255), nullable=False),
            sa.Column("model_version", sa.String(length=100), nullable=False),
            sa.Column(
                "probability_estimate", sa.Numeric(precision=5, scale=4), nullable=False
            ),
            sa.Column(
                "confidence_score", sa.Numeric(precision=5, scale=4), nullable=True
            ),
            sa.Column(
                "recommended_line", sa.Numeric(precision=10, scale=2), nullable=True
            ),
            sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["match_id"], ["core.matches.match_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            schema=m_schema,
        )

        # tip_log
        op.create_table(
            "tip_log",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("match_id", sa.String(length=255), nullable=False),
            sa.Column("tip_generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "odds_at_tip_time", sa.Numeric(precision=10, scale=3), nullable=False
            ),
            sa.Column(
                "min_acceptable_odds", sa.Numeric(precision=10, scale=3), nullable=True
            ),
            sa.Column("published", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("outcome", sa.String(length=20), nullable=False),
            sa.Column("units_result", sa.Numeric(precision=10, scale=2), nullable=True),
            sa.ForeignKeyConstraint(
                ["match_id"], ["core.matches.match_id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            schema=m_schema,
        )


def downgrade() -> None:
    market_schemas = [s for s in SCHEMAS if s != "core"]
    for m_schema in reversed(market_schemas):
        op.drop_table("tip_log", schema=m_schema)
        op.drop_table("model_scores", schema=m_schema)
        op.drop_table("features", schema=m_schema)

    op.drop_table("results", schema="core")
    op.drop_index("idx_odds_match_market", table_name="odds", schema="core")
    op.drop_table("odds", schema="core")
    op.drop_index("ix_core_matches_match_start_time", table_name="matches", schema="core")
    op.drop_index("ix_core_matches_league", table_name="matches", schema="core")
    op.drop_table("matches", schema="core")

    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
