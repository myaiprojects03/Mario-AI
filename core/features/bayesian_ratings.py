"""
Bayesian Rating Update Engine (Conjugate Normal-Normal Update).

Design Rationale:
Normal-Normal conjugate updates provide a simple, mathematically rigorous, closed-form Bayesian update for continuous scoring rates (goals in FIFA or points in eBasketball).
Unlike custom heuristic ratings, the variance term automatically acts as an adaptive learning rate:
when a player has few matches (sigma_prior is high), new observations quickly adjust their mean;
as match count increases (sigma_prior shrinks), the rating stabilizes, providing robust protection against small-sample noise.

Conjugate Math Formulas:
    Prior: theta ~ N(mu_prior, sigma_prior^2)
    Observation: x_t ~ N(theta, sigma_obs^2)
    Learning Weight: K = sigma_prior^2 / (sigma_prior^2 + sigma_obs^2)
    Posterior Mean: mu_post = mu_prior + K * (x_t - mu_prior)
    Posterior Variance: sigma_post^2 = (1 - K) * sigma_prior^2
"""

from typing import Tuple, Dict, Any, Optional
import numpy as np
import polars as pl
import pandas as pd


def update_bayesian_rating(
    mu_prior: float,
    sigma_prior: float,
    obs_value: float,
    sigma_obs: float,
) -> Tuple[float, float]:
    """
    Computes closed-form Normal-Normal Bayesian conjugate update.

    Args:
        mu_prior: Prior mean belief.
        sigma_prior: Prior standard deviation belief.
        obs_value: Observed scalar score (goals or points).
        sigma_obs: Observation noise standard deviation.

    Returns:
        Tuple[float, float]: (mu_post, sigma_post)
    """
    var_prior = sigma_prior ** 2
    var_obs = sigma_obs ** 2

    # Learning weight K
    K = var_prior / (var_prior + var_obs)

    mu_post = float(mu_prior + K * (obs_value - mu_prior))
    var_post = float((1.0 - K) * var_prior)
    sigma_post = float(np.sqrt(max(var_post, 1e-6)))

    return mu_post, sigma_post


def compute_bayesian_ratings_trajectory(
    df: pl.DataFrame,
    entity_col: str,
    score_col: str,
    time_col: str = "startedAt",
    default_mu: float = 1.5,
    default_sigma: float = 1.0,
    obs_sigma: float = 1.2,
    prefix: str = "bayesian_rating",
) -> pl.DataFrame:
    """
    Replays match history chronologically per entity (player/team) and attaches the PRIOR rating
    (computed strictly BEFORE observing the current match score) to each match.

    Zero-Leakage Guarantee:
        The rating assigned to match t is the prior rating before match t's outcome is observed.

    Args:
        df: Input Polars DataFrame containing match records.
        entity_col: Column name identifying entity (e.g. 'home_player' or 'away_player').
        score_col: Column name identifying entity's scored points/goals (e.g. 'home.goals').
        time_col: Column name identifying match start timestamp.
        default_mu: Prior mean initialization.
        default_sigma: Prior std initialization.
        obs_sigma: Observation noise std.
        prefix: Prefix for generated feature columns.

    Returns:
        pl.DataFrame: DataFrame with '{prefix}_mean' and '{prefix}_std' columns attached.
    """
    if df.is_empty():
        return df.with_columns([
            pl.lit(default_mu).alias(f"{prefix}_mean"),
            pl.lit(default_sigma).alias(f"{prefix}_std"),
        ])

    df_pd = df.to_pandas() if isinstance(df, pl.DataFrame) else df.copy()
    
    # Sort chronologically
    sort_cols = [c for c in [time_col, "match_id"] if c in df_pd.columns]
    if sort_cols:
        df_pd = df_pd.sort_values(by=sort_cols).reset_index(drop=True)

    prior_means = np.full(len(df_pd), default_mu, dtype=float)
    prior_stds = np.full(len(df_pd), default_sigma, dtype=float)

    # In-memory dictionary tracking current (mu, sigma) per entity
    ratings_dict: Dict[str, Tuple[float, float]] = {}

    for idx in range(len(df_pd)):
        entity_id = str(df_pd[entity_col].iloc[idx])
        score_val = df_pd[score_col].iloc[idx]

        # Retrieve prior rating before this match
        curr_mu, curr_sigma = ratings_dict.get(entity_id, (default_mu, default_sigma))
        prior_means[idx] = curr_mu
        prior_stds[idx] = curr_sigma

        # Update rating if score is available
        if pd.notna(score_val):
            post_mu, post_sigma = update_bayesian_rating(
                curr_mu, curr_sigma, float(score_val), obs_sigma
            )
            ratings_dict[entity_id] = (post_mu, post_sigma)

    df_pd[f"{prefix}_mean"] = prior_means
    df_pd[f"{prefix}_std"] = prior_stds

    return pl.from_pandas(df_pd)
