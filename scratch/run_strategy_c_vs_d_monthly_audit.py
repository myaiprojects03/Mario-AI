"""
Script to compute calendar month-by-month breakdown for Strategy C vs Strategy D.
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


def run_monthly_audit():
    engine = create_engine(settings.DATABASE_URL)
    df = load_training_dataset(engine)

    splitter = WalkForwardSplitter(
        train_days=45,
        test_days=7,
        step_days=7,
        time_col="match_start_time",
    )

    split_idx = 0
    test_records = []
    xgb_raw_preds, xgb_calibrated_preds = [], []
    dc_preds, blend_preds = [], []
    actual_outcomes = []

    dc_model = PoissonDixonColesModel()
    xgb_model = XGBoostGoalsOUModel()
    blend_model = BlendedGoalsOUModel(weight_xgb=0.60)

    for train_idx, test_idx in splitter.split(df):
        split_idx += 1
        df_train = df[train_idx]
        df_test = df[test_idx]

        # Inner Holdout Calibration (80/20 train/validation split inside df_train)
        n_tr = len(df_train)
        split_pt = int(n_tr * 0.80)
        df_tr_sub = df_train[:split_pt]
        df_val_sub = df_train[split_pt:]

        xgb_sub = XGBoostGoalsOUModel()
        xgb_sub.fit(df_tr_sub)
        p_val_sub = xgb_sub.predict_probs(df_val_sub)

        df_val_pd = df_val_sub.to_pandas()
        line_col_val = "odds.over_under.line" if "odds.over_under.line" in df_val_pd.columns else "line_value"
        lines_val = df_val_pd[line_col_val].fillna(2.5).values.astype(float) if line_col_val in df_val_pd.columns else np.full(len(df_val_pd), 2.5)
        totals_val = (df_val_pd["home.goals"].values + df_val_pd["away.goals"].values).astype(float)
        y_val_sub = (totals_val > lines_val).astype(float)

        calibrator_fold = ConfidenceCalibrator(method="isotonic")
        calibrator_fold.fit(p_val_sub, y_val_sub)

        # Fit final models on full df_train
        dc_model.fit(df_train)
        xgb_model.fit(df_train)
        blend_model.fit(df_train)

        # Predict on df_test
        p_dc = dc_model.predict_probs(df_test, use_dixon_coles=True)
        p_xgb_raw = xgb_model.predict_probs(df_test)
        p_xgb_cal = calibrator_fold.predict_confidence(p_xgb_raw)
        p_blend = blend_model.predict_probs(df_test)

        df_test_pd = df_test.to_pandas()
        line_col_test = "odds.over_under.line" if "odds.over_under.line" in df_test_pd.columns else "line_value"
        lines_test = df_test_pd[line_col_test].fillna(2.5).values.astype(float) if line_col_test in df_test_pd.columns else np.full(len(df_test_pd), 2.5)
        totals_test = (df_test_pd["home.goals"].values + df_test_pd["away.goals"].values).astype(float)
        is_win = (totals_test > lines_test).astype(float)

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
                "line_value": lines_test[idx],
            })
            dc_preds.append(p_dc[idx])
            xgb_raw_preds.append(p_xgb_raw[idx])
            xgb_calibrated_preds.append(p_xgb_cal[idx])
            blend_preds.append(p_blend[idx])
            actual_outcomes.append(is_win[idx])

    df_eval_base = pl.DataFrame(test_records)
    engine_50 = BacktestEngine(global_odds_floor=1.60, min_confidence=0.50)
    engine_unfiltered = BacktestEngine(global_odds_floor=1.60, min_confidence=0.0)

    # Strategy C: Out-of-fold Calibrated (P_cal >= 0.50)
    df_strat_c = df_eval_base.with_columns(pl.Series("confidence", xgb_calibrated_preds))
    res_c = engine_50.evaluate_tips(df_strat_c, is_money_line=False)

    # Strategy D: Value Edge (P_raw > Implied = 1 / odds_close)
    df_strat_d = df_eval_base.with_columns(
        pl.Series("confidence", xgb_raw_preds),
        (pl.Series("confidence", xgb_raw_preds) - (1.0 / pl.col("odds_close"))).alias("edge")
    ).filter(pl.col("edge") > 0.0)
    res_d = engine_unfiltered.evaluate_tips(df_strat_d, is_money_line=False)

    print("\n==========================================================================")
    print(" MONTHLY BREAKDOWN COMPARISON: STRATEGY C VS STRATEGY D")
    print("==========================================================================")
    print("STRATEGY C (Holdout Calibrated P >= 0.50):")
    print(f"Total Units: +{res_c['total_units']:,.2f} | ROI: {res_c['roi_pct']:.2f}% | Hit Rate: {res_c['hit_rate']*100:.2f}% | Tips: {res_c['tips_evaluated']:,}")
    for m in res_c["per_window_breakdown"]:
        flag = "[NEGATIVE/DRAWDOWN]" if m["units"] < 0 else "[POSITIVE]"
        print(f"  Month: {m['window']} | Tips: {m['tips']:,} | Units: {m['units']:+,.2f} | ROI: {m['roi_pct']:+.2f}% | Hit Rate: {m['hit_rate']*100:.2f}% {flag}")

    print("\nSTRATEGY D (Value Edge: P_model > P_implied):")
    print(f"Total Units: +{res_d['total_units']:,.2f} | ROI: {res_d['roi_pct']:.2f}% | Hit Rate: {res_d['hit_rate']*100:.2f}% | Tips: {res_d['tips_evaluated']:,}")
    for m in res_d["per_window_breakdown"]:
        flag = "[NEGATIVE/DRAWDOWN]" if m["units"] < 0 else "[POSITIVE]"
        print(f"  Month: {m['window']} | Tips: {m['tips']:,} | Units: {m['units']:+,.2f} | ROI: {m['roi_pct']:+.2f}% | Hit Rate: {m['hit_rate']*100:.2f}% {flag}")


if __name__ == "__main__":
    run_monthly_audit()
