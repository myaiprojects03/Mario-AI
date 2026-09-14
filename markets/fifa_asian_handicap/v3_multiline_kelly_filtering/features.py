"""
FIFA Asian Handicap V3 Feature Engineering Package.
Extends V1 features with recency EMA margin differentials.
"""

import polars as pl
from markets.fifa_asian_handicap.features import build_fifa_asian_handicap_features, AH_FEATURE_COLUMNS as V1_FEATURE_COLUMNS

V3_FEATURE_COLUMNS = V1_FEATURE_COLUMNS + [
    "ema_margin_diff_5",
    "ema_margin_diff_10",
]


def build_fifa_ah_v3_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds FIFA Asian Handicap V3 feature dataframe.
    """
    if df.is_empty():
        return df

    work_df = build_fifa_asian_handicap_features(df)

    work_df = work_df.with_columns([
        (pl.col("home_scored_roll_mean_5") - pl.col("home_conceded_roll_mean_5") -
         (pl.col("away_scored_roll_mean_5") - pl.col("away_conceded_roll_mean_5"))).alias("ema_margin_diff_5"),
        (pl.col("home_scored_roll_mean_10") - pl.col("home_conceded_roll_mean_10") -
         (pl.col("away_scored_roll_mean_10") - pl.col("away_conceded_roll_mean_10"))).alias("ema_margin_diff_10"),
    ])

    meta_cols = [c for c in [
        "match_start_time", "startedAt", "home.goals", "away.goals",
        "final_home_score", "final_away_score", "odds_close",
        "closingOdds.asian_handicap.home", "source", "league"
    ] if c in work_df.columns and c not in V3_FEATURE_COLUMNS]

    return work_df.select(V3_FEATURE_COLUMNS + meta_cols)
