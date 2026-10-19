"""
Reseed Shadow Evaluator from Scratch for Oct 5th - Present using Re-Evaluated Models.
===================================================================================
1. Strictly Isolated: Clears ONLY core.shadow_tips_eval and core.shadow_results.
   DOES NOT TOUCH core.published_tips, core.results, core.tip_audit_log, core.matches.
2. Synchronized with run_local_shadow_evaluator.py: Imports and uses the exact same
   evaluation pipeline, feature builders, models, calibration, and settlements.
3. Retrieves true home_player, away_player, and league by joining core.matches.
4. Skips rows with missing required data rather than injecting "Player1" / "Home".
5. Rejects matches missing market lines (line is None or line <= 0) instead of assuming 2.5 or 110.5.
6. Eliminates arbitrary 0.45, 0.35, 0.50 stubs: implied probabilities are calculated strictly
   via complementary odds (1.0 / get_complementary_odds(...)) or skipped if invalid.
7. Proper underdog floor in get_complementary_odds: round(1.0 / max(0.04, target_vig - 1.0/odds), 3).
8. FIFA Goals O/U Edge locked at 3% (0.03).
"""

import os
import sys

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)
for cand in [r"D:\Mario AI Code", WORKSPACE_DIR]:
    if os.path.exists(cand) and cand not in sys.path:
        sys.path.append(cand)

from run_local_shadow_evaluator import (
    DB_URL,
    SHADOW_START_DATE,
    MODELS_DIR,
    CHANNEL_MIN_EDGE,
    init_shadow_db,
    clean_and_sync_oct5_shadow_data,
    print_shadow_telemetry,
    get_shadow_model_manager,
    get_complementary_odds,
    regularize_calibrated_prob,
    calculate_single_settlement as calculate_settlement
)

def reseed_shadow_evaluator():
    """Reseeds shadow evaluation pipeline from scratch with 100% synchronized evaluator logic."""
    print("=" * 80, flush=True)
    print(f"RESEEDING SHADOW EVALUATOR FROM {SHADOW_START_DATE} ONWARDS", flush=True)
    print(f"Database: {DB_URL}", flush=True)
    print(f"Model Directory: {MODELS_DIR}", flush=True)
    print(f"FIFA Goals O/U Edge: {CHANNEL_MIN_EDGE.get('fifa_goals_ou', 0.03):.2%}", flush=True)
    print("=" * 80, flush=True)

    init_shadow_db()
    clean_and_sync_oct5_shadow_data(clean=True)
    print_shadow_telemetry()

if __name__ == "__main__":
    reseed_shadow_evaluator()
