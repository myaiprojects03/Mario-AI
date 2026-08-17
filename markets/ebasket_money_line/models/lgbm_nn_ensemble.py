"""
LightGBM + Neural Network Ensemble Model for eBasketball Money Line.

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


class LightGBMNNEnsembleMLModel:
    """
    Ensemble model combining Gradient Boosting and Neural Network for eBasketball Money Line.
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
        """Extracts numerical feature matrix X and target binary outcome vector y."""
        df_pd = df.to_pandas() if isinstance(df, pl.DataFrame) else df

        from markets.ebasket_money_line.features import EBASKET_ML_FEATURE_COLUMNS
        candidate_cols = [c for c in EBASKET_ML_FEATURE_COLUMNS if c != "match_id"]

        if is_training or not self.feature_names:
            self.feature_names = [c for c in candidate_cols if c in df_pd.columns]

        if self.feature_names:
            X = df_pd[self.feature_names].fillna(0.0).values.astype(float)
        else:
            X = np.zeros((len(df_pd), 1))

        # Target binary vector y: 1 if home_goals > away_goals else 0
        y = None
        if "home.goals" in df_pd.columns and "away.goals" in df_pd.columns:
            home_g = df_pd["home.goals"].values.astype(float)
            away_g = df_pd["away.goals"].values.astype(float)
            y = (home_g > away_g).astype(float)

        return X, y

    def fit(self, df_train: pl.DataFrame) -> "LightGBMNNEnsembleMLModel":
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
        """Predicts blended P(Home Win) probabilities."""
        if self.xgb_model is None or self.nn_model is None:
            raise RuntimeError("LightGBMNNEnsembleMLModel must be fit before calling predict_probs!")

        X_test, _ = self._prepare_features_and_target(df_test, is_training=False)

        p_xgb = self.xgb_model.predict_proba(X_test)[:, 1]
        p_nn = self.nn_model.predict_proba(X_test)[:, 1]

        p_blend = (self.weight_lgb * p_xgb) + ((1.0 - self.weight_lgb) * p_nn)
        return np.clip(p_blend, 0.01, 0.99)
