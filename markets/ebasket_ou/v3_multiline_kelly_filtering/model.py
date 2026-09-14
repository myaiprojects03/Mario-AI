"""
eBasketball Over/Under V3 Model Pipeline (Multi-Line Expansion, Combined Pace & Quarter-Kelly Staking).
"""

import os
import sys
import logging
from typing import Dict, Any, List, Tuple

import joblib
import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import create_engine
from xgboost import XGBClassifier

sys.path.insert(0, ".")
from core.config.settings import settings
from core.validation.walk_forward import WalkForwardSplitter
from markets.ebasket_ou.v3_multiline_kelly_filtering.features import build_ebasket_ou_v3_features
from markets._shared.multiline_v3_features import evaluate_percentile_tiers_with_kelly

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("markets.ebasket_ou.v3.model")

MODEL_VERSION = "v3.0.0"
ODDS_FLOOR = 1.60


def load_training_dataset(engine) -> pl.DataFrame:
    logger.info("Querying PostgreSQL core.matches for eBasketball O/U V3 dataset...")
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
        CAST(o.line_value AS FLOAT) AS "line_value",
        CAST(o.odds_open AS FLOAT) AS "odds.over_under.over",
        CAST(o.odds_close AS FLOAT) AS "closingOdds.over_under.over",
        CAST(o.odds_close AS FLOAT) AS "odds_close"
    FROM core.matches m
    JOIN core.results r ON m.match_id = r.match_id
    JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = 'ebasket_ou' AND o.side = 'over'
    WHERE m.sport = 'ebasket' AND m.source IN ('csv_backfill', 'jarbet_history')
    ORDER BY m.match_id, m.match_start_time ASC
    """

    with engine.connect() as conn:
        df_pd = pd.read_sql(sql, conn)
        df_raw = pl.from_pandas(df_pd)

    df_features_sub = build_ebasket_ou_v3_features(df_raw)
    meta_cols = ["match_id", "startedAt", "match_start_time", "home.goals", "away.goals", "closingOdds.over_under.over", "odds_close", "line_value"]
    meta_cols = [c for c in meta_cols if c in df_raw.columns and c not in df_features_sub.columns]
    meta_cols.insert(0, "match_id")

    df_features = df_raw.select(meta_cols).join(df_features_sub, on="match_id", how="inner")
    logger.info(f"Loaded {len(df_features):,} eBasketball O/U V3 training matches.")
    return df_features


def run_v3_backtest(df: pl.DataFrame) -> Tuple[Any, List[Dict[str, Any]], List[Dict[str, Any]]]:
    splitter = WalkForwardSplitter(train_days=45, test_days=7, step_days=7, time_col="match_start_time")
    feature_cols = [c for c in df.columns if c not in [
        "match_id", "startedAt", "match_start_time", "home.goals", "away.goals",
        "final_home_score", "final_away_score", "closingOdds.over_under.over", "odds_close", "line_value",
        "league", "home_player", "away_player", "home_team", "away_team", "duration_minutes", "source"
    ]]

    test_records = []
    final_xgb = None

    for train_idx, test_idx in splitter.split(df):
        df_tr = df[train_idx].to_pandas()
        df_te = df[test_idx].to_pandas()

        X_tr = df_tr[feature_cols].fillna(0).values
        line_tr = df_tr["line_value"].values
        y_tr = (df_tr["home.goals"].values + df_tr["away.goals"].values > line_tr).astype(int)

        X_te = df_te[feature_cols].fillna(0).values
        line_te = df_te["line_value"].values
        y_te = (df_te["home.goals"].values + df_te["away.goals"].values > line_te).astype(float)

        xgb = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42, eval_metric="logloss")
        xgb.fit(X_tr, y_tr)
        final_xgb = xgb
        p_te = xgb.predict_proba(X_te)[:, 1]

        for idx in range(len(df_te)):
            odds_close = df_te["odds_close"].iloc[idx] if "odds_close" in df_te.columns else 1.83
            if pd.isna(odds_close) or float(odds_close) <= 1.0:
                odds_close = 1.83

            odds_close = float(odds_close)
            p_over = float(p_te[idx])
            p_under = 1.0 - p_over

            edge_over = p_over - (1.0 / odds_close)
            edge_under = p_under - (1.0 / odds_close)

            if edge_over >= 0.020 and odds_close >= ODDS_FLOOR:
                test_records.append({
                    "match_id": df_te["match_id"].iloc[idx],
                    "startedAt": df_te["startedAt"].iloc[idx],
                    "side": "over",
                    "line": line_te[idx],
                    "odds_close": odds_close,
                    "is_win": y_te[idx],
                    "confidence": p_over,
                    "edge": edge_over,
                })

            if edge_under >= 0.020 and odds_close >= ODDS_FLOOR:
                test_records.append({
                    "match_id": df_te["match_id"].iloc[idx],
                    "startedAt": df_te["startedAt"].iloc[idx],
                    "side": "under",
                    "line": line_te[idx],
                    "odds_close": odds_close,
                    "is_win": 1.0 - y_te[idx],
                    "confidence": p_under,
                    "edge": edge_under,
                })

    tier_results = evaluate_percentile_tiers_with_kelly(test_records, percentiles=[100, 90, 80, 70, 50], odds_floor=ODDS_FLOOR)
    return final_xgb, test_records, tier_results


def save_v3_artifacts(model: Any, tier_results: List[Dict[str, Any]], total_rows: int):
    artifact_dir = "markets/ebasket_ou/v3_multiline_kelly_filtering/artifacts"
    os.makedirs(artifact_dir, exist_ok=True)

    with open(os.path.join(artifact_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*.joblib\n*.pkl\n*.bin\n")

    model_file = os.path.join(artifact_dir, f"ebasket_ou_model_{MODEL_VERSION}.joblib")
    joblib.dump(model, model_file)
    logger.info(f"Saved V3 model artifact to {model_file}")

    md_content = f"""# eBasketball Over/Under V3 Model Results Report

## Executive Summary
- **Model Version**: `{MODEL_VERSION}`
- **Training Matches Used**: **{total_rows:,} matches** (`csv_backfill` + `jarbet_history`)
- **Odds Floor**: **{ODDS_FLOOR:.2f} Minimum Odds Floor**

---

## Filter Sweet-Spot Comparison Matrix (Flat Staking vs Quarter-Kelly)

| Filter Tier | Tips Evaluated | Daily Tips | Hit Rate (%) | Flat Net Units | Flat Units/Mo | Flat ROI (%) | Kelly Net Units | Kelly Units/Mo | Kelly ROI (%) |
|---|---|---|---|---|---|---|---|---|---|
"""
    for r in tier_results:
        md_content += f"| `{r['tier_name']}` | {r['tips_evaluated']:,} | {r['daily_tips']} | {r['hit_rate']:.2f}% | {r['flat_total_units']:+,.2f} | {r['flat_monthly_rate']:+,.2f} | {r['flat_roi']:+.2f}% | **{r['kelly_total_units']:+,.2f}** | **{r['kelly_monthly_rate']:+,.2f}** | **{r['kelly_roi']:+.2f}%** |\n"

    report_path = "markets/ebasket_ou/v3_multiline_kelly_filtering/RESULTS.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    logger.info(f"Wrote V3 performance report to {report_path}")


def main():
    engine = create_engine(settings.DATABASE_URL)
    df_train = load_training_dataset(engine)
    model, _, tier_results = run_v3_backtest(df_train)
    save_v3_artifacts(model, tier_results, len(df_train))


if __name__ == "__main__":
    main()
