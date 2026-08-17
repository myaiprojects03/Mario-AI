"""
Ensemble Blended Model for FIFA 1X2 Money Line.

Implementation Details:
- Combines LightGBM Multiclass model and Multinomial Logistic Regression model.
- Default weighting: 60% LightGBM + 40% Multinomial Logistic.
"""

import numpy as np
import polars as pl
from markets.fifa_money_line.models.logistic_baseline import MultinomialLogisticMLModel
from markets.fifa_money_line.models.lgbm_model import LightGBMMoneyLineModel


class BlendedMoneyLineModel:
    """
    Ensemble Blended Model combining LightGBM and Multinomial Logistic Regression models for Money Line.
    """

    def __init__(self, weight_lgb: float = 0.60):
        self.weight_lgb = weight_lgb
        self.logistic_model = MultinomialLogisticMLModel()
        self.lgbm_model = LightGBMMoneyLineModel()
        self.is_fitted = False

    def fit(self, df_train: pl.DataFrame) -> "BlendedMoneyLineModel":
        """Fits both underlying Multinomial Logistic and LightGBM models."""
        self.logistic_model.fit(df_train)
        self.lgbm_model.fit(df_train)
        self.is_fitted = True
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts blended P(Home Win) probabilities."""
        if not self.is_fitted:
            raise RuntimeError("BlendedMoneyLineModel must be fit before calling predict_probs!")

        p_log = self.logistic_model.predict_probs(df_test)
        p_lgb = self.lgbm_model.predict_probs(df_test)

        p_blend = (self.weight_lgb * p_lgb) + ((1.0 - self.weight_lgb) * p_log)
        return np.clip(p_blend, 0.01, 0.99)
