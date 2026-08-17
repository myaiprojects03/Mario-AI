"""
Unit tests for core/features/bayesian_ratings.py and anti-leakage reproducibility verification.
"""

import pytest
import numpy as np
import polars as pl
from datetime import datetime, timedelta, timezone

from core.features.bayesian_ratings import (
    update_bayesian_rating,
    compute_bayesian_ratings_trajectory,
)


def test_conjugate_update_math():
    """Verifies exact Normal-Normal conjugate Bayesian update calculation."""
    mu_prior, sigma_prior = 1.5, 1.0
    obs_val, sigma_obs = 3.0, 1.2

    mu_post, sigma_post = update_bayesian_rating(mu_prior, sigma_prior, obs_val, sigma_obs)

    # Expected K = 1.0^2 / (1.0^2 + 1.2^2) = 1.0 / (1.0 + 1.44) = 1.0 / 2.44 ~ 0.409836
    # Expected mu_post = 1.5 + 0.409836 * (3.0 - 1.5) = 1.5 + 0.614754 = 2.114754
    # Expected var_post = (1 - 0.409836) * 1.0 = 0.590164 -> sigma_post ~ 0.768221
    assert pytest.approx(mu_post, abs=1e-4) == 2.11475
    assert pytest.approx(sigma_post, abs=1e-4) == 0.76822
    assert sigma_post < sigma_prior  # Posterior uncertainty MUST decrease after observation


def test_mutate_future_assert_past_unchanged_anti_leakage():
    """
    CRITICAL ANTI-LEAKAGE REPRODUCIBILITY TEST:
    Proves that mutating a FUTURE match outcome (Match #4) leaves the rating
    at a PAST match (Match #3) 100% identical.
    """
    base_time = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    records = [
        {"match_id": "m1", "startedAt": (base_time + timedelta(days=1)).isoformat(), "player": "P1", "goals": 2.0},
        {"match_id": "m2", "startedAt": (base_time + timedelta(days=2)).isoformat(), "player": "P1", "goals": 1.0},
        {"match_id": "m3", "startedAt": (base_time + timedelta(days=3)).isoformat(), "player": "P1", "goals": 3.0},
        {"match_id": "m4", "startedAt": (base_time + timedelta(days=4)).isoformat(), "player": "P1", "goals": 0.0},
        {"match_id": "m5", "startedAt": (base_time + timedelta(days=5)).isoformat(), "player": "P1", "goals": 1.0},
    ]

    df_original = pl.DataFrame(records)

    # 1. Compute original trajectory
    df_res_orig = compute_bayesian_ratings_trajectory(
        df_original,
        entity_col="player",
        score_col="goals",
        time_col="startedAt",
        default_mu=1.5,
        default_sigma=1.0,
        obs_sigma=1.2,
        prefix="rating",
    )

    m3_mean_orig = df_res_orig.filter(pl.col("match_id") == "m3")["rating_mean"][0]
    m3_std_orig = df_res_orig.filter(pl.col("match_id") == "m3")["rating_std"][0]

    # 2. Mutate FUTURE Match #4 score from 0.0 to 999.0
    records_mutated = [r.copy() for r in records]
    records_mutated[3]["goals"] = 999.0  # Extreme future score mutation
    df_mutated = pl.DataFrame(records_mutated)

    # 3. Compute mutated trajectory
    df_res_mut = compute_bayesian_ratings_trajectory(
        df_mutated,
        entity_col="player",
        score_col="goals",
        time_col="startedAt",
        default_mu=1.5,
        default_sigma=1.0,
        obs_sigma=1.2,
        prefix="rating",
    )

    m3_mean_mut = df_res_mut.filter(pl.col("match_id") == "m3")["rating_mean"][0]
    m3_std_mut = df_res_mut.filter(pl.col("match_id") == "m3")["rating_std"][0]

    # ASSERTION: Match #3 rating BEFORE Match #4 score observation MUST be 100% identical!
    assert m3_mean_orig == m3_mean_mut, f"LEAKAGE DETECTED: Match #3 mean changed from {m3_mean_orig} to {m3_mean_mut}!"
    assert m3_std_orig == m3_std_mut, f"LEAKAGE DETECTED: Match #3 std changed from {m3_std_orig} to {m3_std_mut}!"

    # Also assert that Match #5 rating DID change due to Match #4 mutation
    m5_mean_orig = df_res_orig.filter(pl.col("match_id") == "m5")["rating_mean"][0]
    m5_mean_mut = df_res_mut.filter(pl.col("match_id") == "m5")["rating_mean"][0]
    assert m5_mean_orig != m5_mean_mut, "Match #5 rating should have changed after Match #4 mutation!"
