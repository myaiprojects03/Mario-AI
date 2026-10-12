"""
FIFA 1X2 Money Line Feature Engineering Package.

SCHEMA DOCUMENTATION (CLEAN PRE-MATCH FEATURES, ZERO SYNTHETIC PADDING):
- match_id (str): Unique match identifier key.
- is_reliable_5 (bool): True if player has >= 3 prior historical matches for 5-match window.
- is_reliable_10 (bool): True if player has >= 5 prior historical matches for 10-match window.
- home_win_rate_roll_5 (float): Past 5-match rolling win rate for home player (past-only shift=1, null/NaN if insufficient matches).
- home_win_rate_roll_10 (float): Past 10-match rolling win rate for home player (past-only shift=1).
- home_draw_rate_roll_5 (float): Past 5-match rolling draw rate for home player.
- home_draw_rate_roll_10 (float): Past 10-match rolling draw rate for home player.
- home_loss_rate_roll_5 (float): Past 5-match rolling loss rate for home player.
- home_loss_rate_roll_10 (float): Past 10-match rolling loss rate for home player.
- away_win_rate_roll_5 (float): Past 5-match rolling win rate for away player.
- away_win_rate_roll_10 (float): Past 10-match rolling win rate for away player.
- away_draw_rate_roll_5 (float): Past 5-match rolling draw rate for away player.
- away_draw_rate_roll_10 (float): Past 10-match rolling draw rate for away player.
- away_loss_rate_roll_5 (float): Past 5-match rolling loss rate for away player.
- away_loss_rate_roll_10 (float): Past 10-match rolling loss rate for away player.
- home_net_gd_10 (float): Past 10-match rolling net goal differential for home player.
- away_net_gd_10 (float): Past 10-match rolling net goal differential for away player.
- net_gd_diff_10 (float): Difference in net goal differential between home and away players.
- home_win_rate_home_games (float): Rolling home win rate for home player.
- away_win_rate_away_games (float): Rolling away win rate for away player.
- home_form_streak (int): Current signed win/loss streak for home player (+N for wins, -N for losses, 0 for draw/start).
- away_form_streak (int): Current signed win/loss streak for away player (+N for wins, -N for losses, 0 for draw/start).
- draw_prob_roll_10 (float): Explicit draw probability feature based on 10-match rolling draw rate.
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_win_rate_a (float): Home player's win rate in previous head-to-head encounters.
- odds_implied_prob_home (float): Implied win probability from pre-match open money line odds (1.0 / odds.money_line.home).
- odds_implied_prob_away (float): Implied win probability from pre-match open money line odds (1.0 / odds.money_line.away).
- implied_vs_hist_divergence (float): Pre-match implied probability minus historical win rate.
- home_bayesian_rating_mean / std: TrueSkill/Bayesian rating mean and variance.
- away_bayesian_rating_mean / std: TrueSkill/Bayesian rating mean and variance.
- bayesian_rating_diff: Rating differential between home and away player.
"""

from typing import List, Tuple
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features


ML_FEATURE_COLUMNS = [
    "is_reliable_5",
    "is_reliable_10",
    "home_win_rate_roll_5",
    "home_win_rate_roll_10",
    "home_draw_rate_roll_5",
    "home_draw_rate_roll_10",
    "home_loss_rate_roll_5",
    "home_loss_rate_roll_10",
    "away_win_rate_roll_5",
    "away_win_rate_roll_10",
    "away_draw_rate_roll_5",
    "away_draw_rate_roll_10",
    "away_loss_rate_roll_5",
    "away_loss_rate_roll_10",
    "home_net_gd_10",
    "away_net_gd_10",
    "net_gd_diff_10",
    "home_win_rate_home_games",
    "away_win_rate_away_games",
    "home_form_streak",
    "away_form_streak",
    "draw_prob_roll_10",
    "h2h_matches_count",
    "h2h_win_rate_a",
    "odds_implied_prob_home",
    "odds_implied_prob_away",
    "implied_vs_hist_divergence",
    "home_bayesian_rating_mean",
    "home_bayesian_rating_std",
    "away_bayesian_rating_mean",
    "away_bayesian_rating_std",
    "bayesian_rating_diff",
]


def _compute_signed_form_streaks_fast(df: pl.DataFrame, player_col: str, prefix: str) -> pl.Series:
    """
    Computes past-only signed streak length for a player (+N for win streak, -N for loss streak, 0 for draw/start).
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


def build_fifa_money_line_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds clean FIFA 1X2 Money Line feature dataframe.
    Point-in-time past-only, zero closing odds leakage, zero synthetic padding.
    """
    if df.is_empty():
        return df

    # Deduplicate and sort chronologically
    work_df = df.unique(subset=["match_id"]).sort("startedAt") if "match_id" in df.columns else df.sort("startedAt")

    # Map match_id from _id if missing
    if "match_id" not in work_df.columns and "_id" in work_df.columns:
        work_df = work_df.with_columns(pl.col("_id").alias("match_id"))

    # Map player and team columns if nested or renamed
    if "home.name" in work_df.columns and "home_player" not in work_df.columns:
        work_df = work_df.with_columns(pl.col("home.name").alias("home_player"))
    if "away.name" in work_df.columns and "away_player" not in work_df.columns:
        work_df = work_df.with_columns(pl.col("away.name").alias("away_player"))

    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"

    # 1. Match Outcome Indicators (from home player's perspective)
    work_df = work_df.with_columns([
        (pl.col(home_score_col) > pl.col(away_score_col)).cast(pl.Float64).alias("is_win"),
        (pl.col(home_score_col) == pl.col(away_score_col)).cast(pl.Float64).alias("is_draw"),
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

    # 3. Rolling Win / Draw / Loss Rates per Player (past-only shift=1)
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col="is_win", time_col="startedAt", window_sizes=[5, 10], prefix="home_win")
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col="is_draw", time_col="startedAt", window_sizes=[5, 10], prefix="home_draw")
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col="is_loss", time_col="startedAt", window_sizes=[5, 10], prefix="home_loss")

    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col="is_loss", time_col="startedAt", window_sizes=[5, 10], prefix="away_win")
    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col="is_draw", time_col="startedAt", window_sizes=[5, 10], prefix="away_draw")
    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col="is_win", time_col="startedAt", window_sizes=[5, 10], prefix="away_loss")

    work_df = work_df.with_columns([
        pl.col("home_win_roll_mean_5").alias("home_win_rate_roll_5"),
        pl.col("home_win_roll_mean_10").alias("home_win_rate_roll_10"),
        pl.col("home_draw_roll_mean_5").alias("home_draw_rate_roll_5"),
        pl.col("home_draw_roll_mean_10").alias("home_draw_rate_roll_10"),
        pl.col("home_loss_roll_mean_5").alias("home_loss_rate_roll_5"),
        pl.col("home_loss_roll_mean_10").alias("home_loss_rate_roll_10"),
        pl.col("away_win_roll_mean_5").alias("away_win_rate_roll_5"),
        pl.col("away_win_roll_mean_10").alias("away_win_rate_roll_10"),
        pl.col("away_draw_roll_mean_5").alias("away_draw_rate_roll_5"),
        pl.col("away_draw_roll_mean_10").alias("away_draw_rate_roll_10"),
        pl.col("away_loss_roll_mean_5").alias("away_loss_rate_roll_5"),
        pl.col("away_loss_roll_mean_10").alias("away_loss_rate_roll_10"),
    ])

    # 4. Net Goal Differential Features (Net form)
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col=home_score_col, time_col="startedAt", window_sizes=[10], prefix="h_sc")
    work_df = compute_rolling_features(work_df, entity_col="home_player", value_col=away_score_col, time_col="startedAt", window_sizes=[10], prefix="h_cc")
    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col=away_score_col, time_col="startedAt", window_sizes=[10], prefix="a_sc")
    work_df = compute_rolling_features(work_df, entity_col="away_player", value_col=home_score_col, time_col="startedAt", window_sizes=[10], prefix="a_cc")

    work_df = work_df.with_columns([
        (pl.col("h_sc_roll_mean_10") - pl.col("h_cc_roll_mean_10")).alias("home_net_gd_10"),
        (pl.col("a_sc_roll_mean_10") - pl.col("a_cc_roll_mean_10")).alias("away_net_gd_10"),
    ])
    work_df = work_df.with_columns([
        (pl.col("home_net_gd_10") - pl.col("away_net_gd_10")).alias("net_gd_diff_10")
    ])

    # 5. Home vs Away Tendencies
    work_df = work_df.with_columns([
        pl.col("home_win_rate_roll_10").alias("home_win_rate_home_games"),
        pl.col("away_win_rate_roll_10").alias("away_win_rate_away_games"),
    ])

    # 6. Signed Form Streaks (+N wins, -N losses, 0 draw/start)
    home_streaks = _compute_signed_form_streaks_fast(work_df, player_col="home_player", prefix="home")
    away_streaks = _compute_signed_form_streaks_fast(work_df, player_col="away_player", prefix="away")
    work_df = work_df.with_columns([home_streaks, away_streaks])

    # 7. Explicit Draw Probability Feature
    work_df = work_df.with_columns(
        pl.col("home_draw_rate_roll_10").alias("draw_prob_roll_10")
    )

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

    # 9. Pre-Match Moneyline Odds Implied Probabilities
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

    work_df = work_df.with_columns(
        (pl.col("odds_implied_prob_home") - pl.col("home_win_rate_roll_10")).alias("implied_vs_hist_divergence")
    )

    # 10. League HT/FT Goal Ratio
    home_ht_col = "home.goalsHT" if "home.goalsHT" in work_df.columns else "ht_home_score"
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

    # 11. Bayesian Rating Trajectory Engine
    from core.features.bayesian_ratings import compute_bayesian_ratings_trajectory
    home_bayesian = compute_bayesian_ratings_trajectory(
        work_df, entity_col="home_player", score_col=home_score_col, time_col="startedAt",
        default_mu=1.5, default_sigma=1.0, obs_sigma=1.2, prefix="home_bayesian_rating"
    )
    away_bayesian = compute_bayesian_ratings_trajectory(
        work_df, entity_col="away_player", score_col=away_score_col, time_col="startedAt",
        default_mu=1.5, default_sigma=1.0, obs_sigma=1.2, prefix="away_bayesian_rating"
    )

    work_df = work_df.with_columns([
        home_bayesian["home_bayesian_rating_mean"].alias("home_bayesian_rating_mean"),
        home_bayesian["home_bayesian_rating_std"].alias("home_bayesian_rating_std"),
        away_bayesian["away_bayesian_rating_mean"].alias("away_bayesian_rating_mean"),
        away_bayesian["away_bayesian_rating_std"].alias("away_bayesian_rating_std"),
        (home_bayesian["home_bayesian_rating_mean"] - away_bayesian["away_bayesian_rating_mean"]).alias("bayesian_rating_diff"),
    ])

    # Metadata & target columns for downstream settlement & evaluation
    meta_cols = [c for c in [
        "match_id", "_id", "startedAt", "league", "home_player", "away_player",
        home_score_col, away_score_col, ml_home_col, ml_away_col,
        "odds.draw_no_bet.home", "odds.draw_no_bet.away", "odds.money_line.draw"
    ] if c in work_df.columns]

    return work_df.select(ML_FEATURE_COLUMNS + [c for c in meta_cols if c not in ML_FEATURE_COLUMNS])

