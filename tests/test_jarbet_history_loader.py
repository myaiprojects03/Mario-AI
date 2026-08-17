import unittest
import responses
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.db import Base, get_engine, Match, Odds, Result
from core.ingestion.jarbet_client import JarBetClient
from core.ingestion.jarbet_history_loader import JarBetHistoryLoader


class TestJarBetHistoryLoader(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database for testing upserts and overlap
        self.engine = get_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db_session = Session(bind=self.engine)

        self.base_url = "https://data.jarvisbet.com.br"
        self.client = JarBetClient(base_url=self.base_url, api_key="test_api_key")
        self.client.min_interval = 0.001
        self.loader = JarBetHistoryLoader(client=self.client)

    def tearDown(self):
        self.db_session.close()

    def test_filter_confirmed_results(self):
        records = [
            # Valid record
            {
                "_id": "rec_001",
                "league": "Esoccer Battle",
                "home": {"name": "PlayerA", "teamName": "TeamA", "goals": 2},
                "away": {"name": "PlayerB", "teamName": "TeamB", "goals": 1},
            },
            # Missing goals (incomplete record)
            {
                "_id": "rec_002",
                "league": "Esoccer Battle",
                "home": {"name": "PlayerA", "teamName": "TeamA"},
                "away": {"name": "PlayerB", "teamName": "TeamB"},
            },
            # Non-integer score
            {
                "_id": "rec_003",
                "league": "Esoccer Battle",
                "home": {"name": "PlayerA", "teamName": "TeamA", "goals": "invalid"},
                "away": {"name": "PlayerB", "teamName": "TeamB", "goals": 1},
            },
        ]

        valid, skipped = self.loader.filter_confirmed_results(records)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(skipped), 2)
        self.assertEqual(valid[0]["_id"], "rec_001")

    @responses.activate
    def test_ingestion_and_source_tagging(self):
        sample_payload = [
            {
                "_id": "hist_101",
                "idMatchBet365": "999101",
                "league": "Esoccer Battle - 8 mins play",
                "home": {"name": "Bomb1to", "teamName": "Real Madrid", "goals": 4},
                "away": {"name": "KraftVK", "teamName": "Barcelona", "goals": 2},
                "startedAt": "2026-07-01T12:00:00Z",
                "odds": {
                    "over_under": {"over": 1.85, "under": 1.85, "line": 5.5},
                    "money_line": {"home": 2.10, "away": 2.80, "draw": 3.40},
                },
            }
        ]

        responses.add(
            responses.GET,
            f"{self.base_url}/history/pre",
            json=sample_payload,
            status=200,
        )

        # Execute loader ingestion for Bomb1to
        report = self.loader.ingest_sport_history("fifa", db_session=self.db_session)
        self.assertGreaterEqual(report["total_ingested"], 1)

        db_match = self.db_session.query(Match).filter_by(match_id="hist_101").first()
        self.assertIsNotNone(db_match)
        self.assertEqual(db_match.source, "jarbet_history")
        self.assertEqual(db_match.home_player, "Bomb1to")

        db_res = self.db_session.query(Result).filter_by(match_id="hist_101").first()
        self.assertIsNotNone(db_res)
        self.assertEqual(db_res.final_home_score, 4)
        self.assertEqual(db_res.final_away_score, 2)
        self.assertEqual(db_res.settlement_source, "jarbet_history")

    def test_overlap_metrics_calculation(self):
        # Insert an existing csv_backfill match via upsert
        rec_csv = {
            "match_id": "csv_001",
            "league": "Esoccer Battle",
            "home": {"name": "PlayerA", "teamName": "Bayern"},
            "away": {"name": "PlayerB", "teamName": "Dortmund"},
            "match_start_time": "2026-06-01T10:00:00Z",
        }
        self.loader.client.upsert_match_data([rec_csv], sport="fifa", db_session=self.db_session, default_source="csv_backfill")

        # Insert a overlapping jarbet_history match (matching csv_001 by ID)
        rec_hist1 = {
            "match_id": "csv_001",
            "league": "Esoccer Battle",
            "home": {"name": "PlayerA", "teamName": "Bayern"},
            "away": {"name": "PlayerB", "teamName": "Dortmund"},
            "match_start_time": "2026-06-01T10:00:00Z",
        }
        # Insert a new jarbet_history match
        rec_hist2 = {
            "match_id": "hist_new_002",
            "league": "Esoccer Battle",
            "home": {"name": "PlayerC", "teamName": "Chelsea"},
            "away": {"name": "PlayerD", "teamName": "Arsenal"},
            "match_start_time": "2026-06-01T10:00:00Z",
        }
        self.loader.client.upsert_match_data([rec_hist1, rec_hist2], sport="fifa", db_session=self.db_session, default_source="jarbet_history")

        metrics = self.loader.compute_overlap_metrics(
            db_session=self.db_session,
            sport="fifa",
            raw_pulled_count=2,
            valid_count=2,
            skipped_count=0,
            ingested_ids={"csv_001", "hist_new_002"},
        )

        self.assertEqual(metrics["total_ingested"], 2)


if __name__ == "__main__":
    unittest.main()
