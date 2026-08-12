"""
Feature Drift & Population Stability Monitoring Module.

Provides PSI (Population Stability Index), 2-sample KS-test, and baseline distribution persistence.
Designed for seamless reuse in Phase 3 live production monitoring.
"""

import os
import json
from typing import Dict, Any, Tuple
import numpy as np
from scipy import stats


def compute_psi(baseline: np.ndarray, target: np.ndarray, num_bins: int = 10, eps: float = 1e-6) -> float:
    """
    Computes Population Stability Index (PSI) between baseline and target feature distributions.

    Interpretation:
    - PSI < 0.10: Stable distribution (no drift).
    - 0.10 <= PSI < 0.25: Moderate drift (monitor closely).
    - PSI >= 0.25: Significant drift (re-calibrate or re-train model).

    Args:
        baseline: Baseline distribution array (e.g. initial 3-6 months training data).
        target: Target distribution array (e.g. recent test window or live production data).
        num_bins: Number of quantile bins.
        eps: Epsilon factor to prevent division-by-zero or log-of-zero.

    Returns:
        float: Computed Population Stability Index (PSI).
    """
    baseline = np.asarray(baseline, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)

    # Filter out NaNs/Infs
    baseline = baseline[np.isfinite(baseline)]
    target = target[np.isfinite(target)]

    if len(baseline) == 0 or len(target) == 0:
        return 0.0

    # Determine quantile bin edges from baseline
    quantiles = np.linspace(0, 100, num_bins + 1)
    bins = np.percentile(baseline, quantiles)
    # Ensure unique strictly increasing bin edges
    bins = np.unique(bins)
    if len(bins) < 2:
        return 0.0

    bins[0] = -np.inf
    bins[-1] = np.inf

    # Calculate bin counts & proportions
    baseline_counts, _ = np.histogram(baseline, bins=bins)
    target_counts, _ = np.histogram(target, bins=bins)

    b_pct = baseline_counts / len(baseline)
    t_pct = target_counts / len(target)

    # Add epsilon for zero-count bins
    b_pct = np.where(b_pct == 0, eps, b_pct)
    t_pct = np.where(t_pct == 0, eps, t_pct)

    # PSI formula: sum((target% - baseline%) * ln(target% / baseline%))
    psi_value = np.sum((t_pct - b_pct) * np.log(t_pct / b_pct))
    return float(psi_value)


def compute_ks_test(baseline: np.ndarray, target: np.ndarray) -> Tuple[float, float]:
    """
    Performs 2-sample Kolmogorov-Smirnov test comparing baseline vs target distributions.

    Returns:
        Tuple[float, float]: (ks_statistic, p_value).
    """
    baseline = np.asarray(baseline, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)

    baseline = baseline[np.isfinite(baseline)]
    target = target[np.isfinite(target)]

    if len(baseline) == 0 or len(target) == 0:
        return 0.0, 1.0

    res = stats.ks_2samp(baseline, target)
    return float(res.statistic), float(res.pvalue)


def save_baseline_distribution(
    feature_name: str,
    baseline_data: np.ndarray,
    version: str = "v1",
    storage_dir: str = "data/baselines",
) -> str:
    """
    Saves baseline distribution summary (quantiles, mean, std) to a versioned JSON file.
    Enables Phase 3 live monitoring to load baselines without recomputing from raw database records.

    Returns:
        str: Absolute file path where baseline was persisted.
    """
    arr = np.asarray(baseline_data, dtype=np.float64)
    arr = arr[np.isfinite(arr)]

    os.makedirs(storage_dir, exist_ok=True)
    file_path = os.path.join(storage_dir, f"{feature_name}_{version}.json")

    quantiles = np.percentile(arr, np.linspace(0, 100, 21)).tolist() if len(arr) > 0 else []

    payload = {
        "feature_name": feature_name,
        "version": version,
        "sample_count": int(len(arr)),
        "mean": float(np.mean(arr)) if len(arr) > 0 else 0.0,
        "std": float(np.std(arr)) if len(arr) > 0 else 0.0,
        "min": float(np.min(arr)) if len(arr) > 0 else 0.0,
        "max": float(np.max(arr)) if len(arr) > 0 else 0.0,
        "quantiles_5pct": quantiles,
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return os.path.abspath(file_path)


def load_baseline_distribution(
    feature_name: str,
    version: str = "v1",
    storage_dir: str = "data/baselines",
) -> Dict[str, Any]:
    """
    Loads persisted baseline distribution metadata.

    Raises:
        FileNotFoundError: If requested baseline file does not exist.
    """
    file_path = os.path.join(storage_dir, f"{feature_name}_{version}.json")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Baseline file for '{feature_name}' (version '{version}') not found at {file_path}.")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
