"""
Empirical Audit Script for XGBoost Model Leakage, Walk-Forward Split Timestamps,
Confidence Threshold Filtering, and Raw Unfiltered Performance Comparison.
"""

import sys
import site
import pandas as pd
import numpy as np
import polars as pl
from sqlalchemy import create_engine

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from core.validation.walk_forward import WalkForwardSplitter
from core.validation.backtest_engine import BacktestEngine
from core.validation.confidence import ConfidenceCalibrator
from markets.fifa_goals_ou.model import load_training_dataset
from markets.fifa_goals_ou.models import (
    PoissonDixonColesModel,
    XGBoostGoalsOUModel,
    BlendedGoalsOUModel,
)


def run_empirical_audit():
    engine = create_engine(settings.DATABASE_URL)
    df = load_training_dataset(engine)

    print("\n==========================================================================")
    print(" 1. WALK-FORWARD SPLIT TIMESTAMP LEAKAGE AUDIT (TASK 8 ASSERTION VERIFICATION)")
    print("==========================================================================")
    
    splitter = WalkForwardSplitter(
        train_days=45,
        test_days=7,
        step_days=7,
        time_col="match_start_time",
    )

    split_idx = 0
    test_records = []
    dc_preds, xgb_preds, blend_preds = [], [], []
    actual_outcomes = []

    dc_model = PoissonDixonColesModel()
    xgb_model = XGBoostGoalsOUModel()
    blend_model = BlendedGoalsOUModel(weight_xgb=0.60)

    for train_idx, test_idx in splitter.split(df):
        split_idx += 1
        df_train = df[train_idx]
        df_test = df[test_idx]

        train_times = df_train["match_start_time"].to_numpy()
        test_times = df_test["match_start_time"].to_numpy()

        max_train_t = pd.to_datetime(train_times.max())
        min_test_t = pd.to_datetime(test_times.min())

        print(f"Fold {split_idx}: Train [{pd.to_datetime(train_times.min())} to {max_train_t}] | Test [{min_test_t} to {pd.to_datetime(test_times.max())}]")
        print(f"  -> Max Train ({max_train_t}) < Min Test ({min_test_t})? {max_train_t < min_test_t}")
        assert max_train_t < min_test_t, f"Data leakage detected in Fold {split_idx}!"

        # Fit models on train window
        dc_model.fit(df_train)
        xgb_model.fit(df_train)
        blend_model.fit(df_train)

        # Predict on test window
        p_dc = dc_model.predict_probs(df_test, use_dixon_coles=True)
        p_xgb = xgb_model.predict_probs(df_test)
        p_blend = blend_model.predict_probs(df_test)

        df_test_pd = df_test.to_pandas()
        line_col = "odds.over_under.line" if "odds.over_under.line" in df_test_pd.columns else "line_value"
        lines = df_test_pd[line_col].fillna(2.5).values.astype(float) if line_col in df_test_pd.columns else np.full(len(df_test_pd), 2.5)
        totals = (df_test_pd["home.goals"].values + df_test_pd["away.goals"].values).astype(float)
        is_win = (totals > lines).astype(float)

        for idx in range(len(df_test_pd)):
            t_val = df_test_pd["match_start_time"].iloc[idx] if "match_start_time" in df_test_pd.columns else df_test_pd["startedAt"].iloc[idx]
            
            odds_val = None
            for col_candidate in ["closingOdds.over_under.over", "odds.over_under.over", "odds_close"]:
                if col_candidate in df_test_pd.columns:
                    val = df_test_pd[col_candidate].iloc[idx]
                    if pd.notna(val) and float(val) > 1.0:
                        odds_val = float(val)
                        break
            if odds_val is None:
                odds_val = 1.90

            test_records.append({
                "match_id": df_test_pd["match_id"].iloc[idx],
                "startedAt": t_val,
                "odds_close": odds_val,
                "is_win": is_win[idx],
                "line_value": lines[idx],
            })
            dc_preds.append(p_dc[idx])
            xgb_preds.append(p_xgb[idx])
            blend_preds.append(p_blend[idx])
            actual_outcomes.append(is_win[idx])

    print(f"\nCompleted {split_idx} folds. Total test match samples evaluated: {len(test_records):,}")

    df_eval_base = pl.DataFrame(test_records)
    engine_unfiltered = BacktestEngine(global_odds_floor=1.60, min_confidence=0.0)

    print("\n==========================================================================")
    print(" 2. RAW MODEL PERFORMANCE WITHOUT CONFIDENCE FILTERING (MIN_CONFIDENCE = 0.0)")
    print("==========================================================================")
    
    # 1. Dixon Coles Raw
    df_dc_raw = df_eval_base.with_columns(pl.Series("confidence", dc_preds))
    res_dc_raw = engine_unfiltered.evaluate_tips(df_dc_raw, is_money_line=False)

    # 2. XGBoost Raw
    df_xgb_raw = df_eval_base.with_columns(pl.Series("confidence", xgb_preds))
    res_xgb_raw = engine_unfiltered.evaluate_tips(df_xgb_raw, is_money_line=False)

    # 3. Blended Model Raw
    df_blend_raw = df_eval_base.with_columns(pl.Series("confidence", blend_preds))
    res_blend_raw = engine_unfiltered.evaluate_tips(df_blend_raw, is_money_line=False)

    print(f"Dixon-Coles Raw:  {res_dc_raw['total_units']:,.2f} Units | ROI: {res_dc_raw['roi_pct']:.2f}% | Hit Rate: {res_dc_raw['hit_rate']*100:.2f}% | Tips: {res_dc_raw['tips_evaluated']:,}")
    print(f"XGBoost Raw:      {res_xgb_raw['total_units']:,.2f} Units | ROI: {res_xgb_raw['roi_pct']:.2f}% | Hit Rate: {res_xgb_raw['hit_rate']*100:.2f}% | Tips: {res_xgb_raw['tips_evaluated']:,}")
    print(f"Blended Raw:      {res_blend_raw['total_units']:,.2f} Units | ROI: {res_blend_raw['roi_pct']:.2f}% | Hit Rate: {res_blend_raw['hit_rate']*100:.2f}% | Tips: {res_blend_raw['tips_evaluated']:,}")

    print("\n==========================================================================")
    print(" 3. LEAKAGE DIAGNOSTIC: TEST-SET CALIBRATION VS OUT-OF-FOLD CALIBRATION")
    print("==========================================================================")

    # Post-hoc Test Set Calibrator (LEAKAGE)
    calibrator_leaked = ConfidenceCalibrator(method="isotonic")
    leaked_conf = calibrator_leaked.fit(np.array(xgb_preds), np.array(actual_outcomes)).predict_confidence(np.array(xgb_preds))
    
    engine_filtered = BacktestEngine(global_odds_floor=1.60, min_confidence=0.50)
    df_leaked = df_eval_base.with_columns(pl.Series("confidence", leaked_conf))
    res_leaked = engine_filtered.evaluate_tips(df_leaked, is_money_line=False)

    print(f"[TEST SET CALIBRATION LEAKAGE]:  {res_leaked['total_units']:,.2f} Units | ROI: {res_leaked['roi_pct']:.2f}% | Hit Rate: {res_leaked['hit_rate']*100:.2f}% | Tips: {res_leaked['tips_evaluated']:,}")

    # Proper Value Edge Filter (P_model > Implied Probability = 1 / odds_close)
    df_edge = df_eval_base.with_columns(
        pl.Series("confidence", xgb_preds),
        (pl.Series("confidence", xgb_preds) - (1.0 / pl.col("odds_close"))).alias("edge")
    ).filter(pl.col("edge") > 0.02)  # 2% value edge over bookmaker odds

    res_edge = engine_unfiltered.evaluate_tips(df_edge, is_money_line=False)
    print(f"[PROPER VALUE EDGE FILTER (>2%)]: {res_edge['total_units']:,.2f} Units | ROI: {res_edge['roi_pct']:.2f}% | Hit Rate: {res_edge['hit_rate']*100:.2f}% | Tips: {res_edge['tips_evaluated']:,}")


if __name__ == "__main__":
    run_empirical_audit()
