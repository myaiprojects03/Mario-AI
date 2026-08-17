"""
Unit tests for eBasketball Over/Under Model Pipeline (Task 12).
"""

import pytest
import numpy as np
import polars as pl
from datetime import datetime, timedelta, timezone

from markets.ebasket_ou.models import (
    NormalDistributionOUModel,
    LightGBMNNEnsembleOUModel,
)
from markets.ebasket_ou.model import (
    generate_model_scores_df,
    MODEL_VERSION,
    EBASKET_OU_ODDS_FLOOR,
)
from core.validation.walk_forward import WalkForwardSplitter


@pytest.fixture
def sample_ebasket_ou_dataframe():
    """Generates synthetic dataframe for eBasketball Over/Under model testing."""
    n_rows = 100
    base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    records = []
    for i in range(n_rows):
        t_val = base_time + timedelta(hours=i)
        records.append({
            "match_id": f"eb_{i}",
            "startedAt": t_val.isoformat(),
            "match_start_time": t_val,
            "home.goals": float(np.random.randint(50, 70)),
            "away.goals": float(np.random.randint(50, 70)),
            "home_scored_roll_mean_5": 58.0,
            "home_scored_roll_mean_10": 57.5,
            "home_conceded_roll_mean_5": 54.0,
            "home_conceded_roll_mean_10": 53.5,
            "away_scored_roll_mean_5": 55.0,
            "away_scored_roll_mean_10": 54.5,
            "away_conceded_roll_mean_5": 56.0,
            "away_conceded_roll_mean_10": 55.5,
            "expected_total_points": 112.0,
            "ht_ft_points_ratio_roll": 0.48,
            "ou_line_value": 111.5,
            "ou_line_diff": 0.5,
            "ou_line_over_hit_rate_roll": 0.52,
            "hour_of_day_utc": 14,
            "odds_drift_abs": 0.05,
            "odds_drift_pct": 2.5,
            "is_reliable_5": True,
            "is_reliable_10": True,
            "odds.over_under.line": 111.5,
            "closingOdds.over_under.over": 1.90,
            "odds_close": 1.90,
        })
    return pl.DataFrame(records)


def test_ebasket_ou_odds_floor_is_1_60():
    """Verifies that 1.60 odds floor is enforced for eBasketball O/U."""
    assert EBASKET_OU_ODDS_FLOOR == 1.60


def test_submodels_fitting_and_predicting(sample_ebasket_ou_dataframe):
    """Tests fitting and predicting across Normal baseline and LightGBM+NN ensemble."""
    df_train = sample_ebasket_ou_dataframe[:80]
    df_test = sample_ebasket_ou_dataframe[80:]

    norm_model = NormalDistributionOUModel()
    norm_model.fit(df_train)
    p_norm = norm_model.predict_probs(df_test)
    assert len(p_norm) == len(df_test)
    assert np.all((p_norm >= 0.01) & (p_norm <= 0.99))

    ens_model = LightGBMNNEnsembleOUModel()
    ens_model.fit(df_train)
    p_ens = ens_model.predict_probs(df_test)
    assert len(p_ens) == len(df_test)
    assert np.all((p_ens >= 0.01) & (p_ens <= 0.99))


def test_walk_forward_splitter_timestamp_assertion(sample_ebasket_ou_dataframe):
    """Verifies max(train_timestamp) < min(test_timestamp) across all walk-forward splits."""
    splitter = WalkForwardSplitter(
        train_days=2,
        test_days=1,
        step_days=1,
        time_col="match_start_time",
    )

    split_count = 0
    for train_idx, test_idx in splitter.split(sample_ebasket_ou_dataframe):
        split_count += 1
        df_tr = sample_ebasket_ou_dataframe[train_idx]
        df_te = sample_ebasket_ou_dataframe[test_idx]

        max_train_t = df_tr["match_start_time"].max()
        min_test_t = df_te["match_start_time"].min()
        assert max_train_t < min_test_t

    assert split_count > 0


def test_model_scores_schema_compliance(sample_ebasket_ou_dataframe):
    """Verifies output DataFrame matches core.model_scores schema."""
    conf = np.full(len(sample_ebasket_ou_dataframe), 0.65)
    model_scores = generate_model_scores_df(
        sample_ebasket_ou_dataframe,
        conf,
        "eBasketball O/U Ensemble",
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
    assert model_scores["model_version"][0] == f"ebasket_ou_{MODEL_VERSION}"
    assert len(model_scores) == len(sample_ebasket_ou_dataframe)
