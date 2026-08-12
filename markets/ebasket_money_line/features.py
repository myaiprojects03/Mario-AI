"""
eBasketball Money Line Feature Engineering Package.

SCHEMA DOCUMENTATION:
- match_id (str): Unique match identifier key.
- is_reliable_5 (bool): True if player has >= 3 prior historical matches for 5-match window.
- is_reliable_10 (bool): True if player has >= 3 prior historical matches for 10-match window.
- home_win_rate_roll_5 (float): Past 5-match rolling win rate for home player (fallback: 0.50).
- home_win_rate_roll_10 (float): Past 10-match rolling win rate for home player (fallback: 0.50).
- away_win_rate_roll_5 (float): Past 5-match rolling win rate for away player (fallback: 0.50).
- away_win_rate_roll_10 (float): Past 10-match rolling win rate for away player (fallback: 0.50).
- margin_of_victory_roll_10 (float): Rolling average point differential (home_scored_10 - away_scored_10).
- hour_of_day_utc (int): Hour of match start in UTC (statistically validated via ANOVA).
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_win_rate_a (float): Home player's win rate in previous head-to-head encounters.
- h2h_mean_point_diff (float): Average point margin in previous head-to-head encounters.
- odds_implied_prob (float): Implied win probability from closing money line odds (1 / odds_close).
- implied_vs_hist_divergence (float): Implied probability minus historical win rate (odds_implied_prob - home_win_rate_roll_10).
- odds_drift_abs (float): Absolute closing minus opening money line odds drift.
- odds_drift_pct (float): Percentage closing minus opening money line odds drift.
"""

from typing import List
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features
from markets._shared.ebasket_features import build_shared_ebasket_features


# NOTE: eBasketball matches cannot end in a draw (overtime is played until a winner emerges).
# Draw probability feature is explicitly omitted and MUST NOT be included in EBASKET_ML_FEATURE_COLUMNS.
EBASKET_ML_FEATURE_COLUMNS = [
    "match_id",
    "is_reliable_5",
    "is_reliable_10",
    "home_win_rate_roll_5",
    "home_win_rate_roll_10",
    "away_win_rate_roll_5",
    "away_win_rate_roll_10",
    "margin_of_victory_roll_10",
    "hour_of_day_utc",
    "h2h_matches_count",
    "h2h_win_rate_a",
    "h2h_mean_point_diff",
    "odds_implied_prob",
    "implied_vs_hist_divergence",
    "odds_drift_abs",
    "odds_drift_pct",
]


def build_ebasket_money_line_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds eBasketball Money Line feature dataframe keyed by match_id.
    """
    if df.is_empty():
        return df

    work_df = df.sort("startedAt")

    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"

    # 1. Match Outcome Indicators (No draws in eBasketball)
    work_df = work_df.with_columns([
        (pl.col(home_score_col) > pl.col(away_score_col)).cast(pl.Float64).alias("is_win"),
        (pl.col(home_score_col) < pl.col(away_score_col)).cast(pl.Float64).alias("is_loss"),
    ])

    # 2. Prior Match Count & Reliability Flags
    work_df = work_df.with_columns(
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("player_prior_match_count")
    )
    work_df = work_df.with_columns([
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_5"),
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_10"),
    ])

    # 3. Rolling Win Rates (Windows 5 & 10, fallback: 0.50)
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col="is_win", time_col="startedAt", window_sizes=[5, 10], prefix="home_win"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col="is_loss", time_col="startedAt", window_sizes=[5, 10], prefix="away_win"
    )
    work_df = work_df.with_columns([
        pl.col("home_win_roll_mean_5").fill_null(0.50).alias("home_win_rate_roll_5"),
        pl.col("home_win_roll_mean_10").fill_null(0.50).alias("home_win_rate_roll_10"),
        pl.col("away_win_roll_mean_5").fill_null(0.50).alias("away_win_rate_roll_5"),
        pl.col("away_win_roll_mean_10").fill_null(0.50).alias("away_win_rate_roll_10"),
    ])

    # 4. Shared eBasketball Base Features (for points and hour_of_day_utc)
    shared_df = build_shared_ebasket_features(work_df)
    work_df = work_df.with_columns([
        shared_df["home_scored_roll_mean_10"].alias("home_scored_roll_mean_10"),
        shared_df["away_scored_roll_mean_10"].alias("away_scored_roll_mean_10"),
        shared_df["hour_of_day_utc"].alias("hour_of_day_utc"),
    ])

    # 5. Margin-of-Victory Trend (Rolling Point Differential)
    work_df = work_df.with_columns(
        (pl.col("home_scored_roll_mean_10") - pl.col("away_scored_roll_mean_10")).alias("margin_of_victory_roll_10")
    )

    # 6. Head-to-Head History
    work_df = compute_h2h_features(
        work_df,
        entity_a_col="home_player",
        entity_b_col="away_player",
        time_col="startedAt",
        score_a_col=home_score_col,
        score_b_col=away_score_col,
        prefix="h2h",
    )
    work_df = work_df.with_columns(
        pl.col("h2h_mean_score_diff").alias("h2h_mean_point_diff")
    )

    # 7. Money Line Odds Efficiency & Divergence
    close_col = "closingOdds.money_line.home" if "closingOdds.money_line.home" in work_df.columns else "odds_close"
    if close_col in work_df.columns:
        work_df = work_df.with_columns(
            pl.when(pl.col(close_col).is_not_null() & (pl.col(close_col) > 0))
            .then(1.0 / pl.col(close_col))
            .otherwise(0.50)
            .alias("odds_implied_prob")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.50).alias("odds_implied_prob"))

    work_df = work_df.with_columns(
        (pl.col("odds_implied_prob") - pl.col("home_win_rate_roll_10")).alias("implied_vs_hist_divergence")
    )

    # 8. Odds Drift
    open_col = "odds.money_line.home" if "odds.money_line.home" in work_df.columns else "odds_open"
    if open_col in work_df.columns and close_col in work_df.columns:
        work_df = add_odds_drift_columns(work_df, open_col=open_col, close_col=close_col, prefix="odds")
    else:
        work_df = work_df.with_columns([
            pl.lit(0.0).alias("odds_drift_abs"),
            pl.lit(0.0).alias("odds_drift_pct"),
        ])

    # Fill any missing feature columns with defaults
    for col in EBASKET_ML_FEATURE_COLUMNS:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            elif col == "hour_of_day_utc":
                work_df = work_df.with_columns(pl.lit(12).alias(col))
            elif col == "h2h_matches_count":
                work_df = work_df.with_columns(pl.lit(0).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(EBASKET_ML_FEATURE_COLUMNS)
