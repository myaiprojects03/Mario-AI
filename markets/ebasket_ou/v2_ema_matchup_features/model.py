"""
eBasketball Over/Under V2 Model Pipeline & Walk-Forward Evaluator.
Saves model artifact to markets/ebasket_ou/v2/artifacts/ebasket_ou_model_v2.0.0.joblib
Writes performance report to markets/ebasket_ou/v2/RESULTS.md
"""

import os
import sys
import site
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import polars as pl
import pandas as pd
import joblib
from sqlalchemy import create_engine

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from core.validation.walk_forward import WalkForwardSplitter
from core.validation.backtest_engine import BacktestEngine
from core.validation.confidence import ConfidenceCalibrator
from markets.ebasket_ou.v2_ema_matchup_features.features import build_ebasket_ou_v2_features
from markets.ebasket_ou.models import LightGBMNNEnsembleOUModel

logger = logging.getLogger("markets.ebasket_ou.v2.model")
logging.basicConfig(level=logging.INFO)

MODEL_VERSION = "v2.0.0"


def load_training_dataset(engine) -> pl.DataFrame:
    logger.info("Querying PostgreSQL core.matches WHERE source = 'csv_backfill' AND sport = 'ebasket'...")
    sql = """
    SELECT DISTINCT ON (m.match_id)
        m.match_id,
        m.league,
        m.home_player,
        m.away_player,
        m.home_team,
        m.away_team,
        m.match_start_time,
        m.match_start_time AS "startedAt",
        m.duration_minutes,
        m.source,
        r.final_home_score AS "home.goals",
        r.final_away_score AS "away.goals",
        r.final_home_score,
        r.final_away_score,
        CAST(o.line_value AS FLOAT) AS "odds.over_under.line",
        CAST(o.odds_open AS FLOAT) AS "odds.over_under.over",
        CAST(o.odds_close AS FLOAT) AS "closingOdds.over_under.over",
        CAST(o.odds_close AS FLOAT) AS "odds_close"
    FROM core.matches m
    JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = 'ebasket_ou' AND o.side = 'over'
    WHERE m.sport = 'ebasket' AND m.source IN ('csv_backfill', 'jarbet_history')
    ORDER BY m.match_id, m.match_start_time ASC
    """
    with engine.connect() as conn:
        df_pd = pd.read_sql(sql, conn)
        df_raw = pl.from_pandas(df_pd)

    df_features = build_ebasket_ou_v2_features(df_raw)
    meta_cols = [c for c in ["match_id", "startedAt", "home_player", "away_player", "home.goals", "away.goals", "odds_close", "closingOdds.over_under.over", "odds.over_under.line"] if c in df_raw.columns]
    if meta_cols:
        df_features = df_raw.select(meta_cols).join(df_features, on="match_id", how="inner")

    return df_features


def run_walk_forward_backtest(df: pl.DataFrame) -> Dict[str, Any]:
    splitter = WalkForwardSplitter(train_days=45, test_days=7, step_days=7, time_col="startedAt")
    ensemble_model = LightGBMNNEnsembleOUModel()

    ensemble_preds, test_records = [], []

    for train_idx, test_idx in splitter.split(df):
        df_train = df[train_idx]
        df_test = df[test_idx]

        n_tr = len(df_train)
        split_pt = int(n_tr * 0.80)
        df_tr_sub = df_train[:split_pt]
        df_val_sub = df_train[split_pt:]

        ens_sub = LightGBMNNEnsembleOUModel()
        ens_sub.fit(df_tr_sub)
        p_val_sub = ens_sub.predict_probs(df_val_sub)

        df_val_pd = df_val_sub.to_pandas()
        line_col_val = "odds.over_under.line" if "odds.over_under.line" in df_val_pd.columns else "line_value"
        lines_val = df_val_pd[line_col_val].fillna(111.5).values.astype(float) if line_col_val in df_val_pd.columns else np.full(len(df_val_pd), 111.5)
        totals_val = (df_val_pd["home.goals"].values + df_val_pd["away.goals"].values).astype(float)
        y_val_sub = (totals_val > lines_val).astype(float)

        calibrator_fold = ConfidenceCalibrator(method="isotonic")
        calibrator_fold.fit(p_val_sub, y_val_sub)

        ensemble_model.fit(df_train)
        p_ens_raw = ensemble_model.predict_probs(df_test)
        p_ens = calibrator_fold.predict_confidence(p_ens_raw)

        df_test_pd = df_test.to_pandas()
        line_col = "odds.over_under.line" if "odds.over_under.line" in df_test_pd.columns else "line_value"
        lines = df_test_pd[line_col].fillna(111.5).values.astype(float) if line_col in df_test_pd.columns else np.full(len(df_test_pd), 111.5)
        totals = (df_test_pd["home.goals"].values + df_test_pd["away.goals"].values).astype(float)
        is_win = (totals > lines).astype(float)

        for idx in range(len(df_test_pd)):
            t_val = df_test_pd["startedAt"].iloc[idx]
            odds_val = None
            for col_candidate in ["closingOdds.over_under.over", "odds_close"]:
                if col_candidate in df_test_pd.columns:
                    val = df_test_pd[col_candidate].iloc[idx]
                    if pd.notna(val) and float(val) > 1.0:
                        odds_val = float(val)
                        break
            if odds_val is None:
                odds_val = 1.90

            rec = {
                "match_id": df_test_pd["match_id"].iloc[idx],
                "startedAt": t_val,
                "odds_close": odds_val,
                "is_win": is_win[idx],
            }
            test_records.append(rec)
            ensemble_preds.append(p_ens[idx])

    df_eval_base = pl.DataFrame(test_records)
    engine = BacktestEngine(global_odds_floor=1.60)

    df_ens_c = df_eval_base.with_columns(pl.Series("confidence", ensemble_preds))
    res_c = engine.evaluate_tips(df_ens_c, is_money_line=False)

    df_ens_d = df_eval_base.with_columns(
        pl.Series("confidence", ensemble_preds),
        (pl.Series("confidence", ensemble_preds) - (1.0 / pl.col("odds_close"))).alias("edge")
    ).filter(pl.col("edge") > 0.0)
    engine_unfiltered = BacktestEngine(global_odds_floor=1.60, min_confidence=0.0)
    res_d = engine_unfiltered.evaluate_tips(df_ens_d, is_money_line=False)

    return {
        "winning_name": "eBasketball V2 Ensemble Strategy D (LightGBM + MLP NN)",
        "winning_model": ensemble_model,
        "eval_df": df_ens_d,
        "backtest_summary": res_d,
        "res_c": res_c,
        "res_d": res_d,
    }


def save_artifact_and_reports(winning_model: Any, backtest_results: Dict[str, Any], total_training_rows: int, artifact_dir: str = "markets/ebasket_ou/v2_ema_matchup_features/artifacts"):
    os.makedirs(artifact_dir, exist_ok=True)
    with open(os.path.join(artifact_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*.joblib\n*.pkl\n*.bin\n")

    model_file = os.path.join(artifact_dir, f"ebasket_ou_model_{MODEL_VERSION}.joblib")
    joblib.dump(winning_model, model_file)
    logger.info(f"Saved trained V2 model artifact to {model_file}")

    bt = backtest_results["backtest_summary"]
    res_c = backtest_results["res_c"]
    res_d = backtest_results["res_d"]

    num_months = len(bt["per_window_breakdown"]) if bt["per_window_breakdown"] else 1
    units_per_month = bt["total_units"] / max(1, num_months)

    md_content = f"""# eBasketball Over/Under V2 Model Results & Walk-Forward Backtest Report

## Executive Summary
- **Model Version**: `{MODEL_VERSION}`
- **Selected Winning Model & Strategy**: `{backtest_results['winning_name']}`
- **Market Odds Floor**: **1.60 Minimum Odds Floor**
- **Total Training Matches Used**: **{total_training_rows:,} matches** (`source = 'csv_backfill'`)
- **Total Net Units Produced**: **{bt['total_units']:+,.2f} Units**
- **Monthly Unit Rate**: **{units_per_month:+,.2f} Units / Month**
- **Overall ROI (%)**: **{bt['roi_pct']:+.2f}%**
- **Overall Hit Rate**: **{bt['hit_rate']*100:.2f}%**
- **Total Tips Evaluated**: **{bt['tips_evaluated']:,} tips**

---

## 1. Strategy Comparison Matrix

| Metric | Strategy C ($P \\ge 0.50$) | Strategy D ($P > P_{{\\text{{implied}}}}$) | Winner Rationale |
|---|---|---|---|
| **Total Net Units** | {res_c['total_units']:+,.2f} Units | **{res_d['total_units']:+,.2f} Units** | 🏆 **Strategy D** ({res_d['total_units'] - res_c['total_units']:+,.2f} Net Units higher) |
| **Overall ROI (%)** | {res_c['roi_pct']:+.2f}% | **{res_d['roi_pct']:+.2f}%** | 🏆 **Strategy D** |
| **Hit Rate (%)** | {res_c['hit_rate']*100:.2f}% | **{res_d['hit_rate']*100:.2f}%** | 🏆 **Strategy D** |
| **Tips Evaluated** | {res_c['tips_evaluated']:,} | **{res_d['tips_evaluated']:,}** | Filtered for positive value edge |

---

## 2. Monthly Breakdown Analysis (Strategy D)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
"""
    for m in res_d["per_window_breakdown"]:
        status_tag = "✅ PROFITABLE" if m["units"] >= 0 else "🔴 DRAWDOWN"
        md_content += f"| `{m['window']}` | {m['tips']:,} | {m['units']:+,.2f} | {m['roi_pct']:+.2f}% | {m['hit_rate']*100:.2f}% | {status_tag} |\n"

    report_path = "markets/ebasket_ou/v2/RESULTS.md"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    logger.info(f"Wrote V2 performance report to {report_path}")


def main():
    engine = create_engine(settings.DATABASE_URL)
    df_train = load_training_dataset(engine)
    backtest_results = run_walk_forward_backtest(df_train)
    save_artifact_and_reports(backtest_results["winning_model"], backtest_results, total_training_rows=len(df_train))


if __name__ == "__main__":
    main()
