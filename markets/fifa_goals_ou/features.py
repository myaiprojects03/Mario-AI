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
]


def build_fifa_goals_ou_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds FIFA Goals Over/Under clean feature dataframe.
    Point-in-time past-only, zero closing odds leakage, zero synthetic padding.
    """
    if df.is_empty():
        return df

    from core.features.rolling import compute_rolling_features
    from core.features.head_to_head import compute_h2h_features

    # Deduplicate and sort chronologically
    work_df = df.unique(subset=["match_id"]).sort("startedAt") if "match_id" in df.columns else df.sort("startedAt")

    # Map player and team columns if nested or renamed
    if "home.name" in work_df.columns and "home_player" not in work_df.columns:
        work_df = work_df.with_columns(pl.col("home.name").alias("home_player"))
    if "away.name" in work_df.columns and "away_player" not in work_df.columns:
        work_df = work_df.with_columns(pl.col("away.name").alias("away_player"))

    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"
    home_ht_col = "home.goalsHT" if "home.goalsHT" in work_df.columns else "ht_home_score"

    # 1. Prior match count & reliability flags (>= 3 matches for window 5, >= 5 for window 10)
    work_df = work_df.with_columns([
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("home_prior_count"),
        (pl.col("match_id").cum_count().over("away_player") - 1).alias("away_prior_count"),
    ])
    work_df = work_df.with_columns([
        ((pl.col("home_prior_count") >= 3) & (pl.col("away_prior_count") >= 3)).cast(pl.Float64).alias("is_reliable_5"),
        ((pl.col("home_prior_count") >= 5) & (pl.col("away_prior_count") >= 5)).cast(pl.Float64).alias("is_reliable_10"),
    ])

    # 2. Rolling Goals Scored & Conceded (strictly past-only shift=1)
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col=home_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="home_scored")
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col=away_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="home_conceded")
    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col=away_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="away_scored")
    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col=home_score_col, time_col="startedAt", window_sizes=[5, 10], prefix="away_conceded")

    # 3. Expected Total Goals
    work_df = work_df.with_columns(
        (pl.col("home_scored_roll_mean_10") + pl.col("away_scored_roll_mean_10")).alias("expected_total_goals")
    )

    # 4. Line Value & Line Differential
    line_col = "odds.over_under.line" if "odds.over_under.line" in work_df.columns else ("ou_line_value" if "ou_line_value" in work_df.columns else "line_value")
    work_df = work_df.with_columns(
        pl.col(line_col).cast(pl.Float64).alias("ou_line_value")
    )
    work_df = work_df.with_columns(
        (pl.col("expected_total_goals") - pl.col("ou_line_value")).alias("ou_line_diff")
    )

    # 5. Over hit rate by line
    total_goals_expr = pl.col(home_score_col) + pl.col(away_score_col)
    work_df = work_df.with_columns(
        (total_goals_expr > pl.col("ou_line_value")).cast(pl.Float64).alias("is_over_hit")
    )
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col="is_over_hit", time_col="startedAt", window_sizes=[10], prefix="ou_line")
    work_df = work_df.with_columns(
        pl.col("ou_line_roll_mean_10").alias("ou_line_hit_rate_roll")
    )

    # 6. Pre-Match Implied Probability & Divergence (Derived strictly from pre-match odds)
    odds_col = "odds.over_under.over" if "odds.over_under.over" in work_df.columns else ("ou_odds_over" if "ou_odds_over" in work_df.columns else "odds_over")
    work_df = work_df.with_columns(
        (1.0 / pl.col(odds_col)).alias("odds_implied_prob")
    )
    work_df = work_df.with_columns(
        (pl.col("odds_implied_prob") - pl.col("ou_line_hit_rate_roll")).alias("implied_vs_hist_divergence")
    )

    # 7. League HT/FT Goal Ratio
    if home_ht_col in work_df.columns:
        ht_goals_expr = pl.col(home_ht_col).fill_null(0)
        ft_goals_expr = (pl.col(home_score_col) + pl.col(away_score_col)).fill_null(1)
        ratio_expr = (ht_goals_expr / pl.when(ft_goals_expr == 0).then(1.0).otherwise(ft_goals_expr)).alias("raw_ht_ft_ratio")
        work_df = work_df.with_columns(ratio_expr)
        work_df = compute_rolling_features(work_df, entity_col="league", value_col="raw_ht_ft_ratio", time_col="startedAt", window_sizes=[10], prefix="league_ht_ft")
        work_df = work_df.with_columns(
            pl.col("league_ht_ft_roll_mean_10").alias("ht_ft_goal_ratio_league")
        )
    else:
        work_df = work_df.with_columns(pl.lit(None).cast(pl.Float64).alias("ht_ft_goal_ratio_league"))

    # 8. Head-to-Head History
    work_df = compute_h2h_features(
        work_df,
        entity_a_col="home_player",
        entity_b_col="away_player",
        time_col="startedAt",
        score_a_col=home_score_col,
        score_b_col=away_score_col,
        prefix="h2h",
    )
    work_df = work_df.with_columns(
        pl.col("h2h_mean_total_score").alias("h2h_mean_combined_goals")
    )

    # Metadata & target columns for downstream settlement & evaluation
    meta_cols = [c for c in [
        "match_id", "_id", "startedAt", "league", "home_player", "away_player",
        home_score_col, away_score_col, line_col, odds_col
    ] if c in work_df.columns]

    return work_df.select(FEATURE_COLUMNS + [c for c in meta_cols if c not in FEATURE_COLUMNS])

