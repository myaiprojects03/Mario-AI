"""
FIFA Asian Handicap Feature Engineering Package.

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
- expected_home_margin (float): Rolling expected home margin (home_scored_10 - away_scored_10).
- handicap_line_value (float): Asian handicap line value offered (e.g. -0.5, -1.0, +0.5, +1.25).
- normalized_adjusted_margin (float): Handicap-adjusted expected margin (expected_home_margin + handicap_line_value).
- h2h_matches_count (int): Count of previous head-to-head encounters between players.
- h2h_mean_combined_goals (float): Average total goals scored in previous H2H encounters.
- ht_ft_goal_ratio_league (float): League-segmented first-half to full-time goal ratio.
- odds_implied_prob (float): Implied probability derived from odds_close (1 / odds_close).
- implied_vs_hist_divergence (float): Implied probability minus historical hit rate.
- odds_drift_abs (float): Absolute closing minus opening odds drift.
- odds_drift_pct (float): Percentage closing minus opening odds drift.
"""

from typing import List
import polars as pl

from markets._shared.fifa_goals_features import build_shared_fifa_goals_features


AH_FEATURE_COLUMNS = [
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
    "home_net_gd_10",
    "away_net_gd_10",
    "net_gd_diff_10",
    "net_gd_margin_vs_line",
    "handicap_line_value",
    "ml_implied_prob_home",
    "ml_implied_prob_away",
    "ml_implied_diff",
    "ah_odds_implied_prob",
    "cross_market_divergence",
    "h2h_matches_count",
    "h2h_mean_combined_goals",
    "ht_ft_goal_ratio_league",
]


def build_fifa_asian_handicap_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Builds clean, re-engineered FIFA Asian Handicap feature dataframe.
    Point-in-time past-only, zero closing odds leakage, zero synthetic padding.
    Includes Net Goal Differential (GD) and Cross-Market Moneyline Arbitrage.
    """
    if df.is_empty():
        return df

    from core.features.rolling import compute_rolling_features
    from core.features.head_to_head import compute_h2h_features

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

    # 3. Net Goal Differential Features (Offensive vs Defensive Balance)
    work_df = work_df.with_columns([
        (pl.col("home_scored_roll_mean_10") - pl.col("home_conceded_roll_mean_10")).alias("home_net_gd_10"),
        (pl.col("away_scored_roll_mean_10") - pl.col("away_conceded_roll_mean_10")).alias("away_net_gd_10"),
    ])
    work_df = work_df.with_columns([
        (pl.col("home_net_gd_10") - pl.col("away_net_gd_10")).alias("net_gd_diff_10")
    ])

    # 4. Asian Handicap Line & Net GD Relative to Line
    ah_line_col = "odds.asian_handicap.line" if "odds.asian_handicap.line" in work_df.columns else ("handicap_line_value" if "handicap_line_value" in work_df.columns else "line_value")
    work_df = work_df.with_columns(
        pl.col(ah_line_col).cast(pl.Float64).alias("handicap_line_value")
    )
    work_df = work_df.with_columns(
        (pl.col("net_gd_diff_10") + pl.col("handicap_line_value")).alias("net_gd_margin_vs_line")
    )

    # 5. Cross-Market Moneyline Arbitrage Features
    ml_home_col = "odds.money_line.home" if "odds.money_line.home" in work_df.columns else "ml_home"
    ml_away_col = "odds.money_line.away" if "odds.money_line.away" in work_df.columns else "ml_away"
    ah_odds_col = "odds.asian_handicap.home" if "odds.asian_handicap.home" in work_df.columns else ("ah_odds_home" if "ah_odds_home" in work_df.columns else "odds_home")

    if ml_home_col in work_df.columns and ml_away_col in work_df.columns:
        work_df = work_df.with_columns([
            pl.when(pl.col(ml_home_col) > 1.0).then(1.0 / pl.col(ml_home_col)).otherwise(None).alias("ml_implied_prob_home"),
            pl.when(pl.col(ml_away_col) > 1.0).then(1.0 / pl.col(ml_away_col)).otherwise(None).alias("ml_implied_prob_away"),
            pl.when(pl.col(ah_odds_col) > 1.0).then(1.0 / pl.col(ah_odds_col)).otherwise(None).alias("ah_odds_implied_prob"),
        ])
        work_df = work_df.with_columns([
            (pl.col("ml_implied_prob_home") - pl.col("ml_implied_prob_away")).alias("ml_implied_diff")
        ])
        work_df = work_df.with_columns([
            (pl.col("ml_implied_diff") - (pl.col("ah_odds_implied_prob") - 0.50)).alias("cross_market_divergence")
        ])
    else:
        work_df = work_df.with_columns([
            pl.lit(None).cast(pl.Float64).alias("ml_implied_prob_home"),
            pl.lit(None).cast(pl.Float64).alias("ml_implied_prob_away"),
            pl.lit(None).cast(pl.Float64).alias("ml_implied_diff"),
            pl.when(pl.col(ah_odds_col) > 1.0).then(1.0 / pl.col(ah_odds_col)).otherwise(None).alias("ah_odds_implied_prob"),
            pl.lit(None).cast(pl.Float64).alias("cross_market_divergence"),
        ])

    # 6. League HT/FT Goal Ratio
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
    work_df = work_df.with_columns(
        pl.col("h2h_mean_total_score").alias("h2h_mean_combined_goals")
    )

    # Metadata & target columns for downstream settlement & evaluation
    meta_cols = [c for c in [
        "match_id", "_id", "startedAt", "league", "home_player", "away_player",
        home_score_col, away_score_col, ah_line_col, ah_odds_col,
        "odds.asian_handicap.away", ml_home_col, ml_away_col
    ] if c in work_df.columns]

    return work_df.select(AH_FEATURE_COLUMNS + [c for c in meta_cols if c not in AH_FEATURE_COLUMNS])


