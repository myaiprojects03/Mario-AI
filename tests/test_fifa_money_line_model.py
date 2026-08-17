"""
Unit tests for FIFA 1X2 Money Line Model Pipeline (Task 11).
"""

import pytest
import numpy as np
import polars as pl
from datetime import datetime, timedelta, timezone

from markets.fifa_money_line.models import (
    MultinomialLogisticMLModel,
    LightGBMMoneyLineModel,
    BlendedMoneyLineModel,
)
from markets.fifa_money_line.model import (
    generate_model_scores_df,
    MODEL_VERSION,
    MONEY_LINE_ODDS_FLOOR,
)
from core.validation.walk_forward import WalkForwardSplitter


@pytest.fixture
def sample_match_dataframe():
    """Generates synthetic dataframe for FIFA Money Line model testing."""
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
            "home_win_rate_roll_5": 0.50,
            "home_win_rate_roll_10": 0.45,
            "home_draw_rate_roll_5": 0.20,
            "home_draw_rate_roll_10": 0.20,
            "home_loss_rate_roll_5": 0.30,
            "home_loss_rate_roll_10": 0.35,
            "away_win_rate_roll_5": 0.40,
            "away_win_rate_roll_10": 0.40,
            "away_draw_rate_roll_5": 0.20,
            "away_draw_rate_roll_10": 0.20,
            "away_loss_rate_roll_5": 0.40,
            "away_loss_rate_roll_10": 0.40,
            "home_win_rate_home_games": 0.55,
            "away_win_rate_away_games": 0.35,
            "home_form_streak": 2,
            "away_form_streak": -1,
            "draw_prob_roll_10": 0.20,
            "h2h_matches_count": 3,
            "h2h_win_rate_a": 0.66,
            "odds_implied_prob": 0.52,
            "implied_vs_hist_divergence": 0.07,
            "odds_drift_abs": 0.05,
            "odds_drift_pct": 2.5,
            "is_reliable_5": True,
            "is_reliable_10": True,
            "closingOdds.money_line.home": 1.90,
            "odds_close": 1.90,
        })
    return pl.DataFrame(records)


def test_odds_floor_is_1_70():
    """Verifies that 1.70 odds floor is enforced for Money Line markets."""
    assert MONEY_LINE_ODDS_FLOOR == 1.70


def test_submodels_fitting_and_predicting(sample_match_dataframe):
    """Tests fitting and predicting across Multinomial Logistic, LightGBM, and Blended ML models."""
    df_train = sample_match_dataframe[:80]
    df_test = sample_match_dataframe[80:]

    logistic_model = MultinomialLogisticMLModel()
    logistic_model.fit(df_train)
    p_log = logistic_model.predict_probs(df_test)
    assert len(p_log) == len(df_test)
    assert np.all((p_log >= 0.01) & (p_log <= 0.99))

    lgbm_model = LightGBMMoneyLineModel()
    lgbm_model.fit(df_train)
    p_lgb = lgbm_model.predict_probs(df_test)
    assert len(p_lgb) == len(df_test)
    assert np.all((p_lgb >= 0.01) & (p_lgb <= 0.99))

    blend_model = BlendedMoneyLineModel(weight_lgb=0.60)
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
        "LightGBM Money Line",
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
    assert model_scores["model_version"][0] == f"fifa_money_line_{MODEL_VERSION}"
    assert len(model_scores) == len(sample_match_dataframe)
