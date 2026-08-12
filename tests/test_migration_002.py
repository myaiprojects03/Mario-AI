import unittest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from alembic.config import Config
from alembic import command

from core.config.settings import settings
from core.db import Base, Match, OddsSnapshot, get_engine


class TestMigration002(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.alembic_cfg = Config("alembic.ini")
        if settings.DATABASE_URL:
            cls.alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    def test_migration_upgrade_and_downgrade_cycle(self):
        """Test upgrading to 002, downgrading to 001, and upgrading back to head."""
        # 1. Upgrade head (002)
        command.upgrade(self.alembic_cfg, "head")

        # 2. Downgrade back to 001_initial_schema
        command.downgrade(self.alembic_cfg, "001_initial_schema")

        # 3. Upgrade back to head
        command.upgrade(self.alembic_cfg, "head")

    def test_insert_multiple_odds_snapshots(self):
        """Test inserting multiple odds_snapshots rows for the same match at different polled_at timestamps."""
        engine = get_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(bind=engine)

        match_id = "test_multi_snapshot_001"
        match = Match(
            match_id=match_id,
            sport="fifa",
            league="FIFA GG League",
            home_team="Arsenal",
            away_team="Chelsea",
            match_start_time=datetime.now(timezone.utc),
            source="jarbet_live",
            game_version="FIFA 26",
        )
        session.add(match)
        session.commit()

        # Insert 3 snapshot polls at different timestamps for the same match & market
        now = datetime.now(timezone.utc)
        snapshots = [
            OddsSnapshot(
                match_id=match_id,
                market_type="fifa_goals_ou",
                line_value=2.5,
                side="over",
                odds_value=1.80,
                polled_at=now - timedelta(minutes=10),
                source="jarbet_live",
            ),
            OddsSnapshot(
                match_id=match_id,
                market_type="fifa_goals_ou",
                line_value=2.5,
                side="over",
                odds_value=1.85,
                polled_at=now - timedelta(minutes=5),
                source="jarbet_live",
            ),
            OddsSnapshot(
                match_id=match_id,
                market_type="fifa_goals_ou",
                line_value=2.5,
                side="over",
                odds_value=1.92,
                polled_at=now,
                source="jarbet_live",
            ),
        ]
        session.add_all(snapshots)
        session.commit()

        retrieved_snapshots = (
            session.query(OddsSnapshot)
            .filter_by(match_id=match_id, market_type="fifa_goals_ou")
            .order_by(OddsSnapshot.polled_at.asc())
            .all()
        )
        self.assertEqual(len(retrieved_snapshots), 3)
        self.assertEqual(float(retrieved_snapshots[0].odds_value), 1.80)
        self.assertEqual(float(retrieved_snapshots[1].odds_value), 1.85)
        self.assertEqual(float(retrieved_snapshots[2].odds_value), 1.92)

        session.close()


if __name__ == "__main__":
    unittest.main()
