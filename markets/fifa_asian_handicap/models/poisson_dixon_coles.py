"""
Poisson & Dixon-Coles Model for FIFA Asian Handicap.

Implementation Details:
- Fits Poisson GLMs for home goals and away goals on rolling team attack/defense features.
- Applies Dixon-Coles tau correction for low-scoring outcome dependency (0-0, 1-0, 0-1, 1-1).
- Sums joint probability matrix P(h, a) for all outcome pairs where (h - a + handicap_line) > 0.
"""

from typing import Optional
import numpy as np
import polars as pl
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
import statsmodels.api as sm


class PoissonDixonColesAHModel:
    """
    Poisson / Dixon-Coles Model for FIFA Asian Handicap prediction.
    """

    def __init__(self, max_goals: int = 12):
        self.max_goals = max_goals
        self.home_glm = None
        self.away_glm = None
        self.rho: float = 0.0
        self.mean_home_lambda: float = 1.45
        self.mean_away_mu: float = 1.25
        self.is_fitted: bool = False

    def _tau(self, x: int, y: int, lambda_val: float, mu_val: float, rho: float) -> float:
        """Dixon-Coles adjustment factor for low-scoring dependency."""
        if x == 0 and y == 0:
            return 1.0 - (lambda_val * mu_val * rho)
        elif x == 1 and y == 0:
            return 1.0 + (mu_val * rho)
        elif x == 0 and y == 1:
            return 1.0 + (lambda_val * rho)
        elif x == 1 and y == 1:
            return 1.0 - rho
        else:
            return 1.0

    def fit(self, df_train: pl.DataFrame) -> "PoissonDixonColesAHModel":
        """Fits Poisson GLMs and Dixon-Coles parameter on training dataset."""
        df_pd = df_train.to_pandas() if isinstance(df_train, pl.DataFrame) else df_train

        if "home.goals" not in df_pd.columns or "away.goals" not in df_pd.columns:
            raise ValueError("Training dataset must contain 'home.goals' and 'away.goals' target columns!")

        y_home = df_pd["home.goals"].astype(float).values
        y_away = df_pd["away.goals"].astype(float).values

        self.mean_home_lambda = max(float(np.mean(y_home)), 0.5)
        self.mean_away_mu = max(float(np.mean(y_away)), 0.5)

        # Build feature matrices for Poisson GLMs
        feature_cols_home = [c for c in ["home_scored_roll_mean_5", "away_conceded_roll_mean_5"] if c in df_pd.columns]
        feature_cols_away = [c for c in ["away_scored_roll_mean_5", "home_conceded_roll_mean_5"] if c in df_pd.columns]

        if feature_cols_home and feature_cols_away:
            X_home = sm.add_constant(df_pd[feature_cols_home].fillna(2.28).values)
            X_away = sm.add_constant(df_pd[feature_cols_away].fillna(2.28).values)
        else:
            X_home = np.ones((len(df_pd), 1))
            X_away = np.ones((len(df_pd), 1))

        try:
            self.home_glm = sm.GLM(y_home, X_home, family=sm.families.Poisson()).fit()
            self.away_glm = sm.GLM(y_away, X_away, family=sm.families.Poisson()).fit()
        except Exception:
            self.home_glm = None
            self.away_glm = None

        # Dixon-Coles rho optimization via MLE (Vectorized)
        if self.home_glm is not None and self.away_glm is not None:
            l_vals = np.clip(self.home_glm.predict(X_home), 0.1, 8.0)
            m_vals = np.clip(self.away_glm.predict(X_away), 0.1, 8.0)
        else:
            l_vals = np.full(len(y_home), self.mean_home_lambda)
            m_vals = np.full(len(y_away), self.mean_away_mu)

        mask00 = (y_home == 0) & (y_away == 0)
        mask10 = (y_home == 1) & (y_away == 0)
        mask01 = (y_home == 0) & (y_away == 1)
        mask11 = (y_home == 1) & (y_away == 1)
        p_base = poisson.pmf(y_home, l_vals) * poisson.pmf(y_away, m_vals)

        def _neg_log_likelihood(params):
            rho_cand = params[0]
            tau_vals = np.ones_like(y_home)
            tau_vals[mask00] = np.maximum(1.0 - (l_vals[mask00] * m_vals[mask00] * rho_cand), 1e-5)
            tau_vals[mask10] = np.maximum(1.0 + (m_vals[mask10] * rho_cand), 1e-5)
            tau_vals[mask01] = np.maximum(1.0 + (l_vals[mask01] * rho_cand), 1e-5)
            tau_vals[mask11] = np.maximum(1.0 - rho_cand, 1e-5)

            probs = np.maximum(p_base * tau_vals, 1e-10)
            return -float(np.sum(np.log(probs)))

        res = minimize(_neg_log_likelihood, [0.0], bounds=[(-0.3, 0.3)], method="L-BFGS-B")
        if res.success:
            self.rho = float(res.x[0])

        self.is_fitted = True
        return self

    def predict_probs(self, df_test: pl.DataFrame, use_dixon_coles: bool = True) -> np.ndarray:
        """
        Predicts P(Home Goals - Away Goals + Handicap Line > 0) for each match in df_test.
        """
        df_pd = df_test.to_pandas() if isinstance(df_test, pl.DataFrame) else df_test

        line_col = "odds.asian_handicap.line" if "odds.asian_handicap.line" in df_pd.columns else "handicap_line_value"
        lines = df_pd[line_col].fillna(-0.5).values.astype(float) if line_col in df_pd.columns else np.full(len(df_pd), -0.5)

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

        N = len(df_pd)
        h_arr = np.arange(self.max_goals).reshape(1, self.max_goals, 1) # (1, M, 1)
        a_arr = np.arange(self.max_goals).reshape(1, 1, self.max_goals) # (1, 1, M)

        lam_grid = lambdas[:, None, None] # (N, 1, 1)
        mu_grid = mus[:, None, None]      # (N, 1, 1)

        p_h = poisson.pmf(h_arr, lam_grid) # (N, M, 1)
        p_a = poisson.pmf(a_arr, mu_grid)  # (N, 1, M)
        p_joint = p_h * p_a                # (N, M, M)

        if use_dixon_coles and self.rho != 0.0:
            tau = np.ones_like(p_joint)
            tau[:, 0, 0] = np.maximum(1.0 - (lambdas * mus * self.rho), 0.0)
            tau[:, 1, 0] = np.maximum(1.0 + (mus * self.rho), 0.0)
            tau[:, 0, 1] = np.maximum(1.0 + (lambdas * self.rho), 0.0)
            tau[:, 1, 1] = np.maximum(1.0 - self.rho, 0.0)
            p_joint = np.maximum(p_joint * tau, 0.0)

        # Margin condition: h - a + line
        margins = h_arr - a_arr + lines[:, None, None] # (N, M, M)
        win_mask = (margins > 0).astype(float)
        push_mask = (margins == 0).astype(float)

        probs = np.sum(p_joint * (win_mask + 0.5 * push_mask), axis=(1, 2))
        return np.clip(probs, 0.01, 0.99)
