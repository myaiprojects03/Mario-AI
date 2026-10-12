"""
Gradient Boosting Classifier Model for eBasketball Money Line.

Implementation Details:
- Binary classifier predicting Home Win probability: P(Home Win).
- Fits xgboost.XGBClassifier with objective='binary:logistic'.
- Native NaN handling (zero synthetic imputation).
"""

from typing import List, Tuple, Optional
import numpy as np
import polars as pl
import pandas as pd
import xgboost as xgb


class LightGBMEbasketMoneyLineModel:
    """
    Gradient Boosting Binary Classifier for eBasketball Money Line prediction.
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        subsample: float = 0.85,
        colsample_bytree: float = 0.85,
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
        """Extracts numerical feature matrix X and target binary outcome vector y."""
        df_pd = df.to_pandas() if isinstance(df, pl.DataFrame) else df

        from markets.ebasket_money_line.features import EBASKET_ML_FEATURE_COLUMNS
        candidate_cols = [c for c in EBASKET_ML_FEATURE_COLUMNS if c != "match_id"]

        if is_training or not self.feature_names:
            self.feature_names = [c for c in candidate_cols if c in df_pd.columns]

        if self.feature_names:
            X = df_pd[self.feature_names].values.astype(float)
        else:
            X = np.zeros((len(df_pd), 1))

        # Target binary vector y: 1 if Home Win (home.goals > away.goals), 0 if Away Win
        y = None
        if "home.goals" in df_pd.columns and "away.goals" in df_pd.columns:
            home_g = df_pd["home.goals"].values.astype(float)
            away_g = df_pd["away.goals"].values.astype(float)
            y = (home_g > away_g).astype(int)

        return X, y

    def fit(self, df_train: pl.DataFrame) -> "LightGBMEbasketMoneyLineModel":
        """Fits binary gradient boosting model on training dataset."""
        X_train, y_train = self._prepare_features_and_target(df_train, is_training=True)

        if y_train is None:
            raise ValueError("Training dataset must contain 'home.goals' and 'away.goals' target columns!")

        self.model = xgb.XGBClassifier(
            objective="binary:logistic",
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            random_state=self.random_state,
            n_jobs=-1,
            eval_metric="logloss",
        )
        self.model.fit(X_train, y_train)
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts P(Home Win) probabilities."""
        if self.model is None:
            raise RuntimeError("Model must be fit before calling predict_probs!")

        X_test, _ = self._prepare_features_and_target(df_test, is_training=False)
        probs = self.model.predict_proba(X_test)[:, 1]
        return np.clip(probs, 0.01, 0.99)

    def predict_proba_2way(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts 2-way probabilities [P(Away Win), P(Home Win)]."""
        if self.model is None:
            raise RuntimeError("Model must be fit before calling predict_proba_2way!")

        X_test, _ = self._prepare_features_and_target(df_test, is_training=False)
        return self.model.predict_proba(X_test)
