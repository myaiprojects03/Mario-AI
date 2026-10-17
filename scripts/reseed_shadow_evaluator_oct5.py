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
from datetime import datetime, timezone
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

from run_local_shadow_evaluator import MODELS_DIR, get_shadow_model_manager, init_shadow_db, CHANNEL_MIN_EDGE

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
    print(f"Connecting to database: {DB_URL}")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Initialize shadow tables if needed, then clear shadow tips table
    init_shadow_db()
    print("Clearing core.shadow_tips_eval...")
    cur.execute("TRUNCATE TABLE core.shadow_tips_eval RESTART IDENTITY;")
    conn.commit()

    # 2. Load model manager
    mgr = get_shadow_model_manager()
    print(f"Loaded {len(mgr.bundles)} re-evaluated models from {MODELS_DIR}")

    # 3. Pull all unique match opportunities from Oct 5th onwards
    print("Gathering unique match opportunities from Oct 5, 2026 onwards...")
    cur.execute("""
        WITH raw_opps AS (
            SELECT match_id, channel_key, sport, fixture, side, line, odds, kickoff_at_utc, published_at_utc as eval_time
            FROM core.published_tips
            WHERE published_at_utc >= '2026-10-05 00:00:00+00'
            UNION
            SELECT match_id, channel_key, sport, fixture, side, line, odds, kickoff_at_utc, evaluated_at_utc as eval_time
            FROM core.shadow_tips_eval
            WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00'
        )
        SELECT DISTINCT ON (match_id, channel_key)
            match_id, channel_key, sport, fixture, side, line, odds, kickoff_at_utc, eval_time
        FROM raw_opps
        ORDER BY match_id, channel_key, eval_time ASC;
    """)
    opps = cur.fetchall()
    print(f"Found {len(opps)} distinct match opportunities to evaluate from scratch.")

    # 4. Pull all verified final scores from core.results and core.shadow_results
    cur.execute("""
        SELECT match_id, final_home_score, final_away_score, settled_at
        FROM core.results
        WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
    """)
    results_map = {str(r["match_id"]): (float(r["final_home_score"]), float(r["final_away_score"]), r["settled_at"]) for r in cur.fetchall()}
    
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
    print(f"Loaded {len(results_map)} verified match results from core.results & core.shadow_results.")

    shadow_results_dict = {}
    tips_to_insert = []
    min_odds = 1.60

    for opp in opps:
        ch_key = opp["channel_key"]
        min_edge = CHANNEL_MIN_EDGE.get(ch_key, 0.05)
        sport = opp["sport"]
        mid = str(opp["match_id"])
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

        players = re.findall(r'\(([^)]+)\)', fixture)
        h_player = players[0].strip() if len(players) > 0 else "Player1"
        a_player = players[1].strip() if len(players) > 1 else "Player2"

        h_team = fixture.split(" (")[0].strip() if " (" in fixture else "Home"
        if " vs " in fixture:
            a_part = fixture.split(" vs ")[1]
            a_team = a_part.split(" (")[0].strip() if " (" in a_part else "Away"
        elif " x " in fixture:
            a_part = fixture.split(" x ")[1]
            a_team = a_part.split(" (")[0].strip() if " (" in a_part else "Away"
        else:
            a_team = "Away"

        h_sc, h_cc, h_rel = mgr.get_player_stats(sport, h_player)
        a_sc, a_cc, a_rel = mgr.get_player_stats(sport, a_player)

        pick = None

        # 1. FIFA Goals O/U
        if ch_key == "fifa_goals_ou":
            line_val = orig_line if orig_line > 0 else 2.5
            o_odds = orig_odds if orig_side == "over" else 1.90
            u_odds = orig_odds if orig_side == "under" else 1.90

            exp_tot = (h_sc + a_cc) / 2.0 + (a_sc + h_cc) / 2.0
            imp_p_over = 1.0 / o_odds if o_odds > 1.0 else 0.50

            feat_vec = {
                'is_reliable_5': 1.0 if (h_rel and a_rel) else 0.0,
                'is_reliable_10': 1.0 if (h_rel and a_rel) else 0.0,
                'home_scored_roll_mean_5': h_sc, 'home_scored_roll_mean_10': h_sc,
                'home_conceded_roll_mean_5': h_cc, 'home_conceded_roll_mean_10': h_cc,
                'away_scored_roll_mean_5': a_sc, 'away_scored_roll_mean_10': a_sc,
                'away_conceded_roll_mean_5': a_cc, 'away_conceded_roll_mean_10': a_cc,
                'expected_total_goals': exp_tot,
                'h2h_matches_count': 0.0, 'h2h_mean_combined_goals': exp_tot,
                'ou_line_value': line_val, 'ou_line_diff': exp_tot - line_val,
                'ou_line_hit_rate_roll': 0.50, 'ht_ft_goal_ratio_league': 0.45,
                'odds_implied_prob': imp_p_over,
                'implied_vs_hist_divergence': imp_p_over - 0.50,
                'tournament_duration_minutes': 12.0 if "12 min" in fixture.lower() else (10.0 if "10 min" in fixture.lower() else (6.0 if "6 min" in fixture.lower() else 8.0)),
                'is_whole_line': 1.0 if abs(line_val - round(line_val)) < 1e-4 else 0.0,
                'gamer_intraday_loss_streak': 0.0,
            }
            X = pd.DataFrame([feat_vec])[feat_names]
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            edge_o = cal_p - imp_p_over

            # Enforce Specification Rule: OVER-Only at min_edge (0.03)
            if edge_o >= min_edge and o_odds >= min_odds:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Gols", 1.0 / o_odds)

        # 2. FIFA Asian Handicap
        elif ch_key == "fifa_asian_handicap":
            line_val = orig_line
            h_odds = orig_odds if orig_side == "home" else 1.90
            a_odds = orig_odds if orig_side == "away" else 1.90

            diff_exp = (h_sc - h_cc) - (a_sc - a_cc)
            imp_p_home = 1.0 / h_odds if h_odds > 1.0 else 0.50

            feat_vec = {
                'is_reliable_5': 1.0 if (h_rel and a_rel) else 0.0,
                'is_reliable_10': 1.0 if (h_rel and a_rel) else 0.0,
                'home_scored_roll_mean_5': h_sc, 'home_scored_roll_mean_10': h_sc,
                'home_conceded_roll_mean_5': h_cc, 'home_conceded_roll_mean_10': h_cc,
                'away_scored_roll_mean_5': a_sc, 'away_scored_roll_mean_10': a_sc,
                'away_conceded_roll_mean_5': a_cc, 'away_conceded_roll_mean_10': a_cc,
                'home_net_gd_10': h_sc - h_cc, 'away_net_gd_10': a_sc - a_cc,
                'net_gd_diff_10': diff_exp,
                'net_gd_margin_vs_line': diff_exp + line_val,
                'handicap_line_value': line_val,
                'ml_implied_prob_home': 0.45, 'ml_implied_prob_away': 0.35, 'ml_implied_diff': 0.10,
                'ah_odds_implied_prob': imp_p_home,
                'cross_market_divergence': 0.0,
                'h2h_matches_count': 0.0, 'h2h_mean_combined_goals': 5.0,
                'ht_ft_goal_ratio_league': 0.45
            }
            X = pd.DataFrame([feat_vec])[feat_names]
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            edge_h = cal_p - imp_p_home
            edge_a = (1.0 - cal_p) - (1.0 / a_odds if a_odds > 1.0 else 0.50)

            if edge_h >= min_edge and h_odds >= min_odds:
                pick = ("home", line_val, h_odds, cal_p, edge_h, f"{h_team} (Handicap {line_val:+.1f})", 1.0 / h_odds)
            elif edge_a >= min_edge and a_odds >= min_odds:
                pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Handicap {-line_val:+.1f})", 1.0 / a_odds)

        # 3. FIFA Money Line
        elif ch_key == "fifa_money_line":
            h_odds = orig_odds if orig_side == "home" else 2.10
            a_odds = orig_odds if orig_side == "away" else 2.10

            diff_exp = (h_sc - h_cc) - (a_sc - a_cc)
            imp_p_h = 1.0 / h_odds if h_odds > 1.0 else 0.45
            imp_p_a = 1.0 / a_odds if a_odds > 1.0 else 0.35

            feat_vec = {
                'is_reliable_5': 1.0 if (h_rel and a_rel) else 0.0,
                'is_reliable_10': 1.0 if (h_rel and a_rel) else 0.0,
                'home_win_rate_roll_5': 0.50, 'home_win_rate_roll_10': 0.50,
                'home_draw_rate_roll_5': 0.20, 'home_draw_rate_roll_10': 0.20,
                'home_loss_rate_roll_5': 0.30, 'home_loss_rate_roll_10': 0.30,
                'away_win_rate_roll_5': 0.40, 'away_win_rate_roll_10': 0.40,
                'away_draw_rate_roll_5': 0.20, 'away_draw_rate_roll_10': 0.20,
                'away_loss_rate_roll_5': 0.40, 'away_loss_rate_roll_10': 0.40,
                'home_net_gd_10': h_sc - h_cc, 'away_net_gd_10': a_sc - a_cc,
                'net_gd_diff_10': diff_exp,
                'home_win_rate_home_games': 0.50, 'away_win_rate_away_games': 0.40,
                'home_form_streak': 1.0 if diff_exp > 0 else -1.0,
                'away_form_streak': -1.0 if diff_exp > 0 else 1.0,
                'draw_prob_roll_10': 0.20, 'h2h_matches_count': 0.0, 'h2h_win_rate_a': 0.40,
                'odds_implied_prob_home': imp_p_h, 'odds_implied_prob_away': imp_p_a,
                'implied_vs_hist_divergence': 0.0,
                'home_bayesian_rating_mean': 1500.0 + diff_exp * 50.0, 'home_bayesian_rating_std': 50.0,
                'away_bayesian_rating_mean': 1500.0 - diff_exp * 50.0, 'away_bayesian_rating_std': 50.0,
                'bayesian_rating_diff': diff_exp * 100.0
            }
            X = pd.DataFrame([feat_vec])[feat_names]
            raw_p = model.predict_proba(X)[0] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0]
            cal_h, cal_a = calibrator
            p_h = float(cal_h.predict([raw_p[0]])[0])
            p_a = float(cal_a.predict([raw_p[2] if len(raw_p) > 2 else raw_p[1]])[0])
            edge_h = p_h - imp_p_h
            edge_a = p_a - imp_p_a

            if edge_h >= min_edge and h_odds >= min_odds:
                pick = ("home", 0.0, h_odds, p_h, edge_h, f"{h_team} (Empate Anula)", imp_p_h)
            elif edge_a >= min_edge and a_odds >= min_odds:
                pick = ("away", 0.0, a_odds, p_a, edge_a, f"{a_team} (Empate Anula)", imp_p_a)

        # 4. eBasket Money Line
        elif ch_key == "ebasket_money_line":
            h_odds = orig_odds if orig_side == "home" else 2.00
            a_odds = orig_odds if orig_side == "away" else 2.00

            diff_exp = (h_sc - h_cc) - (a_sc - a_cc)
            imp_p_h = 1.0 / h_odds if h_odds > 1.0 else 0.50
            imp_p_a = 1.0 / a_odds if a_odds > 1.0 else 0.50

            feat_vec = {
                'is_reliable_5': 1.0 if (h_rel and a_rel) else 0.0,
                'is_reliable_10': 1.0 if (h_rel and a_rel) else 0.0,
                'home_win_rate_roll_5': 0.50, 'home_win_rate_roll_10': 0.50,
                'away_win_rate_roll_5': 0.50, 'away_win_rate_roll_10': 0.50,
                'win_rate_diff_10': 0.0,
                'home_points_scored_roll_10': h_sc, 'home_points_conceded_roll_10': h_cc,
                'away_points_scored_roll_10': a_sc, 'away_points_conceded_roll_10': a_cc,
                'home_net_point_diff_10': h_sc - h_cc, 'away_net_point_diff_10': a_sc - a_cc,
                'net_point_diff_delta_10': diff_exp,
                'home_form_streak': 0.0, 'away_form_streak': 0.0,
                'h2h_matches_count': 0.0, 'h2h_win_rate_a': 0.50, 'h2h_mean_point_diff': 0.0,
                'odds_implied_prob_home': imp_p_h, 'odds_implied_prob_away': imp_p_a,
                'market_vig': 0.05, 'implied_prob_ratio': 1.0, 'implied_vs_hist_divergence': 0.0,
                'home_bayesian_rating_mean': 1500.0 + diff_exp * 10.0, 'home_bayesian_rating_std': 40.0,
                'away_bayesian_rating_mean': 1500.0 - diff_exp * 10.0, 'away_bayesian_rating_std': 40.0,
                'bayesian_rating_diff': diff_exp * 20.0, 'hour_of_day_utc': 12.0
            }
            X = pd.DataFrame([feat_vec])[feat_names]
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            edge_h = cal_p - imp_p_h
            edge_a = (1.0 - cal_p) - imp_p_a

            if edge_h >= min_edge and h_odds >= min_odds:
                pick = ("home", 0.0, h_odds, cal_p, edge_h, f"{h_team} (Vencer)", imp_p_h)
            elif edge_a >= min_edge and a_odds >= min_odds:
                pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Vencer)", imp_p_a)

        # 5. eBasket O/U
        elif ch_key == "ebasket_ou":
            line_val = orig_line if orig_line > 0 else 110.5
            o_odds = orig_odds if orig_side == "over" else 1.90
            u_odds = orig_odds if orig_side == "under" else 1.90

            exp_tot = (h_sc + a_cc) / 2.0 + (a_sc + h_cc) / 2.0
            imp_p_o = 1.0 / o_odds if o_odds > 1.0 else 0.50

            feat_vec = {
                'is_reliable_5': 1.0 if (h_rel and a_rel) else 0.0,
                'is_reliable_10': 1.0 if (h_rel and a_rel) else 0.0,
                'home_scored_roll_mean_5': h_sc, 'home_scored_roll_mean_10': h_sc,
                'home_conceded_roll_mean_5': h_cc, 'home_conceded_roll_mean_10': h_cc,
                'away_scored_roll_mean_5': a_sc, 'away_scored_roll_mean_10': a_sc,
                'away_conceded_roll_mean_5': a_cc, 'away_conceded_roll_mean_10': a_cc,
                'expected_total_points_5': exp_tot, 'expected_total_points_10': exp_tot,
                'expected_total_conceded_10': exp_tot, 'blended_projected_points_10': exp_tot,
                'ou_line_value': line_val, 'ou_line_diff_10': exp_tot - line_val,
                'home_total_pts_std_10': 8.0, 'away_total_pts_std_10': 8.0,
                'odds_implied_prob_over': imp_p_o, 'odds_implied_prob_under': 1.05 - imp_p_o,
                'market_vig': 0.05, 'implied_prob_ratio_over': 1.0,
                'home_bayesian_rating_mean': 1500.0, 'home_bayesian_rating_std': 40.0,
                'away_bayesian_rating_mean': 1500.0, 'away_bayesian_rating_std': 40.0,
                'bayesian_total_points': exp_tot, 'bayesian_line_diff': exp_tot - line_val,
                'h2h_matches_count': 0.0, 'h2h_mean_total_score': exp_tot,
                'hour_of_day_utc': 12.0
            }
            X = pd.DataFrame([feat_vec])[feat_names]
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            edge_o = cal_p - imp_p_o
            edge_u = (1.0 - cal_p) - (1.0 / u_odds if u_odds > 1.0 else 0.50)

            if edge_o >= min_edge and o_odds >= min_odds:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Pontos", imp_p_o)
            elif edge_u >= min_edge and u_odds >= min_odds:
                pick = ("under", line_val, u_odds, 1.0 - cal_p, edge_u, f"Menos de {line_val} Pontos", 1.0 / u_odds)

        if pick is not None:
            side, line, odds, model_p, edge, pick_str, imp_p = pick

            status = "PENDING"
            outcome = None
            final_score = None
            net_units = None
            settled_at = None

            if mid in results_map:
                fh, fa, res_settled = results_map[mid]
                status = "SETTLED"
                final_score = f"{int(fh)}-{int(fa)}"
                outcome, net_units = calculate_settlement(
                    ch=ch_key, side=side, line=line, odds=odds, fh=float(fh), fa=float(fa)
                )
                settled_at = res_settled if res_settled else (ko_time + timedelta(minutes=15))

                shadow_results_dict[mid] = (mid, mid, sport, fh, fa, settled_at, "oct5_reseed")

            tips_to_insert.append((
                mid, mid, sport, ch_key, "eSports", fixture, ch_key,
                pick_str, side, line, odds, round(imp_p, 4), round(model_p, 4), round(edge, 4),
                status, final_score, outcome, net_units, ko_time, eval_time, settled_at
            ))

    print(f"Generated {len(tips_to_insert)} qualifying shadow tips from scratch using Re-Evaluated Models!")

    from psycopg2.extras import execute_values

    # 5. Bulk insert verified scores into core.shadow_results
    if shadow_results_dict:
        print(f"Bulk inserting {len(shadow_results_dict)} results into core.shadow_results...")
        res_sql = """
            INSERT INTO core.shadow_results (
                match_id, bet365_id, sport, final_home_score, final_away_score, settled_at_utc, source
            ) VALUES %s
            ON CONFLICT (match_id) DO NOTHING;
        """
        execute_values(cur, res_sql, list(shadow_results_dict.values()), page_size=1000)

    # 6. Bulk insert tips into core.shadow_tips_eval
    if tips_to_insert:
        print(f"Bulk inserting {len(tips_to_insert)} shadow tips into core.shadow_tips_eval...")
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
    print("Successfully committed all reseeded shadow tips to core.shadow_tips_eval and core.shadow_results.")

    from run_local_shadow_evaluator import print_shadow_telemetry
    print_shadow_telemetry()
    conn.close()

if __name__ == "__main__":
    reseed_shadow_evaluator()
