"""
Shared eBasketball V2 Feature Builder.
Includes:
- Exponential Moving Average (EMA) decay weighting (alpha=0.30) for rapid form shifts.
- H2H Player Matchup Interaction Vectors (Offense vs Defense rating differentials).
- Rolling half-time to full-time pace ratio.
- Hour of day UTC & Odds drift.
- Bayesian rating trajectories.
"""

from typing import Optional, List
import polars as pl
import numpy as np

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features
from core.features.bayesian_ratings import compute_bayesian_ratings_trajectory


def compute_ema_features(
    df: pl.DataFrame, entity_col: str, value_col: str, time_col: str, alpha: float = 0.30, prefix: str = "ema"
) -> pl.Series:
    """
    Computes past-only Exponential Moving Average (EMA) per entity.
    Strictly excludes current match's own value (shift=1).
    """
    records = df.select(["match_id", entity_col, time_col, value_col]).to_dicts()
    
    entity_emas = {}
    ema_values = []

    for r in records:
        entity = r[entity_col]
        val = r[value_col]
        
        current_ema = entity_emas.get(entity, 55.6)
        ema_values.append(current_ema)

        # Update EMA AFTER recording current match value (past-only)
        if val is not None and not np.isnan(val):
            entity_emas[entity] = alpha * val + (1.0 - alpha) * current_ema

    return pl.Series(f"{prefix}_ema", ema_values)


def build_shared_ebasket_v2_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds shared V2 points-based feature vectors for eBasketball matches.
    """
    if df.is_empty():
        return df

    work_df = df.sort("startedAt")
    
    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"
    home_ht_col = "home.goalsHT" if "home.goalsHT" in work_df.columns else "ht_home_score"
    away_ht_col = "away.goalsHT" if "away.goalsHT" in work_df.columns else "ht_away_score"

    # 1. Prior Match Count & Reliability Flags
    work_df = work_df.with_columns(
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("player_prior_match_count")
    )
    work_df = work_df.with_columns([
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_5"),
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_10"),
    ])

    # 2. Rolling Points Scored & Conceded (Windows 5 & 10)
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col=home_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="home_scored"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col=away_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="home_conceded"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col=away_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="away_scored"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col=home_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="away_conceded"
    )

    # 3. EMA Decay Features (alpha=0.30)
    home_scored_ema = compute_ema_features(work_df, entity_col="home_player", value_col=home_score_col, time_col="startedAt", alpha=0.30, prefix="home_scored")
    home_conceded_ema = compute_ema_features(work_df, entity_col="home_player", value_col=away_score_col, time_col="startedAt", alpha=0.30, prefix="home_conceded")
    away_scored_ema = compute_ema_features(work_df, entity_col="away_player", value_col=away_score_col, time_col="startedAt", alpha=0.30, prefix="away_scored")
    away_conceded_ema = compute_ema_features(work_df, entity_col="away_player", value_col=home_score_col, time_col="startedAt", alpha=0.30, prefix="away_conceded")

    work_df = work_df.with_columns([
        home_scored_ema.alias("home_scored_ema"),
        home_conceded_ema.alias("home_conceded_ema"),
        away_scored_ema.alias("away_scored_ema"),
        away_conceded_ema.alias("away_conceded_ema"),
    ])

    # 4. H2H Matchup Interaction Ratings (Offense vs Defense Differentials)
    work_df = work_df.with_columns([
        (pl.col("home_scored_ema") - pl.col("away_conceded_ema")).alias("matchup_home_offense_edge"),
        (pl.col("away_scored_ema") - pl.col("home_conceded_ema")).alias("matchup_away_offense_edge"),
        (
            (pl.col("home_scored_ema") - pl.col("away_conceded_ema")) -
            (pl.col("away_scored_ema") - pl.col("home_conceded_ema"))
        ).alias("matchup_net_rating_diff"),
        (pl.col("home_scored_ema") + pl.col("away_scored_ema")).alias("expected_total_points_v2"),
    ])

    # 5. Pace Indicators (First-Half vs Total Points Ratio)
    if home_ht_col in work_df.columns and away_ht_col in work_df.columns:
        ht_pts_expr = (pl.col(home_ht_col).fill_null(0) + pl.col(away_ht_col).fill_null(0))
        ft_pts_expr = (pl.col(home_score_col).fill_null(55.6) + pl.col(away_score_col).fill_null(55.6))
        pace_ratio_expr = (ht_pts_expr / pl.when(ft_pts_expr == 0).then(111.2).otherwise(ft_pts_expr)).alias("raw_pace_ratio")
        work_df = work_df.with_columns(pace_ratio_expr)
        
        work_df = compute_rolling_features(
            work_df, entity_col="league", value_col="raw_pace_ratio", time_col="startedAt", window_sizes=[10], prefix="league_pace"
        )
        work_df = work_df.with_columns(
            pl.col("league_pace_roll_mean_10").fill_null(0.48).alias("ht_ft_points_ratio_roll")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.48).alias("ht_ft_points_ratio_roll"))

    # 6. Hour of Day (UTC) Feature
    work_df = work_df.with_columns(
        pl.col("startedAt").dt.hour().cast(pl.Int64).alias("hour_of_day_utc")
    )

    # 7. Odds Drift
    open_col = "odds.over_under.over" if "odds.over_under.over" in work_df.columns else "odds_open"
    close_col = "closingOdds.over_under.over" if "closingOdds.over_under.over" in work_df.columns else "odds_close"
    if open_col in work_df.columns and close_col in work_df.columns:
        work_df = add_odds_drift_columns(work_df, open_col=open_col, close_col=close_col, prefix="odds")
    else:
        work_df = work_df.with_columns([
            pl.lit(0.0).alias("odds_drift_abs"),
            pl.lit(0.0).alias("odds_drift_pct"),
        ])

    # 8. Bayesian Rating Trajectory Engine
    home_bayesian = compute_bayesian_ratings_trajectory(
        work_df, entity_col="home_player", score_col=home_score_col, time_col="startedAt",
        default_mu=55.0, default_sigma=15.0, obs_sigma=12.0, prefix="home_bayesian_rating"
    )
    away_bayesian = compute_bayesian_ratings_trajectory(
        work_df, entity_col="away_player", score_col=away_score_col, time_col="startedAt",
        default_mu=55.0, default_sigma=15.0, obs_sigma=12.0, prefix="away_bayesian_rating"
    )

    work_df = work_df.with_columns([
        home_bayesian["home_bayesian_rating_mean"].alias("home_bayesian_rating_mean"),
        home_bayesian["home_bayesian_rating_std"].alias("home_bayesian_rating_std"),
        away_bayesian["away_bayesian_rating_mean"].alias("away_bayesian_rating_mean"),
        away_bayesian["away_bayesian_rating_std"].alias("away_bayesian_rating_std"),
        (home_bayesian["home_bayesian_rating_mean"] - away_bayesian["away_bayesian_rating_mean"]).alias("bayesian_rating_diff"),
    ])

    return work_df
