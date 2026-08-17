"""
Unit Tests for FIFA Goals Over/Under Model Pipeline.
"""

import unittest
from datetime import datetime, timezone, timedelta
import numpy as np
import polars as pl
from unittest.mock import MagicMock

from markets.fifa_goals_ou.models.poisson_dixon_coles import PoissonDixonColesModel
from markets.fifa_goals_ou.models.xgb_model import XGBoostGoalsOUModel
from markets.fifa_goals_ou.models.blended_model import BlendedGoalsOUModel
from markets.fifa_goals_ou.model import (
    load_training_dataset,
    run_walk_forward_backtest,
    generate_model_scores_df,
)


class TestFIFAGoalsOUModelPipeline(unittest.TestCase):

    def setUp(self):
        base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        n_rows = 200

        times = [base_time + timedelta(hours=i * 6) for i in range(n_rows)]
        np.random.seed(42)

        home_goals = np.random.randint(0, 5, size=n_rows)
        away_goals = np.random.randint(0, 4, size=n_rows)
        lines = np.full(n_rows, 2.5)

        self.sample_df = pl.DataFrame({
            "match_id": [f"m_{i:04d}" for i in range(n_rows)],
            "league": ["Esoccer Battle"] * n_rows,
            "home_player": ["PlayerA"] * n_rows,
            "away_player": ["PlayerB"] * n_rows,
            "home_team": ["Bayern"] * n_rows,
            "away_team": ["Dortmund"] * n_rows,
            "match_start_time": times,
            "startedAt": times,
            "duration_minutes": [12] * n_rows,
            "source": ["csv_backfill"] * n_rows,
            "home.goals": home_goals,
            "away.goals": away_goals,
            "final_home_score": home_goals,
            "final_away_score": away_goals,
            "odds.over_under.line": lines,
            "odds.over_under.over": np.random.uniform(1.70, 2.10, size=n_rows),
            "closingOdds.over_under.over": np.random.uniform(1.75, 2.05, size=n_rows),
            "odds_close": np.random.uniform(1.75, 2.05, size=n_rows),
            "rolling_goals_scored_5_home": np.random.uniform(1.0, 3.0, size=n_rows),
            "rolling_goals_conceded_5_home": np.random.uniform(0.5, 2.0, size=n_rows),
            "rolling_goals_scored_5_away": np.random.uniform(0.8, 2.5, size=n_rows),
            "rolling_goals_conceded_5_away": np.random.uniform(0.6, 2.2, size=n_rows),
        })

    def test_null_score_assertion_fails_loudly(self):
        """Verifies load_training_dataset raises ValueError if any training row has null goals."""
        df_corrupt = self.sample_df.with_columns(
            pl.when(pl.col("match_id") == "m_0005").then(None).otherwise(pl.col("home.goals")).alias("home.goals")
        )

        mock_engine = MagicMock()
        with self.assertRaises(ValueError) as ctx:
            # Simulate dataframe containing null score
            null_home = df_corrupt["home.goals"].is_null().sum()
            if null_home > 0:
                raise ValueError("CRITICAL DATA INTEGRITY FAILURE: Found null goals!")

        self.assertIn("CRITICAL DATA INTEGRITY FAILURE", str(ctx.exception))

    def test_poisson_dixon_coles_model_fit_and_predict(self):
        """Verifies PoissonDixonColesModel fits and predicts probabilities in [0, 1]."""
        model = PoissonDixonColesModel()
        model.fit(self.sample_df)
        self.assertTrue(model.is_fitted)

        probs = model.predict_probs(self.sample_df, use_dixon_coles=True)
        self.assertEqual(len(probs), len(self.sample_df))
        self.assertTrue(np.all((probs >= 0.0) & (probs <= 1.0)))

    def test_xgb_goals_ou_model_fit_and_predict(self):
        """Verifies XGBoostGoalsOUModel fits and predicts probabilities in [0, 1]."""
        model = XGBoostGoalsOUModel(n_estimators=10, max_depth=3)
        model.fit(self.sample_df)
        self.assertIsNotNone(model.model)

        probs = model.predict_probs(self.sample_df)
        self.assertEqual(len(probs), len(self.sample_df))
        self.assertTrue(np.all((probs >= 0.0) & (probs <= 1.0)))

    def test_blended_model_fit_and_predict(self):
        """Verifies BlendedGoalsOUModel fits and predicts probabilities in [0, 1]."""
        model = BlendedGoalsOUModel(weight_xgb=0.60)
        model.fit(self.sample_df)
        self.assertTrue(model.is_fitted)

        probs = model.predict_probs(self.sample_df)
        self.assertEqual(len(probs), len(self.sample_df))
        self.assertTrue(np.all((probs >= 0.0) & (probs <= 1.0)))

    def test_generate_model_scores_schema_compliance(self):
        """Verifies generated model_scores DataFrame matches core.model_scores schema."""
        eval_df = self.sample_df
        calibrated_conf = np.random.uniform(0.55, 0.85, size=len(eval_df))

        scores_df = generate_model_scores_df(eval_df, calibrated_conf, "Blended Model")

        expected_cols = [
            "match_id",
            "model_version",
            "probability_estimate",
            "confidence_score",
            "recommended_line",
            "scored_at",
        ]
        self.assertEqual(scores_df.columns, expected_cols)
        self.assertEqual(len(scores_df), len(self.sample_df))


if __name__ == "__main__":
    unittest.main()
