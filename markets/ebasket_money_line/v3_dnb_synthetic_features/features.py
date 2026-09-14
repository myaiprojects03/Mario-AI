"""
eBasketball Money Line V3 Feature Engineering Package (DNB Synthetic Transforms & Quarter Scoring Pace).
"""

import polars as pl
from markets.ebasket_money_line.features import build_ebasket_money_line_features, EBASKET_ML_FEATURE_COLUMNS as V1_FEATURE_COLUMNS

V3_EBASKET_ML_FEATURE_COLUMNS = V1_FEATURE_COLUMNS + [
    "win_rate_diff_5",
    "win_rate_diff_10",
    "bayesian_rating_mean_diff",
    "volatility_index_diff",
]


def build_ebasket_ml_v3_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds eBasketball Money Line V3 feature dataframe.
    """
    if df.is_empty():
        return df

    work_df = build_ebasket_money_line_features(df)

    work_df = work_df.with_columns([
        (pl.col("home_win_rate_roll_5") - pl.col("away_win_rate_roll_5")).alias("win_rate_diff_5"),
        (pl.col("home_win_rate_roll_10") - pl.col("away_win_rate_roll_10")).alias("win_rate_diff_10"),
        (pl.col("home_bayesian_rating_mean") - pl.col("away_bayesian_rating_mean")).alias("bayesian_rating_mean_diff"),
        (pl.col("home_bayesian_rating_std") - pl.col("away_bayesian_rating_std")).alias("volatility_index_diff"),
    ])

    meta_cols = [c for c in [
        "match_start_time", "startedAt", "home.goals", "away.goals",
        "final_home_score", "final_away_score", "odds_close",
        "closingOdds.money_line.home", "source", "league"
    ] if c in work_df.columns and c not in V3_EBASKET_ML_FEATURE_COLUMNS]

    return work_df.select(V3_EBASKET_ML_FEATURE_COLUMNS + meta_cols)
