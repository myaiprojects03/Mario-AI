from typing import Optional, List
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features


def build_shared_fifa_goals_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds shared goal-based feature vectors for FIFA matches.
    Used as the foundation by both fifa_goals_ou and fifa_asian_handicap markets.
    
    GUARANTEES:
    - Strictly past-only (shift=1) rolling aggregations to prevent data leakage.
    - Adds `is_reliable_5` and `is_reliable_10` boolean flags (True when prior matches >= 3).
    - H2H player-team pairing history.
    - League-segmented HT vs FT goal ratio.
    - Implied probability vs historical hit rate divergence.
    - Absolute and percentage odds drift.
    """
    if df.is_empty():
        return df

    # Standardize column names if needed
    work_df = df.sort("startedAt")
    
    # Ensure home/away score columns exist
    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"
    home_ht_col = "home.goalsHT" if "home.goalsHT" in work_df.columns else "ht_home_score"

    # 1. Rolling Goals Scored & Conceded (Player & Team, Windows 5 & 10)
    # Compute prior match count per player to establish reliability
    work_df = work_df.with_columns(
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("player_prior_match_count")
    )
    
    # Reliability Flags (True if at least 3 prior matches exist)
    work_df = work_df.with_columns([
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_5"),
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_10"),
    ])

    # Rolling goals scored/conceded for home player
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col=home_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="home_scored"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col=away_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="home_conceded"
    )

    # Rolling goals scored/conceded for away player
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col=away_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="away_scored"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col=home_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="away_conceded"
    )

    # Impute baseline priors for first-time matches (0 prior matches)
    roll_cols_to_fill = [
        "home_scored_roll_mean_5", "home_scored_roll_mean_10",
        "home_conceded_roll_mean_5", "home_conceded_roll_mean_10",
        "away_scored_roll_mean_5", "away_scored_roll_mean_10",
        "away_conceded_roll_mean_5", "away_conceded_roll_mean_10",
    ]
    for rcol in roll_cols_to_fill:
        if rcol in work_df.columns:
            work_df = work_df.with_columns(pl.col(rcol).fill_null(2.28))

    # Expected Total Goals from rolling averages (Window 10)
    work_df = work_df.with_columns(
        (
            pl.col("home_scored_roll_mean_10").fill_null(2.28) +
            pl.col("away_scored_roll_mean_10").fill_null(2.28)
        ).alias("expected_total_goals")
    )

    # 2. Head-to-Head History between Player Pairings
    work_df = compute_h2h_features(
        work_df,
        entity_a_col="home_player",
        entity_b_col="away_player",
        time_col="startedAt",
        score_a_col=home_score_col,
        score_b_col=away_score_col,
        prefix="h2h",
    )
    # Rename h2h_mean_total_score to h2h_mean_combined_goals
    if "h2h_mean_total_score" in work_df.columns:
        work_df = work_df.with_columns(
            pl.col("h2h_mean_total_score").alias("h2h_mean_combined_goals")
        )

    # 3. Over/Under Hit Rate by Line Value
    line_col = "odds.over_under.line" if "odds.over_under.line" in work_df.columns else "line_value"
    if line_col in work_df.columns:
        # Check if actual total goals went over line
        total_goals_expr = pl.col(home_score_col) + pl.col(away_score_col)
        work_df = work_df.with_columns(
            (total_goals_expr > pl.col(line_col)).cast(pl.Float64).alias("is_over_hit")
        )
        # Compute rolling past over hit rate per player
        work_df = compute_rolling_features(
            work_df, entity_col="home_player", value_col="is_over_hit", time_col="startedAt", window_sizes=[10], prefix="ou_line"
        )
        work_df = work_df.with_columns(
            pl.col("ou_line_roll_mean_10").fill_null(0.50).alias("ou_line_hit_rate_roll")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.50).alias("ou_line_hit_rate_roll"))

    # 4. First-Half vs Full-Time Goal Ratio by League (League-Segmented)
    if home_ht_col in work_df.columns:
        ht_goals_expr = pl.col(home_ht_col).fill_null(0)
        ft_goals_expr = (pl.col(home_score_col) + pl.col(away_score_col)).fill_null(1)
        ratio_expr = (ht_goals_expr / pl.when(ft_goals_expr == 0).then(1.0).otherwise(ft_goals_expr)).alias("raw_ht_ft_ratio")
        work_df = work_df.with_columns(ratio_expr)
        
        # League-segmented rolling ht/ft ratio
        work_df = compute_rolling_features(
            work_df, entity_col="league", value_col="raw_ht_ft_ratio", time_col="startedAt", window_sizes=[10], prefix="league_ht_ft"
        )
        work_df = work_df.with_columns(
            pl.col("league_ht_ft_roll_mean_10").fill_null(0.42).alias("ht_ft_goal_ratio_league")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.42).alias("ht_ft_goal_ratio_league"))

    # 5. Odds Implied Probability vs Historical Frequency Divergence
    close_col = "closingOdds.over_under.over" if "closingOdds.over_under.over" in work_df.columns else "odds_close"
    if close_col in work_df.columns:
        work_df = work_df.with_columns(
            pl.when(pl.col(close_col).is_not_null() & (pl.col(close_col) > 0))
            .then(1.0 / pl.col(close_col))
            .otherwise(0.50)
            .alias("odds_implied_prob")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.50).alias("odds_implied_prob"))

    work_df = work_df.with_columns(
        (pl.col("odds_implied_prob") - pl.col("ou_line_hit_rate_roll")).alias("implied_vs_hist_divergence")
    )

    # 6. Odds Drift (from core/features/odds_drift.py)
    open_col = "odds.over_under.over" if "odds.over_under.over" in work_df.columns else "odds_open"
    if open_col in work_df.columns and close_col in work_df.columns:
        work_df = add_odds_drift_columns(work_df, open_col=open_col, close_col=close_col, prefix="odds")
    else:
        work_df = work_df.with_columns([
            pl.lit(0.0).alias("odds_drift_abs"),
            pl.lit(0.0).alias("odds_drift_pct"),
        ])

    return work_df
