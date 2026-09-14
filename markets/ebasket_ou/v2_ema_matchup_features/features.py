"""
eBasketball Over/Under V2 Feature Builder.
Imports shared V2 features from markets._shared.ebasket_v2_features
"""

from typing import List
import polars as pl
from markets._shared.ebasket_v2_features import build_shared_ebasket_v2_features

EBASKET_OU_FEATURE_COLUMNS_V2 = [
    "match_id",
    "is_reliable_5",
    "is_reliable_10",
    "home_scored_ema",
    "home_conceded_ema",
    "away_scored_ema",
    "away_conceded_ema",
    "matchup_home_offense_edge",
    "matchup_away_offense_edge",
    "matchup_net_rating_diff",
    "expected_total_points_v2",
    "ht_ft_points_ratio_roll",
    "hour_of_day_utc",
    "odds_drift_abs",
    "odds_drift_pct",
    "home_bayesian_rating_mean",
    "home_bayesian_rating_std",
    "away_bayesian_rating_mean",
    "away_bayesian_rating_std",
    "bayesian_rating_diff",
]


def build_ebasket_ou_v2_features(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df

    work_df = build_shared_ebasket_v2_features(df)

    for col in EBASKET_OU_FEATURE_COLUMNS_V2:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(EBASKET_OU_FEATURE_COLUMNS_V2)
