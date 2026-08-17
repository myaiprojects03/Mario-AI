"""
Unit tests for FIFA Asian Handicap Model Pipeline (Task 10).
"""

import pytest
import numpy as np
import polars as pl
from datetime import datetime, timedelta, timezone

from markets.fifa_asian_handicap.models import (
    PoissonDixonColesAHModel,
    XGBoostAsianHandicapModel,
    BlendedAsianHandicapModel,
)
from markets.fifa_asian_handicap.model import (
    generate_model_scores_df,
    MODEL_VERSION,
)
from core.validation.walk_forward import WalkForwardSplitter


@pytest.fixture
def sample_match_dataframe():
    """Generates synthetic dataframe for Asian Handicap model testing."""
    n_rows = 100
    base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    records = []
    for i in range(n_rows):
        t_val = base_time + timedelta(hours=i)
        records.append({
            "match_id": f"m_{i}",
            "startedAt": t_val.isoformat(),
            "match_start_time": t_val,
            "home.goals": float(np.random.randint(0, 5)),
            "away.goals": float(np.random.randint(0, 5)),
            "home_scored_roll_mean_5": 2.1,
            "home_scored_roll_mean_10": 2.0,
            "home_conceded_roll_mean_5": 1.2,
            "home_conceded_roll_mean_10": 1.1,
            "away_scored_roll_mean_5": 1.5,
            "away_scored_roll_mean_10": 1.4,
            "away_conceded_roll_mean_5": 1.8,
            "away_conceded_roll_mean_10": 1.7,
            "expected_home_margin": 0.6,
            "handicap_line_value": -0.5,
            "normalized_adjusted_margin": 0.1,
            "h2h_matches_count": 2,
            "h2h_mean_combined_goals": 3.0,
            "ht_ft_goal_ratio_league": 0.45,
            "odds_implied_prob": 0.52,
            "implied_vs_hist_divergence": 0.02,
            "odds_drift_abs": 0.05,
            "odds_drift_pct": 2.5,
            "is_reliable_5": True,
            "is_reliable_10": True,
            "odds.asian_handicap.line": -0.5,
            "closingOdds.asian_handicap.home": 1.90,
            "odds_close": 1.90,
        })
    return pl.DataFrame(records)


def test_submodels_fitting_and_predicting(sample_match_dataframe):
    """Tests fitting and predicting across Dixon-Coles, XGBoost, and Blended AH models."""
    df_train = sample_match_dataframe[:80]
    df_test = sample_match_dataframe[80:]

    dc_model = PoissonDixonColesAHModel()
    dc_model.fit(df_train)
    p_dc = dc_model.predict_probs(df_test)
    assert len(p_dc) == len(df_test)
    assert np.all((p_dc >= 0.01) & (p_dc <= 0.99))

    xgb_model = XGBoostAsianHandicapModel()
    xgb_model.fit(df_train)
    p_xgb = xgb_model.predict_probs(df_test)
    assert len(p_xgb) == len(df_test)
    assert np.all((p_xgb >= 0.01) & (p_xgb <= 0.99))

    blend_model = BlendedAsianHandicapModel(weight_xgb=0.60)
    blend_model.fit(df_train)
    p_blend = blend_model.predict_probs(df_test)
    assert len(p_blend) == len(df_test)
    assert np.all((p_blend >= 0.01) & (p_blend <= 0.99))


def test_walk_forward_splitter_timestamp_assertion(sample_match_dataframe):
    """Verifies max(train_timestamp) < min(test_timestamp) across all walk-forward splits."""
    splitter = WalkForwardSplitter(
        train_days=2,
        test_days=1,
        step_days=1,
        time_col="match_start_time",
    )

    split_count = 0
    for train_idx, test_idx in splitter.split(sample_match_dataframe):
        split_count += 1
        df_tr = sample_match_dataframe[train_idx]
        df_te = sample_match_dataframe[test_idx]

        max_train_t = df_tr["match_start_time"].max()
        min_test_t = df_te["match_start_time"].min()
        assert max_train_t < min_test_t

    assert split_count > 0


def test_model_scores_schema_compliance(sample_match_dataframe):
    """Verifies output DataFrame matches core.model_scores schema."""
    conf = np.full(len(sample_match_dataframe), 0.65)
    model_scores = generate_model_scores_df(
        sample_match_dataframe,
        conf,
        "XGBoost Asian Handicap",
    )

    expected_cols = [
        "match_id",
        "model_version",
        "probability_estimate",
        "confidence_score",
        "recommended_line",
        "scored_at",
    ]
    assert list(model_scores.columns) == expected_cols
    assert model_scores["model_version"][0] == f"fifa_asian_handicap_{MODEL_VERSION}"
    assert len(model_scores) == len(sample_match_dataframe)
