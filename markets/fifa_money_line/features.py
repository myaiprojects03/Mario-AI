"""
FIFA 1X2 Money Line Feature Engineering Package.

SCHEMA DOCUMENTATION:
- match_id (str): Unique match identifier key.
- is_reliable_5 (bool): True if player has >= 3 prior historical matches for 5-match window.
- is_reliable_10 (bool): True if player has >= 3 prior historical matches for 10-match window.
- home_win_rate_roll_5 (float): Past 5-match rolling win rate for home player (fallback: 0.40).
- home_win_rate_roll_10 (float): Past 10-match rolling win rate for home player (fallback: 0.40).
- home_draw_rate_roll_5 (float): Past 5-match rolling draw rate for home player (fallback: 0.20).
- home_draw_rate_roll_10 (float): Past 10-match rolling draw rate for home player (fallback: 0.20).
- home_loss_rate_roll_5 (float): Past 5-match rolling loss rate for home player (fallback: 0.40).
- home_loss_rate_roll_10 (float): Past 10-match rolling loss rate for home player (fallback: 0.40).
- away_win_rate_roll_5 (float): Past 5-match rolling win rate for away player (fallback: 0.40).
- away_win_rate_roll_10 (float): Past 10-match rolling win rate for away player (fallback: 0.40).
- away_draw_rate_roll_5 (float): Past 5-match rolling draw rate for away player (fallback: 0.20).
- away_draw_rate_roll_10 (float): Past 10-match rolling draw rate for away player (fallback: 0.20).
- away_loss_rate_roll_5 (float): Past 5-match rolling loss rate for away player (fallback: 0.40).
- away_loss_rate_roll_10 (float): Past 10-match rolling loss rate for away player (fallback: 0.40).
- home_win_rate_home_games (float): Rolling home win rate specifically in home games for home player.
- away_win_rate_away_games (float): Rolling away win rate specifically in away games for away player.
- home_form_streak (int): Current signed win/loss streak for home player (+N for wins, -N for losses, 0 for draw/start).
- away_form_streak (int): Current signed win/loss streak for away player (+N for wins, -N for losses, 0 for draw/start).
- draw_prob_roll_10 (float): Explicit draw probability feature based on 10-match rolling draw rate.
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_win_rate_a (float): Home player's win rate in previous head-to-head encounters.
- odds_implied_prob (float): Implied win probability from closing money line odds (1 / odds_close).
- implied_vs_hist_divergence (float): Implied probability minus historical win rate (odds_implied_prob - home_win_rate_roll_10).
- odds_drift_abs (float): Absolute closing minus opening money line odds drift.
- odds_drift_pct (float): Percentage closing minus opening money line odds drift.
"""

from typing import List, Tuple
import polars as pl

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features


ML_FEATURE_COLUMNS = [
    "match_id",
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
    "home_win_rate_home_games",
    "away_win_rate_away_games",
    "home_form_streak",
    "away_form_streak",
    "draw_prob_roll_10",
    "h2h_matches_count",
    "h2h_win_rate_a",
    "odds_implied_prob",
    "implied_vs_hist_divergence",
    "odds_drift_abs",
    "odds_drift_pct",
]


def _compute_signed_form_streaks(df: pl.DataFrame, player_col: str, prefix: str) -> pl.Series:
    """
    Computes past-only signed streak length for a player (+N for win streak, -N for loss streak, 0 for draw/start).
    Strictly excludes current match's own outcome.
    """
    records = df.select(["match_id", player_col, "startedAt", "is_win", "is_draw", "is_loss"]).to_dicts()
    
    # Hash table tracking current streak state per player
    player_streaks = {}
    streak_values = []

    for r in records:
        player = r[player_col]
        current_streak = player_streaks.get(player, 0)
        streak_values.append(current_streak)

        # Update streak AFTER recording current match feature value (past-only)
        if r["is_win"] == 1.0:
            player_streaks[player] = current_streak + 1 if current_streak > 0 else 1
        elif r["is_loss"] == 1.0:
            player_streaks[player] = current_streak - 1 if current_streak < 0 else -1
        else:
            player_streaks[player] = 0

    return pl.Series(f"{prefix}_form_streak", streak_values)


def build_fifa_money_line_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds FIFA 1X2 Money Line feature dataframe keyed by match_id.
    """
    if df.is_empty():
        return df

    work_df = df.sort("startedAt")

    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"

    # 1. Match Outcome Indicators (from home player's perspective)
    work_df = work_df.with_columns([
        (pl.col(home_score_col) > pl.col(away_score_col)).cast(pl.Float64).alias("is_win"),
        (pl.col(home_score_col) == pl.col(away_score_col)).cast(pl.Float64).alias("is_draw"),
        (pl.col(home_score_col) < pl.col(away_score_col)).cast(pl.Float64).alias("is_loss"),
    ])

    # 2. Prior Match Count & Reliability Flags
    work_df = work_df.with_columns(
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("player_prior_match_count")
    )
    work_df = work_df.with_columns([
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_5"),
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_10"),
    ])

    # 3. Rolling Win / Draw / Loss Rates per Player (Home & Away, Windows 5 & 10)
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col="is_win", time_col="startedAt", window_sizes=[5, 10], prefix="home_win"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col="is_draw", time_col="startedAt", window_sizes=[5, 10], prefix="home_draw"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="home_player", value_col="is_loss", time_col="startedAt", window_sizes=[5, 10], prefix="home_loss"
    )

    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col="is_loss", time_col="startedAt", window_sizes=[5, 10], prefix="away_win"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col="is_draw", time_col="startedAt", window_sizes=[5, 10], prefix="away_draw"
    )
    work_df = compute_rolling_features(
        work_df, entity_col="away_player", value_col="is_win", time_col="startedAt", window_sizes=[5, 10], prefix="away_loss"
    )

    # Impute Fallback Priors (Cold-Start: 40% Win, 20% Draw, 40% Loss)
    work_df = work_df.with_columns([
        pl.col("home_win_roll_mean_5").fill_null(0.40).alias("home_win_rate_roll_5"),
        pl.col("home_win_roll_mean_10").fill_null(0.40).alias("home_win_rate_roll_10"),
        pl.col("home_draw_roll_mean_5").fill_null(0.20).alias("home_draw_rate_roll_5"),
        pl.col("home_draw_roll_mean_10").fill_null(0.20).alias("home_draw_rate_roll_10"),
        pl.col("home_loss_roll_mean_5").fill_null(0.40).alias("home_loss_rate_roll_5"),
        pl.col("home_loss_roll_mean_10").fill_null(0.40).alias("home_loss_rate_roll_10"),
        pl.col("away_win_roll_mean_5").fill_null(0.40).alias("away_win_rate_roll_5"),
        pl.col("away_win_roll_mean_10").fill_null(0.40).alias("away_win_rate_roll_10"),
        pl.col("away_draw_roll_mean_5").fill_null(0.20).alias("away_draw_rate_roll_5"),
        pl.col("away_draw_roll_mean_10").fill_null(0.20).alias("away_draw_rate_roll_10"),
        pl.col("away_loss_roll_mean_5").fill_null(0.40).alias("away_loss_rate_roll_5"),
        pl.col("away_loss_roll_mean_10").fill_null(0.40).alias("away_loss_rate_roll_10"),
    ])

    # 4. Home vs Away Tendencies
    work_df = work_df.with_columns([
        pl.col("home_win_rate_roll_10").alias("home_win_rate_home_games"),
        pl.col("away_win_rate_roll_10").alias("away_win_rate_away_games"),
    ])

    # 5. Signed Form Streaks (+N wins, -N losses, 0 draw/start)
    home_streaks = _compute_signed_form_streaks(work_df, player_col="home_player", prefix="home")
    away_streaks = _compute_signed_form_streaks(work_df, player_col="away_player", prefix="away")
    work_df = work_df.with_columns([home_streaks, away_streaks])

    # 6. Explicit Draw Probability Feature
    # NOTE: Draw probability feature is unique to FIFA 1X2 Money Line (eBasketball has no draws and must NOT share this feature).
    work_df = work_df.with_columns(
        pl.col("home_draw_rate_roll_10").alias("draw_prob_roll_10")
    )

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

    # 8. Money Line Odds Implied Probability & Divergence
    close_col = "closingOdds.money_line.home" if "closingOdds.money_line.home" in work_df.columns else "odds_close"
    if close_col in work_df.columns:
        work_df = work_df.with_columns(
            pl.when(pl.col(close_col).is_not_null() & (pl.col(close_col) > 0))
            .then(1.0 / pl.col(close_col))
            .otherwise(0.40)
            .alias("odds_implied_prob")
        )
    else:
        work_df = work_df.with_columns(pl.lit(0.40).alias("odds_implied_prob"))

    work_df = work_df.with_columns(
        (pl.col("odds_implied_prob") - pl.col("home_win_rate_roll_10")).alias("implied_vs_hist_divergence")
    )

    # 9. Odds Drift (from core/features/odds_drift.py)
    open_col = "odds.money_line.home" if "odds.money_line.home" in work_df.columns else "odds_open"
    if open_col in work_df.columns and close_col in work_df.columns:
        work_df = add_odds_drift_columns(work_df, open_col=open_col, close_col=close_col, prefix="odds")
    else:
        work_df = work_df.with_columns([
            pl.lit(0.0).alias("odds_drift_abs"),
            pl.lit(0.0).alias("odds_drift_pct"),
        ])

    # Fill any remaining missing feature columns with defaults
    for col in ML_FEATURE_COLUMNS:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            elif col.endswith("streak") or col == "h2h_matches_count":
                work_df = work_df.with_columns(pl.lit(0).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(ML_FEATURE_COLUMNS)
