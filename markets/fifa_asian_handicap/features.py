"""
FIFA Asian Handicap Feature Engineering Package.

SCHEMA DOCUMENTATION:
- match_id (str): Unique match identifier key.
- is_reliable_5 (bool): True if player has >= 3 prior historical matches for 5-match window.
- is_reliable_10 (bool): True if player has >= 3 prior historical matches for 10-match window.
- home_scored_roll_5 (float): Past 5-match rolling mean goals scored by home player.
- home_scored_roll_10 (float): Past 10-match rolling mean goals scored by home player.
- home_conceded_roll_5 (float): Past 5-match rolling mean goals conceded by home player.
- home_conceded_roll_10 (float): Past 10-match rolling mean goals conceded by home player.
- away_scored_roll_5 (float): Past 5-match rolling mean goals scored by away player.
- away_scored_roll_10 (float): Past 10-match rolling mean goals scored by away player.
- away_conceded_roll_5 (float): Past 5-match rolling mean goals conceded by away player.
- away_conceded_roll_10 (float): Past 10-match rolling mean goals conceded by away player.
- expected_home_margin (float): Rolling expected home margin (home_scored_10 - away_scored_10).
- handicap_line_value (float): Asian handicap line value offered (e.g. -0.5, -1.0, +0.5, +1.25).
- normalized_adjusted_margin (float): Handicap-adjusted expected margin (expected_home_margin + handicap_line_value).
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_mean_combined_goals (float): Average total goals scored in previous H2H encounters.
- ht_ft_goal_ratio_league (float): League-segmented first-half to full-time goal ratio.
- odds_implied_prob (float): Implied probability derived from odds_close (1 / odds_close).
- implied_vs_hist_divergence (float): Implied probability minus historical hit rate.
- odds_drift_abs (float): Absolute closing minus opening odds drift.
- odds_drift_pct (float): Percentage closing minus opening odds drift.
"""

from typing import List
import polars as pl

from markets._shared.fifa_goals_features import build_shared_fifa_goals_features


AH_FEATURE_COLUMNS = [
    "match_id",
    "is_reliable_5",
    "is_reliable_10",
    "home_scored_roll_mean_5",
    "home_scored_roll_mean_10",
    "home_conceded_roll_mean_5",
    "home_conceded_roll_mean_10",
    "away_scored_roll_mean_5",
    "away_scored_roll_mean_10",
    "away_conceded_roll_mean_5",
    "away_conceded_roll_mean_10",
    "expected_home_margin",
    "handicap_line_value",
    "normalized_adjusted_margin",
    "h2h_matches_count",
    "h2h_mean_combined_goals",
    "ht_ft_goal_ratio_league",
    "odds_implied_prob",
    "implied_vs_hist_divergence",
    "odds_drift_abs",
    "odds_drift_pct",
]


def build_fifa_asian_handicap_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds FIFA Asian Handicap feature dataframe keyed by match_id, with normalized handicap margin.
    """
    if df.is_empty():
        return df

    # 1. Shared FIFA goals features
    work_df = build_shared_fifa_goals_features(df)

    # 2. Asian Handicap Variable Line Normalization
    ah_line_col = "odds.asian_handicap.line" if "odds.asian_handicap.line" in work_df.columns else "line_value"
    if ah_line_col in work_df.columns:
        work_df = work_df.with_columns(
            pl.col(ah_line_col).fill_null(-0.5).cast(pl.Float64).alias("handicap_line_value")
        )
    else:
        work_df = work_df.with_columns(pl.lit(-0.5).alias("handicap_line_value"))

    # Expected Home Margin = Home Scored Roll 10 - Away Scored Roll 10
    work_df = work_df.with_columns(
        (
            pl.col("home_scored_roll_mean_10").fill_null(0.0) -
            pl.col("away_scored_roll_mean_10").fill_null(0.0)
        ).alias("expected_home_margin")
    )

    # Normalized Adjusted Margin = Expected Home Margin + Handicap Line Value
    work_df = work_df.with_columns(
        (pl.col("expected_home_margin") + pl.col("handicap_line_value")).alias("normalized_adjusted_margin")
    )

    # Fill any missing feature columns with default values
    for col in AH_FEATURE_COLUMNS:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            elif col == "h2h_matches_count":
                work_df = work_df.with_columns(pl.lit(0).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(AH_FEATURE_COLUMNS)
