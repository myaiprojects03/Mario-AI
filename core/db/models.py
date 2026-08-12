from typing import Dict, Any
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# JSONType uses JSONB on PostgreSQL and JSON fallback on other engines (e.g. SQLite tests)
JSONType = JSON().with_variant(JSONB, "postgresql")

MARKET_SCHEMAS = [
    "fifa_goals_ou",
    "fifa_asian_handicap",
    "fifa_money_line",
    "ebasket_ou",
    "ebasket_money_line",
]

# -------------------------------------------------------------------
# Shared Core Schema Models (schema="core")
# -------------------------------------------------------------------


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = {"schema": "core"}

    match_id = Column(String(255), primary_key=True)
    sport = Column(String(50), nullable=False)  # fifa / ebasket
    league = Column(String(100), nullable=False, index=True)
    home_player = Column(String(100), nullable=True)
    away_player = Column(String(100), nullable=True)
    home_team = Column(String(100), nullable=False)
    away_team = Column(String(100), nullable=False)
    match_start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(Integer, nullable=True)
    source = Column(String(50), nullable=False)  # csv_backfill / jarbet_live
    raw_payload = Column(JSONType, nullable=True)

    # NOTE: Backfilling game_version for existing historical FIFA/eBasket rows
    # (by inferring the version from match date vs known version-release dates)
    # is a follow-up task, not done in this migration.
    game_version = Column(String(50), nullable=True)

    odds_list = relationship("Odds", back_populates="match", cascade="all, delete-orphan")
    odds_snapshots = relationship("OddsSnapshot", back_populates="match", cascade="all, delete-orphan")
    results = relationship("Result", back_populates="match", cascade="all, delete-orphan")


# NOTE: core.odds (open/close summary) stays as-is and is understood to be
# a derived convenience view of the first and last rows in core.odds_snapshots
# per match/market/side.
class Odds(Base):
    __tablename__ = "odds"
    __table_args__ = (
        Index("idx_odds_match_market", "match_id", "market_type"),
        {"schema": "core"},
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    match_id = Column(String(255), ForeignKey("core.matches.match_id", ondelete="CASCADE"), nullable=False)
    market_type = Column(String(50), nullable=False)
    line_value = Column(Numeric(10, 2), nullable=True)  # O/U & AH lines
    odds_open = Column(Numeric(10, 3), nullable=True)
    odds_close = Column(Numeric(10, 3), nullable=True)
    odds_snapshot_time = Column(DateTime(timezone=True), nullable=False)
    side = Column(String(20), nullable=False)  # home / away / over / under

    match = relationship("Match", back_populates="odds_list")


class OddsSnapshot(Base):
    """Granular odds polling sequence table for microstructural/trajectory features."""
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        Index("idx_odds_snapshots_match_market_polled", "match_id", "market_type", "polled_at"),
        {"schema": "core"},
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    match_id = Column(String(255), ForeignKey("core.matches.match_id", ondelete="CASCADE"), nullable=False)
    market_type = Column(String(50), nullable=False)
    line_value = Column(Numeric(10, 2), nullable=True)
    side = Column(String(20), nullable=False)  # home / away / over / under
    odds_value = Column(Numeric(10, 3), nullable=False)
    polled_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(String(50), nullable=False)  # jarbet_live / betsapi / csv_backfill

    match = relationship("Match", back_populates="odds_snapshots")


class Result(Base):
    __tablename__ = "results"
    __table_args__ = {"schema": "core"}

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    match_id = Column(String(255), ForeignKey("core.matches.match_id", ondelete="CASCADE"), nullable=False)
    final_home_score = Column(Integer, nullable=False)
    final_away_score = Column(Integer, nullable=False)
    settled_at = Column(DateTime(timezone=True), nullable=False)
    settlement_source = Column(String(50), nullable=False)  # betsapi / manual

    match = relationship("Match", back_populates="results")


# -------------------------------------------------------------------
# Per-Market Schema Models Factory
# -------------------------------------------------------------------


def create_market_models_for_schema(schema_name: str) -> Dict[str, Any]:
    """Dynamically generate model classes for a specific market schema."""
    prefix = schema_name.title().replace("_", "")

    feature_class = type(
        f"{prefix}Feature",
        (Base,),
        {
            "__tablename__": "features",
            "__table_args__": {"schema": schema_name},
            "id": Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
            "match_id": Column(String(255), ForeignKey("core.matches.match_id", ondelete="CASCADE"), nullable=False),
            "feature_vector": Column(JSONType, nullable=False),
            "computed_at": Column(DateTime(timezone=True), nullable=False),
        },
    )

    model_score_class = type(
        f"{prefix}ModelScore",
        (Base,),
        {
            "__tablename__": "model_scores",
            "__table_args__": {"schema": schema_name},
            "id": Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
            "match_id": Column(String(255), ForeignKey("core.matches.match_id", ondelete="CASCADE"), nullable=False),
            "model_version": Column(String(100), nullable=False),
            "probability_estimate": Column(Numeric(5, 4), nullable=False),
            "confidence_score": Column(Numeric(5, 4), nullable=True),
            "recommended_line": Column(Numeric(10, 2), nullable=True),
            "scored_at": Column(DateTime(timezone=True), nullable=False),
        },
    )

    tip_log_class = type(
        f"{prefix}TipLog",
        (Base,),
        {
            "__tablename__": "tip_log",
            "__table_args__": {"schema": schema_name},
            "id": Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
            "match_id": Column(String(255), ForeignKey("core.matches.match_id", ondelete="CASCADE"), nullable=False),
            "tip_generated_at": Column(DateTime(timezone=True), nullable=False),
            "odds_at_tip_time": Column(Numeric(10, 3), nullable=False),
            "min_acceptable_odds": Column(Numeric(10, 3), nullable=True),
            "published": Column(Boolean, default=False, nullable=False),
            "outcome": Column(String(20), nullable=False),  # win / loss / void / pending
            "units_result": Column(Numeric(10, 2), nullable=True),
        },
    )

    return {
        "Feature": feature_class,
        "ModelScore": model_score_class,
        "TipLog": tip_log_class,
    }


# Global registry of models per schema
MARKET_MODELS: Dict[str, Dict[str, Any]] = {
    schema: create_market_models_for_schema(schema) for schema in MARKET_SCHEMAS
}

# Explicit class aliases for easy direct imports:
FifaGoalsOUFeature = MARKET_MODELS["fifa_goals_ou"]["Feature"]
FifaGoalsOUModelScore = MARKET_MODELS["fifa_goals_ou"]["ModelScore"]
FifaGoalsOUTipLog = MARKET_MODELS["fifa_goals_ou"]["TipLog"]

FifaAsianHandicapFeature = MARKET_MODELS["fifa_asian_handicap"]["Feature"]
FifaAsianHandicapModelScore = MARKET_MODELS["fifa_asian_handicap"]["ModelScore"]
FifaAsianHandicapTipLog = MARKET_MODELS["fifa_asian_handicap"]["TipLog"]

FifaMoneyLineFeature = MARKET_MODELS["fifa_money_line"]["Feature"]
FifaMoneyLineModelScore = MARKET_MODELS["fifa_money_line"]["ModelScore"]
FifaMoneyLineTipLog = MARKET_MODELS["fifa_money_line"]["TipLog"]

EbasketOUFeature = MARKET_MODELS["ebasket_ou"]["Feature"]
EbasketOUModelScore = MARKET_MODELS["ebasket_ou"]["ModelScore"]
EbasketOUTipLog = MARKET_MODELS["ebasket_ou"]["TipLog"]

EbasketMoneyLineFeature = MARKET_MODELS["ebasket_money_line"]["Feature"]
EbasketMoneyLineModelScore = MARKET_MODELS["ebasket_money_line"]["ModelScore"]
EbasketMoneyLineTipLog = MARKET_MODELS["ebasket_money_line"]["TipLog"]
