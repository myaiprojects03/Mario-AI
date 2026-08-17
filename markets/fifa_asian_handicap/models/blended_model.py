"""
Ensemble Blended Model for FIFA Asian Handicap.

Implementation Details:
- Combines Dixon-Coles Poisson model and XGBoost feature classifier.
- Default weighting: 60% XGBoost + 40% Dixon-Coles.
"""

import numpy as np
import polars as pl
from markets.fifa_asian_handicap.models.poisson_dixon_coles import PoissonDixonColesAHModel
from markets.fifa_asian_handicap.models.xgb_model import XGBoostAsianHandicapModel


class BlendedAsianHandicapModel:
    """
    Ensemble Blended Model combining XGBoost and Dixon-Coles Poisson models for Asian Handicap.
    """

    def __init__(self, weight_xgb: float = 0.60):
        self.weight_xgb = weight_xgb
        self.dc_model = PoissonDixonColesAHModel()
        self.xgb_model = XGBoostAsianHandicapModel()
        self.is_fitted = False

    def fit(self, df_train: pl.DataFrame) -> "BlendedAsianHandicapModel":
        """Fits both underlying Dixon-Coles and XGBoost models."""
        self.dc_model.fit(df_train)
        self.xgb_model.fit(df_train)
        self.is_fitted = True
        return self

    def predict_probs(self, df_test: pl.DataFrame) -> np.ndarray:
        """Predicts blended P(Handicap Covered) probabilities."""
        if not self.is_fitted:
            raise RuntimeError("BlendedAsianHandicapModel must be fit before calling predict_probs!")

        p_dc = self.dc_model.predict_probs(df_test, use_dixon_coles=True)
        p_xgb = self.xgb_model.predict_probs(df_test)

        p_blend = (self.weight_xgb * p_xgb) + ((1.0 - self.weight_xgb) * p_dc)
        return np.clip(p_blend, 0.01, 0.99)
