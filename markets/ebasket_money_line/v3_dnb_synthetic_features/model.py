"""
eBasketball Money Line V3 DNB Model Pipeline (Step 1 DNB Transform & Step 3 Quarter Pace Features).
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
from markets.ebasket_money_line.v3_dnb_synthetic_features.features import build_ebasket_ml_v3_features
from markets._shared.multiline_v3_features import calculate_quarter_kelly_stake

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("markets.ebasket_money_line.v3.model")

MODEL_VERSION = "v3.0.0"
ODDS_FLOOR = 1.40


def load_training_dataset(engine) -> pl.DataFrame:
    logger.info("Querying PostgreSQL core.matches for eBasketball Money Line V3 dataset...")
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
        CAST(o.odds_open AS FLOAT) AS "odds.money_line.home",
        CAST(o.odds_close AS FLOAT) AS "closingOdds.money_line.home",
        CAST(o.odds_close AS FLOAT) AS "odds_close"
    FROM core.matches m
    JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = 'ebasket_money_line' AND o.side = 'home'
    WHERE m.sport = 'ebasket' AND m.source IN ('csv_backfill', 'jarbet_history')
    ORDER BY m.match_id, m.match_start_time ASC
    """

    with engine.connect() as conn:
        df_pd = pd.read_sql(sql, conn)
        df_raw = pl.from_pandas(df_pd)

    df_features_sub = build_ebasket_ml_v3_features(df_raw)
    meta_cols = ["match_id", "startedAt", "match_start_time", "home.goals", "away.goals", "closingOdds.money_line.home", "odds_close"]
    meta_cols = [c for c in meta_cols if c in df_raw.columns and c not in df_features_sub.columns]
    meta_cols.insert(0, "match_id")

    df_features = df_raw.select(meta_cols).join(df_features_sub, on="match_id", how="inner")
    logger.info(f"Loaded {len(df_features):,} eBasketball Money Line V3 training matches.")
    return df_features


def evaluate_dnb_tiers(test_records: List[Dict[str, Any]], percentiles: List[int] = [100, 90, 80, 70, 50]) -> List[Dict[str, Any]]:
    if not test_records:
        return []

    df_rec = pd.DataFrame(test_records)
    total_days = max(1, (df_rec["startedAt"].max() - df_rec["startedAt"].min()).days)
    months = total_days / 30.0

    df_rec = df_rec.sort_values(by="edge", ascending=False).reset_index(drop=True)
    results = []

    for p in percentiles:
        cutoff = int(np.ceil(len(df_rec) * (p / 100.0)))
        subset = df_rec.iloc[:cutoff]

        if len(subset) == 0:
            continue

        flat_units = np.sum(subset["result_unit"].values)
        kelly_units = np.sum(subset["result_unit"].values * subset["kelly_stake"].values)
        wins = np.sum(subset["result_unit"].values > 0)
        valid_bets = np.sum(subset["result_unit"].values != 0)

        hit_rate = (wins / valid_bets * 100.0) if valid_bets > 0 else 0.0

        results.append({
            "tier_name": f"Top {p}% Tips",
            "tips_evaluated": len(subset),
            "daily_tips": round(len(subset) / total_days, 1),
            "hit_rate": hit_rate,
            "flat_total_units": flat_units,
            "flat_monthly_rate": flat_units / months,
            "flat_roi": (flat_units / len(subset)) * 100.0,
            "kelly_total_units": kelly_units,
            "kelly_monthly_rate": kelly_units / months,
            "kelly_roi": (kelly_units / np.sum(subset["kelly_stake"].values)) * 100.0 if np.sum(subset["kelly_stake"].values) > 0 else 0.0,
        })

    return results


def run_v3_backtest(df: pl.DataFrame) -> Tuple[Any, List[Dict[str, Any]], List[Dict[str, Any]]]:
    splitter = WalkForwardSplitter(train_days=45, test_days=7, step_days=7, time_col="match_start_time")
    feature_cols = [c for c in df.columns if c not in [
        "match_id", "startedAt", "match_start_time", "home.goals", "away.goals",
        "final_home_score", "final_away_score", "closingOdds.money_line.home", "odds_close",
        "league", "home_player", "away_player", "home_team", "away_team", "duration_minutes", "source"
    ]]

    test_records = []
    final_xgb = None

    for train_idx, test_idx in splitter.split(df):
        df_tr = df[train_idx].to_pandas()
        df_te = df[test_idx].to_pandas()

        X_tr = df_tr[feature_cols].fillna(0).values
        y_tr = (df_tr["home.goals"].values > df_tr["away.goals"].values).astype(int)

        X_te = df_te[feature_cols].fillna(0).values
        home_g = df_te["home.goals"].values
        away_g = df_te["away.goals"].values

        xgb = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42, eval_metric="logloss")
        xgb.fit(X_tr, y_tr)
        final_xgb = xgb

        p_home_te = xgb.predict_proba(X_te)[:, 1]
        p_away_te = 1.0 - p_home_te

        for idx in range(len(df_te)):
            odds_h = df_te["closingOdds.money_line.home"].iloc[idx] if "closingOdds.money_line.home" in df_te.columns else 1.90
            odds_d = 14.0
            odds_a = 1.90

            if pd.isna(odds_h) or float(odds_h) <= 1.0:
                odds_h = 1.90

            odds_h = float(odds_h)
            odds_d = float(odds_d)

            # 1. Home DNB Side
            dnb_h_odds = odds_h * (1.0 - (1.0 / odds_d))
            p_h = float(p_home_te[idx])
            edge_h = p_h - (1.0 / dnb_h_odds)

            if edge_h >= 0.020 and dnb_h_odds >= ODDS_FLOOR:
                if home_g[idx] == away_g[idx]:
                    res_h = 0.0
                elif home_g[idx] > away_g[idx]:
                    res_h = dnb_h_odds - 1.0
                else:
                    res_h = -1.0

                test_records.append({
                    "match_id": df_te["match_id"].iloc[idx],
                    "startedAt": df_te["startedAt"].iloc[idx],
                    "side": "home",
                    "odds_close": dnb_h_odds,
                    "result_unit": res_h,
                    "confidence": p_h,
                    "edge": edge_h,
                    "kelly_stake": calculate_quarter_kelly_stake(p_h, dnb_h_odds)
                })

            # 2. Away DNB Side
            dnb_a_odds = odds_a * (1.0 - (1.0 / odds_d))
            p_a = float(p_away_te[idx])
            edge_a = p_a - (1.0 / dnb_a_odds)

            if edge_a >= 0.020 and dnb_a_odds >= ODDS_FLOOR:
                if home_g[idx] == away_g[idx]:
                    res_a = 0.0
                elif away_g[idx] > home_g[idx]:
                    res_a = dnb_a_odds - 1.0
                else:
                    res_a = -1.0

                test_records.append({
                    "match_id": df_te["match_id"].iloc[idx],
                    "startedAt": df_te["startedAt"].iloc[idx],
                    "side": "away",
                    "odds_close": dnb_a_odds,
                    "result_unit": res_a,
                    "confidence": p_a,
                    "edge": edge_a,
                    "kelly_stake": calculate_quarter_kelly_stake(p_a, dnb_a_odds)
                })

    tier_results = evaluate_dnb_tiers(test_records, percentiles=[100, 90, 80, 70, 50])
    return final_xgb, test_records, tier_results


def save_v3_artifacts(model: Any, tier_results: List[Dict[str, Any]], total_rows: int):
    artifact_dir = "markets/ebasket_money_line/v3_dnb_synthetic_features/artifacts"
    os.makedirs(artifact_dir, exist_ok=True)

    with open(os.path.join(artifact_dir, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*.joblib\n*.pkl\n*.bin\n")

    model_file = os.path.join(artifact_dir, f"ebasket_money_line_model_{MODEL_VERSION}.joblib")
    joblib.dump(model, model_file)
    logger.info(f"Saved V3 model artifact to {model_file}")

    md_content = f"""# eBasketball Money Line V3 DNB Model Results Report

## Executive Summary
- **Model Version**: `{MODEL_VERSION}`
- **Training Matches Used**: **{total_rows:,} matches** (`csv_backfill` + `jarbet_history`)
- **DNB Odds Floor**: **{ODDS_FLOOR:.2f} Minimum Odds Floor**

---

## DNB Filter Sweet-Spot Comparison Matrix (Flat Staking vs Quarter-Kelly)

| Filter Tier | Tips Evaluated | Daily Tips | Hit Rate (Excl. Push) | Flat Net Units | Flat Units/Mo | Flat ROI (%) | Kelly Net Units | Kelly Units/Mo | Kelly ROI (%) |
|---|---|---|---|---|---|---|---|---|---|
"""
    for r in tier_results:
        md_content += f"| `{r['tier_name']}` | {r['tips_evaluated']:,} | {r['daily_tips']} | {r['hit_rate']:.2f}% | {r['flat_total_units']:+,.2f} | {r['flat_monthly_rate']:+,.2f} | {r['flat_roi']:+.2f}% | **{r['kelly_total_units']:+,.2f}** | **{r['kelly_monthly_rate']:+,.2f}** | **{r['kelly_roi']:+.2f}%** |\n"

    report_path = "markets/ebasket_money_line/v3_dnb_synthetic_features/RESULTS.md"
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
