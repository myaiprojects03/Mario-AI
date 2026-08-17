"""
Ensemble Blended Model for FIFA Goals Over/Under.

Implementation Details:
- Blends probabilities from XGBoost Feature Model and Dixon-Coles Poisson Model:
  P_blend = w * P_xgb + (1 - w) * P_dixon_coles
- Weight w is optimized or configured to maximize backtested unit profit.
"""

import numpy as np
import polars as pl
from .poisson_dixon_coles import PoissonDixonColesModel
from .xgb_model import XGBoostGoalsOUModel


class BlendedGoalsOUModel:
    """
    Ensemble Blended Model combining XGBoost and Dixon-Coles Poisson models.
    """

    def __init__(self, weight_xgb: float = 0.60):
        self.weight_xgb = weight_xgb
        self.dc_model = PoissonDixonColesModel()
        self.xgb_model = XGBoostGoalsOUModel()
        self.is_fitted = False

    def fit(self, df_train: pl.DataFrame) -> "BlendedGoalsOUModel":
        """Fits both underlying Dixon-Coles and XGBoost models."""
        self.dc_model.fit(df_train)
        self.xgb_model.fit(df_train)
        self.is_fitted = True
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts blended P(Total Goals > Line) probabilities."""
        if not self.is_fitted:
            raise RuntimeError("BlendedGoalsOUModel must be fit before calling predict_probs!")

        p_dc = self.dc_model.predict_probs(df_test, use_dixon_coles=True)
        p_xgb = self.xgb_model.predict_probs(df_test)

        p_blend = (self.weight_xgb * p_xgb) + ((1.0 - self.weight_xgb) * p_dc)
        return np.clip(p_blend, 0.01, 0.99)
