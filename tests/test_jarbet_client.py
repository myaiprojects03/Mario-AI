import unittest
import responses
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.db import Base, get_engine, Match, Odds
from core.ingestion.jarbet_client import (
    JarBetClient,
    detect_odds_snapshot_behavior,
    analyze_half_time_odds_presence,
)


class TestJarBetClient(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database for testing upserts
        self.engine = get_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db_session = Session(bind=self.engine)
        
        self.base_url = "https://api.jarbet.example.com"
        self.client = JarBetClient(base_url=self.base_url, api_key="test_api_key")
        self.client.min_interval = 0.001  # Speed up tests

    def tearDown(self):
        self.db_session.close()

    @responses.activate
    def test_successful_fetch_and_parse(self):
        sample_payload = {
            "matches": [
                {
                    "match_id": "m_101",
                    "league": "FIFA GG League",
                    "home_team": "Real Madrid",
                    "away_team": "Barcelona",
                    "home_player": "PLAYER_A",
                    "away_player": "PLAYER_B",
                    "match_start_time": "2026-08-11T12:00:00Z",
                    "odds": [
                        {
                            "market_type": "fifa_goals_ou",
                            "line_value": 2.5,
                            "odds_open": 1.85,
                            "odds_close": 1.90,
                            "side": "over",
                        }
                    ],
                }
            ]
        }

        responses.add(
            responses.GET,
            f"{self.base_url}/matches/pre",
            json=sample_payload,
            status=200,
            headers={"X-RateLimit-Remaining": "10", "X-RateLimit-Limit": "100"},
        )

        matches_raw = self.client.get_fifa_pre()
        self.assertEqual(len(matches_raw), 1)

        upserted = self.client.upsert_match_data(matches_raw, sport="fifa", db_session=self.db_session)
        self.assertEqual(len(upserted), 1)

        db_match = self.db_session.query(Match).filter_by(match_id="m_101").first()
        self.assertIsNotNone(db_match)
        self.assertEqual(db_match.home_team, "Real Madrid")

        db_odds = self.db_session.query(Odds).filter_by(match_id="m_101").all()
        self.assertEqual(len(db_odds), 1)
        self.assertEqual(float(db_odds[0].line_value), 2.5)

    @responses.activate
    def test_rate_limit_429_backoff(self):
        responses.add(
            responses.GET,
            f"{self.base_url}/matches/pre",
            status=429,
            headers={"Retry-After": "0.01", "X-RateLimit-Remaining": "0"},
        )
        responses.add(
            responses.GET,
            f"{self.base_url}/matches/pre",
            json=[{"id": "m_102", "home_team": "Bayern", "away_team": "Dortmund"}],
            status=200,
            headers={"X-RateLimit-Remaining": "10"},
        )

        matches_raw = self.client.get_fifa_pre()
        self.assertEqual(len(matches_raw), 1)
        self.assertEqual(matches_raw[0]["id"], "m_102")

    def test_malformed_payload_handling(self):
        records = [
            {
                "match_id": "valid_001",
                "league": "FIFA League",
                "home_team": "Team A",
                "away_team": "Team B",
            },
            "invalid_non_dict_string_item",
            {
                "match_id": "valid_002",
                "league": "FIFA League",
                "home_team": "Team C",
                "away_team": "Team D",
            },
        ]

        upserted = self.client.upsert_match_data(records, sport="fifa", db_session=self.db_session)
        self.assertEqual(len(upserted), 2)
        match_ids = [m.match_id for m in upserted]
        self.assertIn("valid_001", match_ids)
        self.assertIn("valid_002", match_ids)

    @responses.activate
    def test_5xx_retry_behavior(self):
        responses.add(
            responses.GET,
            f"{self.base_url}/matches/ebasket/pre",
            status=500,
        )
        responses.add(
            responses.GET,
            f"{self.base_url}/matches/ebasket/pre",
            json=[{"id": "eb_101", "home_team": "Lakers", "away_team": "Celtics"}],
            status=200,
        )

        matches_raw = self.client.get_ebasket_pre()
        self.assertEqual(len(matches_raw), 1)
        self.assertEqual(matches_raw[0]["id"], "eb_101")

    def test_empirical_detection_functions(self):
        rec1 = {"match_id": "m_test", "odds": {"odds_open": 1.80, "odds_close": 1.85}}
        rec2 = {"match_id": "m_test", "odds": {"odds_open": 1.80, "odds_close": 1.95}}
        
        snapshot_res = detect_odds_snapshot_behavior(rec1, rec2)
        self.assertTrue(snapshot_res["is_dynamic"])
        self.assertEqual(snapshot_res["behavior_type"], "Dynamic Updates Across Polls")

        fifa_recs = [
            {"league": "League A", "over_under_ht": 1.5},
            {"league": "League A", "over_under_ht": 1.5},
            {"league": "League B"},  # missing HT odds
        ]

        ht_res = analyze_half_time_odds_presence(fifa_recs)
        self.assertIn("League A", ht_res)
        self.assertEqual(ht_res["League A"]["rate"], 100.0)
        self.assertEqual(ht_res["League B"]["rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
