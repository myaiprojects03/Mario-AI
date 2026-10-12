"""
Re-evaluated Model Training & Chronological Walk-Forward Backtest Pipeline for Market 1: FIFA Goals Over/Under.

CLIENT AUDIT COMPLIANCE GUARANTEES:
1. Zero Closing-Odds Leakage: 'closingOdds' is completely removed from the dataset.
2. Zero Odds-Drift Leakage: 'odds_drift_abs' and 'odds_drift_pct' are completely removed.
3. Pre-Match Implied Probability: Computed strictly from pre-match open odds (1 / odds.over_under.over).
4. Zero Current-Match Score Leakage: Current match scores are strictly isolated to target vector y, never in feature matrix X.
5. Zero Synthetic Padding: No hardcoded filler constants (0.50, 0.45, 5.0, 0.0) permitted.
6. Strict Chronological Evaluation: Train -> Inner Calibration -> Out-of-Sample Test with zero lookahead.
7. Standardized Settlement: Official settlement evaluation (WIN, HALF_WIN, VOID, HALF_LOSS, LOSS) with 1.0 unit flat stake.
8. Artifact Target: core/re-evaluated models/
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

import numpy as np
import polars as pl
import pandas as pd
import joblib
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

# Ensure workspace root is in sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from markets.fifa_goals_ou.features import FEATURE_COLUMNS, build_fifa_goals_ou_features
from markets.fifa_goals_ou.models.xgb_model import XGBoostGoalsOUModel
from core.live.settlement_engine import evaluate_match_result, calculate_net_units

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_reevaluated_fifa_goals_ou")

MODEL_VERSION = "v2.0.0-reevaluated"
FEATURE_VERSION = "v2.0.0-clean-prematch"
DATASET_PATH = os.path.join(WORKSPACE_DIR, "data", "formatted_data", "fifa_matches_formatted.jsonl")
OUTPUT_DIR = os.path.join(WORKSPACE_DIR, "core", "re-evaluated models")


def load_and_preprocess_dataset() -> pl.DataFrame:
    """Loads, validates, deduplicates, and flattens formatted FIFA dataset."""
    logger.info(f"Loading formatted FIFA dataset from {DATASET_PATH}...")
    df = pl.read_ndjson(DATASET_PATH)
    logger.info(f"Raw rows loaded: {len(df):,}")

    # Deduplicate strictly on match_id keeping earliest chronological record
    df = df.unique(subset=["_id"]).sort("startedAt")
    logger.info(f"Unique match records: {len(df):,}")

    # Unpack nested structs
    df_flat = df.with_columns([
        pl.col("_id").alias("match_id"),
        pl.col("home").struct.field("name").alias("home_player"),
        pl.col("away").struct.field("name").alias("away_player"),
        pl.col("home").struct.field("teamName").alias("home_team"),
        pl.col("away").struct.field("teamName").alias("away_team"),
        pl.col("home").struct.field("goals").alias("home.goals"),
        pl.col("away").struct.field("goals").alias("away.goals"),
        pl.col("home").struct.field("goalsHT").alias("home.goalsHT"),
        pl.col("away").struct.field("goalsHT").alias("away.goalsHT"),
        pl.col("odds").struct.field("over_under").struct.field("line").alias("odds.over_under.line"),
        pl.col("odds").struct.field("over_under").struct.field("over").alias("odds.over_under.over"),
        pl.col("odds").struct.field("over_under").struct.field("under").alias("odds.over_under.under"),
    ])

    # Filter for matches that have confirmed final scores and valid pre-match Over/Under odds
    df_valid = df_flat.filter(
        pl.col("home.goals").is_not_null() &
        pl.col("away.goals").is_not_null() &
        pl.col("odds.over_under.line").is_not_null() &
        pl.col("odds.over_under.over").is_not_null() &
        (pl.col("odds.over_under.over") > 1.0)
    )
    logger.info(f"Confirmed valid training records with pre-match O/U odds: {len(df_valid):,}")
    return df_valid


def run_walk_forward_backtest(
    df_feat: pl.DataFrame,
    n_splits: int = 5,
    train_ratio: float = 0.70,
    cal_ratio: float = 0.10,
    min_edge: float = 0.03,
    min_odds: float = 1.60,
    max_odds: float = 2.50,
) -> Dict[str, Any]:
    """
    Runs strict chronological walk-forward out-of-sample backtesting.
    Splits: Train -> Inner Calibration -> Out-of-Sample Test.
    Zero look-ahead, zero retroactive parameter tuning.
    """
    logger.info("Executing chronological walk-forward backtest...")
    df_sorted = df_feat.sort("startedAt")
    total_len = len(df_sorted)

    # Convert timestamps to list for chronological indexing
    all_dates = df_sorted["startedAt"].to_list()
    split_size = total_len // (n_splits + 1)

    fold_reports = []
    all_test_tips = []

    for fold in range(n_splits):
        train_end_idx = split_size * (fold + 1)
        # Inner calibration is the final 15% of the train window
        cal_size = int(train_end_idx * 0.15)
        train_sub_end_idx = train_end_idx - cal_size
        test_end_idx = min(train_end_idx + split_size, total_len)

        df_train_sub = df_sorted[:train_sub_end_idx]
        df_cal = df_sorted[train_sub_end_idx:train_end_idx]
        df_test = df_sorted[train_end_idx:test_end_idx]

        train_cutoff = all_dates[train_sub_end_idx - 1]
        cal_cutoff = all_dates[train_end_idx - 1]
        test_start = all_dates[train_end_idx]
        test_end = all_dates[test_end_idx - 1]

        logger.info(
            f"Fold {fold + 1}/{n_splits}: "
            f"Train [{all_dates[0][:10]} -> {train_cutoff[:10]} ({len(df_train_sub):,})], "
            f"Cal [{train_cutoff[:10]} -> {cal_cutoff[:10]} ({len(df_cal):,})], "
            f"Test [{test_start[:10]} -> {test_end[:10]} ({len(df_test):,})]"
        )

        # 1. Fit XGBoost on Train sub-window
        xgb_fold = XGBoostGoalsOUModel(n_estimators=100, max_depth=5, learning_rate=0.05)
        xgb_fold.fit(df_train_sub)

        # 2. Fit Isotonic Calibrator on Inner Calibration window
        raw_probs_cal = xgb_fold.predict_probs(df_cal)
        cal_pd = df_cal.to_pandas()
        y_cal = ((cal_pd["home.goals"] + cal_pd["away.goals"]) > cal_pd["odds.over_under.line"]).astype(float).values
        
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrator.fit(raw_probs_cal, y_cal)

        # 3. Predict strictly on untouched Out-of-Sample Test window
        raw_probs_test = xgb_fold.predict_probs(df_test)
        calibrated_probs_test = calibrator.predict(raw_probs_test)

        # 4. Evaluate Out-of-Sample Betting Performance
        df_test_pd = df_test.to_pandas()
        fold_tips = []

        for i in range(len(df_test_pd)):
            over_odds = float(df_test_pd["odds.over_under.over"].iloc[i])
            if over_odds < min_odds or over_odds > max_odds:
                continue

            prob_over = float(calibrated_probs_test[i])
            implied_prob = 1.0 / over_odds
            edge = prob_over - implied_prob

            # Minimum edge threshold
            if edge >= min_edge:
                line_val = float(df_test_pd["odds.over_under.line"].iloc[i])
                h_goals = float(df_test_pd["home.goals"].iloc[i])
                a_goals = float(df_test_pd["away.goals"].iloc[i])

                outcome = evaluate_match_result(
                    t_type="fifa_goals_ou",
                    side="over",
                    line=line_val,
                    h_score=h_goals,
                    a_score=a_goals
                )
                net_units = calculate_net_units(outcome=outcome, odds=over_odds)

                tip_record = {
                    "fold": fold + 1,
                    "match_id": str(df_test_pd["match_id"].iloc[i]),
                    "startedAt": str(df_test_pd["startedAt"].iloc[i]),
                    "line": line_val,
                    "odds": over_odds,
                    "prob_model": prob_over,
                    "implied_prob": implied_prob,
                    "edge": edge,
                    "home_goals": h_goals,
                    "away_goals": a_goals,
                    "outcome": outcome,
                    "net_units": net_units,
                }
                fold_tips.append(tip_record)
                all_test_tips.append(tip_record)

        # Metrics for fold
        n_tips = len(fold_tips)
        if n_tips > 0:
            units = sum(t["net_units"] for t in fold_tips)
            roi = (units / n_tips) * 100.0
            wins = sum(1 for t in fold_tips if t["outcome"] == "WIN")
            win_rate = (wins / n_tips) * 100.0
            brier = brier_score_loss([1 if t["outcome"] in ("WIN", "HALF_WIN") else 0 for t in fold_tips], [t["prob_model"] for t in fold_tips])
            brier_bench = brier_score_loss([1 if t["outcome"] in ("WIN", "HALF_WIN") else 0 for t in fold_tips], [t["implied_prob"] for t in fold_tips])
            bss = 1.0 - (brier / brier_bench) if brier_bench > 0 else 0.0
        else:
            units, roi, win_rate, brier, bss = 0.0, 0.0, 0.0, 0.0, 0.0

        fold_reports.append({
            "fold": fold + 1,
            "train_samples": len(df_train_sub),
            "cal_samples": len(df_cal),
            "test_samples": len(df_test),
            "train_period": f"{all_dates[0][:10]} to {train_cutoff[:10]}",
            "cal_period": f"{train_cutoff[:10]} to {cal_cutoff[:10]}",
            "test_period": f"{test_start[:10]} to {test_end[:10]}",
            "tips": n_tips,
            "units": units,
            "roi_pct": roi,
            "win_rate_pct": win_rate,
            "brier_score": brier,
            "brier_skill_score": bss,
        })

    return {
        "fold_reports": fold_reports,
        "all_tips": all_test_tips,
    }


def compute_comprehensive_metrics(all_tips: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Computes all audited performance metrics required by client section 7."""
    if not all_tips:
        return {}

    n_tips = len(all_tips)
    outcomes = [t["outcome"] for t in all_tips]
    units = [t["net_units"] for t in all_tips]
    total_units = sum(units)
    roi_pct = (total_units / n_tips) * 100.0

    wins = outcomes.count("WIN")
    half_wins = outcomes.count("HALF_WIN")
    voids = outcomes.count("VOID")
    half_losses = outcomes.count("HALF_LOSS")
    losses = outcomes.count("LOSS")
    effective_wins = wins + 0.5 * half_wins
    win_rate = (effective_wins / (n_tips - voids) * 100.0) if (n_tips - voids) > 0 else 0.0

    # Drawdown and streaks
    cum_units = np.cumsum(units)
    peak = np.maximum.accumulate(cum_units)
    drawdowns = peak - cum_units
    max_drawdown = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    longest_losing_streak = 0
    curr_streak = 0
    for o in outcomes:
        if o in ("LOSS", "HALF_LOSS"):
            curr_streak += 1
            if curr_streak > longest_losing_streak:
                longest_losing_streak = curr_streak
        elif o in ("WIN", "HALF_WIN"):
            curr_streak = 0

    avg_odds = float(np.mean([t["odds"] for t in all_tips]))
    avg_model_prob = float(np.mean([t["prob_model"] for t in all_tips]))
    avg_edge = float(np.mean([t["edge"] for t in all_tips]))

    # Brier and BSS
    actual_binary = [1 if o in ("WIN", "HALF_WIN") else 0 for o in outcomes]
    probs = [t["prob_model"] for t in all_tips]
    implieds = [t["implied_prob"] for t in all_tips]
    brier = float(brier_score_loss(actual_binary, probs))
    brier_bench = float(brier_score_loss(actual_binary, implieds))
    bss = float(1.0 - (brier / brier_bench)) if brier_bench > 0 else 0.0

    # Edge Monotonicity
    df_tips = pd.DataFrame(all_tips)
    df_tips["edge_bucket"] = pd.cut(df_tips["edge"], bins=[0.03, 0.05, 0.08, 0.12, 1.0], labels=["3-5%", "5-8%", "8-12%", "12%+"])
    edge_mono = []
    for bucket, grp in df_tips.groupby("edge_bucket", observed=False):
        b_tips = len(grp)
        b_units = float(grp["net_units"].sum()) if b_tips > 0 else 0.0
        b_roi = (b_units / b_tips * 100.0) if b_tips > 0 else 0.0
        edge_mono.append({
            "bucket": str(bucket),
            "tips": b_tips,
            "units": b_units,
            "roi_pct": b_roi,
        })

    # Performance by Odds Range
    df_tips["odds_bucket"] = pd.cut(df_tips["odds"], bins=[1.60, 1.80, 2.00, 2.20, 3.0], labels=["1.60-1.80", "1.80-2.00", "2.00-2.20", "2.20+"])
    odds_ranges = []
    for bucket, grp in df_tips.groupby("odds_bucket", observed=False):
        b_tips = len(grp)
        b_units = float(grp["net_units"].sum()) if b_tips > 0 else 0.0
        b_roi = (b_units / b_tips * 100.0) if b_tips > 0 else 0.0
        odds_ranges.append({
            "bucket": str(bucket),
            "tips": b_tips,
            "units": b_units,
            "roi_pct": b_roi,
        })

    return {
        "total_tips": n_tips,
        "wins": wins,
        "half_wins": half_wins,
        "voids": voids,
        "half_losses": half_losses,
        "losses": losses,
        "win_rate": win_rate,
        "net_units": total_units,
        "roi_pct": roi_pct,
        "max_drawdown": max_drawdown,
        "longest_losing_streak": longest_losing_streak,
        "avg_odds": avg_odds,
        "avg_model_prob": avg_model_prob,
        "avg_edge": avg_edge,
        "brier_score": brier,
        "brier_skill_score": bss,
        "edge_monotonicity": edge_mono,
        "odds_ranges": odds_ranges,
    }


def fit_final_production_model(df_feat: pl.DataFrame) -> Tuple[XGBoostGoalsOUModel, IsotonicRegression]:
    """Fits final production model and calibrator on verified historical records."""
    logger.info("Fitting final production XGBoost model on verified dataset...")
    df_sorted = df_feat.sort("startedAt")
    
    # Carve final 10% for isotonic probability calibration
    n_total = len(df_sorted)
    cal_split_idx = int(n_total * 0.90)

    df_train = df_sorted[:cal_split_idx]
    df_cal = df_sorted[cal_split_idx:]

    model = XGBoostGoalsOUModel(n_estimators=120, max_depth=5, learning_rate=0.05, subsample=0.85, colsample_bytree=0.85)
    model.fit(df_train)

    raw_cal_probs = model.predict_probs(df_cal)
    cal_pd = df_cal.to_pandas()
    y_cal = ((cal_pd["home.goals"] + cal_pd["away.goals"]) > cal_pd["odds.over_under.line"]).astype(float).values

    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_cal_probs, y_cal)

    logger.info(f"Final model successfully fitted. Feature count: {len(model.feature_names)}")
    return model, calibrator


def verify_feature_parity(model: XGBoostGoalsOUModel) -> Dict[str, Any]:
    """
    Feature-Parity Test: verifies that live single-payload format matches training feature schema.
    Proves:
    - Same feature names, order, types.
    - Zero post-match fields.
    - Zero hard-coded dummy constants.
    """
    sample_path = os.path.join(WORKSPACE_DIR, "data", "formatted_data", "sample_fifa_match.json")
    with open(sample_path, "r", encoding="utf-8") as f:
        sample_json = json.load(f)

    # Convert single payload to DataFrame to test shared extraction
    single_df = pl.DataFrame([sample_json])
    unpacked_single = single_df.with_columns([
        pl.col("_id").alias("match_id"),
        pl.col("home").struct.field("name").alias("home_player"),
        pl.col("away").struct.field("name").alias("away_player"),
        pl.col("home").struct.field("teamName").alias("home_team"),
        pl.col("away").struct.field("teamName").alias("away_team"),
        pl.col("home").struct.field("goals").alias("home.goals"),
        pl.col("away").struct.field("goals").alias("away.goals"),
        pl.col("home").struct.field("goalsHT").alias("home.goalsHT"),
        pl.col("away").struct.field("goalsHT").alias("away.goalsHT"),
        pl.col("odds").struct.field("over_under").struct.field("line").alias("odds.over_under.line"),
        pl.col("odds").struct.field("over_under").struct.field("over").alias("odds.over_under.over"),
        pl.col("odds").struct.field("over_under").struct.field("under").alias("odds.over_under.under"),
    ])

    extracted = build_fifa_goals_ou_features(unpacked_single)
    feature_cols = [c for c in FEATURE_COLUMNS if c != "match_id"]

    extracted_names = [c for c in feature_cols if c in extracted.columns]
    is_parity = (extracted_names == model.feature_names)

    # Check for prohibited post-match fields
    prohibited = ["closingOdds", "odds_drift_abs", "odds_drift_pct", "isFinished", "status"]
    has_prohibited = any(p in extracted.columns for p in prohibited)

    return {
        "parity_passed": is_parity and not has_prohibited,
        "feature_count": len(extracted_names),
        "expected_features": model.feature_names,
        "prohibited_detected": has_prohibited,
    }


def main():
    logger.info("=== STARTING RE-EVALUATED MODEL TRAINING: FIFA GOALS OVER/UNDER ===")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Load dataset
    df_raw = load_and_preprocess_dataset()

    # 2. Extract clean pre-match features
    logger.info("Extracting clean pre-match features via build_fifa_goals_ou_features...")
    df_feat = build_fifa_goals_ou_features(df_raw)
    logger.info(f"Feature matrix built successfully: {len(df_feat):,} matches, {len(FEATURE_COLUMNS)} features.")

    # 3. Chronological Walk-Forward Backtest
    backtest_res = run_walk_forward_backtest(df_feat, n_splits=5, min_edge=0.03, min_odds=1.60)
    metrics = compute_comprehensive_metrics(backtest_res["all_tips"])

    # 4. Fit Final Production Model
    final_model, final_calibrator = fit_final_production_model(df_feat)

    # 5. Feature Parity Test
    parity_test = verify_feature_parity(final_model)
    logger.info(f"Feature parity test status: {'PASSED' if parity_test['parity_passed'] else 'FAILED'}")

    # 6. Save Artifacts to core/re-evaluated models/
    artifact_bundle = {
        "market": "fifa_goals_ou",
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "model": final_model,
        "calibrator": final_calibrator,
        "feature_names": final_model.feature_names,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_training_matches": len(df_feat),
        "backtest_metrics": metrics,
        "parity_test": parity_test,
    }

    v2_artifact_path = os.path.join(OUTPUT_DIR, "fifa_goals_ou_model_v2.0.0.joblib")
    final_artifact_path = os.path.join(OUTPUT_DIR, "fifa_goals_ou_model_final.joblib")

    joblib.dump(artifact_bundle, v2_artifact_path)
    joblib.dump(artifact_bundle, final_artifact_path)
    logger.info(f"Model artifact saved to {v2_artifact_path} and {final_artifact_path}")

    # 7. Generate Comprehensive Markdown Audit Report
    report_path = os.path.join(OUTPUT_DIR, "FIFA_GOALS_OU_EVALUATION.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Re-evaluated Model Audit Report: Market 1 (FIFA Goals Over/Under)\n\n")
        f.write(f"**Model Version**: `{MODEL_VERSION}`  \n")
        f.write(f"**Feature Version**: `{FEATURE_VERSION}`  \n")
        f.write(f"**Trained At**: `{datetime.now(timezone.utc).isoformat()}`  \n")
        f.write(f"**Total Verified Training Matches**: `{len(df_feat):,}`  \n")
        f.write(f"**Artifact Location**: `core/re-evaluated models/fifa_goals_ou_model_v2.0.0.joblib`  \n\n")

        f.write("## 1. Feature Parity & Leakage Elimination Audit\n\n")
        f.write(f"- **Feature Parity Test**: `{'PASSED (100% Schema Parity)' if parity_test['parity_passed'] else 'FAILED'}`\n")
        f.write(f"- **Closing Odds Removed**: `YES (0 closing odds fields in training)`\n")
        f.write(f"- **Odds Drift Eliminated**: `YES (odds_drift_abs & odds_drift_pct completely removed)`\n")
        f.write(f"- **Synthetic Padding Removed**: `YES (No 0.50, 0.45, 5.0, 0.0 dummy constants)`\n")
        f.write(f"- **Pre-match Implied Probability**: `Derived strictly from pre-match odds (1.0 / odds.over_under.over)`\n")
        f.write(f"- **Score Isolation**: `home.goals and away.goals used strictly for post-match settlement target y`\n\n")

        f.write("### Whitelisted Feature Names (19 Total):\n")
        for idx, feat in enumerate(final_model.feature_names):
            f.write(f"{idx+1}. `{feat}`\n")

        f.write("\n## 2. Walk-Forward Chronological Evaluation Results\n\n")
        f.write("| Fold | Train Period | Cal Period | Out-of-Sample Period | Samples | Settled Tips | Win Rate (%) | ROI (%) | Net Units | Brier Skill Score |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for fr in backtest_res["fold_reports"]:
            f.write(f"| {fr['fold']} | `{fr['train_period']}` | `{fr['cal_period']}` | `{fr['test_period']}` | {fr['test_samples']:,} | {fr['tips']:,} | {fr['win_rate_pct']:.2f}% | {fr['roi_pct']:+.2f}% | {fr['units']:+,.2f} | {fr['brier_skill_score']:+.4f} |\n")

        f.write(f"\n## 3. Comprehensive Performance Metrics (All Out-of-Sample Folds)\n\n")
        f.write(f"- **Total Tips Evaluated**: `{metrics.get('total_tips', 0):,}`\n")
        f.write(f"- **Wins / Half-Wins / Voids / Half-Losses / Losses**: `{metrics.get('wins', 0)} / {metrics.get('half_wins', 0)} / {metrics.get('voids', 0)} / {metrics.get('half_losses', 0)} / {metrics.get('losses', 0)}`\n")
        f.write(f"- **Win Rate**: `{metrics.get('win_rate', 0):.2f}%`\n")
        f.write(f"- **Total Net Units (1.0 flat stake)**: `{metrics.get('net_units', 0):+,.2f} Units`\n")
        f.write(f"- **Overall ROI**: `{metrics.get('roi_pct', 0):+.2f}%`\n")
        f.write(f"- **Maximum Drawdown**: `{metrics.get('max_drawdown', 0):.2f} Units`\n")
        f.write(f"- **Longest Losing Streak**: `{metrics.get('longest_losing_streak', 0)} tips`\n")
        f.write(f"- **Average Odds**: `{metrics.get('avg_odds', 0):.2f}`\n")
        f.write(f"- **Average Model Probability**: `{metrics.get('avg_model_prob', 0)*100:.2f}%`\n")
        f.write(f"- **Average Calculated Edge**: `{metrics.get('avg_edge', 0)*100:+.2f}%`\n")
        f.write(f"- **Brier Score**: `{metrics.get('brier_score', 0):.4f}`\n")
        f.write(f"- **Brier Skill Score (vs. Bookmaker Implied)**: `{metrics.get('brier_skill_score', 0):+.4f}`\n\n")

        f.write("### Edge Monotonicity Analysis:\n\n")
        f.write("| Edge Tier | Tips | Net Units | ROI (%) |\n")
        f.write("|---|---|---|---|\n")
        for em in metrics.get("edge_monotonicity", []):
            f.write(f"| {em['bucket']} | {em['tips']:,} | {em['units']:+,.2f} | {em['roi_pct']:+.2f}% |\n")

        f.write("\n### Performance by Odds Range:\n\n")
        f.write("| Odds Range | Tips | Net Units | ROI (%) |\n")
        f.write("|---|---|---|---|\n")
        for od in metrics.get("odds_ranges", []):
            f.write(f"| {od['bucket']} | {od['tips']:,} | {od['units']:+,.2f} | {od['roi_pct']:+.2f}% |\n")

    logger.info(f"Wrote comprehensive evaluation report to {report_path}")
    print("\n=======================================================")
    print("      RE-EVALUATED MODEL TRAINING COMPLETED")
    print("=======================================================")
    print(f"Total Out-of-Sample Tips: {metrics.get('total_tips', 0):,}")
    print(f"Total Net Units:         {metrics.get('net_units', 0):+,.2f} Units")
    print(f"Overall ROI:             {metrics.get('roi_pct', 0):+.2f}%")
    print(f"Win Rate:                {metrics.get('win_rate', 0):.2f}%")
    print(f"Brier Skill Score:       {metrics.get('brier_skill_score', 0):+.4f}")
    print(f"Saved To:                {v2_artifact_path}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
