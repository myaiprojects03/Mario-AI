"""
XGBoost Classifier Model for FIFA Goals Over/Under Feature Learning.

Implementation Details:
- Trains xgboost.XGBClassifier on Task 5 engineered feature vectors.
- Predicts P(Total Goals > Line) directly.
- Handles missing feature values cleanly with xgboost built-in NaN handling.
"""

from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import polars as pl
import pandas as pd
import xgboost as xgb


class XGBoostGoalsOUModel:
    """
    XGBoost Classifier for FIFA Goals Over/Under prediction.
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        random_state: int = 42,
    ):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.random_state = random_state

        self.model = None
        self.feature_names: List[str] = []

    def _prepare_features_and_target(
        self, df: pl.DataFrame, is_training: bool = True
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Extracts numerical feature matrix X and target binary vector y."""
        df_pd = df.to_pandas() if isinstance(df, pl.DataFrame) else df

        from markets.fifa_goals_ou.features import FEATURE_COLUMNS
        candidate_cols = [c for c in FEATURE_COLUMNS if c != "match_id"]

        if is_training or not self.feature_names:
            self.feature_names = [c for c in candidate_cols if c in df_pd.columns]

        # Extract X matrix
        if self.feature_names:
            X = df_pd[self.feature_names].values.astype(float)
        else:
            X = np.zeros((len(df_pd), 1))

        # Target vector y: 1 if total goals > line else 0
        y = None
        if "home.goals" in df_pd.columns and "away.goals" in df_pd.columns:
            line_col = "odds.over_under.line" if "odds.over_under.line" in df_pd.columns else "line_value"
            lines = df_pd[line_col].fillna(2.5).values.astype(float) if line_col in df_pd.columns else np.full(len(df_pd), 2.5)
            total_goals = (df_pd["home.goals"].values + df_pd["away.goals"].values).astype(float)
            y = (total_goals > lines).astype(float)

        return X, y

    def fit(self, df_train: pl.DataFrame) -> "XGBoostGoalsOUModel":
        """Fits XGBoost classifier on training dataframe."""
        X_train, y_train = self._prepare_features_and_target(df_train, is_training=True)

        if y_train is None:
            raise ValueError("Training dataset must contain 'home.goals' and 'away.goals' target columns!")

        self.model = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            random_state=self.random_state,
            eval_metric="logloss",
        )
        self.model.fit(X_train, y_train)
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts P(Total Goals > Line) probabilities."""
        if self.model is None:
            raise RuntimeError("XGBoostGoalsOUModel must be fit before calling predict_probs!")

        X_test, _ = self._prepare_features_and_target(df_test, is_training=False)
        probs = self.model.predict_proba(X_test)[:, 1]
        return np.clip(probs, 0.01, 0.99)
