"""
eBasketball Over/Under Feature Engineering Package.

SCHEMA DOCUMENTATION (CLEAN PRE-MATCH FEATURES, ZERO SYNTHETIC PADDING):
- is_reliable_5 (bool): True if both home & away players have >= 3 prior historical matches.
- is_reliable_10 (bool): True if both home & away players have >= 5 prior historical matches.
- home_scored_roll_mean_5 (float): Past 5-match rolling mean points scored by home player (shift=1).
- home_scored_roll_mean_10 (float): Past 10-match rolling mean points scored by home player (shift=1).
- home_conceded_roll_mean_5 (float): Past 5-match rolling mean points conceded by home player (shift=1).
- home_conceded_roll_mean_10 (float): Past 10-match rolling mean points conceded by home player (shift=1).
- away_scored_roll_mean_5 (float): Past 5-match rolling mean points scored by away player (shift=1).
- away_scored_roll_mean_10 (float): Past 10-match rolling mean points scored by away player (shift=1).
- away_conceded_roll_mean_5 (float): Past 5-match rolling mean points conceded by away player (shift=1).
- away_conceded_roll_mean_10 (float): Past 10-match rolling mean points conceded by away player (shift=1).
- expected_total_points_5 (float): Sum of 5-match expected points (home_scored_5 + away_scored_5).
- expected_total_points_10 (float): Sum of 10-match expected points (home_scored_10 + away_scored_10).
- expected_total_conceded_10 (float): Sum of 10-match expected points conceded (home_conceded_10 + away_conceded_10).
- blended_projected_points_10 (float): Balanced projection (expected_scored_10 + expected_conceded_10) / 2.0.
- ou_line_value (float): Pre-match open total points line offered (odds.over_under.line).
- ou_line_diff_10 (float): Projected total points minus target line (blended_projected_points_10 - ou_line_value).
- home_total_pts_std_10 (float): Rolling standard deviation of total match points in home player's games.
- away_total_pts_std_10 (float): Rolling standard deviation of total match points in away player's games.
- odds_implied_prob_over (float): Implied probability from open Over odds (1.0 / odds.over_under.over).
- odds_implied_prob_under (float): Implied probability from open Under odds (1.0 / odds.over_under.under).
- market_vig (float): Bookmaker total overround vigorish.
- implied_prob_ratio_over (float): De-vigged normalized pre-match Over implied probability.
- home_bayesian_rating_mean (float): Bayesian rating mean for home player (past-only).
- home_bayesian_rating_std (float): Bayesian rating standard deviation for home player.
- away_bayesian_rating_mean (float): Bayesian rating mean for away player (past-only).
- away_bayesian_rating_std (float): Bayesian rating standard deviation for away player.
- bayesian_total_points (float): Sum of Bayesian expected scoring (home + away).
- bayesian_line_diff (float): Bayesian total points minus target line (bayesian_total_points - ou_line_value).
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_mean_total_score (float): Average total points in previous head-to-head encounters.
- hour_of_day_utc (float): Hour of match kickoff in UTC.
"""

from typing import List
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.head_to_head import compute_h2h_features
from core.features.bayesian_ratings import compute_bayesian_ratings_trajectory


EBASKET_OU_FEATURE_COLUMNS = [
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
    "expected_total_points_5",
    "expected_total_points_10",
    "expected_total_conceded_10",
    "blended_projected_points_10",
    "ou_line_value",
    "ou_line_diff_10",
    "home_total_pts_std_10",
    "away_total_pts_std_10",
    "odds_implied_prob_over",
    "odds_implied_prob_under",
    "market_vig",
    "implied_prob_ratio_over",
    "home_bayesian_rating_mean",
    "home_bayesian_rating_std",
    "away_bayesian_rating_mean",
    "away_bayesian_rating_std",
    "bayesian_total_points",
    "bayesian_line_diff",
    "h2h_matches_count",
    "h2h_mean_total_score",
    "hour_of_day_utc",
]


def build_ebasket_ou_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds clean, leakage-free eBasketball Over/Under feature dataframe keyed by match_id.
    Point-in-time past-only (shift=1), zero closing odds leakage, zero odds drift, zero synthetic padding.
    """
    if df.is_empty():
        return df

    # Deduplicate and sort chronologically
    work_df = df.unique(subset=["match_id"]).sort("startedAt") if "match_id" in df.columns else df.sort("startedAt")

    # Map match_id from _id if missing
    if "match_id" not in work_df.columns and "_id" in work_df.columns:
        work_df = work_df.with_columns(pl.col("_id").alias("match_id"))

    # Map player names
    if "home.name" in work_df.columns and "home_player" not in work_df.columns:
        work_df = work_df.with_columns(pl.col("home.name").alias("home_player"))
    if "away.name" in work_df.columns and "away_player" not in work_df.columns:
        work_df = work_df.with_columns(pl.col("away.name").alias("away_player"))

    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"

    # Compute match total points for volatility calculations
    work_df = work_df.with_columns([
        (pl.col(home_score_col) + pl.col(away_score_col)).alias("match_total_points")
    ])

    # 1. Prior Match Count & Reliability Flags
    work_df = work_df.with_columns([
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("home_prior_count"),
        (pl.col("match_id").cum_count().over("away_player") - 1).alias("away_prior_count"),
    ])
    work_df = work_df.with_columns([
        ((pl.col("home_prior_count") >= 3) & (pl.col("away_prior_count") >= 3)).cast(pl.Float64).alias("is_reliable_5"),
        ((pl.col("home_prior_count") >= 5) & (pl.col("away_prior_count") >= 5)).cast(pl.Float64).alias("is_reliable_10"),
    ])

    # 2. Rolling Points Scored and Conceded (past-only shift=1, null/NaN if insufficient matches)
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

    # Rolling total match points standard deviation (pace volatility)
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col="match_total_points", time_col="startedAt", window_sizes=[10], prefix="home_tot"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col="match_total_points", time_col="startedAt", window_sizes=[10], prefix="away_tot"
    )

    work_df = work_df.with_columns([
        pl.col("home_scored_roll_mean_5").alias("home_scored_roll_mean_5"),
        pl.col("home_scored_roll_mean_10").alias("home_scored_roll_mean_10"),
        pl.col("home_conceded_roll_mean_5").alias("home_conceded_roll_mean_5"),
        pl.col("home_conceded_roll_mean_10").alias("home_conceded_roll_mean_10"),
        pl.col("away_scored_roll_mean_5").alias("away_scored_roll_mean_5"),
        pl.col("away_scored_roll_mean_10").alias("away_scored_roll_mean_10"),
        pl.col("away_conceded_roll_mean_5").alias("away_conceded_roll_mean_5"),
        pl.col("away_conceded_roll_mean_10").alias("away_conceded_roll_mean_10"),
        pl.col("home_tot_roll_std_10").alias("home_total_pts_std_10"),
        pl.col("away_tot_roll_std_10").alias("away_total_pts_std_10"),
    ])

    # 3. Aggregated Expected Total Points Projections
    work_df = work_df.with_columns([
        (pl.col("home_scored_roll_mean_5") + pl.col("away_scored_roll_mean_5")).alias("expected_total_points_5"),
        (pl.col("home_scored_roll_mean_10") + pl.col("away_scored_roll_mean_10")).alias("expected_total_points_10"),
        (pl.col("home_conceded_roll_mean_10") + pl.col("away_conceded_roll_mean_10")).alias("expected_total_conceded_10"),
    ])
    work_df = work_df.with_columns([
        ((pl.col("expected_total_points_10") + pl.col("expected_total_conceded_10")) / 2.0).alias("blended_projected_points_10")
    ])

    # 4. Target O/U Line Differentials
    line_col = "odds.over_under.line" if "odds.over_under.line" in work_df.columns else "ou_line"
    if line_col in work_df.columns:
        work_df = work_df.with_columns([
            pl.col(line_col).cast(pl.Float64).alias("ou_line_value")
        ])
    else:
        work_df = work_df.with_columns(pl.lit(None).cast(pl.Float64).alias("ou_line_value"))

    work_df = work_df.with_columns([
        (pl.col("blended_projected_points_10") - pl.col("ou_line_value")).alias("ou_line_diff_10")
    ])

    # 5. Pre-Match O/U Odds Implied Probabilities (NO closing odds, NO drift)
    ou_over_col = "odds.over_under.over" if "odds.over_under.over" in work_df.columns else "ou_over"
    ou_under_col = "odds.over_under.under" if "odds.over_under.under" in work_df.columns else "ou_under"

    if ou_over_col in work_df.columns and ou_under_col in work_df.columns:
        work_df = work_df.with_columns([
            pl.when(pl.col(ou_over_col) > 1.0).then(1.0 / pl.col(ou_over_col)).otherwise(None).alias("odds_implied_prob_over"),
            pl.when(pl.col(ou_under_col) > 1.0).then(1.0 / pl.col(ou_under_col)).otherwise(None).alias("odds_implied_prob_under"),
        ])
    else:
        work_df = work_df.with_columns([
            pl.lit(None).cast(pl.Float64).alias("odds_implied_prob_over"),
            pl.lit(None).cast(pl.Float64).alias("odds_implied_prob_under"),
        ])

    work_df = work_df.with_columns([
        (pl.col("odds_implied_prob_over") + pl.col("odds_implied_prob_under") - 1.0).alias("market_vig"),
        (pl.col("odds_implied_prob_over") / (pl.col("odds_implied_prob_over") + pl.col("odds_implied_prob_under"))).alias("implied_prob_ratio_over"),
    ])

    # 6. Bayesian Continuous Scoring Engine (Prior belief before current match)
    home_bayesian = compute_bayesian_ratings_trajectory(
        work_df, entity_col="home_player", score_col=home_score_col, time_col="startedAt",
        default_mu=55.0, default_sigma=10.0, obs_sigma=10.0, prefix="home_bayesian_rating"
    )
    away_bayesian = compute_bayesian_ratings_trajectory(
        work_df, entity_col="away_player", score_col=away_score_col, time_col="startedAt",
        default_mu=55.0, default_sigma=10.0, obs_sigma=10.0, prefix="away_bayesian_rating"
    )

    work_df = work_df.with_columns([
        home_bayesian["home_bayesian_rating_mean"].alias("home_bayesian_rating_mean"),
        home_bayesian["home_bayesian_rating_std"].alias("home_bayesian_rating_std"),
        away_bayesian["away_bayesian_rating_mean"].alias("away_bayesian_rating_mean"),
        away_bayesian["away_bayesian_rating_std"].alias("away_bayesian_rating_std"),
        (home_bayesian["home_bayesian_rating_mean"] + away_bayesian["away_bayesian_rating_mean"]).alias("bayesian_total_points"),
    ])
    work_df = work_df.with_columns([
        (pl.col("bayesian_total_points") - pl.col("ou_line_value")).alias("bayesian_line_diff")
    ])

    # 7. Head-to-Head History
    work_df = compute_h2h_features(
        work_df,
        entity_a_col="home_player",
        entity_b_col="away_player",
        time_col="startedAt",
        score_a_col=home_score_col,
        score_b_col=away_score_col,
        prefix="h2h",
    )
    work_df = work_df.with_columns([
        pl.col("h2h_mean_total_score").alias("h2h_mean_total_score")
    ])

    # 8. Hour of Day UTC
    if "startedAt" in work_df.columns:
        work_df = work_df.with_columns(
            pl.col("startedAt").str.strptime(pl.Datetime, "%+").dt.hour().cast(pl.Float64).alias("hour_of_day_utc")
        )
    else:
        work_df = work_df.with_columns(pl.lit(None).cast(pl.Float64).alias("hour_of_day_utc"))

    meta_cols = [c for c in [
        "match_id", "_id", "startedAt", "league", "home_player", "away_player",
        home_score_col, away_score_col, ou_over_col, ou_under_col, line_col,
    ] if c in work_df.columns]

    return work_df.select(EBASKET_OU_FEATURE_COLUMNS + [c for c in meta_cols if c not in EBASKET_OU_FEATURE_COLUMNS])
