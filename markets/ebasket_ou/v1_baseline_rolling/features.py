"""
eBasketball Over/Under Feature Engineering Package.

SCHEMA DOCUMENTATION:
- match_id (str): Unique match identifier key.
- is_reliable_5 (bool): True if player has >= 3 prior historical matches for 5-match window.
- is_reliable_10 (bool): True if player has >= 3 prior historical matches for 10-match window.
- home_scored_roll_mean_5 (float): Past 5-match rolling mean points scored by home player (fallback: 55.6).
- home_scored_roll_mean_10 (float): Past 10-match rolling mean points scored by home player (fallback: 55.6).
- home_conceded_roll_mean_5 (float): Past 5-match rolling mean points conceded by home player (fallback: 55.6).
- home_conceded_roll_mean_10 (float): Past 10-match rolling mean points conceded by home player (fallback: 55.6).
- away_scored_roll_mean_5 (float): Past 5-match rolling mean points scored by away player (fallback: 55.6).
- away_scored_roll_mean_10 (float): Past 10-match rolling mean points scored by away player (fallback: 55.6).
- away_conceded_roll_mean_5 (float): Past 5-match rolling mean points conceded by away player (fallback: 55.6).
- away_conceded_roll_mean_10 (float): Past 10-match rolling mean points conceded by away player (fallback: 55.6).
- expected_total_points (float): Sum of home and away 10-match expected points (home_scored_10 + away_scored_10).
- ht_ft_points_ratio_roll (float): Rolling ratio of first-half points to full-time total points (pace proxy).
- ou_line_value (float): Over/under target line offered (e.g. 110.5, 112.5).
- ou_line_diff (float): Expected total points minus target line (expected_total_points - ou_line_value).
- ou_line_over_hit_rate_roll (float): Rolling historical over-hit rate for target line value.
- hour_of_day_utc (int): Hour of match start in UTC (statistically validated via ANOVA).
- odds_drift_abs (float): Absolute closing minus opening odds drift.
- odds_drift_pct (float): Percentage closing minus opening odds drift.
"""

from typing import List
import polars as pl

from markets._shared.ebasket_features import build_shared_ebasket_features


EBASKET_OU_FEATURE_COLUMNS = [
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
    "expected_total_points",
    "ht_ft_points_ratio_roll",
    "ou_line_value",
    "ou_line_diff",
    "ou_line_over_hit_rate_roll",
    "hour_of_day_utc",
    "odds_drift_abs",
    "odds_drift_pct",
    "home_bayesian_rating_mean",
    "home_bayesian_rating_std",
    "away_bayesian_rating_mean",
    "away_bayesian_rating_std",
    "bayesian_rating_diff",
]


def build_ebasket_ou_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds eBasketball Over/Under feature dataframe keyed by match_id.
    """
    if df.is_empty():
        return df

    # 1. Shared eBasketball features
    work_df = build_shared_ebasket_features(df)

    # 2. O/U Target Line Differentials
    line_col = "odds.over_under.line" if "odds.over_under.line" in work_df.columns else "line_value"
    if line_col in work_df.columns:
        work_df = work_df.with_columns(
            pl.col(line_col).fill_null(111.5).cast(pl.Float64).alias("ou_line_value")
        )
    else:
        work_df = work_df.with_columns(pl.lit(111.5).alias("ou_line_value"))

    work_df = work_df.with_columns(
        (pl.col("expected_total_points") - pl.col("ou_line_value")).alias("ou_line_diff")
    )

    # Fill any missing feature columns with defaults
    for col in EBASKET_OU_FEATURE_COLUMNS:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            elif col == "hour_of_day_utc":
                work_df = work_df.with_columns(pl.lit(12).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(EBASKET_OU_FEATURE_COLUMNS)
