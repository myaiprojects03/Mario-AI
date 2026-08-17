import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import create_engine
from core.config.settings import settings
from core.validation.backtest_engine import BacktestEngine
from markets.fifa_money_line.model import load_training_dataset, run_walk_forward_backtest

engine = create_engine(settings.DATABASE_URL)
df_train = load_training_dataset(engine)

# We can run walk-forward and test various strategy filters on the predictions
from core.validation.walk_forward import WalkForwardSplitter
from core.validation.confidence import ConfidenceCalibrator
from markets.fifa_money_line.models import (
    MultinomialLogisticMLModel,
    LightGBMMoneyLineModel,
    BlendedMoneyLineModel,
)

splitter = WalkForwardSplitter(train_days=45, test_days=7, step_days=7, time_col="match_start_time")
logistic_model = MultinomialLogisticMLModel()
lgbm_model = LightGBMMoneyLineModel()
blend_model = BlendedMoneyLineModel(weight_lgb=0.60)

test_records = []
log_preds, lgb_preds, blend_preds = [], [], []

print("Running walk forward splits...")
for train_idx, test_idx in splitter.split(df_train):
    df_tr = df_train[train_idx]
    df_te = df_train[test_idx]

    n_tr = len(df_tr)
    split_pt = int(n_tr * 0.80)
    df_tr_sub = df_tr[:split_pt]
    df_val_sub = df_tr[split_pt:]

    lgb_sub = LightGBMMoneyLineModel()
    lgb_sub.fit(df_tr_sub)
    p_val_sub = lgb_sub.predict_probs(df_val_sub)

    df_val_pd = df_val_sub.to_pandas()
    y_val_sub = (df_val_pd["home.goals"].values > df_val_pd["away.goals"].values).astype(float)

    calibrator = ConfidenceCalibrator(method="isotonic")
    calibrator.fit(p_val_sub, y_val_sub)

    logistic_model.fit(df_tr)
    lgbm_model.fit(df_tr)
    blend_model.fit(df_tr)

    p_log = logistic_model.predict_probs(df_te)
    p_lgb = calibrator.predict_confidence(lgbm_model.predict_probs(df_te))
    p_blend = blend_model.predict_probs(df_te)

    df_te_pd = df_te.to_pandas()
    is_win = (df_te_pd["home.goals"].values > df_te_pd["away.goals"].values).astype(float)

    for idx in range(len(df_te_pd)):
        odds_val = df_te_pd["closingOdds.money_line.home"].iloc[idx] if "closingOdds.money_line.home" in df_te_pd.columns else 1.90
        if pd.isna(odds_val) or float(odds_val) <= 1.0:
            odds_val = 1.90
        test_records.append({
            "match_id": df_te_pd["match_id"].iloc[idx],
            "startedAt": df_te_pd["startedAt"].iloc[idx],
            "odds_close": float(odds_val),
            "is_win": is_win[idx],
        })
        log_preds.append(p_log[idx])
        lgb_preds.append(p_lgb[idx])
        blend_preds.append(p_blend[idx])

df_eval = pl.DataFrame(test_records)
engine = BacktestEngine(global_odds_floor=1.70, money_line_floor=1.70)

print("\n=== STRATEGY AUDIT ON MONEY LINE (1.70 ODDS FLOOR) ===")
for name, preds in [("Logistic", log_preds), ("LightGBM", lgb_preds), ("Blend", blend_preds)]:
    print(f"\n--- {name} ---")
    for p_min in [0.40, 0.45, 0.50, 0.55, 0.60]:
        df_p = df_eval.with_columns(pl.Series("confidence", preds))
        eng = BacktestEngine(global_odds_floor=1.70, money_line_floor=1.70, min_confidence=p_min)
        res = eng.evaluate_tips(df_p, is_money_line=True)
        print(f"P >= {p_min:.2f}: Units: {res['total_units']:+,.2f} | ROI: {res['roi_pct']:+.2f}% | Hit Rate: {res['hit_rate']*100:.2f}% | Tips: {res['tips_evaluated']}")

    for edge_min in [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]:
        df_edge = df_eval.with_columns(
            pl.Series("confidence", preds),
            (pl.Series("confidence", preds) - (1.0 / pl.col("odds_close"))).alias("edge")
        ).filter(pl.col("edge") >= edge_min)
        eng = BacktestEngine(global_odds_floor=1.70, money_line_floor=1.70, min_confidence=0.0)
        res = eng.evaluate_tips(df_edge, is_money_line=True)
        print(f"Value Edge >= {edge_min:.2f}: Units: {res['total_units']:+,.2f} | ROI: {res['roi_pct']:+.2f}% | Hit Rate: {res['hit_rate']*100:.2f}% | Tips: {res['tips_evaluated']}")
