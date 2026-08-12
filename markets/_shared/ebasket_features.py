from typing import Optional, List
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features


def build_shared_ebasket_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds shared points-based feature vectors for eBasketball matches.
    Used as the foundation by both ebasket_ou and ebasket_money_line markets.
    
    GUARANTEES:
    - Strictly past-only (shift=1) rolling aggregations to prevent data leakage.
    - Adds `is_reliable_5` and `is_reliable_10` boolean flags (True when prior matches >= 3).
    - Cold-start fallback value of 55.6 points per team per match (global population average).
    - Pace indicators (first-half vs total points ratio).
    - Historical line accuracy (rolling over-hit rate).
    - Hour-of-day UTC feature (statistically validated via ANOVA).
    - Absolute and percentage odds drift.
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

    # 2. Rolling Points Scored & Conceded (Player & Team, Windows 5 & 10)
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

    # Impute Fallback Priors for Cold-Start (0 prior matches): 55.6 points per team
    roll_cols_to_fill = [
        "home_scored_roll_mean_5", "home_scored_roll_mean_10",
        "home_conceded_roll_mean_5", "home_conceded_roll_mean_10",
        "away_scored_roll_mean_5", "away_scored_roll_mean_10",
        "away_conceded_roll_mean_5", "away_conceded_roll_mean_10",
    ]
    for rcol in roll_cols_to_fill:
        if rcol in work_df.columns:
            work_df = work_df.with_columns(pl.col(rcol).fill_null(55.6))

    # Expected Total Points from rolling averages (Window 10)
    work_df = work_df.with_columns(
        (
            pl.col("home_scored_roll_mean_10").fill_null(55.6) +
            pl.col("away_scored_roll_mean_10").fill_null(55.6)
        ).alias("expected_total_points")
    )

    # 3. Pace Indicators (First-Half vs Total Points Ratio)
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

    # 4. Line Accuracy (Historical Over-Hit Rate for Target Line Value)
    line_col = "odds.over_under.line" if "odds.over_under.line" in work_df.columns else "line_value"
    if line_col in work_df.columns:
        total_pts_expr = pl.col(home_score_col) + pl.col(away_score_col)
        work_df = work_df.with_columns(
            (total_pts_expr > pl.col(line_col)).cast(pl.Float64).alias("is_over_hit")
        )
        work_df = compute_rolling_features(
            work_df, entity_col="home_player", value_col="is_over_hit", time_col="startedAt", window_sizes=[10], prefix="ebasket_line"
        )
        work_df = work_df.with_columns(
            pl.col("ebasket_line_roll_mean_10").fill_null(0.50).alias("ou_line_over_hit_rate_roll")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.50).alias("ou_line_over_hit_rate_roll"))

    # 5. Hour of Day (UTC) Feature (Statistically validated via ANOVA)
    work_df = work_df.with_columns(
        pl.col("startedAt").dt.hour().cast(pl.Int64).alias("hour_of_day_utc")
    )

    # 6. Odds Drift (from core/features/odds_drift.py)
    open_col = "odds.over_under.over" if "odds.over_under.over" in work_df.columns else "odds_open"
    close_col = "closingOdds.over_under.over" if "closingOdds.over_under.over" in work_df.columns else "odds_close"
    if open_col in work_df.columns and close_col in work_df.columns:
        work_df = add_odds_drift_columns(work_df, open_col=open_col, close_col=close_col, prefix="odds")
    else:
        work_df = work_df.with_columns([
            pl.lit(0.0).alias("odds_drift_abs"),
            pl.lit(0.0).alias("odds_drift_pct"),
        ])

    return work_df
