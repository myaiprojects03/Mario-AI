"""Core feature engineering module providing past-only rolling, odds drift, and head-to-head utilities."""

from core.features.rolling import compute_rolling_features
from core.features.odds_drift import compute_odds_drift_pair, add_odds_drift_columns
from core.features.head_to_head import compute_h2h_features

__all__ = [
    "compute_rolling_features",
    "compute_odds_drift_pair",
    "add_odds_drift_columns",
    "compute_h2h_features",
]
