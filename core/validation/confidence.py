"""
Probability Calibration and Confidence Threshold Tuning Module.

PROVIDES:
- ConfidenceCalibrator: Isotonic Regression & Platt Scaling probability calibration.
- search_optimal_threshold: Grid-search function finding the optimal minimum confidence cutoff for tip publication.
"""

from typing import Dict, Any, List, Union
import numpy as np
import polars as pl
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from core.validation.backtest_engine import BacktestEngine


class ConfidenceCalibrator:
    """
    Fits probability calibration models (Isotonic Regression or Platt Scaling)
    on held-out validation slices to convert raw model probabilities into calibrated confidence scores.
    """

    def __init__(self, method: str = "isotonic"):
        """
        Args:
            method (str): 'isotonic' for IsotonicRegression or 'platt' for LogisticRegression.
        """
        if method not in ["isotonic", "platt"]:
            raise ValueError("method must be 'isotonic' or 'platt'.")
        
        self.method = method
        self.model = None

    def fit(self, raw_probs: np.ndarray, y_true: np.ndarray) -> "ConfidenceCalibrator":
        """
        Fits calibration model on raw predicted probabilities and actual binary outcomes.
        """
        p = np.clip(np.asarray(raw_probs, dtype=np.float64), 0.0, 1.0)
        y = np.asarray(y_true, dtype=np.float64)

        if self.method == "isotonic":
            self.model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            self.model.fit(p, y)
        elif self.method == "platt":
            # Platt scaling: LogisticRegression on log-odds
            log_odds = np.log(p / np.clip(1.0 - p, 1e-7, 1.0)).reshape(-1, 1)
            self.model = LogisticRegression(C=1.0, solver="lbfgs")
            self.model.fit(log_odds, y)

        return self

    def predict_confidence(self, raw_probs: np.ndarray) -> np.ndarray:
        """
        Applies fitted calibration model to map raw probabilities to calibrated confidence scores.
        """
        if self.model is None:
            raise RuntimeError("ConfidenceCalibrator must be fit before calling predict_confidence.")

        p = np.clip(np.asarray(raw_probs, dtype=np.float64), 0.0, 1.0)

        if self.method == "isotonic":
            calibrated = self.model.predict(p)
        elif self.method == "platt":
            log_odds = np.log(p / np.clip(1.0 - p, 1e-7, 1.0)).reshape(-1, 1)
            calibrated = self.model.predict_proba(log_odds)[:, 1]

        return np.clip(calibrated, 0.0, 1.0)


def search_optimal_threshold(
    df_backtest: Union[pl.DataFrame, pd.DataFrame],
    min_threshold: float = 0.50,
    max_threshold: float = 0.90,
    step: float = 0.01,
    is_money_line: bool = False,
    global_odds_floor: float = 1.60,
    money_line_floor: float = 1.70,
    confidence_col: str = "confidence",
    odds_col: str = "odds_close",
    outcome_col: str = "is_win",
) -> Dict[str, Any]:
    """
    Grid-searches confidence thresholds to find the cutoff maximizing net units generated in backtests.

    Returns:
        Dict detailing optimal_threshold, max_units, corresponding ROI%, and full threshold curve results.
    """
    thresholds = np.arange(min_threshold, max_threshold + (step / 2.0), step)
    results = []

    best_units = -np.inf
    best_threshold = min_threshold
    best_summary = None

    for th in thresholds:
        th_val = float(np.round(th, 4))
        engine = BacktestEngine(
            global_odds_floor=global_odds_floor,
            money_line_floor=money_line_floor,
            min_confidence=th_val,
        )
        res = engine.evaluate_tips(
            df=df_backtest,
            is_money_line=is_money_line,
            confidence_col=confidence_col,
            odds_col=odds_col,
            outcome_col=outcome_col,
        )

        entry = {
            "threshold": th_val,
            "units": res["total_units"],
            "roi_pct": res["roi_pct"],
            "hit_rate": res["hit_rate"],
            "tips_evaluated": res["tips_evaluated"],
        }
        results.append(entry)

        if res["total_units"] > best_units and res["tips_evaluated"] > 0:
            best_units = res["total_units"]
            best_threshold = th_val
            best_summary = entry

    if best_summary is None:
        best_summary = {"threshold": min_threshold, "units": 0.0, "roi_pct": 0.0, "hit_rate": 0.0, "tips_evaluated": 0}

    return {
        "optimal_threshold": best_threshold,
        "max_units": float(best_summary["units"]),
        "optimal_summary": best_summary,
        "threshold_curve": results,
    }
