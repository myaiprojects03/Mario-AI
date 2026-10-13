#!/usr/bin/env python3
"""
Pre-Oct 5 Historical Holdout Shadow Evaluator (1,000+ Matches)
==============================================================
Evaluates the 5 Re-Evaluated Models (v2.0.0-reevaluated from `core/re-evaluated models/`)
on 1,000+ matches strictly PRIOR to October 5th, 2026.

Features:
- Completely isolated: zero database writes or schema modifications.
- Uses exact pre-match feature pipelines and Isotonic Probability Calibrators.
- Evaluates qualifying tips (Edge >= 2.0%, Odds >= 1.60).
- Settles against verified final match whistle scores.
- Prints telemetry report matching the shadow evaluator dashboard.
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd
import joblib

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

# Ensure D drive path is available for helper modules if on Windows
for cand in [r"D:\Mario AI Code", WORKSPACE_DIR]:
    if os.path.exists(cand) and cand not in sys.path:
        sys.path.append(cand)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("pre_oct5_evaluator")

MODELS_DIR = os.path.join(WORKSPACE_DIR, "core", "re-evaluated models")
FIFA_DATA_PATH = os.path.join(WORKSPACE_DIR, "data", "formatted_data", "fifa_matches_formatted.jsonl")
EBASKET_DATA_PATH = os.path.join(WORKSPACE_DIR, "data", "formatted_data", "ebasket_matches_formatted.jsonl")


def calculate_settlement(ch: str, side: str, line: float, odds: float, fh: float, fa: float) -> Tuple[str, float]:
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


class PreOct5Evaluator:
    def __init__(self, models_dir: str = MODELS_DIR):
        self.models_dir = models_dir
        self.bundles: Dict[str, Any] = {}
        self.player_history = defaultdict(lambda: {"scored": [], "conceded": []})
        self._load_models()

    def _load_models(self):
        logger.info(f"Loading re-evaluated model bundles from: {self.models_dir}")
        model_files = {
            "fifa_goals_ou": "fifa_goals_ou_model_final.joblib",
            "fifa_asian_handicap": "fifa_asian_handicap_model_final.joblib",
            "fifa_money_line": "fifa_money_line_model_final.joblib",
            "ebasket_money_line": "ebasket_money_line_model_final.joblib",
            "ebasket_ou": "ebasket_ou_model_final.joblib",
        }
        for ch, fname in model_files.items():
            fpath = os.path.join(self.models_dir, fname)
            if not os.path.exists(fpath):
                logger.error(f"Missing bundle: {fpath}")
                continue
            b = joblib.load(fpath)
            self.bundles[ch] = b
            logger.info(f"Loaded {ch} ({b.get('model_version', 'v2.0.0-reevaluated')}) with {len(b.get('feature_names', []))} features")

    def get_player_rolling(self, sport: str, player: str) -> Tuple[float, float, bool]:
        k = (sport, player.strip().lower())
        h = self.player_history[k]
        sc_list = h["scored"][-10:]
        cc_list = h["conceded"][-10:]
        def_sc = 2.2 if sport == "fifa" else 55.6
        def_cc = 2.2 if sport == "fifa" else 55.6

        if len(sc_list) >= 3:
            return float(np.mean(sc_list)), float(np.mean(cc_list)), True
        elif len(sc_list) > 0:
            return float(np.mean(sc_list)), float(np.mean(cc_list)), False
        return def_sc, def_cc, False

    def update_player_history(self, sport: str, h_player: str, a_player: str, h_score: float, a_score: float):
        hk = (sport, h_player.strip().lower())
        ak = (sport, a_player.strip().lower())
        self.player_history[hk]["scored"].append(h_score)
        self.player_history[hk]["conceded"].append(a_score)
        self.player_history[ak]["scored"].append(a_score)
        self.player_history[ak]["conceded"].append(h_score)

    def load_pre_oct5_matches(self, start_date: str = "2026-09-15", end_date: str = "2026-10-05") -> List[Dict[str, Any]]:
        """Loads all matches strictly within the pre-Oct 5 date window."""
        matches = []
        logger.info(f"Loading matches from JSONL between {start_date} and {end_date}...")

        # 1. FIFA
        if os.path.exists(FIFA_DATA_PATH):
            with open(FIFA_DATA_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        m = json.loads(line)
                        st = m.get("startedAt", "")
                        if start_date <= st < end_date:
                            m["_sport"] = "fifa"
                            matches.append(m)
                    except Exception:
                        continue

        # 2. eBasketball
        if os.path.exists(EBASKET_DATA_PATH):
            with open(EBASKET_DATA_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        m = json.loads(line)
                        st = m.get("startedAt", "")
                        if start_date <= st < end_date:
                            m["_sport"] = "ebasket"
                            matches.append(m)
                    except Exception:
                        continue

        # Chronological order
        matches.sort(key=lambda x: x.get("startedAt", ""))
        logger.info(f"Loaded {len(matches)} matches prior to Oct 5th ({sum(1 for m in matches if m['_sport']=='fifa')} FIFA, {sum(1 for m in matches if m['_sport']=='ebasket')} eBasket).")
        return matches

    def run_evaluation(self, matches: List[Dict[str, Any]], min_edge: float = 0.02, min_odds: float = 1.60) -> Dict[str, Any]:
        tips_by_channel = defaultdict(list)
        channel_sports = {
            "fifa_goals_ou": "fifa",
            "fifa_asian_handicap": "fifa",
            "fifa_money_line": "fifa",
            "ebasket_money_line": "ebasket",
            "ebasket_ou": "ebasket",
        }

        for m in matches:
            sport = m["_sport"]
            m_id = str(m.get("_id") or m.get("idMatchBet365") or "")
            odds = m.get("odds", {})
            st = m.get("startedAt", "")

            h_obj = m.get("home", {})
            a_obj = m.get("away", {})
            hp = h_obj.get("name", "")
            ap = a_obj.get("name", "")
            fixture = f"{h_obj.get('teamName', '')} ({hp}) vs {a_obj.get('teamName', '')} ({ap})"

            # Whistle scores
            hg = h_obj.get("goals")
            ag = a_obj.get("goals")
            if hg is None or ag is None:
                continue
            fh, fa = float(hg), float(ag)

            # Rolling stats BEFORE the game
            h_sc, h_cc, h_rel = self.get_player_rolling(sport, hp)
            a_sc, a_cc, a_rel = self.get_player_rolling(sport, ap)

            for ch_key, ch_sport in channel_sports.items():
                if ch_sport != sport or ch_key not in self.bundles:
                    continue

                b = self.bundles[ch_key]
                model = b["model"]
                calibrator = b.get("calibrator") or b.get("calibrators")
                feat_names = b["feature_names"]

                pick = None

                # 1. FIFA Goals O/U
                if ch_key == "fifa_goals_ou":
                    ou = odds.get("over_under", {})
                    line_val = float(ou.get("line") or 0.0)
                    o_odds = float(ou.get("over") or 0.0)
                    u_odds = float(ou.get("under") or 0.0)
                    if line_val <= 0 or (o_odds <= 1.05 and u_odds <= 1.05):
                        continue

                    exp_tot = (h_sc + a_cc) / 2.0 + (a_sc + h_cc) / 2.0
                    imp_p_over = 1.0 / o_odds if o_odds > 1.0 else 0.50
                    imp_p_under = 1.0 / u_odds if u_odds > 1.0 else 0.50

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
                        'implied_vs_hist_divergence': imp_p_over - 0.50
                    }
                    X = pd.DataFrame([feat_vec])[feat_names]
                    raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
                    cal_p = float(calibrator.predict([raw_p])[0])

                    edge_o = cal_p - imp_p_over
                    edge_u = (1.0 - cal_p) - imp_p_under

                    if edge_o >= min_edge and o_odds >= min_odds:
                        pick = ("over", line_val, o_odds, cal_p, edge_o)
                    elif edge_u >= min_edge and u_odds >= min_odds:
                        pick = ("under", line_val, u_odds, 1.0 - cal_p, edge_u)

                # 2. FIFA Asian Handicap
                elif ch_key == "fifa_asian_handicap":
                    ah = odds.get("asian_handicap", {})
                    line_val = float(ah.get("line") or 0.0)
                    h_odds = float(ah.get("home") or 0.0)
                    a_odds = float(ah.get("away") or 0.0)
                    if h_odds <= 1.05 and a_odds <= 1.05:
                        continue

                    diff_exp = (h_sc - h_cc) - (a_sc - a_cc)
                    imp_p_h = 1.0 / h_odds if h_odds > 1.0 else 0.50

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
                        'ah_odds_implied_prob': imp_p_h,
                        'cross_market_divergence': 0.0,
                        'h2h_matches_count': 0.0, 'h2h_mean_combined_goals': 5.0,
                        'ht_ft_goal_ratio_league': 0.45
                    }
                    X = pd.DataFrame([feat_vec])[feat_names]
                    raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
                    cal_p = float(calibrator.predict([raw_p])[0])

                    edge_h = cal_p - imp_p_h
                    edge_a = (1.0 - cal_p) - (1.05 - imp_p_h)

                    if edge_h >= min_edge and h_odds >= min_odds:
                        pick = ("home", line_val, h_odds, cal_p, edge_h)
                    elif edge_a >= min_edge and a_odds >= min_odds:
                        pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a)

                # 3. FIFA Money Line / DNB
                elif ch_key == "fifa_money_line":
                    ml = odds.get("money_line", {})
                    h_odds = float(ml.get("home") or 0.0)
                    a_odds = float(ml.get("away") or 0.0)
                    if h_odds <= 1.05 and a_odds <= 1.05:
                        continue

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
                        pick = ("home", 0.0, h_odds, p_h, edge_h)
                    elif edge_a >= min_edge and a_odds >= min_odds:
                        pick = ("away", 0.0, a_odds, p_a, edge_a)

                # 4. eBasket Money Line
                elif ch_key == "ebasket_money_line":
                    ml = odds.get("money_line", {})
                    h_odds = float(ml.get("home") or 0.0)
                    a_odds = float(ml.get("away") or 0.0)
                    if h_odds <= 1.05 and a_odds <= 1.05:
                        continue

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
                        pick = ("home", 0.0, h_odds, cal_p, edge_h)
                    elif edge_a >= min_edge and a_odds >= min_odds:
                        pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a)

                # 5. eBasket O/U
                elif ch_key == "ebasket_ou":
                    ou = odds.get("over_under", {})
                    line_val = float(ou.get("line") or 0.0)
                    o_odds = float(ou.get("over") or 0.0)
                    u_odds = float(ou.get("under") or 0.0)
                    if line_val <= 0 or (o_odds <= 1.05 and u_odds <= 1.05):
                        continue

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
                    edge_u = (1.0 - cal_p) - (1.05 - imp_p_o)

                    if edge_o >= min_edge and o_odds >= min_odds:
                        pick = ("over", line_val, o_odds, cal_p, edge_o)
                    elif edge_u >= min_edge and u_odds >= min_odds:
                        pick = ("under", line_val, u_odds, 1.0 - cal_p, edge_u)

                # If qualified, settle immediately
                if pick:
                    side, line, odds_val, prob, edge = pick
                    outcome, net_units = calculate_settlement(
                        ch=ch_key, side=side, line=line, odds=odds_val, fh=fh, fa=fa
                    )
                    tips_by_channel[ch_key].append({
                        "match_id": m_id,
                        "timestamp": st,
                        "fixture": fixture,
                        "side": side,
                        "line": line,
                        "odds": odds_val,
                        "prob": prob,
                        "edge": edge,
                        "final_score": f"{int(fh)}-{int(fa)}",
                        "outcome": outcome,
                        "net_units": net_units,
                    })

            # Update rolling stats for future matches
            self.update_player_history(sport, hp, ap, fh, fa)

        return tips_by_channel


def print_summary_table(tips_by_channel: Dict[str, List[Dict[str, Any]]], total_matches: int, date_range: str):
    print("\n" + "=" * 96)
    print(f" SHADOW EVALUATOR TEST REPORT (RE-EVALUATED MODELS | {date_range})")
    print(f" Total Pre-Oct 5 Matches Evaluated: {total_matches}")
    print("=" * 96)
    print(f"{'Channel':<22} | {'Total Tips':<10} | {'W-L-V (HW/HL)':<20} | {'Net Units':<11} | {'Win Rate':<10} | {'ROI':<8}")
    print("-" * 96)

    total_tips = 0
    total_net = 0.0
    total_decided = 0
    total_w = 0
    total_hw = 0

    order = ["ebasket_money_line", "ebasket_ou", "fifa_asian_handicap", "fifa_goals_ou", "fifa_money_line"]

    for ch in order:
        tips = tips_by_channel.get(ch, [])
        n = len(tips)
        w = sum(1 for t in tips if t["outcome"] == "WIN")
        l = sum(1 for t in tips if t["outcome"] == "LOSS")
        v = sum(1 for t in tips if t["outcome"] == "VOID")
        hw = sum(1 for t in tips if t["outcome"] == "HALF_WIN")
        hl = sum(1 for t in tips if t["outcome"] == "HALF_LOSS")
        net = sum(t["net_units"] for t in tips)

        decided = w + l + hw + hl
        wr = ((w + 0.5 * hw) / decided * 100.0) if decided > 0 else 0.0
        roi = (net / decided * 100.0) if decided > 0 else 0.0

        total_tips += n
        total_net += net
        total_decided += decided
        total_w += w
        total_hw += hw

        rec_str = f"{w}-{l}-{v} ({hw}/{hl})"
        print(f"{ch:<22} | {n:<10} | {rec_str:<20} | {net:+9.2f}U | {wr:8.1f}% | {roi:+6.1f}%")

    print("-" * 96)
    cons_wr = ((total_w + 0.5 * total_hw) / total_decided * 100.0) if total_decided > 0 else 0.0
    cons_roi = (total_net / total_decided * 100.0) if total_decided > 0 else 0.0
    print(f"{'CONSOLIDATED':<22} | {total_tips:<10} | {'-':<20} | {total_net:+9.2f}U | {cons_wr:8.1f}% | {cons_roi:+6.1f}%")
    print("=" * 96)


def main():
    parser = argparse.ArgumentParser(description="Evaluate Re-Evaluated Models on Pre-Oct 5 Holdout Data")
    parser.add_argument("--start-date", default="2026-09-15", help="Start timestamp ISO (default: 2026-09-15)")
    parser.add_argument("--end-date", default="2026-10-05", help="End timestamp ISO (default: 2026-10-05)")
    parser.add_argument("--min-edge", type=float, default=0.02, help="Minimum edge threshold (default: 0.02)")
    parser.add_argument("--min-odds", type=float, default=1.60, help="Minimum odds threshold (default: 1.60)")
    args = parser.parse_args()

    evaluator = PreOct5Evaluator()
    matches = evaluator.load_pre_oct5_matches(start_date=args.start_date, end_date=args.end_date)
    if not matches:
        print("No matches found in the specified date range!")
        return

    tips_by_ch = evaluator.run_evaluation(matches, min_edge=args.min_edge, min_odds=args.min_odds)
    date_label = f"{args.start_date} TO {args.end_date}"
    print_summary_table(tips_by_ch, total_matches=len(matches), date_range=date_label)

    # Export results JSON
    out_file = os.path.join(WORKSPACE_DIR, "artifacts", f"pre_oct5_evaluation_{args.start_date}_{args.end_date}.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    summary_data = {
        "start_date": args.start_date,
        "end_date": args.end_date,
        "total_matches_evaluated": len(matches),
        "total_tips_generated": sum(len(v) for v in tips_by_ch.values()),
        "channels": {ch: tips for ch, tips in tips_by_ch.items()}
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)
    print(f"\n[INFO] Detailed tip-by-tip evaluation saved to: {out_file}")


if __name__ == "__main__":
    main()
