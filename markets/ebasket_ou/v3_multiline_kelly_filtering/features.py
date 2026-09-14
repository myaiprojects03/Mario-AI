"""
eBasketball Over/Under V3 Feature Engineering Package.
Extends V1 features with combined game pace and scoring volatility vectors.
"""

import polars as pl
from markets.ebasket_ou.features import build_ebasket_ou_features, EBASKET_OU_FEATURE_COLUMNS as V1_FEATURE_COLUMNS

V3_EBASKET_OU_FEATURE_COLUMNS = V1_FEATURE_COLUMNS + [
    "combined_scoring_pace_5",
    "combined_scoring_pace_10",
    "combined_scoring_volatility_5",
]


def build_ebasket_ou_v3_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds eBasketball Over/Under V3 feature dataframe.
    """
    if df.is_empty():
        return df

    work_df = build_ebasket_ou_features(df)

    work_df = work_df.with_columns([
        (pl.col("home_scored_roll_mean_5") + pl.col("away_scored_roll_mean_5")).alias("combined_scoring_pace_5"),
        (pl.col("home_scored_roll_mean_10") + pl.col("away_scored_roll_mean_10")).alias("combined_scoring_pace_10"),
        (pl.col("home_bayesian_rating_std") + pl.col("away_bayesian_rating_std")).alias("combined_scoring_volatility_5"),
    ])

    meta_cols = [c for c in [
        "match_start_time", "startedAt", "home.goals", "away.goals",
        "final_home_score", "final_away_score", "odds_close",
        "closingOdds.over_under.over", "odds.over_under.line", "source", "league"
    ] if c in work_df.columns and c not in V3_EBASKET_OU_FEATURE_COLUMNS]

    return work_df.select(V3_EBASKET_OU_FEATURE_COLUMNS + meta_cols)
