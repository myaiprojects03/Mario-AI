"""
Unit tests for eBasketball Money Line Model Pipeline (Task 12).
"""

import pytest
import numpy as np
import polars as pl
from datetime import datetime, timedelta, timezone

from markets.ebasket_money_line.models import (
    LogisticRegressionMoneyLineModel,
    LightGBMNNEnsembleMLModel,
)
from markets.ebasket_money_line.model import (
    generate_model_scores_df,
    MODEL_VERSION,
    EBASKET_ML_ODDS_FLOOR,
)
from core.validation.walk_forward import WalkForwardSplitter


@pytest.fixture
def sample_ebasket_ml_dataframe():
    """Generates synthetic dataframe for eBasketball Money Line model testing."""
    n_rows = 100
    base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    records = []
    for i in range(n_rows):
        t_val = base_time + timedelta(hours=i)
        records.append({
            "match_id": f"eb_ml_{i}",
            "startedAt": t_val.isoformat(),
            "match_start_time": t_val,
            "home.goals": float(np.random.randint(50, 70)),
            "away.goals": float(np.random.randint(50, 70)),
            "home_win_rate_roll_5": 0.55,
            "home_win_rate_roll_10": 0.52,
            "away_win_rate_roll_5": 0.45,
            "away_win_rate_roll_10": 0.48,
            "margin_of_victory_roll_10": 3.5,
            "hour_of_day_utc": 14,
            "h2h_matches_count": 2,
            "h2h_win_rate_a": 0.50,
            "h2h_mean_point_diff": 2.0,
            "odds_implied_prob": 0.52,
            "implied_vs_hist_divergence": 0.02,
            "odds_drift_abs": 0.05,
            "odds_drift_pct": 2.5,
            "is_reliable_5": True,
            "is_reliable_10": True,
            "closingOdds.money_line.home": 1.90,
            "odds_close": 1.90,
        })
    return pl.DataFrame(records)


def test_ebasket_ml_odds_floor_is_1_70():
    """Verifies that 1.70 odds floor is enforced for eBasketball Money Line."""
    assert EBASKET_ML_ODDS_FLOOR == 1.70


def test_submodels_fitting_and_predicting(sample_ebasket_ml_dataframe):
    """Tests fitting and predicting across Logistic baseline and LightGBM+NN ensemble."""
    df_train = sample_ebasket_ml_dataframe[:80]
    df_test = sample_ebasket_ml_dataframe[80:]

    log_model = LogisticRegressionMoneyLineModel()
    log_model.fit(df_train)
    p_log = log_model.predict_probs(df_test)
    assert len(p_log) == len(df_test)
    assert np.all((p_log >= 0.01) & (p_log <= 0.99))

    ens_model = LightGBMNNEnsembleMLModel()
    ens_model.fit(df_train)
    p_ens = ens_model.predict_probs(df_test)
    assert len(p_ens) == len(df_test)
    assert np.all((p_ens >= 0.01) & (p_ens <= 0.99))


def test_walk_forward_splitter_timestamp_assertion(sample_ebasket_ml_dataframe):
    """Verifies max(train_timestamp) < min(test_timestamp) across all walk-forward splits."""
    splitter = WalkForwardSplitter(
        train_days=2,
        test_days=1,
        step_days=1,
        time_col="match_start_time",
    )

    split_count = 0
    for train_idx, test_idx in splitter.split(sample_ebasket_ml_dataframe):
        split_count += 1
        df_tr = sample_ebasket_ml_dataframe[train_idx]
        df_te = sample_ebasket_ml_dataframe[test_idx]

        max_train_t = df_tr["match_start_time"].max()
        min_test_t = df_te["match_start_time"].min()
        assert max_train_t < min_test_t

    assert split_count > 0


def test_model_scores_schema_compliance(sample_ebasket_ml_dataframe):
    """Verifies output DataFrame matches core.model_scores schema."""
    conf = np.full(len(sample_ebasket_ml_dataframe), 0.65)
    model_scores = generate_model_scores_df(
        sample_ebasket_ml_dataframe,
        conf,
        "eBasketball Money Line Ensemble",
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
    assert model_scores["model_version"][0] == f"ebasket_money_line_{MODEL_VERSION}"
    assert len(model_scores) == len(sample_ebasket_ml_dataframe)
