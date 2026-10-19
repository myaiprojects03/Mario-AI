"""
Reseed Shadow Evaluator from Scratch for Oct 5th - Present using Re-Evaluated Models.
===================================================================================
1. Strictly Isolated: Clears ONLY core.shadow_tips_eval and core.shadow_results.
   DOES NOT TOUCH core.published_tips, core.results, core.tip_audit_log, core.matches.
2. Evaluates all match opportunities from Oct 5th, 2026 00:00:00 UTC to present.
3. Uses exclusively the Re-Evaluated Models (core/re-evaluated models/*_final.joblib).
4. Generates shadow tips from scratch using standard qualification thresholds.
5. Settles tips against final scores from core.results and JarBet API.
6. Prints final telemetry summary.
"""

import os
import sys
import re
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import numpy as np
import joblib

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)
for cand in [r"D:\Mario AI Code", WORKSPACE_DIR]:
    if os.path.exists(cand) and cand not in sys.path:
        sys.path.append(cand)

DB_URL = os.getenv("DATABASE_URL") or "postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai"

from run_local_shadow_evaluator import (
    MODELS_DIR, get_shadow_model_manager, init_shadow_db, CHANNEL_MIN_EDGE,
    get_complementary_odds, regularize_calibrated_prob
)

def calculate_settlement(ch: str, side: str, line: float, odds: float, fh: float, fa: float):
    """Exact settlement calculation matching production rules."""
    outcome = "VOID"
    net_units = 0.0

    if "ou" in ch:
        tot = fh + fa
        diff = tot - line
        if side == "over":
            if diff > 0.25: outcome, net_units = "WIN", odds - 1.0
            elif diff == 0.25: outcome, net_units = "HALF_WIN", 0.5 * (odds - 1.0)
            elif diff == 0.0: outcome, net_units = "VOID", 0.0
            elif diff == -0.25: outcome, net_units = "HALF_LOSS", -0.5
            else: outcome, net_units = "LOSS", -1.0
        else: # under
            if diff < -0.25: outcome, net_units = "WIN", odds - 1.0
            elif diff == -0.25: outcome, net_units = "HALF_WIN", 0.5 * (odds - 1.0)
            elif diff == 0.0: outcome, net_units = "VOID", 0.0
            elif diff == 0.25: outcome, net_units = "HALF_LOSS", -0.5
            else: outcome, net_units = "LOSS", -1.0

    elif "asian_handicap" in ch:
        diff = (fa - fh) + line if side == "away" else (fh - fa) + line
        if diff > 0.25: outcome, net_units = "WIN", odds - 1.0
        elif diff == 0.25: outcome, net_units = "HALF_WIN", 0.5 * (odds - 1.0)
        elif diff == 0.0: outcome, net_units = "VOID", 0.0
        elif diff == -0.25: outcome, net_units = "HALF_LOSS", -0.5
        else: outcome, net_units = "LOSS", -1.0

    elif "money_line" in ch:
        if "ebasket" in ch:
            if (side == "home" and fh > fa) or (side == "away" and fa > fh):
                outcome, net_units = "WIN", odds - 1.0
            else:
                outcome, net_units = "LOSS", -1.0
        else: # FIFA DNB
            if (side == "home" and fh > fa) or (side == "away" and fa > fh):
                outcome, net_units = "WIN", odds - 1.0
            elif fh == fa:
                outcome, net_units = "VOID", 0.0
            else:
                outcome, net_units = "LOSS", -1.0

    return outcome, round(net_units, 4)

def reseed_shadow_evaluator():
    print(f"Connecting to database: {DB_URL}", flush=True)
    init_shadow_db()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 2. Load model manager
    mgr = get_shadow_model_manager()
    print(f"Loaded {len(mgr.bundles)} re-evaluated models from {MODELS_DIR}", flush=True)

    # 3. Pull all unique match opportunities from Oct 5th onwards BEFORE clearing table
    print("Gathering unique match opportunities from Oct 5, 2026 onwards...", flush=True)
    cur.execute("""
        WITH raw_opps AS (
            SELECT match_id, match_id as bet365_id, channel_key, sport, 'eSports' as league, fixture, home_player, away_player, side, line, odds, kickoff_at_utc, published_at_utc as eval_time
            FROM core.published_tips
            WHERE published_at_utc >= '2026-10-05 00:00:00+00'
            UNION
            SELECT match_id, bet365_id, channel_key, sport, league, fixture, NULL as home_player, NULL as away_player, side, line, odds, kickoff_at_utc, evaluated_at_utc as eval_time
            FROM core.shadow_tips_eval
            WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00'
        )
        SELECT DISTINCT ON (match_id, channel_key)
            match_id, bet365_id, channel_key, sport, league, fixture, home_player, away_player, side, line, odds, kickoff_at_utc, eval_time
        FROM raw_opps
        ORDER BY match_id, channel_key, eval_time ASC;
    """)
    opps = cur.fetchall()
    conn.commit()
    print(f"Found {len(opps)} distinct match opportunities to evaluate from scratch.", flush=True)

    # 4. Now safely clear core.shadow_tips_eval
    print("Clearing core.shadow_tips_eval...", flush=True)
    cur.execute("TRUNCATE TABLE core.shadow_tips_eval RESTART IDENTITY;")
    conn.commit()

    # 5. Pull all verified final scores from core.results and core.shadow_results
    cur.execute("""
        SELECT match_id, final_home_score, final_away_score, settled_at
        FROM core.results
        WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
    """)
    results_map = {str(r["match_id"]): (float(r["final_home_score"]), float(r["final_away_score"]), r["settled_at"]) for r in cur.fetchall()}
    conn.commit()
    
    cur.execute("""
        SELECT match_id, bet365_id, final_home_score, final_away_score, settled_at_utc
        FROM core.shadow_results
        WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
    """)
    for r in cur.fetchall():
        score_t = (float(r["final_home_score"]), float(r["final_away_score"]), r["settled_at_utc"])
        if r["match_id"] and str(r["match_id"]) not in results_map:
            results_map[str(r["match_id"])] = score_t
        if r["bet365_id"] and str(r["bet365_id"]) not in results_map:
            results_map[str(r["bet365_id"])] = score_t
    conn.commit()
    print(f"Loaded {len(results_map)} verified match results from core.results & core.shadow_results.", flush=True)

    shadow_results_dict = {}
    tips_to_insert = []
    min_odds = 1.60

    for idx, opp in enumerate(opps):
        if idx % 500 == 0:
            print(f"Evaluating opportunity {idx}/{len(opps)} ({round(idx*100.0/len(opps), 1)}%)...", flush=True)
        ch_key = opp["channel_key"]
        min_edge = CHANNEL_MIN_EDGE.get(ch_key, 0.05)
        sport = opp["sport"]
        mid = str(opp["match_id"])
        b365_id = str(opp.get("bet365_id") or mid)
        league = str(opp.get("league") or "eSports")
        fixture = opp["fixture"] or ""
        orig_side = str(opp["side"] or "home").lower()
        orig_line = float(opp["line"] or 0.0)
        orig_odds = float(opp["odds"] or 1.90)
        ko_time = opp["kickoff_at_utc"]
        eval_time = opp["eval_time"] or ko_time

        if ch_key not in mgr.bundles:
            continue

        bundle = mgr.bundles[ch_key]
        model = bundle["model"]
        calibrator = bundle.get("calibrator") or bundle.get("calibrators")
        feat_names = bundle["feature_names"]

        h_player = opp.get("home_player")
        a_player = opp.get("away_player")
        if not h_player or not a_player:
            players = re.findall(r'\(([^)]+)\)', fixture)
            h_player = h_player or (players[0].strip() if len(players) > 0 else "Player1")
            a_player = a_player or (players[1].strip() if len(players) > 1 else "Player2")

        h_team = fixture.split(" (")[0].strip() if " (" in fixture else "Home"
        if " vs " in fixture:
            a_part = fixture.split(" vs ")[1]
            a_team = a_part.split(" (")[0].strip() if " (" in a_part else "Away"
        elif " x " in fixture:
            a_part = fixture.split(" x ")[1]
            a_team = a_part.split(" (")[0].strip() if " (" in a_part else "Away"
        else:
            a_team = "Away"

        pick = None

        # 1. FIFA Goals O/U
        if ch_key == "fifa_goals_ou":
            line_val = orig_line if orig_line > 0 else 2.5
            if orig_side == "over":
                o_odds = orig_odds
                u_odds = get_complementary_odds(orig_odds, 1.06)
            else:
                u_odds = orig_odds
                o_odds = get_complementary_odds(orig_odds, 1.06)

            odds_info = {
                "over_odds": o_odds, "under_odds": u_odds,
                "duration_minutes": mgr.get_tournament_duration(fixture, league)
            }
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_time, fixture=fixture, league=league)
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            imp_p_over = 1.0 / o_odds if o_odds > 1.0 else 0.50
            edge_o = cal_p - imp_p_over

            # Enforce Specification Rule: OVER-Only at min_edge (0.03)
            if edge_o >= min_edge and o_odds >= min_odds:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Gols", imp_p_over)

        # 2. FIFA Asian Handicap
        elif ch_key == "fifa_asian_handicap":
            line_val = orig_line
            if orig_side == "home":
                h_odds = orig_odds
                a_odds = get_complementary_odds(orig_odds, 1.06)
            else:
                a_odds = orig_odds
                h_odds = get_complementary_odds(orig_odds, 1.06)

            odds_info = {"home_odds": h_odds, "away_odds": a_odds}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_time, fixture=fixture, league=league)
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            imp_p_home = 1.0 / h_odds if h_odds > 1.0 else 0.50
            imp_p_away = 1.0 / a_odds if a_odds > 1.0 else 0.50
            edge_h = cal_p - imp_p_home
            edge_a = (1.0 - cal_p) - imp_p_away

            if edge_h >= min_edge and h_odds >= min_odds and edge_h >= edge_a:
                pick = ("home", line_val, h_odds, cal_p, edge_h, f"{h_team} (Handicap {line_val:+.1f})", imp_p_home)
            elif edge_a >= min_edge and a_odds >= min_odds and edge_a > edge_h:
                pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Handicap {-line_val:+.1f})", imp_p_away)

        # 3. FIFA Money Line
        elif ch_key == "fifa_money_line":
            if orig_side == "home":
                h_odds = orig_odds
                a_odds = get_complementary_odds(orig_odds, 1.07)
            else:
                a_odds = orig_odds
                h_odds = get_complementary_odds(orig_odds, 1.07)

            odds_info = {"home_odds": h_odds, "away_odds": a_odds}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, 0.0, odds_info, ko_time, fixture=fixture, league=league)
            if hasattr(model, "model") and hasattr(model.model, "predict_proba"):
                raw_p = model.model.predict_proba(X)[0]
            else:
                raw_p = model.predict_proba(X)[0]

            cal_h, cal_a = calibrator
            p_h = float(cal_h.predict([raw_p[0]])[0])
            p_a = float(cal_a.predict([raw_p[2] if len(raw_p) > 2 else raw_p[1]])[0])
            imp_p_h = 1.0 / h_odds if h_odds > 1.0 else 0.45
            imp_p_a = 1.0 / a_odds if a_odds > 1.0 else 0.35
            edge_h = p_h - imp_p_h
            edge_a = p_a - imp_p_a

            if edge_h >= min_edge and h_odds >= min_odds and edge_h >= edge_a:
                pick = ("home", 0.0, h_odds, p_h, edge_h, f"{h_team} (Empate Anula)", imp_p_h)
            elif edge_a >= min_edge and a_odds >= min_odds and edge_a > edge_h:
                pick = ("away", 0.0, a_odds, p_a, edge_a, f"{a_team} (Empate Anula)", imp_p_a)

        # 4. eBasket Money Line
        elif ch_key == "ebasket_money_line":
            if orig_side == "home":
                h_odds = orig_odds
                a_odds = get_complementary_odds(orig_odds, 1.05)
            else:
                a_odds = orig_odds
                h_odds = get_complementary_odds(orig_odds, 1.05)

            odds_info = {"home_odds": h_odds, "away_odds": a_odds}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, 0.0, odds_info, ko_time, fixture=fixture, league=league)
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            imp_p_h = 1.0 / h_odds if h_odds > 1.0 else 0.50
            imp_p_a = 1.0 / a_odds if a_odds > 1.0 else 0.50
            edge_h = cal_p - imp_p_h
            edge_a = (1.0 - cal_p) - imp_p_a

            if edge_h >= min_edge and h_odds >= min_odds and edge_h >= edge_a:
                pick = ("home", 0.0, h_odds, cal_p, edge_h, f"{h_team} (Vencer)", imp_p_h)
            elif edge_a >= min_edge and a_odds >= min_odds and edge_a > edge_h:
                pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Vencer)", imp_p_a)

        # 5. eBasket O/U
        elif ch_key == "ebasket_ou":
            line_val = orig_line if orig_line > 0 else 110.5
            if orig_side == "over":
                o_odds = orig_odds
                u_odds = get_complementary_odds(orig_odds, 1.05)
            else:
                u_odds = orig_odds
                o_odds = get_complementary_odds(orig_odds, 1.05)

            odds_info = {"over_odds": o_odds, "under_odds": u_odds}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_time, fixture=fixture, league=league)
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = regularize_calibrated_prob(float(calibrator.predict([raw_p])[0]))
            imp_p_o = 1.0 / o_odds if o_odds > 1.0 else 0.50
            imp_p_u = 1.0 / u_odds if u_odds > 1.0 else 0.50
            edge_o = cal_p - imp_p_o
            edge_u = (1.0 - cal_p) - imp_p_u

            if edge_o >= min_edge and o_odds >= min_odds and edge_o >= edge_u:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Pontos", imp_p_o)
            elif edge_u >= min_edge and u_odds >= min_odds and edge_u > edge_o:
                pick = ("under", line_val, u_odds, 1.0 - cal_p, edge_u, f"Menos de {line_val} Pontos", imp_p_u)

        if pick is not None:
            side, line, odds, model_p, edge, pick_str, imp_p = pick

            status = "PENDING"
            outcome = None
            final_score = None
            net_units = None
            settled_at = None

            fh, fa, res_settled = None, None, None
            if mid in results_map:
                fh, fa, res_settled = results_map[mid]
            elif b365_id and b365_id in results_map:
                fh, fa, res_settled = results_map[b365_id]

            if fh is not None and fa is not None:
                status = "SETTLED"
                final_score = f"{int(fh)}-{int(fa)}"
                outcome, net_units = calculate_settlement(
                    ch=ch_key, side=side, line=line, odds=odds, fh=float(fh), fa=float(fa)
                )
                if res_settled:
                    settled_at = res_settled
                elif ko_time:
                    if sport == "ebasket":
                        settled_at = ko_time + timedelta(minutes=35)
                    else:
                        dur_mins = mgr.get_tournament_duration(fixture, league)
                        settled_at = ko_time + timedelta(minutes=dur_mins + 3.0)
                else:
                    settled_at = eval_time or datetime.now(timezone.utc)

                shadow_results_dict[mid] = (mid, b365_id, sport, fh, fa, settled_at, "oct5_reseed")

            tips_to_insert.append((
                mid, b365_id, sport, ch_key, league, fixture, ch_key,
                pick_str, side, line, odds, round(imp_p, 4), round(model_p, 4), round(edge, 4),
                status, final_score, outcome, net_units, ko_time, eval_time, settled_at
            ))

    print(f"Generated {len(tips_to_insert)} qualifying shadow tips from scratch using Re-Evaluated Models!", flush=True)

    from psycopg2.extras import execute_values

    # 5. Bulk insert verified scores into core.shadow_results
    if shadow_results_dict:
        print(f"Bulk inserting {len(shadow_results_dict)} results into core.shadow_results...", flush=True)
        res_sql = """
            INSERT INTO core.shadow_results (
                match_id, bet365_id, sport, final_home_score, final_away_score, settled_at_utc, source
            ) VALUES %s
            ON CONFLICT (match_id) DO NOTHING;
        """
        execute_values(cur, res_sql, list(shadow_results_dict.values()), page_size=1000)

    # 6. Bulk insert tips into core.shadow_tips_eval
    if tips_to_insert:
        print(f"Bulk inserting {len(tips_to_insert)} shadow tips into core.shadow_tips_eval...", flush=True)
        tips_sql = """
            INSERT INTO core.shadow_tips_eval (
                match_id, bet365_id, sport, channel_key, league, fixture, market_type,
                pick_str, side, line, odds, implied_prob, model_prob, estimated_edge,
                status, final_score, outcome, net_units, kickoff_at_utc, evaluated_at_utc, settled_at_utc
            ) VALUES %s
            ON CONFLICT (match_id, channel_key) DO UPDATE SET
                status = EXCLUDED.status,
                final_score = EXCLUDED.final_score,
                outcome = EXCLUDED.outcome,
                net_units = EXCLUDED.net_units,
                settled_at_utc = EXCLUDED.settled_at_utc;
        """
        execute_values(cur, tips_sql, tips_to_insert, page_size=1000)

    conn.commit()
    print("Successfully committed all reseeded shadow tips to core.shadow_tips_eval and core.shadow_results.", flush=True)

    from run_local_shadow_evaluator import print_shadow_telemetry
    print_shadow_telemetry()
    conn.close()

if __name__ == "__main__":
    reseed_shadow_evaluator()
