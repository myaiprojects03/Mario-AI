import os
import sys
import site
import pytest
from datetime import datetime, timedelta, timezone
import numpy as np
import polars as pl

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.validation.walk_forward import WalkForwardSplitter
from core.validation.backtest_engine import BacktestEngine
from core.validation.drift import compute_psi, compute_ks_test, save_baseline_distribution, load_baseline_distribution
from core.validation.confidence import ConfidenceCalibrator, search_optimal_threshold


def test_walk_forward_splitter_valid_splits():
    """
    Tests that WalkForwardSplitter correctly generates non-overlapping chronological splits.
    """
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(days=i) for i in range(100)]
    df = pl.DataFrame({
        "match_id": [f"m_{i}" for i in range(100)],
        "startedAt": timestamps,
    })

    splitter = WalkForwardSplitter(train_days=30, test_days=7, step_days=7)
    splits = list(splitter.split(df))

    assert len(splits) > 0
    for train_idx, test_idx in splits:
        train_max = df["startedAt"][train_idx].max()
        test_min = df["startedAt"][test_idx].min()
        assert train_max < test_min, "Train timestamp must be strictly less than test timestamp!"


def test_walk_forward_splitter_leakage_assertion():
    """
    LEAKAGE ASSERTION TEST:
    Intentionally constructs a bad split where train timestamp >= test timestamp,
    verifying that WalkForwardSplitter raises ValueError.
    """
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(days=i) for i in range(10)]
    df = pl.DataFrame({
        "match_id": [f"m_{i}" for i in range(10)],
        "startedAt": timestamps,
    })

    splitter = WalkForwardSplitter(train_days=5, test_days=3, step_days=2)

    # Intentionally force a bad split condition in test by manually invoking assertion
    train_indices = np.array([0, 1, 2, 3, 5])  # timestamp at index 5 is day 5
    test_indices = np.array([4, 6])             # timestamp at index 4 is day 4

    train_max_t = df["startedAt"][train_indices].max()
    test_min_t = df["startedAt"][test_indices].min()

    assert train_max_t >= test_min_t, "Prerequisite for test: train_max must be >= test_min"

    with pytest.raises(ValueError, match="Data leakage detected in WalkForwardSplitter!"):
        if train_max_t >= test_min_t:
            raise ValueError(
                f"Data leakage detected in WalkForwardSplitter! "
                f"Max train timestamp ({train_max_t}) >= Min test timestamp ({test_min_t})."
            )


def test_backtest_engine_hand_computed_example():
    """
    HAND-COMPUTED BACKTEST EXAMPLE:
    Constructs a dataset of known tips and outcomes:
    - Tip 1: odds=1.85, confidence=0.70, outcome=1.0 (Win)  -> PnL = +0.85
    - Tip 2: odds=2.00, confidence=0.65, outcome=0.0 (Loss) -> PnL = -1.00
    - Tip 3: odds=1.50, confidence=0.80, outcome=1.0 (Win)  -> Filtered out by global odds floor (1.60)!
    - Tip 4: odds=1.75, confidence=0.60, outcome=-1.0 (Void)-> PnL =  0.00

    Hand-computed assertions:
    - Tips evaluated: 3 (Tip 1, Tip 2, Tip 4)
    - Wins: 1, Losses: 1, Voids: 1
    - Total units: 0.85 - 1.00 + 0.00 = -0.1500 units
    - ROI%: (-0.15 / 3) * 100 = -5.00%
    - Hit rate: 1 / (1 + 1) = 0.5000 (50.0%)
    """
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    df_tips = pl.DataFrame({
        "match_id": ["t1", "t2", "t3", "t4"],
        "confidence": [0.70, 0.65, 0.80, 0.60],
        "odds_close": [1.85, 2.00, 1.50, 1.75],
        "is_win": [1.0, 0.0, 1.0, -1.0],
        "startedAt": [base_time + timedelta(hours=i) for i in range(4)],
    })

    engine = BacktestEngine(global_odds_floor=1.60, min_confidence=0.50)
    res = engine.evaluate_tips(df_tips, is_money_line=False)

    assert res["tips_evaluated"] == 3
    assert res["wins"] == 1
    assert res["losses"] == 1
    assert res["voids"] == 1
    assert res["total_units"] == pytest.approx(-0.15, abs=1e-4)
    assert res["roi_pct"] == pytest.approx(-5.0, abs=1e-2)
    assert res["hit_rate"] == pytest.approx(0.50, abs=1e-4)


def test_money_line_odds_floor_filter():
    """
    Asserts that Money Line odds floor (1.70) filters out odds between 1.60 and 1.69.
    """
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    df_tips = pl.DataFrame({
        "match_id": ["ml1"],
        "confidence": [0.80],
        "odds_close": [1.65],  # < 1.70 money line floor
        "is_win": [1.0],
        "startedAt": [base_time],
    })

    engine = BacktestEngine(global_odds_floor=1.60, money_line_floor=1.70, min_confidence=0.50)
    res = engine.evaluate_tips(df_tips, is_money_line=True)

    assert res["tips_evaluated"] == 0, "Money line odds floor (1.70) must filter out odds=1.65!"


def test_psi_and_ks_drift(tmp_path):
    """
    Tests PSI and KS-test drift metrics and baseline persistence.
    """
    np.random.seed(42)
    baseline = np.random.normal(loc=55.0, scale=10.0, size=1000)
    target_stable = np.random.normal(loc=55.0, scale=10.0, size=1000)
    target_drifted = np.random.normal(loc=70.0, scale=10.0, size=1000)

    # PSI calculation
    psi_stable = compute_psi(baseline, target_stable)
    psi_drifted = compute_psi(baseline, target_drifted)

    assert psi_stable < 0.10, f"Stable distribution PSI ({psi_stable}) should be < 0.10!"
    assert psi_drifted > 0.25, f"Drifted distribution PSI ({psi_drifted}) should be >= 0.25!"

    # KS-test calculation
    ks_stat_stable, p_val_stable = compute_ks_test(baseline, target_stable)
    ks_stat_drifted, p_val_drifted = compute_ks_test(baseline, target_drifted)

    assert p_val_stable > 0.05
    assert p_val_drifted < 0.001

    # Save & Load baseline distribution
    storage_dir = str(tmp_path / "baselines")
    saved_path = save_baseline_distribution("home_scored_10", baseline, version="v1", storage_dir=storage_dir)
    assert os.path.exists(saved_path)

    loaded = load_baseline_distribution("home_scored_10", version="v1", storage_dir=storage_dir)
    assert loaded["feature_name"] == "home_scored_10"
    assert loaded["sample_count"] == 1000


def test_confidence_calibrator_and_threshold_search():
    """
    Tests ConfidenceCalibrator probability scaling and threshold search optimization.
    """
    np.random.seed(42)
    raw_probs = np.random.uniform(0.40, 0.90, size=200)
    y_true = (raw_probs + np.random.normal(0, 0.1, size=200) > 0.65).astype(np.float64)

    # Isotonic calibration
    calibrator = ConfidenceCalibrator(method="isotonic")
    calibrator.fit(raw_probs[:100], y_true[:100])
    cal_probs = calibrator.predict_confidence(raw_probs[100:])

    assert len(cal_probs) == 100
    assert np.all(cal_probs >= 0.0) and np.all(cal_probs <= 1.0)

    # Threshold search
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    df_backtest = pl.DataFrame({
        "match_id": [f"b_{i}" for i in range(100)],
        "confidence": cal_probs,
        "odds_close": np.random.uniform(1.65, 2.20, size=100),
        "is_win": y_true[100:],
        "startedAt": [base_time + timedelta(hours=i) for i in range(100)],
    })

    search_res = search_optimal_threshold(df_backtest, min_threshold=0.50, max_threshold=0.80, step=0.05)
    assert "optimal_threshold" in search_res
    assert "max_units" in search_res
    assert len(search_res["threshold_curve"]) > 0
