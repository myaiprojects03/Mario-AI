"""
eBasketball Money Line Feature Engineering Package.

SCHEMA DOCUMENTATION (CLEAN PRE-MATCH FEATURES, ZERO SYNTHETIC PADDING):
- is_reliable_5 (bool): True if both home & away players have >= 3 prior historical matches.
- is_reliable_10 (bool): True if both home & away players have >= 5 prior historical matches.
- home_win_rate_roll_5 (float): Past 5-match rolling win rate for home player (past-only shift=1).
- home_win_rate_roll_10 (float): Past 10-match rolling win rate for home player (past-only shift=1).
- away_win_rate_roll_5 (float): Past 5-match rolling win rate for away player (past-only shift=1).
- away_win_rate_roll_10 (float): Past 10-match rolling win rate for away player (past-only shift=1).
- win_rate_diff_10 (float): Difference in 10-match win rates (home minus away).
- home_points_scored_roll_10 (float): Past 10-match rolling points scored by home player (shift=1).
- home_points_conceded_roll_10 (float): Past 10-match rolling points conceded by home player (shift=1).
- away_points_scored_roll_10 (float): Past 10-match rolling points scored by away player (shift=1).
- away_points_conceded_roll_10 (float): Past 10-match rolling points conceded by away player (shift=1).
- home_net_point_diff_10 (float): Rolling net point differential for home player (scored - conceded).
- away_net_point_diff_10 (float): Rolling net point differential for away player (scored - conceded).
- net_point_diff_delta_10 (float): Relative net point efficiency (home_net_point_diff_10 - away_net_point_diff_10).
- home_form_streak (float): Past-only signed win/loss streak for home player (+N wins, -N losses, 0 start).
- away_form_streak (float): Past-only signed win/loss streak for away player (+N wins, -N losses, 0 start).
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_win_rate_a (float): Home player's win rate in previous head-to-head encounters.
- h2h_mean_point_diff (float): Average point margin in previous head-to-head encounters.
- odds_implied_prob_home (float): Implied win probability from pre-match open money line odds (1.0 / odds.money_line.home).
- odds_implied_prob_away (float): Implied win probability from pre-match open money line odds (1.0 / odds.money_line.away).
- market_vig (float): Bookmaker total overround vigorish (implied_h + implied_a - 1.0).
- implied_prob_ratio (float): De-vigged normalized pre-match home implied probability.
- implied_vs_hist_divergence (float): Pre-match implied win probability minus historical win rate.
- home_bayesian_rating_mean (float): Bayesian rating mean for home player (past-only).
- home_bayesian_rating_std (float): Bayesian rating standard deviation for home player.
- away_bayesian_rating_mean (float): Bayesian rating mean for away player (past-only).
- away_bayesian_rating_std (float): Bayesian rating standard deviation for away player.
- bayesian_rating_diff (float): Difference in Bayesian skill ratings (home minus away).
- hour_of_day_utc (int): Hour of match kickoff in UTC.
"""

from typing import List
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.head_to_head import compute_h2h_features
from core.features.bayesian_ratings import compute_bayesian_ratings_trajectory


EBASKET_ML_FEATURE_COLUMNS = [
    "is_reliable_5",
    "is_reliable_10",
    "home_win_rate_roll_5",
    "home_win_rate_roll_10",
    "away_win_rate_roll_5",
    "away_win_rate_roll_10",
    "win_rate_diff_10",
    "home_points_scored_roll_10",
    "home_points_conceded_roll_10",
    "away_points_scored_roll_10",
    "away_points_conceded_roll_10",
    "home_net_point_diff_10",
    "away_net_point_diff_10",
    "net_point_diff_delta_10",
    "home_form_streak",
    "away_form_streak",
    "h2h_matches_count",
    "h2h_win_rate_a",
    "h2h_mean_point_diff",
    "odds_implied_prob_home",
    "odds_implied_prob_away",
    "market_vig",
    "implied_prob_ratio",
    "implied_vs_hist_divergence",
    "home_bayesian_rating_mean",
    "home_bayesian_rating_std",
    "away_bayesian_rating_mean",
    "away_bayesian_rating_std",
    "bayesian_rating_diff",
    "hour_of_day_utc",
]


def _compute_signed_streaks_fast(df: pl.DataFrame, player_col: str, prefix: str) -> pl.Series:
    """
    Computes past-only signed streak length for a player (+N for win streak, -N for loss streak, 0 for start).
    Strictly excludes current match's own outcome.
    """
    players = df[player_col].to_list()
    is_wins = df["is_win"].to_list()
    is_losses = df["is_loss"].to_list()

    player_streaks = {}
    streak_values = []

    for i in range(len(players)):
        p = players[i]
        curr = player_streaks.get(p, 0)
        streak_values.append(float(curr))

        w = is_wins[i]
        l = is_losses[i]
        if w == 1.0:
            player_streaks[p] = curr + 1 if curr > 0 else 1
        elif l == 1.0:
            player_streaks[p] = curr - 1 if curr < 0 else -1
        else:
            player_streaks[p] = 0

    return pl.Series(f"{prefix}_form_streak", streak_values)


def build_ebasket_money_line_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds clean, leakage-free eBasketball Money Line feature dataframe keyed by match_id.
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

    # 1. Match Outcome Indicators (from home player's perspective)
    work_df = work_df.with_columns([
        (pl.col(home_score_col) > pl.col(away_score_col)).cast(pl.Float64).alias("is_win"),
        (pl.col(home_score_col) < pl.col(away_score_col)).cast(pl.Float64).alias("is_loss"),
    ])

    # 2. Prior Match Count & Reliability Flags
    work_df = work_df.with_columns([
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("home_prior_count"),
        (pl.col("match_id").cum_count().over("away_player") - 1).alias("away_prior_count"),
    ])
    work_df = work_df.with_columns([
        ((pl.col("home_prior_count") >= 3) & (pl.col("away_prior_count") >= 3)).cast(pl.Float64).alias("is_reliable_5"),
        ((pl.col("home_prior_count") >= 5) & (pl.col("away_prior_count") >= 5)).cast(pl.Float64).alias("is_reliable_10"),
    ])

    # 3. Rolling Win Rates (past-only shift=1, null/NaN if insufficient matches)
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col="is_win", time_col="startedAt", window_sizes=[5, 10], prefix="home_win"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col="is_loss", time_col="startedAt", window_sizes=[5, 10], prefix="away_win"
    )
    work_df = work_df.with_columns([
        pl.col("home_win_roll_mean_5").alias("home_win_rate_roll_5"),
        pl.col("home_win_roll_mean_10").alias("home_win_rate_roll_10"),
        pl.col("away_win_roll_mean_5").alias("away_win_rate_roll_5"),
        pl.col("away_win_roll_mean_10").alias("away_win_rate_roll_10"),
    ])
    work_df = work_df.with_columns(
        (pl.col("home_win_rate_roll_10") - pl.col("away_win_rate_roll_10")).alias("win_rate_diff_10")
    )

    # 4. Rolling Points Scored and Conceded (past-only shift=1)
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col=home_score_col, time_col="startedAt", window_sizes=[10], prefix="home_scored"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col=away_score_col, time_col="startedAt", window_sizes=[10], prefix="home_conceded"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col=away_score_col, time_col="startedAt", window_sizes=[10], prefix="away_scored"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col=home_score_col, time_col="startedAt", window_sizes=[10], prefix="away_conceded"
    )

    work_df = work_df.with_columns([
        pl.col("home_scored_roll_mean_10").alias("home_points_scored_roll_10"),
        pl.col("home_conceded_roll_mean_10").alias("home_points_conceded_roll_10"),
        pl.col("away_scored_roll_mean_10").alias("away_points_scored_roll_10"),
        pl.col("away_conceded_roll_mean_10").alias("away_points_conceded_roll_10"),
    ])

    # 5. Net Point Differential (Net Efficiency Spread)
    work_df = work_df.with_columns([
        (pl.col("home_points_scored_roll_10") - pl.col("home_points_conceded_roll_10")).alias("home_net_point_diff_10"),
        (pl.col("away_points_scored_roll_10") - pl.col("away_points_conceded_roll_10")).alias("away_net_point_diff_10"),
    ])
    work_df = work_df.with_columns(
        (pl.col("home_net_point_diff_10") - pl.col("away_net_point_diff_10")).alias("net_point_diff_delta_10")
    )

    # 6. Signed Form Streaks (+N wins, -N losses, 0 start)
    home_streaks = _compute_signed_streaks_fast(work_df, player_col="home_player", prefix="home")
    away_streaks = _compute_signed_streaks_fast(work_df, player_col="away_player", prefix="away")
    work_df = work_df.with_columns([home_streaks, away_streaks])

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
        pl.col("h2h_mean_score_diff").alias("h2h_mean_point_diff")
    ])

    # 8. Pre-Match Moneyline Odds Implied Probabilities (NO closing odds, NO drift)
    ml_home_col = "odds.money_line.home" if "odds.money_line.home" in work_df.columns else "ml_home"
    ml_away_col = "odds.money_line.away" if "odds.money_line.away" in work_df.columns else "ml_away"

    if ml_home_col in work_df.columns and ml_away_col in work_df.columns:
        work_df = work_df.with_columns([
            pl.when(pl.col(ml_home_col) > 1.0).then(1.0 / pl.col(ml_home_col)).otherwise(None).alias("odds_implied_prob_home"),
            pl.when(pl.col(ml_away_col) > 1.0).then(1.0 / pl.col(ml_away_col)).otherwise(None).alias("odds_implied_prob_away"),
        ])
    else:
        work_df = work_df.with_columns([
            pl.lit(None).cast(pl.Float64).alias("odds_implied_prob_home"),
            pl.lit(None).cast(pl.Float64).alias("odds_implied_prob_away"),
        ])

    work_df = work_df.with_columns([
        (pl.col("odds_implied_prob_home") + pl.col("odds_implied_prob_away") - 1.0).alias("market_vig"),
        (pl.col("odds_implied_prob_home") / (pl.col("odds_implied_prob_home") + pl.col("odds_implied_prob_away"))).alias("implied_prob_ratio"),
    ])
    work_df = work_df.with_columns(
        (pl.col("implied_prob_ratio") - pl.col("home_win_rate_roll_10")).alias("implied_vs_hist_divergence")
    )

    # 9. Bayesian Rating Trajectory Engine (Prior belief before current match)
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
        (home_bayesian["home_bayesian_rating_mean"] - away_bayesian["away_bayesian_rating_mean"]).alias("bayesian_rating_diff"),
    ])

    # 10. Hour of Day UTC
    if "startedAt" in work_df.columns:
        work_df = work_df.with_columns(
            pl.col("startedAt").str.strptime(pl.Datetime, "%+").dt.hour().cast(pl.Float64).alias("hour_of_day_utc")
        )
    else:
        work_df = work_df.with_columns(pl.lit(None).cast(pl.Float64).alias("hour_of_day_utc"))

    meta_cols = [c for c in [
        "match_id", "_id", "startedAt", "league", "home_player", "away_player",
        home_score_col, away_score_col, ml_home_col, ml_away_col,
    ] if c in work_df.columns]

    return work_df.select(EBASKET_ML_FEATURE_COLUMNS + [c for c in meta_cols if c not in EBASKET_ML_FEATURE_COLUMNS])
