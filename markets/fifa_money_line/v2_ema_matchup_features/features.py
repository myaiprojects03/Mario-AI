"""
FIFA 1X2 Money Line V2 Feature Engineering Package.
Includes:
- EMA Decay Win/Draw/Loss rates (alpha=0.30)
- Draw-No-Bet (DNB) synthetic probability transformation
- Head-to-Head matchup rating differentials
- Implied probability vs EMA win-rate divergence
"""

from typing import List, Tuple
import polars as pl
import numpy as np

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features
from core.features.bayesian_ratings import compute_bayesian_ratings_trajectory


ML_FEATURE_COLUMNS_V2 = [
    "match_id",
    "is_reliable_5",
    "is_reliable_10",
    "home_win_rate_ema",
    "home_draw_rate_ema",
    "home_loss_rate_ema",
    "away_win_rate_ema",
    "away_draw_rate_ema",
    "away_loss_rate_ema",
    "home_win_rate_roll_10",
    "away_win_rate_roll_10",
    "home_form_streak",
    "away_form_streak",
    "draw_prob_roll_10",
    "dnb_home_prob",
    "dnb_away_prob",
    "h2h_matches_count",
    "h2h_win_rate_a",
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


def compute_ema_rate(
    df: pl.DataFrame, entity_col: str, value_col: str, time_col: str, default_val: float, alpha: float = 0.30, prefix: str = "ema"
) -> pl.Series:
    records = df.select(["match_id", entity_col, time_col, value_col]).to_dicts()
    entity_emas = {}
    ema_values = []

    for r in records:
        entity = r[entity_col]
        val = r[value_col]
        current_ema = entity_emas.get(entity, default_val)
        ema_values.append(current_ema)

        if val is not None and not np.isnan(val):
            entity_emas[entity] = alpha * val + (1.0 - alpha) * current_ema

    return pl.Series(f"{prefix}_ema", ema_values)


def build_fifa_money_line_v2_features(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df

    work_df = df.sort("startedAt")
    home_score_col = "home.goals" if "home.goals" in work_df.columns else "final_home_score"
    away_score_col = "away.goals" if "away.goals" in work_df.columns else "final_away_score"

    work_df = work_df.with_columns([
        (pl.col(home_score_col) > pl.col(away_score_col)).cast(pl.Float64).alias("is_win"),
        (pl.col(home_score_col) == pl.col(away_score_col)).cast(pl.Float64).alias("is_draw"),
        (pl.col(home_score_col) < pl.col(away_score_col)).cast(pl.Float64).alias("is_loss"),
    ])

    work_df = work_df.with_columns(
        (pl.col("match_id").cum_count().over("home_player") - 1).alias("player_prior_match_count")
    )
    work_df = work_df.with_columns([
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_5"),
        (pl.col("player_prior_match_count") >= 3).alias("is_reliable_10"),
    ])

    # EMA Win/Draw/Loss Rates (alpha=0.30)
    home_win_ema = compute_ema_rate(work_df, "home_player", "is_win", "startedAt", default_val=0.40, alpha=0.30, prefix="home_win_rate")
    home_draw_ema = compute_ema_rate(work_df, "home_player", "is_draw", "startedAt", default_val=0.20, alpha=0.30, prefix="home_draw_rate")
    home_loss_ema = compute_ema_rate(work_df, "home_player", "is_loss", "startedAt", default_val=0.40, alpha=0.30, prefix="home_loss_rate")

    away_win_ema = compute_ema_rate(work_df, "away_player", "is_loss", "startedAt", default_val=0.40, alpha=0.30, prefix="away_win_rate")
    away_draw_ema = compute_ema_rate(work_df, "away_player", "is_draw", "startedAt", default_val=0.20, alpha=0.30, prefix="away_draw_rate")
    away_loss_ema = compute_ema_rate(work_df, "away_player", "is_win", "startedAt", default_val=0.40, alpha=0.30, prefix="away_loss_rate")

    work_df = work_df.with_columns([
        home_win_ema.alias("home_win_rate_ema"),
        home_draw_ema.alias("home_draw_rate_ema"),
        home_loss_ema.alias("home_loss_rate_ema"),
        away_win_ema.alias("away_win_rate_ema"),
        away_draw_ema.alias("away_draw_rate_ema"),
        away_loss_ema.alias("away_loss_rate_ema"),
    ])

    # Standard rolling 10-match for reference
    work_df = compute_rolling_features(work_df, "home_player", "is_win", "startedAt", [10], "home_win")
    work_df = compute_rolling_features(work_df, "away_player", "is_loss", "startedAt", [10], "away_win")

    work_df = work_df.with_columns([
        pl.col("home_win_roll_mean_10").fill_null(0.40).alias("home_win_rate_roll_10"),
        pl.col("away_win_roll_mean_10").fill_null(0.40).alias("away_win_rate_roll_10"),
        pl.col("home_draw_rate_ema").alias("draw_prob_roll_10"),
    ])

    # Draw-No-Bet (DNB) Synthetic Probability Transformation
    work_df = work_df.with_columns([
        (
            pl.col("home_win_rate_ema") / 
            pl.when(1.0 - pl.col("home_draw_rate_ema") <= 0).then(0.80).otherwise(1.0 - pl.col("home_draw_rate_ema"))
        ).alias("dnb_home_prob"),
        (
            pl.col("away_win_rate_ema") / 
            pl.when(1.0 - pl.col("away_draw_rate_ema") <= 0).then(0.80).otherwise(1.0 - pl.col("away_draw_rate_ema"))
        ).alias("dnb_away_prob"),
    ])

    # Form Streaks
    from markets.fifa_money_line.features import _compute_signed_form_streaks
    home_streaks = _compute_signed_form_streaks(work_df, player_col="home_player", prefix="home")
    away_streaks = _compute_signed_form_streaks(work_df, player_col="away_player", prefix="away")
    work_df = work_df.with_columns([home_streaks, away_streaks])

    # H2H History
    work_df = compute_h2h_features(work_df, "home_player", "away_player", "startedAt", home_score_col, away_score_col, "h2h")

    # Odds & Implied Probabilities
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
        (pl.col("odds_implied_prob") - pl.col("home_win_rate_ema")).alias("implied_vs_ema_divergence")
    )

    # Odds Drift
    open_col = "odds.money_line.home" if "odds.money_line.home" in work_df.columns else "odds_open"
    if open_col in work_df.columns and close_col in work_df.columns:
        work_df = add_odds_drift_columns(work_df, open_col=open_col, close_col=close_col, prefix="odds")
    else:
        work_df = work_df.with_columns([pl.lit(0.0).alias("odds_drift_abs"), pl.lit(0.0).alias("odds_drift_pct")])

    # Bayesian Ratings
    home_bayesian = compute_bayesian_ratings_trajectory(work_df, "home_player", home_score_col, "startedAt", 1.5, 1.0, 1.2, "home_bayesian_rating")
    away_bayesian = compute_bayesian_ratings_trajectory(work_df, "away_player", away_score_col, "startedAt", 1.5, 1.0, 1.2, "away_bayesian_rating")

    work_df = work_df.with_columns([
        home_bayesian["home_bayesian_rating_mean"].alias("home_bayesian_rating_mean"),
        home_bayesian["home_bayesian_rating_std"].alias("home_bayesian_rating_std"),
        away_bayesian["away_bayesian_rating_mean"].alias("away_bayesian_rating_mean"),
        away_bayesian["away_bayesian_rating_std"].alias("away_bayesian_rating_std"),
        (home_bayesian["home_bayesian_rating_mean"] - away_bayesian["away_bayesian_rating_mean"]).alias("bayesian_rating_diff"),
    ])

    for col in ML_FEATURE_COLUMNS_V2:
        if col not in work_df.columns:
            if col.startswith("is_reliable"):
                work_df = work_df.with_columns(pl.lit(False).alias(col))
            elif col.endswith("streak") or col == "h2h_matches_count":
                work_df = work_df.with_columns(pl.lit(0).alias(col))
            else:
                work_df = work_df.with_columns(pl.lit(0.0).alias(col))

    return work_df.select(ML_FEATURE_COLUMNS_V2)
