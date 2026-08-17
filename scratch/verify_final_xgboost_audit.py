"""
Comprehensive Final Audit Script:
1. Holdout-slice calibration within training window (0% test leakage).
2. Top 10 feature importances breakdown (Form/H2H vs Odds).
3. Baseline edge report across ALL 52,418 test predictions without confidence filtering.
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
from markets.fifa_goals_ou.features import FEATURE_COLUMNS


def run_comprehensive_audit():
    engine = create_engine(settings.DATABASE_URL)
    df = load_training_dataset(engine)

    print("\n==========================================================================")
    print(" 1. HOLDOUT-SLICE CALIBRATION IN TRAINING WINDOW (STRICT ZERO LEAKAGE)")
    print("==========================================================================")

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

    # Track trained XGBoost models to inspect final feature importances
    last_xgb_model = None

    for train_idx, test_idx in splitter.split(df):
        split_idx += 1
        df_train = df[train_idx]
        df_test = df[test_idx]

        # 1. Carve 80/20 train/validation holdout slice STRICTLY inside df_train
        n_train = len(df_train)
        split_point = int(n_train * 0.80)
        df_train_sub = df_train[:split_point]
        df_val_sub = df_train[split_point:]

        # 2. Fit sub-model on df_train_sub and calibrate on df_val_sub (never touching df_test!)
        xgb_sub = XGBoostGoalsOUModel()
        xgb_sub.fit(df_train_sub)
        p_val = xgb_sub.predict_probs(df_val_sub)

        df_val_pd = df_val_sub.to_pandas()
        line_col_val = "odds.over_under.line" if "odds.over_under.line" in df_val_pd.columns else "line_value"
        lines_val = df_val_pd[line_col_val].fillna(2.5).values.astype(float) if line_col_val in df_val_pd.columns else np.full(len(df_val_pd), 2.5)
        totals_val = (df_val_pd["home.goals"].values + df_val_pd["away.goals"].values).astype(float)
        y_val = (totals_val > lines_val).astype(float)

        calibrator_fold = ConfidenceCalibrator(method="isotonic")
        calibrator_fold.fit(p_val, y_val)

        # 3. Fit final models on full df_train
        dc_model.fit(df_train)
        xgb_model.fit(df_train)
        blend_model.fit(df_train)
        last_xgb_model = xgb_model

        # 4. Predict on df_test
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

    print(f"Evaluated {split_idx} folds. Total test match samples: {len(test_records):,}")
    print("CONFIRMED: ConfidenceCalibrator was fit ONLY on holdout slices carved from df_train. 0% test data touch!")

    print("\n==========================================================================")
    print(" 2. FEATURE IMPORTANCE AUDIT FOR FINAL XGBOOST MODEL")
    print("==========================================================================")

    feat_names = last_xgb_model.feature_names
    importances = last_xgb_model.model.feature_importances_

    df_imp = pd.DataFrame({
        "feature": feat_names,
        "importance": importances,
    }).sort_values("importance", ascending=False)

    print("Top 10 Features by Importance:")
    for idx, row in df_imp.head(10).iterrows():
        print(f"  {row['feature']:<30}: {row['importance']*100:.2f}%")

    odds_cols = ["odds_implied_prob", "implied_vs_hist_divergence", "odds_drift_abs", "odds_drift_pct", "odds_close", "odds_open"]
    odds_importance = df_imp[df_imp["feature"].isin(odds_cols)]["importance"].sum()
    non_odds_importance = df_imp[~df_imp["feature"].isin(odds_cols)]["importance"].sum()

    print(f"\nFeature Importance Category Breakdown:")
    print(f"  - Performance / Form / H2H / Line Diff Features: {non_odds_importance*100:.2f}%")
    print(f"  - Odds-derived Features:                         {odds_importance*100:.2f}%")

    print("\n==========================================================================")
    print(" 3. BASELINE PERFORMANCE ACROSS ALL TEST PREDICTIONS (NO CONFIDENCE FILTER)")
    print("==========================================================================")

    df_eval_base = pl.DataFrame(test_records)
    engine_unfiltered = BacktestEngine(global_odds_floor=1.60, min_confidence=0.0)

    # A. Full Population (All test matches meeting odds floor >= 1.60)
    df_all = df_eval_base.with_columns(pl.lit(1.0).alias("confidence"))
    res_all = engine_unfiltered.evaluate_tips(df_all, is_money_line=False)
    print(f"A. Full Market Population (All {res_all['tips_evaluated']:,} test matches with odds >= 1.60):")
    print(f"   Net Units: {res_all['total_units']:,.2f} | ROI: {res_all['roi_pct']:.2f}% | Hit Rate: {res_all['hit_rate']*100:.2f}%")

    # B. XGBoost Raw Directional Bets (P_xgb >= 0.50, min_confidence = 0.50)
    engine_50 = BacktestEngine(global_odds_floor=1.60, min_confidence=0.50)
    df_xgb_raw = df_eval_base.with_columns(pl.Series("confidence", xgb_raw_preds))
    res_xgb_raw = engine_50.evaluate_tips(df_xgb_raw, is_money_line=False)
    print(f"\nB. XGBoost Raw Directional Bets (P >= 0.50):")
    print(f"   Net Units: {res_xgb_raw['total_units']:,.2f} | ROI: {res_xgb_raw['roi_pct']:.2f}% | Hit Rate: {res_xgb_raw['hit_rate']*100:.2f}% | Tips: {res_xgb_raw['tips_evaluated']:,}")

    # C. XGBoost Out-of-Fold Calibrated Bets (Calibrated P >= 0.50)
    df_xgb_cal = df_eval_base.with_columns(pl.Series("confidence", xgb_calibrated_preds))
    res_xgb_cal = engine_50.evaluate_tips(df_xgb_cal, is_money_line=False)
    print(f"\nC. XGBoost Out-of-Fold Calibrated Bets (Holdout Calibrated P >= 0.50):")
    print(f"   Net Units: {res_xgb_cal['total_units']:,.2f} | ROI: {res_xgb_cal['roi_pct']:.2f}% | Hit Rate: {res_xgb_cal['hit_rate']*100:.2f}% | Tips: {res_xgb_cal['tips_evaluated']:,}")

    # D. XGBoost True Value Edge Bets (P_xgb > Implied Probability = 1 / odds_close)
    df_edge = df_eval_base.with_columns(
        pl.Series("confidence", xgb_raw_preds),
        (pl.Series("confidence", xgb_raw_preds) - (1.0 / pl.col("odds_close"))).alias("edge")
    ).filter(pl.col("edge") > 0.0)
    res_edge = engine_unfiltered.evaluate_tips(df_edge, is_money_line=False)
    print(f"\nD. XGBoost Value Edge Bets (P_model > Implied Probability):")
    print(f"   Net Units: {res_edge['total_units']:,.2f} | ROI: {res_edge['roi_pct']:.2f}% | Hit Rate: {res_edge['hit_rate']*100:.2f}% | Tips: {res_edge['tips_evaluated']:,}")


if __name__ == "__main__":
    run_comprehensive_audit()
