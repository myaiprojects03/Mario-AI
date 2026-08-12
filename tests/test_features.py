import sys
import site
import pytest
from datetime import datetime, timedelta, timezone
import polars as pl

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.leagues import (
    LEAGUES,
    LeagueConfig,
    get_league_config,
    get_duration_minutes,
    list_leagues_by_sport,
)
from core.features.rolling import compute_rolling_features
from core.features.odds_drift import compute_odds_drift_pair, add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features


def test_league_config_registry():
    """Verify LeagueConfig registry contains all 6 required leagues with correct sports and durations."""
    expected_leagues = [
        ("Esoccer Battle", "fifa", 8),
        ("Esoccer H2H GG League", "fifa", 8),
        ("Esoccer Battle Volta", "fifa", 6),
        ("Esoccer GT Leagues", "fifa", 12),
        ("eBasketball H2H GG League", "ebasket", 20),
        ("eBasketball Battle", "ebasket", 20),
    ]

    for name, expected_sport, expected_duration in expected_leagues:
        assert name in LEAGUES, f"League '{name}' missing from LEAGUES registry!"
        cfg = LEAGUES[name]
        assert cfg.sport == expected_sport
        assert cfg.duration_minutes == expected_duration
        assert get_duration_minutes(name, expected_sport) == expected_duration

    fifa_leagues = list_leagues_by_sport("fifa")
    ebasket_leagues = list_leagues_by_sport("ebasket")
    assert len(fifa_leagues) == 4
    assert len(ebasket_leagues) == 2


def test_rolling_no_current_match_leakage():
    """
    DATA LEAKAGE PROOF TEST 1:
    Assert that computing rolling features for match N does NOT include match N's own outcome.
    Mutating match N's outcome must NOT alter match N's rolling features.
    """
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    
    # 5 chronological matches for player 'PLAYER_ALPHA'
    df_original = pl.DataFrame({
        "match_id": ["m1", "m2", "m3", "m4", "m5"],
        "player": ["PLAYER_ALPHA"] * 5,
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "goals": [2.0, 3.0, 1.0, 4.0, 5.0],
    })

    # Compute rolling mean (window N=3)
    res_orig = compute_rolling_features(
        df_original, entity_col="player", value_col="goals", time_col="startedAt", window_sizes=[3]
    )
    
    m3_roll_orig = res_orig.filter(pl.col("match_id") == "m3")["player_goals_roll_mean_3"][0]
    # m3 rolling mean should be mean of m1(2.0) and m2(3.0) = 2.5
    assert m3_roll_orig == 2.5

    # Mutate match m3's OWN goals from 1.0 to 999.0
    df_mutated_m3 = pl.DataFrame({
        "match_id": ["m1", "m2", "m3", "m4", "m5"],
        "player": ["PLAYER_ALPHA"] * 5,
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "goals": [2.0, 3.0, 999.0, 4.0, 5.0],  # m3 outcome changed
    })

    res_mutated = compute_rolling_features(
        df_mutated_m3, entity_col="player", value_col="goals", time_col="startedAt", window_sizes=[3]
    )

    m3_roll_mutated = res_mutated.filter(pl.col("match_id") == "m3")["player_goals_roll_mean_3"][0]

    # PROOF OF NO LEAKAGE: m3's rolling feature is STRICTLY IDENTICAL despite m3's outcome changing
    assert m3_roll_mutated == m3_roll_orig == 2.5


def test_rolling_no_future_match_leakage():
    """
    DATA LEAKAGE PROOF TEST 2:
    Assert that changing a FUTURE match's outcome does NOT alter rolling features computed for earlier matches.
    """
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    df_original = pl.DataFrame({
        "match_id": ["m1", "m2", "m3", "m4", "m5"],
        "player": ["PLAYER_BETA"] * 5,
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "goals": [2.0, 4.0, 6.0, 8.0, 10.0],
    })

    res_orig = compute_rolling_features(
        df_original, entity_col="player", value_col="goals", time_col="startedAt", window_sizes=[3]
    )

    # Future match m5 goals mutated from 10.0 to 5000.0
    df_mutated_future = pl.DataFrame({
        "match_id": ["m1", "m2", "m3", "m4", "m5"],
        "player": ["PLAYER_BETA"] * 5,
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "goals": [2.0, 4.0, 6.0, 8.0, 5000.0],  # m5 future outcome changed
    })

    res_mutated = compute_rolling_features(
        df_mutated_future, entity_col="player", value_col="goals", time_col="startedAt", window_sizes=[3]
    )

    # Compare rolling features for past/earlier matches m1..m4
    for mid in ["m1", "m2", "m3", "m4"]:
        val_orig = res_orig.filter(pl.col("match_id") == mid)["player_goals_roll_mean_3"][0]
        val_mut = res_mutated.filter(pl.col("match_id") == mid)["player_goals_roll_mean_3"][0]
        
        if val_orig is None:
            assert val_mut is None
        else:
            assert val_orig == val_mut


def test_odds_drift():
    """Verify odds drift calculation for single pairs and Polars DataFrames."""
    abs_drift, pct_drift = compute_odds_drift_pair(1.80, 1.98)
    assert abs_drift == pytest.approx(0.18)
    assert pct_drift == pytest.approx(10.0)

    # Missing open or close handles gracefully
    assert compute_odds_drift_pair(None, 1.98) == (None, None)

    # Polars DataFrame helper
    df = pl.DataFrame({
        "odds_open": [1.80, 2.00],
        "odds_close": [1.90, 1.80],
    })

    res_df = add_odds_drift_columns(df, open_col="odds_open", close_col="odds_close")
    assert "odds_drift_abs" in res_df.columns
    assert "odds_drift_pct" in res_df.columns
    assert res_df["odds_drift_abs"][0] == pytest.approx(0.10)
    assert res_df["odds_drift_pct"][0] == pytest.approx(5.55555, rel=1e-3)


def test_head_to_head_strictly_past_only():
    """Verify head-to-head calculations strictly use prior matches only."""
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

    df = pl.DataFrame({
        "match_id": ["m1", "m2", "m3"],
        "home_player": ["P_X", "P_Y", "P_X"],
        "away_player": ["P_Y", "P_X", "P_Y"],
        "startedAt": [base_time, base_time + timedelta(hours=1), base_time + timedelta(hours=2)],
        "home.goals": [3.0, 1.0, 4.0],
        "away.goals": [1.0, 2.0, 0.0],
    })

    res = compute_h2h_features(
        df,
        entity_a_col="home_player",
        entity_b_col="away_player",
        time_col="startedAt",
        score_a_col="home.goals",
        score_b_col="away.goals",
    )

    # Match 1 (first encounter): 0 prior matches
    m1_h2h = res.filter(pl.col("match_id") == "m1")
    assert m1_h2h["h2h_matches_count"][0] == 0

    # Match 3 (third encounter): 2 prior matches (P_X won match 1 3-1, P_X won match 2 2-1 as away)
    m3_h2h = res.filter(pl.col("match_id") == "m3")
    assert m3_h2h["h2h_matches_count"][0] == 2
    assert m3_h2h["h2h_entity_a_wins"][0] == 2
    assert m3_h2h["h2h_win_rate_a"][0] == 1.0
