#!/usr/bin/env python3
"""
Mario AI - Standalone Local Shadow Evaluator & Performance Pipeline
====================================================================
Features:
1. 100% Isolated: Stores predictions in `core.shadow_tips_eval` and scores in `core.shadow_results`.
   Does NOT write to `core.published_tips`, `core.tip_audit_log`, `core.results`, or any production table.
2. ZERO Telegram Impact: No messages are ever sent to Telegram.
3. Live Data Ingestion: Connects directly to live API (`/matches/pre`, `/matches/ebasket/pre`, and `/history/*`).
4. Re-Evaluated ML Models: Evaluates all 5 markets using the newly trained, calibrated `*_final.joblib` bundles.
5. Dedicated Whistle Settlement: Actively fetches finished match scores from the API and saves to `core.shadow_results`.
6. Real-Time Telemetry: Tracks Sample Size, Decided Win Rate, Net Units, and Decided ROI.
"""

import os
import sys
import time
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

import requests
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv
import pandas as pd
import numpy as np
import joblib

# Load local environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SHADOW-PIPELINE] %(message)s"
)
logger = logging.getLogger("shadow_pipeline")

def get_db_url() -> str:
    env_db = os.getenv("DATABASE_URL")
    if env_db:
        if "@db:" in env_db:
            return env_db
        if "localhost" in env_db or "127.0.0.1" in env_db:
            try:
                conn = psycopg2.connect(env_db, connect_timeout=1)
                cur = conn.cursor()
                cur.execute("SELECT count(*) FROM core.published_tips;")
                cnt = cur.fetchone()[0]
                conn.close()
                if cnt > 100:
                    return env_db
            except Exception:
                pass
            return "postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai"
        return env_db
    return "postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai"

DB_URL = get_db_url()
JARBET_BASE_URL = os.getenv("JARBET_BASE_URL", "https://data.jarvisbet.com.br").rstrip("/")
JARBET_API_KEY = os.getenv("JARBET_API_KEY", "")

# Point to re-evaluated models directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
# Also ensure project root is in sys.path
for candidate in [SCRIPT_DIR, r"D:\Mario AI Code"]:
    if os.path.exists(candidate) and candidate not in sys.path:
        sys.path.append(candidate)
MODELS_DIR = os.getenv("MODEL_DIR") or os.path.join(SCRIPT_DIR, "core", "re-evaluated models")
if not os.path.exists(MODELS_DIR):
    alt_dir = os.path.join(SCRIPT_DIR, "core", "re-evaluated models")
    if os.path.exists(alt_dir):
        MODELS_DIR = alt_dir

logger.info(f"Using models directory: {MODELS_DIR}")

# ---------------------------------------------------------------------------
# Database Initialization (Strictly Isolated Tables)
# ---------------------------------------------------------------------------

def init_shadow_db():
    """Ensures isolated shadow evaluation and results tables exist in PostgreSQL."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS core.shadow_tips_eval (
            id SERIAL PRIMARY KEY,
            match_id VARCHAR(64) NOT NULL,
            bet365_id VARCHAR(64),
            sport VARCHAR(32) NOT NULL,
            channel_key VARCHAR(64) NOT NULL,
            league VARCHAR(128),
            fixture VARCHAR(255) NOT NULL,
            market_type VARCHAR(64) NOT NULL,
            pick_str VARCHAR(128) NOT NULL,
            side VARCHAR(32),
            line NUMERIC(6, 2),
            odds NUMERIC(6, 3),
            implied_prob NUMERIC(6, 4),
            model_prob NUMERIC(6, 4),
            estimated_edge NUMERIC(6, 4),
            status VARCHAR(32) DEFAULT 'PENDING',
            final_score VARCHAR(32),
            outcome VARCHAR(32),
            net_units NUMERIC(6, 3),
            kickoff_at_utc TIMESTAMP WITH TIME ZONE,
            evaluated_at_utc TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            settled_at_utc TIMESTAMP WITH TIME ZONE,
            UNIQUE(channel_key, match_id)
        );
        CREATE INDEX IF NOT EXISTS idx_shadow_status ON core.shadow_tips_eval(status);
        CREATE INDEX IF NOT EXISTS idx_shadow_channel ON core.shadow_tips_eval(channel_key);
        CREATE INDEX IF NOT EXISTS idx_shadow_kickoff ON core.shadow_tips_eval(kickoff_at_utc);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_shadow_channel_bet365_uniq 
            ON core.shadow_tips_eval (channel_key, bet365_id)
            WHERE bet365_id IS NOT NULL AND bet365_id != '';

        CREATE TABLE IF NOT EXISTS core.shadow_results (
            match_id VARCHAR(64) PRIMARY KEY,
            bet365_id VARCHAR(64),
            sport VARCHAR(32),
            final_home_score NUMERIC(6, 2) NOT NULL,
            final_away_score NUMERIC(6, 2) NOT NULL,
            settled_at_utc TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            source VARCHAR(64) DEFAULT 'shadow_api_fetcher'
        );
        CREATE INDEX IF NOT EXISTS idx_shadow_results_b365 ON core.shadow_results(bet365_id);

        ALTER TABLE core.shadow_tips_eval ADD COLUMN IF NOT EXISTS pending_reason VARCHAR(128) DEFAULT 'NONE (Fully Settled)';
        ALTER TABLE core.shadow_tips_eval ADD COLUMN IF NOT EXISTS source VARCHAR(64) DEFAULT 'shadow_api_fetcher';
        ALTER TABLE core.shadow_tips_eval ADD COLUMN IF NOT EXISTS time_pending VARCHAR(64);
    """)
    conn.commit()
    conn.close()
    logger.info("Initialized isolated shadow tables: core.shadow_tips_eval & core.shadow_results")

# ---------------------------------------------------------------------------
# Re-Evaluated Model Manager
# ---------------------------------------------------------------------------

class ReevaluatedModelManager:
    """Loads and runs inference using the re-evaluated models."""

    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self.bundles: Dict[str, Any] = {}
        self.player_stats_cache: Dict[Tuple[str, str], Tuple[float, float, int]] = {}
        self.last_cache_refresh = 0.0
        self.load_bundles()
        self.refresh_player_stats()

    def load_bundles(self):
        model_files = {
            "fifa_goals_ou": "fifa_goals_ou_model_final.joblib",
            "fifa_asian_handicap": "fifa_asian_handicap_model_final.joblib",
            "fifa_money_line": "fifa_money_line_model_final.joblib",
            "ebasket_money_line": "ebasket_money_line_model_final.joblib",
            "ebasket_ou": "ebasket_ou_model_final.joblib",
        }
        for market, fname in model_files.items():
            fpath = os.path.join(self.models_dir, fname)
            if os.path.exists(fpath):
                try:
                    self.bundles[market] = joblib.load(fpath)
                    ver = self.bundles[market].get("model_version", "unknown")
                    logger.info(f"Loaded re-evaluated model for {market}: version {ver}")
                except Exception as e:
                    logger.error(f"Error loading bundle {fpath}: {e}")
            else:
                logger.warning(f"Re-evaluated model bundle not found: {fpath}")

    def refresh_player_stats(self):
        """Refreshes historical scoring averages from database (read-only)."""
        now = time.time()
        if now - self.last_cache_refresh < 300 and self.player_stats_cache:
            return

        try:
            conn = psycopg2.connect(DB_URL, connect_timeout=5)
            cur = conn.cursor()
            cur.execute("""
                SELECT m.sport, LOWER(TRIM(home_player)), AVG(r.final_home_score), AVG(r.final_away_score), COUNT(*)
                FROM core.results r JOIN core.matches m ON r.match_id = m.match_id
                WHERE r.final_home_score IS NOT NULL AND r.final_away_score IS NOT NULL
                GROUP BY m.sport, LOWER(TRIM(home_player));
            """)
            stats = {}
            for row in cur.fetchall():
                if row[0] and row[1]:
                    stats[(row[0], row[1])] = (float(row[2]), float(row[3]), int(row[4]))

            cur.execute("""
                SELECT m.sport, LOWER(TRIM(away_player)), AVG(r.final_away_score), AVG(r.final_home_score), COUNT(*)
                FROM core.results r JOIN core.matches m ON r.match_id = m.match_id
                WHERE r.final_home_score IS NOT NULL AND r.final_away_score IS NOT NULL
                GROUP BY m.sport, LOWER(TRIM(away_player));
            """)
            for row in cur.fetchall():
                if row[0] and row[1]:
                    k = (row[0], row[1])
                    if k in stats:
                        sc = (stats[k][0] + float(row[2])) / 2.0
                        cc = (stats[k][1] + float(row[3])) / 2.0
                        stats[k] = (sc, cc, stats[k][2] + int(row[4]))
                    else:
                        stats[k] = (float(row[2]), float(row[3]), int(row[4]))

            conn.close()
            self.player_stats_cache = stats
            self.last_cache_refresh = now
            logger.debug(f"Refreshed player stats cache ({len(stats)} profiles)")
        except Exception as e:
            logger.debug(f"Player stats refresh note: {e}")

    def get_player_stats(self, sport: str, player: str) -> Tuple[float, float, bool]:
        clean_p = player.strip().lower()
        m_handle = re.search(r"\((.*?)\)", clean_p)
        if m_handle:
            clean_p = m_handle.group(1).strip()

        def_sc = 2.2 if sport == "fifa" else 55.6
        def_cc = 2.2 if sport == "fifa" else 55.6

        st = self.player_stats_cache.get((sport, clean_p))
        if st:
            return st[0], st[1], st[2] >= 3
        return def_sc, def_cc, False

GLOBAL_MGR: Optional[ReevaluatedModelManager] = None

def get_shadow_model_manager() -> ReevaluatedModelManager:
    global GLOBAL_MGR
    if GLOBAL_MGR is None:
        GLOBAL_MGR = ReevaluatedModelManager(MODELS_DIR)
    return GLOBAL_MGR

# ---------------------------------------------------------------------------
# Live Match Feed Ingestion
# ---------------------------------------------------------------------------

def fetch_live_matches() -> List[Dict[str, Any]]:
    """Fetches upcoming pre-match fixtures from the API."""
    headers = {"x-api-key": JARBET_API_KEY, "Accept": "application/json"}
    all_matches = []

    # 1. FIFA
    try:
        r = requests.get(f"{JARBET_BASE_URL}/matches/pre", headers=headers, timeout=8)
        if r.status_code == 200:
            d = r.json()
            matches = d.get("matches", d) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for m in matches:
                m["_sport"] = "fifa"
                all_matches.append(m)
    except Exception as e:
        logger.warning(f"Error fetching FIFA live matches: {e}")

    # 2. eBasketball
    try:
        r = requests.get(f"{JARBET_BASE_URL}/matches/ebasket/pre", headers=headers, timeout=8)
        if r.status_code == 200:
            d = r.json()
            matches = d.get("matches", d) if isinstance(d, dict) else (d if isinstance(d, list) else [])
            for m in matches:
                m["_sport"] = "ebasket"
                all_matches.append(m)
    except Exception as e:
        logger.warning(f"Error fetching eBasket live matches: {e}")

    return all_matches

# ---------------------------------------------------------------------------
# Re-Evaluated Shadow Inference Engine
# ---------------------------------------------------------------------------

# Strict High-Edge Parameter Locks per Channel
CHANNEL_MIN_EDGE = {
    "fifa_goals_ou": 0.08,        # Strict Edge > 8% on FIFA Goals
    "fifa_asian_handicap": 0.05,  # Strict Edge > 5% on Asian Handicap
    "fifa_money_line": 0.05,      # Strict Edge > 5% on FIFA Money Line
    "ebasket_money_line": 0.02,   # Unchanged: eBasket Money Line as is (2%)
    "ebasket_ou": 0.02,           # Unchanged: eBasket O/U as is (2%)
}

def evaluate_shadow_opportunities(matches: List[Dict[str, Any]], min_odds: float = 1.60):
    """Evaluates upcoming matches using re-evaluated model bundles and logs shadow tips with strict edge locks."""
    mgr = get_shadow_model_manager()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    new_shadow_count = 0
    channel_list = [
        ("fifa_goals_ou", "fifa"),
        ("fifa_asian_handicap", "fifa"),
        ("fifa_money_line", "fifa"),
        ("ebasket_money_line", "ebasket"),
        ("ebasket_ou", "ebasket"),
    ]

    for match in matches:
        sport = match.get("_sport", "fifa")
        b365_id = str(match.get("idMatchBet365") or "").strip()
        raw_mid = b365_id if b365_id else str(match.get("_id") or "").strip()
        league = str(match.get("league") or match.get("tournament") or "")
        odds_dict = match.get("odds", {})

        home_info = match.get("home", {}) if isinstance(match.get("home"), dict) else {}
        away_info = match.get("away", {}) if isinstance(match.get("away"), dict) else {}
        h_team = home_info.get("teamName", "")
        a_team = away_info.get("teamName", "")
        h_player = home_info.get("name", "")
        a_player = away_info.get("name", "")
        fixture = f"{h_team} ({h_player}) vs {a_team} ({a_player})"

        ko_str = match.get("startedAt")
        ko_dt = None
        if ko_str:
            try:
                ko_dt = datetime.fromisoformat(ko_str.replace("Z", "+00:00"))
            except Exception:
                pass

        h_sc, h_cc, h_rel = mgr.get_player_stats(sport, h_player)
        a_sc, a_cc, a_rel = mgr.get_player_stats(sport, a_player)

        for ch_key, ch_sport in channel_list:
            if ch_sport != sport or ch_key not in mgr.bundles:
                continue

            bundle = mgr.bundles[ch_key]
            model = bundle["model"]
            calibrator = bundle.get("calibrator") or bundle.get("calibrators")
            feat_names = bundle["feature_names"]
            min_edge = CHANNEL_MIN_EDGE.get(ch_key, 0.05)

            pick = None

            # 1. FIFA Goals O/U (Strict Edge > 8%)
            if ch_key == "fifa_goals_ou":
                ou = odds_dict.get("over_under", {}) if isinstance(odds_dict.get("over_under"), dict) else {}
                line_val = float(ou.get("line", 2.5))
                over_odds = float(ou.get("over", 0.0))
                under_odds = float(ou.get("under", 0.0))
                if over_odds <= 1.05 and under_odds <= 1.05:
                    continue

                exp_tot = (h_sc + a_cc) / 2.0 + (a_sc + h_cc) / 2.0
                imp_p_over = 1.0 / over_odds if over_odds > 1.0 else 0.50
                imp_p_under = 1.0 / under_odds if under_odds > 1.0 else 0.50

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

                if edge_o >= min_edge and over_odds >= min_odds:
                    pick = ("over", line_val, over_odds, cal_p, edge_o, f"Mais de {line_val} Gols")
                elif edge_u >= min_edge and under_odds >= min_odds:
                    pick = ("under", line_val, under_odds, 1.0 - cal_p, edge_u, f"Menos de {line_val} Gols")

            # 2. FIFA Asian Handicap (Strict Edge > 5%)
            elif ch_key == "fifa_asian_handicap":
                ah = odds_dict.get("asian_handicap", {}) if isinstance(odds_dict.get("asian_handicap"), dict) else {}
                line_val = float(ah.get("line", 0.0))
                h_odds = float(ah.get("home", 0.0))
                a_odds = float(ah.get("away", 0.0))
                if h_odds <= 1.05 and a_odds <= 1.05:
                    continue

                diff_exp = (h_sc - h_cc) - (a_sc - a_cc)
                imp_p_home = 1.0 / h_odds if h_odds > 1.0 else 0.50
                imp_p_away = 1.0 / a_odds if a_odds > 1.0 else 0.50

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
                edge_a = (1.0 - cal_p) - imp_p_away

                if edge_h >= min_edge and h_odds >= min_odds:
                    pick = ("home", line_val, h_odds, cal_p, edge_h, f"{h_team} (Handicap {line_val:+.1f})")
                elif edge_a >= min_edge and a_odds >= min_odds:
                    pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Handicap {-line_val:+.1f})")

            # 3. FIFA Money Line (Draw No Bet, Strict Edge > 5%)
            elif ch_key == "fifa_money_line":
                ml = odds_dict.get("money_line", odds_dict.get("draw_no_bet", {})) if isinstance(odds_dict.get("money_line", odds_dict.get("draw_no_bet", {})), dict) else {}
                h_odds = float(ml.get("home", 0.0))
                a_odds = float(ml.get("away", 0.0))
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
                    pick = ("home", 0.0, h_odds, p_h, edge_h, f"{h_team} (Empate Anula)")
                elif edge_a >= min_edge and a_odds >= min_odds:
                    pick = ("away", 0.0, a_odds, p_a, edge_a, f"{a_team} (Empate Anula)")

            # 4. eBasket Money Line (Unchanged Edge >= 2%)
            elif ch_key == "ebasket_money_line":
                ml = odds_dict.get("money_line", {}) if isinstance(odds_dict.get("money_line"), dict) else {}
                h_odds = float(ml.get("home", 0.0))
                a_odds = float(ml.get("away", 0.0))
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
                    pick = ("home", 0.0, h_odds, cal_p, edge_h, f"{h_team} (Vencedor)")
                elif edge_a >= min_edge and a_odds >= min_odds:
                    pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Vencedor)")

            # 5. eBasket O/U (Unchanged Edge >= 2%)
            elif ch_key == "ebasket_ou":
                ou = odds_dict.get("over_under", {}) if isinstance(odds_dict.get("over_under"), dict) else {}
                line_val = float(ou.get("line", 110.5))
                over_odds = float(ou.get("over", 0.0))
                under_odds = float(ou.get("under", 0.0))
                if over_odds <= 1.05 and under_odds <= 1.05:
                    continue

                exp_tot = (h_sc + a_cc) / 2.0 + (a_sc + h_cc) / 2.0
                imp_p_o = 1.0 / over_odds if over_odds > 1.0 else 0.50
                imp_p_u = 1.0 / under_odds if under_odds > 1.0 else 0.50

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
                    'odds_implied_prob_over': imp_p_o, 'odds_implied_prob_under': imp_p_u,
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
                edge_u = (1.0 - cal_p) - imp_p_u

                if edge_o >= min_edge and over_odds >= min_odds:
                    pick = ("over", line_val, over_odds, cal_p, edge_o, f"Mais de {line_val} Pontos")
                elif edge_u >= min_edge and under_odds >= min_odds:
                    pick = ("under", line_val, under_odds, 1.0 - cal_p, edge_u, f"Menos de {line_val} Pontos")

            if not pick:
                continue

            side, line_out, odds_out, m_prob, est_edge, pick_str = pick
            required_min_edge = CHANNEL_MIN_EDGE.get(ch_key, 0.05)
            if est_edge < required_min_edge:
                logger.debug(f"Skipping sub-threshold pick: {ch_key} {fixture} (edge {est_edge:.4f} < {required_min_edge:.4f})")
                continue

            imp_prob = 1.0 / odds_out

            try:
                # Deduplicate on (channel_key, bet365_id) and (channel_key, match_id)
                cur.execute("""
                    SELECT 1 FROM core.shadow_tips_eval
                    WHERE channel_key = %s
                      AND (match_id = %s OR (bet365_id = %s AND bet365_id != ''))
                    LIMIT 1;
                """, (ch_key, raw_mid, b365_id))
                if cur.fetchone():
                    continue

                cur.execute("""
                    INSERT INTO core.shadow_tips_eval (
                        match_id, bet365_id, sport, channel_key, league, fixture,
                        market_type, pick_str, side, line, odds, implied_prob,
                        model_prob, estimated_edge, status, kickoff_at_utc,
                        pending_reason, source, time_pending
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, 'PENDING', %s,
                        'AWAITING_MATCH_WHISTLE', 'shadow_api_fetcher', '0.0h'
                    ) ON CONFLICT DO NOTHING;
                """, (
                    raw_mid, b365_id, sport, ch_key, league, fixture,
                    ch_key, pick_str, side, line_out, odds_out, round(imp_prob, 4),
                    round(m_prob, 4), round(est_edge, 4), ko_dt
                ))
                if cur.rowcount > 0:
                    new_shadow_count += 1
                    logger.info(f"  [SHADOW PICK LOGGED] {ch_key.upper()} | {fixture} | Pick: {pick_str} @ {odds_out:.2f} (Prob: {m_prob*100:.1f}%, Edge: +{est_edge*100:.1f}%)")
            except Exception as ins_err:
                logger.debug(f"Insert error for shadow match {raw_mid}: {ins_err}")

    conn.commit()
    conn.close()
    if new_shadow_count > 0:
        logger.info(f"Recorded {new_shadow_count} new shadow predictions with Re-Evaluated Models.")

# ---------------------------------------------------------------------------
# Dedicated Whistle Settlement Fetcher (Direct API to core.shadow_results)
# ---------------------------------------------------------------------------

def fetch_scores_for_pending_shadow_matches():
    """
    Directly queries API for finished scores of pending shadow matches.
    Stores verified results strictly in `core.shadow_results` (never touches core.results).
    """
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Find pending matches where kickoff was at least 12 minutes ago
    cur.execute("""
        SELECT DISTINCT match_id, bet365_id, sport, fixture, kickoff_at_utc
        FROM core.shadow_tips_eval
        WHERE status = 'PENDING'
          AND kickoff_at_utc < NOW() - INTERVAL '10 minutes'
        ORDER BY kickoff_at_utc DESC
        LIMIT 50;
    """)
    pending_matches = cur.fetchall()
    conn.close()

    if not pending_matches:
        return

    logger.info(f"Checking API results for {len(pending_matches)} pending shadow fixtures...")
    headers = {"x-api-key": JARBET_API_KEY, "Accept": "application/json"}
    discovered_scores = {}  # id -> (fh, fa, sport)

    # 1. Quick check: inspect live feeds for recently ended games
    for sport, ep in [("fifa", "/matches/pre"), ("ebasket", "/matches/ebasket/pre")]:
        try:
            r = requests.get(f"{JARBET_BASE_URL}{ep}", headers=headers, timeout=6)
            if r.status_code == 200:
                d = r.json()
                items = d.get("matches", d) if isinstance(d, dict) else (d if isinstance(d, list) else [])
                for m in items:
                    if not isinstance(m, dict):
                        continue
                    m_status = str(m.get("status") or m.get("state") or "").upper()
                    is_fin = m.get("isFinished") is True or m_status in ["ENDED", "FINISHED", "FT", "CLOSED"]
                    h_obj = m.get("home", {}) if isinstance(m.get("home"), dict) else {}
                    a_obj = m.get("away", {}) if isinstance(m.get("away"), dict) else {}
                    hg = h_obj.get("goals") if h_obj.get("goals") is not None else h_obj.get("score")
                    ag = a_obj.get("goals") if a_obj.get("goals") is not None else a_obj.get("score")

                    if hg is not None and ag is not None and (is_fin or (m_status not in ["LIVE", "IN_PLAY"])):
                        try:
                            fh = float(hg)
                            fa = float(ag)
                            raw_id = str(m.get("_id") or m.get("id") or "").strip()
                            b365 = str(m.get("idMatchBet365") or m.get("bet365_id") or "").strip()
                            if raw_id: discovered_scores[raw_id] = (fh, fa, sport, b365)
                            if b365: discovered_scores[b365] = (fh, fa, sport, b365)
                        except (ValueError, TypeError):
                            pass
        except Exception as e:
            logger.debug(f"Feed check note: {e}")

    # 2. Extract player names from remaining pending fixtures and query /history
    pending_ids = set()
    players_to_query = []
    for pm in pending_matches:
        mid = str(pm["match_id"])
        b365 = str(pm["bet365_id"] or "")
        pending_ids.add(mid)
        if b365: pending_ids.add(b365)

        # Extract player handles from fixture string: "HomeTeam (Player1) vs AwayTeam (Player2)"
        found = re.findall(r'\(([^)]+)\)', pm["fixture"])
        for p in found:
            p_clean = p.strip()
            if len(p_clean) > 1 and (pm["sport"], p_clean) not in players_to_query:
                players_to_query.append((pm["sport"], p_clean))

    # Query player history for matching IDs
    for sport, player in players_to_query[:15]:  # Batch up to 15 players per cycle to respect rate limits
        endpoint = "/history/ebasket/pre" if sport == "ebasket" else "/history/pre"
        try:
            r = requests.get(f"{JARBET_BASE_URL}{endpoint}", headers=headers, params={"homeName": player}, timeout=8)
            if r.status_code == 200:
                d = r.json()
                items = d.get("matches", d) if isinstance(d, dict) else (d if isinstance(d, list) else [])
                for m in items:
                    if not isinstance(m, dict):
                        continue
                    m_id = str(m.get("_id") or m.get("id") or "").strip()
                    b_id = str(m.get("idMatchBet365") or m.get("bet365_id") or "").strip()

                    if m_id in pending_ids or b_id in pending_ids:
                        h_obj = m.get("home", {}) if isinstance(m.get("home"), dict) else {}
                        a_obj = m.get("away", {}) if isinstance(m.get("away"), dict) else {}
                        hg = h_obj.get("goals") if h_obj.get("goals") is not None else h_obj.get("score")
                        ag = a_obj.get("goals") if a_obj.get("goals") is not None else a_obj.get("score")
                        if hg is not None and ag is not None:
                            try:
                                fh, fa = float(hg), float(ag)
                                if m_id: discovered_scores[m_id] = (fh, fa, sport, b_id)
                                if b_id: discovered_scores[b_id] = (fh, fa, sport, b_id)
                            except Exception:
                                pass
        except Exception as err:
            logger.debug(f"History query note for {player}: {err}")

    # Persist newly discovered scores into core.shadow_results ONLY
    if discovered_scores:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        saved_count = 0
        for m_key, (fh, fa, sport, b_id) in discovered_scores.items():
            try:
                cur.execute("""
                    INSERT INTO core.shadow_results (
                        match_id, bet365_id, sport, final_home_score, final_away_score, settled_at_utc, source
                    ) VALUES (
                        %s, %s, %s, %s, %s, NOW(), 'shadow_api_fetcher'
                    ) ON CONFLICT (match_id) DO UPDATE SET
                        final_home_score = EXCLUDED.final_home_score,
                        final_away_score = EXCLUDED.final_away_score;
                """, (m_key, b_id, sport, fh, fa))
                saved_count += 1
            except Exception as e:
                logger.debug(f"Shadow result save note: {e}")
        conn.commit()
        conn.close()
        if saved_count > 0:
            logger.info(f"Persisted {saved_count} verified match scores into core.shadow_results.")

def settle_shadow_tips():
    """Settles pending shadow tips against core.shadow_results (and fallback core.results)."""
    fetch_scores_for_pending_shadow_matches()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT s.id, s.match_id, s.bet365_id, s.sport, s.channel_key, s.side, s.line, s.odds,
               COALESCE(sr.final_home_score, r.final_home_score) as final_home_score,
               COALESCE(sr.final_away_score, r.final_away_score) as final_away_score
        FROM core.shadow_tips_eval s
        LEFT JOIN core.shadow_results sr ON (s.match_id = sr.match_id OR s.bet365_id = sr.bet365_id OR s.match_id = sr.bet365_id)
        LEFT JOIN core.results r ON (s.match_id = r.match_id OR s.bet365_id = r.match_id)
        WHERE s.status = 'PENDING'
          AND (sr.final_home_score IS NOT NULL OR r.final_home_score IS NOT NULL);
    """)
    pending = cur.fetchall()

    settled_now = 0
    update_cur = conn.cursor()

    for tip in pending:
        fh = float(tip["final_home_score"])
        fa = float(tip["final_away_score"])
        final_str = f"{int(fh)}-{int(fa)}"
        odds = float(tip["odds"])
        line = float(tip["line"]) if tip["line"] is not None else 0.0
        side = str(tip["side"]).lower()
        ch = tip["channel_key"]

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

        update_cur.execute("""
            UPDATE core.shadow_tips_eval
            SET status = 'SETTLED',
                final_score = %s,
                outcome = %s,
                net_units = %s,
                pending_reason = 'NONE (Fully Settled)',
                source = COALESCE(source, 'shadow_api_fetcher'),
                time_pending = '0.0h (Resolved)',
                settled_at_utc = NOW()
            WHERE id = %s;
        """, (final_str, outcome, round(net_units, 3), tip["id"]))
        settled_now += 1

    # -----------------------------------------------------------------------
    # 4-Hour Rule: Auto-void stale pending fixtures (> 4 hours post-kickoff)
    # -----------------------------------------------------------------------
    update_cur.execute("""
        UPDATE core.shadow_tips_eval
        SET status = 'SETTLED',
            final_score = 'ABANDONED',
            outcome = 'VOID',
            net_units = 0.000,
            pending_reason = 'ABANDONED_FIXTURE (Exceeded 4h whistle window)',
            source = COALESCE(source, 'shadow_api_fetcher'),
            time_pending = ROUND(EXTRACT(EPOCH FROM (NOW() - kickoff_at_utc))/3600.0, 1)::text || 'h (Exceeded limit)',
            settled_at_utc = COALESCE(kickoff_at_utc + INTERVAL '4 hours', NOW())
        WHERE status = 'PENDING'
          AND kickoff_at_utc < NOW() - INTERVAL '4 hours';
    """)
    abandoned_now = update_cur.rowcount
    if abandoned_now > 0:
        logger.info(f"4-Hour Rule applied: Auto-voided {abandoned_now} stale fixtures as ABANDONED_FIXTURE.")

    # Update active fresh pending tips (< 4 hours) with real-time pending tracking fields
    update_cur.execute("""
        UPDATE core.shadow_tips_eval
        SET pending_reason = 'AWAITING_MATCH_WHISTLE',
            source = COALESCE(source, 'shadow_api_fetcher'),
            time_pending = ROUND(EXTRACT(EPOCH FROM (NOW() - kickoff_at_utc))/3600.0, 1)::text || 'h'
        WHERE status = 'PENDING';
    """)

    conn.commit()
    conn.close()
    if settled_now > 0:
        logger.info(f"Settled {settled_now} shadow tips against verified whistle results.")

# ---------------------------------------------------------------------------
# Telemetry Dashboard
# ---------------------------------------------------------------------------
def calculate_single_settlement(ch: str, side: str, line: Optional[float], odds: float, fh: int, fa: int) -> Tuple[str, float]:
    """Calculates settlement outcome and net units given match scores."""
    outcome = "VOID"
    net_units = 0.0

    if "goals_ou" in ch or "ebasket_ou" in ch:
        tot = fh + fa
        line_val = line if line is not None else 0.0
        diff = tot - line_val
        if diff > 0.25: outcome, net_units = ("WIN", odds - 1.0) if side == "over" else ("LOSS", -1.0)
        elif diff == 0.25: outcome, net_units = ("HALF_WIN", 0.5 * (odds - 1.0)) if side == "over" else ("HALF_LOSS", -0.5)
        elif diff == 0.0: outcome, net_units = "VOID", 0.0
        elif diff == -0.25: outcome, net_units = ("HALF_LOSS", -0.5) if side == "over" else ("HALF_WIN", 0.5 * (odds - 1.0))
        else: outcome, net_units = ("LOSS", -1.0) if side == "over" else ("WIN", odds - 1.0)

    elif "asian_handicap" in ch:
        line_val = line if line is not None else 0.0
        diff = (fh - fa) + line_val if side == "home" else (fa - fh) + line_val
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

    return outcome, round(net_units, 3)

def clean_and_sync_oct5_shadow_data(clean: bool = True):
    """
    Cleans shadow tables (if requested) and reseeds all match opportunities from Oct 5th onwards
    evaluating them exclusively with the re-evaluated models (*_final.joblib) and high edge filters.
    All data is strictly saved to core.shadow_tips_eval and core.shadow_results (core.results is UNTOUCHED).
    """
    logger.info("=" * 80)
    logger.info(f"SYNCING SHADOW DATA FROM OCT 5TH (Clean={clean}) WITH RE-EVALUATED MODELS")
    logger.info("=" * 80)

    mgr = get_shadow_model_manager()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Load verified scores from core.results and core.shadow_results
    results_map = {}
    try:
        cur.execute("""
            SELECT match_id, final_home_score, final_away_score, settled_at as settled_at_utc
            FROM core.results
            WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
        """)
        for r in cur.fetchall():
            results_map[str(r["match_id"])] = r
    except Exception as e:
        logger.debug(f"results load note: {e}")

    try:
        cur.execute("""
            SELECT match_id, bet365_id, final_home_score, final_away_score, sport, settled_at_utc
            FROM core.shadow_results
            WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
        """)
        for r in cur.fetchall():
            mid = str(r["match_id"])
            if mid not in results_map:
                results_map[mid] = r
            elif r.get("settled_at_utc") and not results_map[mid].get("settled_at_utc"):
                results_map[mid]["settled_at_utc"] = r["settled_at_utc"]
            if r.get("bet365_id") and str(r["bet365_id"]) not in results_map:
                results_map[str(r["bet365_id"])] = r
    except Exception as e:
        logger.debug(f"shadow_results load note: {e}")

    logger.info(f"Loaded {len(results_map)} verified final scores for historical shadow settlement.")

    # 2. Clean shadow_tips_eval if requested
    if clean:
        logger.info("Cleaning core.shadow_tips_eval...")
        cur.execute("TRUNCATE TABLE core.shadow_tips_eval RESTART IDENTITY;")
        conn.commit()

    # 3. Fetch candidate opportunities since Oct 5th
    cur.execute("""
        WITH raw_opps AS (
            SELECT match_id, match_id as bet365_id, channel_key, sport, fixture, side, line, odds, kickoff_at_utc, published_at_utc as eval_time
            FROM core.published_tips
            WHERE published_at_utc >= '2026-10-05 00:00:00+00'
        )
        SELECT DISTINCT ON (COALESCE(NULLIF(bet365_id, ''), match_id), channel_key)
            match_id, bet365_id, channel_key, sport, fixture, side, line, odds, kickoff_at_utc, eval_time
        FROM raw_opps
        ORDER BY COALESCE(NULLIF(bet365_id, ''), match_id), channel_key, eval_time ASC;
    """)
    opps = cur.fetchall()
    logger.info(f"Loaded {len(opps)} candidate historical opportunities to evaluate from Oct 5th.")

    min_odds = 1.60
    tips_to_insert = []
    shadow_results_to_save = {}

    for row in opps:
        ch_key = row["channel_key"]
        if ch_key not in mgr.bundles:
            continue

        raw_match_id = str(row["match_id"])
        bet365_id = str(row.get("bet365_id") or raw_match_id)
        sport = row["sport"]
        fixture = row["fixture"] or ""
        orig_side = str(row["side"] or "home").lower()
        orig_line = float(row["line"]) if row["line"] is not None else 0.0
        orig_odds = float(row["odds"]) if row["odds"] is not None else 1.90
        ko_time = row["kickoff_at_utc"]
        eval_time = row["eval_time"] or ko_time
        min_edge = CHANNEL_MIN_EDGE.get(ch_key, 0.05)

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

        # 1. FIFA Goals O/U (Strict Edge >= 8%)
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
                'implied_vs_hist_divergence': imp_p_over - 0.50
            }
            X = pd.DataFrame([feat_vec])[feat_names]
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            edge_o = cal_p - imp_p_over
            edge_u = (1.0 - cal_p) - (1.0 / u_odds if u_odds > 1.0 else 0.50)

            if edge_o >= min_edge and o_odds >= min_odds:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Gols")
            elif edge_u >= min_edge and u_odds >= min_odds:
                pick = ("under", line_val, u_odds, 1.0 - cal_p, edge_u, f"Menos de {line_val} Gols")

        # 2. FIFA Asian Handicap (Strict Edge >= 5%)
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
                pick = ("home", line_val, h_odds, cal_p, edge_h, f"{h_team} (Handicap {line_val:+.1f})")
            elif edge_a >= min_edge and a_odds >= min_odds:
                pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Handicap {-line_val:+.1f})")

        # 3. FIFA Money Line (Strict Edge >= 5%)
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
                pick = ("home", 0.0, h_odds, p_h, edge_h, f"{h_team} (Empate Anula)")
            elif edge_a >= min_edge and a_odds >= min_odds:
                pick = ("away", 0.0, a_odds, p_a, edge_a, f"{a_team} (Empate Anula)")

        # 4. eBasket Money Line (Edge >= 2%)
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
                pick = ("home", 0.0, h_odds, cal_p, edge_h, f"{h_team} (Vencer)")
            elif edge_a >= min_edge and a_odds >= min_odds:
                pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Vencer)")

        # 5. eBasket O/U (Edge >= 2%)
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
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Pontos")
            elif edge_u >= min_edge and u_odds >= min_odds:
                pick = ("under", line_val, u_odds, 1.0 - cal_p, edge_u, f"Menos de {line_val} Pontos")

        if pick is not None:
            side, line, odds, model_p, edge, pick_str = pick
            imp_prob = 1.0 / odds

            m_res = results_map.get(raw_match_id) or results_map.get(bet365_id)
            if m_res and m_res["final_home_score"] is not None and m_res["final_away_score"] is not None:
                fh = int(m_res["final_home_score"])
                fa = int(m_res["final_away_score"])
                outcome, net_units = calculate_single_settlement(ch_key, side, line, odds, fh, fa)
                status = "SETTLED"
                final_score = f"{fh}-{fa}"
                settled_at = m_res.get("settled_at_utc")
                if not settled_at or (ko_time and settled_at <= ko_time):
                    duration = timedelta(minutes=15) if sport == "fifa" else timedelta(minutes=20)
                    settled_at = (ko_time + duration) if ko_time else (eval_time + duration)
                pending_reason = "NONE (Fully Settled)"
                src = "shadow_api_fetcher"
                time_pending = "0.0h (Resolved)"
                if raw_match_id not in shadow_results_to_save:
                    shadow_results_to_save[raw_match_id] = (
                        raw_match_id, bet365_id, sport, fh, fa, settled_at, "historic_sync"
                    )
            else:
                # 4-Hour Rule: Auto-void stale fixtures exceeding 4 hours post-kickoff
                now_utc = datetime.now(timezone.utc)
                age_hrs = (now_utc - ko_time).total_seconds() / 3600.0 if ko_time else 0.0
                if age_hrs >= 4.0:
                    status = "SETTLED"
                    final_score = "ABANDONED"
                    outcome = "VOID"
                    net_units = 0.000
                    settled_at = ko_time + timedelta(hours=4) if ko_time else now_utc
                    pending_reason = "ABANDONED_FIXTURE (Exceeded 4h whistle window)"
                    src = "shadow_api_fetcher"
                    time_pending = f"{round(age_hrs, 1)}h (Exceeded limit)"
                else:
                    status = "PENDING"
                    final_score = None
                    outcome = None
                    net_units = 0.0
                    settled_at = None
                    pending_reason = "AWAITING_MATCH_WHISTLE"
                    src = "shadow_api_fetcher"
                    time_pending = f"{round(age_hrs, 1)}h"

            tips_to_insert.append((
                raw_match_id, bet365_id, sport, ch_key, "eSports", fixture,
                bundle.get("market_name", ch_key), pick_str, side, line, odds,
                round(imp_prob, 4), round(float(model_p), 4), round(float(edge), 4),
                status, final_score, outcome, net_units, ko_time, eval_time, settled_at,
                pending_reason, src, time_pending
            ))

    logger.info(f"Re-evaluated models generated {len(tips_to_insert)} qualifying shadow tips with High-Edge filters.")

    if shadow_results_to_save:
        res_sql = """
            INSERT INTO core.shadow_results (
                match_id, bet365_id, sport, final_home_score, final_away_score, settled_at_utc, source
            ) VALUES %s
            ON CONFLICT (match_id) DO NOTHING;
        """
        execute_values(cur, res_sql, list(shadow_results_to_save.values()), page_size=1000)

    if tips_to_insert:
        tips_sql = """
            INSERT INTO core.shadow_tips_eval (
                match_id, bet365_id, sport, channel_key, league, fixture, market_type,
                pick_str, side, line, odds, implied_prob, model_prob, estimated_edge,
                status, final_score, outcome, net_units, kickoff_at_utc, evaluated_at_utc, settled_at_utc,
                pending_reason, source, time_pending
            ) VALUES %s
            ON CONFLICT (channel_key, match_id) DO UPDATE SET
                status = EXCLUDED.status,
                final_score = EXCLUDED.final_score,
                outcome = EXCLUDED.outcome,
                net_units = EXCLUDED.net_units,
                settled_at_utc = EXCLUDED.settled_at_utc,
                pending_reason = EXCLUDED.pending_reason,
                source = EXCLUDED.source,
                time_pending = EXCLUDED.time_pending;
        """
        execute_values(cur, tips_sql, tips_to_insert, page_size=1000)

    conn.commit()
    conn.close()

    # Attempt to fetch scores from JarBet API for any remaining pending shadow matches
    fetch_scores_for_pending_shadow_matches()
    settle_shadow_tips()
    print_shadow_telemetry()

def print_shadow_telemetry():
    """Prints live performance telemetry from core.shadow_tips_eval for Oct 5th onwards."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT channel_key,
               COUNT(*) as total_tips,
               COUNT(*) FILTER (WHERE status = 'PENDING') as pending_count,
               COUNT(*) FILTER (WHERE outcome = 'WIN') as wins,
               COUNT(*) FILTER (WHERE outcome = 'LOSS') as losses,
               COUNT(*) FILTER (WHERE outcome = 'VOID') as voids,
               COUNT(*) FILTER (WHERE outcome = 'HALF_WIN') as half_wins,
               COUNT(*) FILTER (WHERE outcome = 'HALF_LOSS') as half_losses,
               COALESCE(SUM(net_units), 0.0) as net_units
        FROM core.shadow_tips_eval
        WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00'
        GROUP BY channel_key;
    """)
    rows = cur.fetchall()
    conn.close()

    print("\n" + "=" * 92)
    print(" SHADOW MODE TELEMETRY (RE-EVALUATED MODELS | OCT 5TH - PRESENT)")
    print("=" * 92)
    print(f"{'Channel':<22} | {'Total':<6} | {'W-L-V (HW/HL)':<18} | {'Net Units':<10} | {'Win Rate':<10} | {'ROI':<8} | {'Pending'}")
    print("-" * 92)

    tot_tips = 0
    tot_net = 0.0
    tot_decided = 0
    tot_wins = 0

    for r in sorted(rows, key=lambda x: x["channel_key"]):
        w, l, v, hw, hl = r["wins"], r["losses"], r["voids"], r["half_wins"], r["half_losses"]
        decided = w + l + hw + hl
        wr = ((w + 0.5 * hw) / decided * 100.0) if decided > 0 else 0.0
        # ROI computed against decided bets (invested units)
        roi = (float(r["net_units"]) / decided * 100.0) if decided > 0 else 0.0

        tot_tips += r["total_tips"]
        tot_net += float(r["net_units"])
        tot_decided += decided
        tot_wins += (w + 0.5 * hw)

        rec_str = f"{w}-{l}-{v} ({hw}/{hl})"
        print(f"{r['channel_key']:<22} | {r['total_tips']:<6} | {rec_str:<18} | {float(r['net_units']):+9.2f}U | {wr:8.1f}% | {roi:+6.1f}% | {r['pending_count']}")

    print("-" * 92)
    overall_wr = (tot_wins / tot_decided * 100.0) if tot_decided > 0 else 0.0
    overall_roi = (tot_net / tot_decided * 100.0) if tot_decided > 0 else 0.0
    print(f"{'CONSOLIDATED':<22} | {tot_tips:<6} | {'-':<18} | {tot_net:+9.2f}U | {overall_wr:8.1f}% | {overall_roi:+6.1f}% |")
    print("=" * 92 + "\n")

def run_shadow_cycle():
    """Executes a single shadow cycle: fetch matches -> evaluate -> settle -> report."""
    logger.info("Starting Shadow Evaluation Cycle...")
    matches = fetch_live_matches()
    logger.info(f"Fetched {len(matches)} active live fixtures from live API.")
    evaluate_shadow_opportunities(matches)
    settle_shadow_tips()
    print_shadow_telemetry()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mario AI Local Shadow Pipeline")
    parser.add_argument("--loop", "-loop", "-l", action="store_true", help="Run continuously in a loop")
    parser.add_argument("--interval", "-interval", "-i", type=int, default=60, help="Sleep interval in seconds between cycles (default: 60s)")
    parser.add_argument("--clean", "-clean", "-c", action="store_true", help="Clean shadow schema and re-sync from Oct 5th using re-evaluated models")
    parser.add_argument("--resync-oct5", action="store_true", help="Re-sync historical data from Oct 5th without cleaning")
    args = parser.parse_args()

    init_shadow_db()

    env_clean = os.getenv("SHADOW_CLEAN_SYNC", "").strip().lower() in ("true", "1", "yes")

    if args.clean or env_clean:
        clean_and_sync_oct5_shadow_data(clean=True)
    elif args.resync_oct5:
        clean_and_sync_oct5_shadow_data(clean=False)

    if args.loop:
        logger.info(f"Starting continuous shadow monitoring with Re-Evaluated Models (polling every {args.interval}s)... Press Ctrl+C to stop.")
        try:
            while True:
                run_shadow_cycle()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Shadow pipeline stopped by user.")
    else:
        if not (args.clean or env_clean or args.resync_oct5):
            run_shadow_cycle()
