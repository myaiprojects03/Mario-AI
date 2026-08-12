import unittest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from core.db import (
    Base,
    Match,
    Odds,
    Result,
    MARKET_SCHEMAS,
    MARKET_MODELS,
    FifaGoalsOUFeature,
    FifaGoalsOUModelScore,
    FifaGoalsOUTipLog,
    EbasketOUFeature,
    get_engine,
)


class TestDatabaseModels(unittest.TestCase):
    def test_core_table_schemas(self):
        self.assertEqual(Match.__table__.schema, "core")
        self.assertEqual(Odds.__table__.schema, "core")
        self.assertEqual(Result.__table__.schema, "core")
        self.assertEqual(Match.__tablename__, "matches")
        self.assertEqual(Odds.__tablename__, "odds")
        self.assertEqual(Result.__tablename__, "results")

    def test_market_schemas_presence(self):
        expected_schemas = {
            "fifa_goals_ou",
            "fifa_asian_handicap",
            "fifa_money_line",
            "ebasket_ou",
            "ebasket_money_line",
        }
        self.assertEqual(set(MARKET_SCHEMAS), expected_schemas)

    def test_market_table_schemas(self):
        for schema in MARKET_SCHEMAS:
            feature_cls = MARKET_MODELS[schema]["Feature"]
            model_score_cls = MARKET_MODELS[schema]["ModelScore"]
            tip_log_cls = MARKET_MODELS[schema]["TipLog"]

            self.assertEqual(feature_cls.__table__.schema, schema)
            self.assertEqual(model_score_cls.__table__.schema, schema)
            self.assertEqual(tip_log_cls.__table__.schema, schema)

            self.assertEqual(feature_cls.__tablename__, "features")
            self.assertEqual(model_score_cls.__tablename__, "model_scores")
            self.assertEqual(tip_log_cls.__tablename__, "tip_log")

    def test_explicit_alias_imports(self):
        self.assertEqual(FifaGoalsOUFeature.__table__.schema, "fifa_goals_ou")
        self.assertEqual(FifaGoalsOUModelScore.__table__.schema, "fifa_goals_ou")
        self.assertEqual(FifaGoalsOUTipLog.__table__.schema, "fifa_goals_ou")
        self.assertEqual(EbasketOUFeature.__table__.schema, "ebasket_ou")

    def test_odds_composite_index(self):
        indexes = {idx.name: [col.name for col in idx.columns] for idx in Odds.__table__.indexes}
        self.assertIn("idx_odds_match_market", indexes)
        self.assertEqual(indexes["idx_odds_match_market"], ["match_id", "market_type"])

    def test_sqlite_in_memory_session(self):
        engine = get_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(bind=engine)

        match = Match(
            match_id="test_001",
            sport="fifa",
            league="FIFA GG League",
            home_player="PLAYER_A",
            away_player="PLAYER_B",
            home_team="Real Madrid",
            away_team="Barcelona",
            match_start_time=datetime.now(timezone.utc),
            source="csv_backfill",
            raw_payload={"test": True},
        )
        session.add(match)
        session.commit()

        retrieved = session.query(Match).filter_by(match_id="test_001").first()
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.home_team, "Real Madrid")
        session.close()


if __name__ == "__main__":
    unittest.main()
