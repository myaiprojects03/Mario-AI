"""
FIFA Goals Over/Under Feature Engineering Package.

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
- expected_total_goals (float): Combined rolling expected goals (home_scored_10 + away_scored_10).
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_mean_combined_goals (float): Average total goals scored in previous H2H encounters.
- ou_line_value (float): Over/under target line (e.g. 2.5, 3.5, 4.5).
- ou_line_diff (float): Expected total goals minus target line (expected_total_goals - ou_line_value).
- ou_line_hit_rate_roll (float): Rolling historical over hit rate for the match's line value.
- ht_ft_goal_ratio_league (float): League-segmented first-half to full-time goal ratio.
- odds_implied_prob (float): Implied probability derived from odds_close (1 / odds_close).
- implied_vs_hist_divergence (float): Implied probability minus historical hit rate (odds_implied_prob - ou_line_hit_rate_roll).
- odds_drift_abs (float): Absolute closing minus opening odds drift (odds_close - odds_open).
- odds_drift_pct (float): Percentage closing minus opening odds drift.
"""

from typing import List
import polars as pl

from markets._shared.fifa_goals_features import build_shared_fifa_goals_features


FEATURE_COLUMNS = [
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
    "expected_total_goals",
    "h2h_matches_count",
    "h2h_mean_combined_goals",
    "ou_line_value",
    "ou_line_diff",
    "ou_line_hit_rate_roll",
    "ht_ft_goal_ratio_league",
    "odds_implied_prob",
    "implied_vs_hist_divergence",
    "odds_drift_abs",
    "odds_drift_pct",
]


def build_fifa_goals_ou_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds FIFA Goals Over/Under feature dataframe keyed by match_id.
    """
    if df.is_empty():
        return df

    # 1. Shared FIFA goals features
    work_df = build_shared_fifa_goals_features(df)

    # 2. O/U Market Specific Line Differentials
    line_col = "odds.over_under.line" if "odds.over_under.line" in work_df.columns else "line_value"
    if line_col in work_df.columns:
        work_df = work_df.with_columns(
            pl.col(line_col).fill_null(2.5).cast(pl.Float64).alias("ou_line_value")
        )
    else:
        work_df = work_df.with_columns(pl.lit(2.5).alias("ou_line_value"))

    work_df = work_df.with_columns(
        (pl.col("expected_total_goals") - pl.col("ou_line_value")).alias("ou_line_diff")
    )

    # Fill any missing feature columns with default float/int values
    for col in FEATURE_COLUMNS:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            elif col == "h2h_matches_count":
                work_df = work_df.with_columns(pl.lit(0).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(FEATURE_COLUMNS)
