"""
Normal Distribution Baseline Model for eBasketball Over/Under.

Implementation Details:
- eBasketball features higher variance and wider total score range (~60-236 points observed).
- Fits Normal distribution N(mu, sigma^2) on total match points (home_goals + away_goals).
- Predicts P(Total Points > Line) using the Normal Survival Function 1 - Phi((line - mu) / sigma).
"""

from typing import Optional
import numpy as np
import polars as pl
import pandas as pd
from scipy.stats import norm


class NormalDistributionOUModel:
    """
    Normal Distribution Baseline Model for eBasketball Over/Under prediction.
    """

    def __init__(self):
        self.mean_total: float = 111.5
        self.std_total: float = 18.5
        self.is_fitted: bool = False

    def fit(self, df_train: pl.DataFrame) -> "NormalDistributionOUModel":
        """Fits Normal distribution parameters on total points (home.goals + away.goals)."""
        df_pd = df_train.to_pandas() if isinstance(df_train, pl.DataFrame) else df_train

        if "home.goals" not in df_pd.columns or "away.goals" not in df_pd.columns:
            raise ValueError("Training dataset must contain 'home.goals' and 'away.goals' target columns!")

        totals = (df_pd["home.goals"].values + df_pd["away.goals"].values).astype(float)
        
        self.mean_total = max(float(np.mean(totals)), 60.0)
        self.std_total = max(float(np.std(totals)), 5.0)
        self.is_fitted = True
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts P(Total Points > Line) for each match in df_test."""
        df_pd = df_test.to_pandas() if isinstance(df_test, pl.DataFrame) else df_test

        line_col = "odds.over_under.line" if "odds.over_under.line" in df_pd.columns else "ou_line_value"
        lines = df_pd[line_col].fillna(111.5).values.astype(float) if line_col in df_pd.columns else np.full(len(df_pd), 111.5)

        # Survival function 1 - CDF((line - mu) / sigma)
        probs = norm.sf((lines - self.mean_total) / self.std_total)
        return np.clip(probs, 0.01, 0.99)
