"""
Multinomial Logistic Regression Baseline Model for FIFA 1X2 Money Line.

Implementation Details:
- Fits sklearn.linear_model.LogisticRegression with multi_class='multinomial'.
- Predicts 3-way probabilities [P(Home Win), P(Draw), P(Away Win)].
"""

from typing import List, Tuple, Optional
import numpy as np
import polars as pl
import pandas as pd
from sklearn.linear_model import LogisticRegression


class MultinomialLogisticMLModel:
    """
    Multinomial Logistic Regression Baseline Model for FIFA Money Line prediction.
    """

    def __init__(self, max_iter: int = 200, random_state: int = 42):
        self.max_iter = max_iter
        self.random_state = random_state
        self.model = None
        self.feature_names: List[str] = []

    def _prepare_features_and_target(
        self, df: pl.DataFrame, is_training: bool = True
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Extracts numerical feature matrix X and target 3-class outcome vector y."""
        df_pd = df.to_pandas() if isinstance(df, pl.DataFrame) else df

        from markets.fifa_money_line.features import ML_FEATURE_COLUMNS
        candidate_cols = [c for c in ML_FEATURE_COLUMNS if c != "match_id"]

        if is_training or not self.feature_names:
            self.feature_names = [c for c in candidate_cols if c in df_pd.columns]

        if self.feature_names:
            X = df_pd[self.feature_names].fillna(0.0).values.astype(float)
        else:
            X = np.zeros((len(df_pd), 1))

        # Target 3-class vector y: 0 for Home Win, 1 for Draw, 2 for Away Win
        y = None
        if "home.goals" in df_pd.columns and "away.goals" in df_pd.columns:
            home_g = df_pd["home.goals"].values.astype(float)
            away_g = df_pd["away.goals"].values.astype(float)
            y = np.where(home_g > away_g, 0, np.where(home_g == away_g, 1, 2))

        return X, y

    def fit(self, df_train: pl.DataFrame) -> "MultinomialLogisticMLModel":
        """Fits multinomial logistic regression model on training dataset."""
        X_train, y_train = self._prepare_features_and_target(df_train, is_training=True)

        if y_train is None:
            raise ValueError("Training dataset must contain 'home.goals' and 'away.goals' target columns!")

        self.model = LogisticRegression(
            solver="lbfgs",
            max_iter=self.max_iter,
            random_state=self.random_state,
        )
        self.model.fit(X_train, y_train)
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts P(Home Win) probabilities (or full 3-class probabilities if requested)."""
        if self.model is None:
            raise RuntimeError("MultinomialLogisticMLModel must be fit before calling predict_probs!")

        X_test, _ = self._prepare_features_and_target(df_test, is_training=False)
        probs_all = self.model.predict_proba(X_test)
        
        # Default returns P(Home Win) (class index 0)
        if probs_all.shape[1] > 0:
            probs = probs_all[:, 0]
        else:
            probs = np.full(len(df_test), 0.40)

        return np.clip(probs, 0.01, 0.99)
