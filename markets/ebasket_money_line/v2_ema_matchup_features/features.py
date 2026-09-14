"""
eBasketball Money Line V2 Feature Builder.
Includes:
- EMA Decay Win/Loss rates (alpha=0.30)
- Asymmetric favorite odds bucket indicators (1.65 - 2.25)
- H2H Matchup Net Rating Differentials
- Bayesian Rating Differentials
"""

from typing import List
import polars as pl
import numpy as np

from markets._shared.ebasket_v2_features import build_shared_ebasket_v2_features, compute_ema_features

EBASKET_ML_FEATURE_COLUMNS_V2 = [
    "match_id",
    "is_reliable_5",
    "is_reliable_10",
    "home_win_rate_ema",
    "away_win_rate_ema",
    "matchup_net_rating_diff",
    "is_favorite_bucket",
    "odds_implied_prob",
    "implied_vs_ema_divergence",
    "odds_drift_abs",
    "odds_drift_pct",
    "home_bayesian_rating_mean",
    "home_bayesian_rating_std",
    "away_bayesian_rating_mean",
    "away_bayesian_rating_std",
    "bayesian_rating_diff",
]


def build_ebasket_money_line_v2_features(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df

    work_df = build_shared_ebasket_v2_features(df)
    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"

    work_df = work_df.with_columns([
        (pl.col(home_score_col) > pl.col(away_score_col)).cast(pl.Float64).alias("is_win"),
        (pl.col(home_score_col) < pl.col(away_score_col)).cast(pl.Float64).alias("is_loss"),
    ])

    home_win_ema = compute_ema_features(work_df, "home_player", "is_win", "startedAt", alpha=0.30, prefix="home_win_rate")
    away_win_ema = compute_ema_features(work_df, "away_player", "is_loss", "startedAt", alpha=0.30, prefix="away_win_rate")

    work_df = work_df.with_columns([
        home_win_ema.alias("home_win_rate_ema"),
        away_win_ema.alias("away_win_rate_ema"),
    ])

    # Odds & Implied Probabilities
    close_col = "closingOdds.money_line.home" if "closingOdds.money_line.home" in work_df.columns else "odds_close"
    if close_col in work_df.columns:
        work_df = work_df.with_columns([
            pl.when(pl.col(close_col).is_not_null() & (pl.col(close_col) > 0))
            .then(1.0 / pl.col(close_col))
            .otherwise(0.50)
            .alias("odds_implied_prob"),
            (
                pl.col(close_col).is_not_null() & 
                (pl.col(close_col) >= 1.65) & 
                (pl.col(close_col) <= 2.25)
            ).alias("is_favorite_bucket"),
        ])
    else:
        work_df = work_df.with_columns([
            pl.lit(0.50).alias("odds_implied_prob"),
            pl.lit(True).alias("is_favorite_bucket"),
        ])

    work_df = work_df.with_columns(
        (pl.col("odds_implied_prob") - pl.col("home_win_rate_ema")).alias("implied_vs_ema_divergence")
    )

    for col in EBASKET_ML_FEATURE_COLUMNS_V2:
        if col not in work_df.columns:
            if col.startswith("is_reliable") or col == "is_favorite_bucket":
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(EBASKET_ML_FEATURE_COLUMNS_V2)
