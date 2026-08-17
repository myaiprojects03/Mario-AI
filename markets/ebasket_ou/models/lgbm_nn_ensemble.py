"""
LightGBM + Neural Network Ensemble Model for eBasketball Over/Under.

Implementation Details:
- Combines Gradient Boosting (XGBClassifier) and a 3-layer MLP Neural Network (MLPClassifier).
- Default weighting: 60% Gradient Boosting + 40% MLP Neural Network.
"""

from typing import List, Tuple, Optional
import numpy as np
import polars as pl
import pandas as pd
import xgboost as xgb
from sklearn.neural_network import MLPClassifier


class LightGBMNNEnsembleOUModel:
    """
    Ensemble model combining Gradient Boosting and Neural Network for eBasketball Over/Under.
    """

    def __init__(
        self,
        weight_lgb: float = 0.60,
        n_estimators: int = 50,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        random_state: int = 42,
    ):
        self.weight_lgb = weight_lgb
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.random_state = random_state

        self.xgb_model = None
        self.nn_model = None
        self.feature_names: List[str] = []

    def _prepare_features_and_target(
        self, df: pl.DataFrame, is_training: bool = True
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Extracts numerical feature matrix X and binary target vector y (Total Points > Line)."""
        df_pd = df.to_pandas() if isinstance(df, pl.DataFrame) else df

        from markets.ebasket_ou.features import EBASKET_OU_FEATURE_COLUMNS
        candidate_cols = [c for c in EBASKET_OU_FEATURE_COLUMNS if c != "match_id"]

        if is_training or not self.feature_names:
            self.feature_names = [c for c in candidate_cols if c in df_pd.columns]

        if self.feature_names:
            X = df_pd[self.feature_names].fillna(0.0).values.astype(float)
        else:
            X = np.zeros((len(df_pd), 1))

        # Target vector y: 1 if home_goals + away_goals > line_value else 0
        y = None
        if "home.goals" in df_pd.columns and "away.goals" in df_pd.columns:
            line_col = "odds.over_under.line" if "odds.over_under.line" in df_pd.columns else "ou_line_value"
            lines = df_pd[line_col].fillna(111.5).values.astype(float) if line_col in df_pd.columns else np.full(len(df_pd), 111.5)
            totals = (df_pd["home.goals"].values + df_pd["away.goals"].values).astype(float)
            y = (totals > lines).astype(float)

        return X, y

    def fit(self, df_train: pl.DataFrame) -> "LightGBMNNEnsembleOUModel":
        """Fits both XGBoost and Neural Network models on training dataset."""
        X_train, y_train = self._prepare_features_and_target(df_train, is_training=True)

        if y_train is None:
            raise ValueError("Training dataset must contain 'home.goals' and 'away.goals' target columns!")

        # 1. Fit XGBoost Model
        self.xgb_model = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=self.random_state,
            n_jobs=-1,
            eval_metric="logloss",
        )
        self.xgb_model.fit(X_train, y_train)

        # 2. Fit Neural Network Model (3 hidden layers: 64, 32, 16)
        self.nn_model = MLPClassifier(
            hidden_layer_sizes=(64, 32, 16),
            max_iter=200,
            random_state=self.random_state,
            early_stopping=True,
            n_iter_no_change=10,
        )
        self.nn_model.fit(X_train, y_train)

        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts blended P(Total Points > Line) probabilities."""
        if self.xgb_model is None or self.nn_model is None:
            raise RuntimeError("LightGBMNNEnsembleOUModel must be fit before calling predict_probs!")

        X_test, _ = self._prepare_features_and_target(df_test, is_training=False)

        p_xgb = self.xgb_model.predict_proba(X_test)[:, 1]
        p_nn = self.nn_model.predict_proba(X_test)[:, 1]

        p_blend = (self.weight_lgb * p_xgb) + ((1.0 - self.weight_lgb) * p_nn)
        return np.clip(p_blend, 0.01, 0.99)
