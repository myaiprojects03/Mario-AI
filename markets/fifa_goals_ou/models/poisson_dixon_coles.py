"""
Poisson Regression & Dixon-Coles Low-Scoring Adjustment Model for FIFA Goals O/U.

Implementation Details:
1. Baseline Independent Poisson Regression (GLM with Poisson family) for Home & Away goals.
2. Dixon-Coles tau adjustment parameter estimation for low-scoring match outcomes (0-0, 1-0, 0-1, 1-1).
3. Joint distribution calculation P(X=x, Y=y) and Over/Under probability P(X+Y > Line).
"""

from typing import Dict, Any, Tuple, Optional
import numpy as np
import polars as pl
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import statsmodels.api as sm


def _dixon_coles_tau(x: int, y: int, lambda_val: float, mu_val: float, rho: float) -> float:
    """Calculates Dixon-Coles low-scoring tau adjustment factor."""
    if x == 0 and y == 0:
        return 1.0 - (lambda_val * mu_val * rho)
    elif x == 1 and y == 0:
        return 1.0 + (lambda_val * rho)
    elif x == 0 and y == 1:
        return 1.0 + (mu_val * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    else:
        return 1.0


class PoissonDixonColesModel:
    """
    Independent Poisson Baseline & Dixon-Coles Low-Scoring Adjusted Model.
    """

    def __init__(self, max_goals: int = 15):
        self.max_goals = max_goals
        self.rho = -0.05  # Default low-scoring negative correlation parameter
        self.home_glm = None
        self.away_glm = None
        self.is_fitted = False

    def fit(self, df_train: pl.DataFrame) -> "PoissonDixonColesModel":
        """
        Fits Poisson GLMs for home and away goals and estimates Dixon-Coles rho parameter.
        """
        df_pd = df_train.to_pandas() if isinstance(df_train, pl.DataFrame) else df_train

        # Ensure goal outcomes exist
        home_goals = df_pd["home.goals"].values.astype(float)
        away_goals = df_pd["away.goals"].values.astype(float)

        # Build feature matrices for Poisson GLM
        # Use rolling scoring features if present, otherwise default to constant/league mean
        feature_cols_home = [c for c in ["home_scored_roll_mean_5", "away_conceded_roll_mean_5"] if c in df_pd.columns]
        feature_cols_away = [c for c in ["away_scored_roll_mean_5", "home_conceded_roll_mean_5"] if c in df_pd.columns]

        if feature_cols_home and feature_cols_away:
            X_home = sm.add_constant(df_pd[feature_cols_home].fillna(2.28).values)
            X_away = sm.add_constant(df_pd[feature_cols_away].fillna(2.28).values)
        else:
            X_home = np.ones((len(df_pd), 1))
            X_away = np.ones((len(df_pd), 1))

        try:
            self.home_glm = sm.GLM(home_goals, X_home, family=sm.families.Poisson()).fit()
            self.away_glm = sm.GLM(away_goals, X_away, family=sm.families.Poisson()).fit()
        except Exception:
            # Fallback if GLM fails to converge
            self.home_glm = None
            self.away_glm = None

        self.mean_home_lambda = float(np.mean(home_goals))
        self.mean_away_mu = float(np.mean(away_goals))

        # Estimate Dixon-Coles rho parameter via MLE on low-scoring match outcomes
        def _neg_log_likelihood(params):
            r = params[0]
            n_00 = np.sum((home_goals == 0) & (away_goals == 0))
            n_10 = np.sum((home_goals == 1) & (away_goals == 0))
            n_01 = np.sum((home_goals == 0) & (away_goals == 1))
            n_11 = np.sum((home_goals == 1) & (away_goals == 1))

            tau_00 = max(1e-6, _dixon_coles_tau(0, 0, self.mean_home_lambda, self.mean_away_mu, r))
            tau_10 = max(1e-6, _dixon_coles_tau(1, 0, self.mean_home_lambda, self.mean_away_mu, r))
            tau_01 = max(1e-6, _dixon_coles_tau(0, 1, self.mean_home_lambda, self.mean_away_mu, r))
            tau_11 = max(1e-6, _dixon_coles_tau(1, 1, self.mean_home_lambda, self.mean_away_mu, r))

            ll = (n_00 * np.log(tau_00) + n_10 * np.log(tau_10) +
                  n_01 * np.log(tau_01) + n_11 * np.log(tau_11))
            return -ll

        res = minimize(_neg_log_likelihood, [self.rho], bounds=[(-0.3, 0.3)], method="L-BFGS-B")
        if res.success:
            self.rho = float(res.x[0])

        self.is_fitted = True
        return self

    def predict_probs(self, df_test: pl.DataFrame, use_dixon_coles: bool = True) -> np.ndarray:
        """
        Predicts P(Total Goals > Line) for each match in df_test.
        """
        df_pd = df_test.to_pandas() if isinstance(df_test, pl.DataFrame) else df_test

        line_col = "odds.over_under.line" if "odds.over_under.line" in df_pd.columns else "line_value"
        lines = df_pd[line_col].fillna(2.5).values.astype(float) if line_col in df_pd.columns else np.full(len(df_pd), 2.5)

        # Estimate match-level lambdas and mus
        if self.home_glm is not None and self.away_glm is not None:
            feature_cols_home = [c for c in ["home_scored_roll_mean_5", "away_conceded_roll_mean_5"] if c in df_pd.columns]
            feature_cols_away = [c for c in ["away_scored_roll_mean_5", "home_conceded_roll_mean_5"] if c in df_pd.columns]

            if feature_cols_home and feature_cols_away:
                X_home = sm.add_constant(df_pd[feature_cols_home].fillna(2.28).values)
                X_away = sm.add_constant(df_pd[feature_cols_away].fillna(2.28).values)
                lambdas = np.clip(self.home_glm.predict(X_home), 0.1, 8.0)
                mus = np.clip(self.away_glm.predict(X_away), 0.1, 8.0)
            else:
                lambdas = np.full(len(df_pd), self.mean_home_lambda)
                mus = np.full(len(df_pd), self.mean_away_mu)
        else:
            lambdas = np.full(len(df_pd), getattr(self, "mean_home_lambda", 1.45))
            mus = np.full(len(df_pd), getattr(self, "mean_away_mu", 1.25))

        over_probs = np.zeros(len(df_pd))
        goals_range = np.arange(self.max_goals + 1)

        for i in range(len(df_pd)):
            lam = lambdas[i]
            mu = mus[i]
            line = lines[i]

            # Poisson probability vectors
            p_home = poisson.pmf(goals_range, lam)
            p_away = poisson.pmf(goals_range, mu)

            # Outer product joint matrix
            joint_p = np.outer(p_home, p_away)

            if use_dixon_coles:
                # Apply Dixon-Coles tau matrix adjustment
                tau_matrix = np.ones((self.max_goals + 1, self.max_goals + 1))
                for h_g in range(2):
                    for a_g in range(2):
                        tau_matrix[h_g, a_g] = _dixon_coles_tau(h_g, a_g, lam, mu, self.rho)

                joint_p = joint_p * tau_matrix
                joint_p_sum = joint_p.sum()
                if joint_p_sum > 0:
                    joint_p = joint_p / joint_p_sum

            # Sum probabilities where total goals (h_g + a_g) > line
            grid_h, grid_a = np.meshgrid(goals_range, goals_range, indexing="ij")
            over_mask = (grid_h + grid_a) > line
            over_probs[i] = np.sum(joint_p[over_mask])

        return np.clip(over_probs, 0.01, 0.99)
