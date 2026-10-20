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
from collections import defaultdict
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
    return os.getenv("DATABASE_URL") or "postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai"

DB_URL = get_db_url()
JARBET_BASE_URL = os.getenv("JARBET_BASE_URL", "https://data.jarvisbet.com.br").rstrip("/")
JARBET_API_KEY = os.getenv("JARBET_API_KEY", "")
SHADOW_START_DATE = os.getenv("SHADOW_START_DATE", "2026-10-05 00:00:00+00")

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
# Centralized Market Configuration & Constants
# ---------------------------------------------------------------------------

CHANNEL_MIN_EDGE = {
    "fifa_goals_ou": 0.03,        # Augmented Model: 3% edge on OVER-only
    "fifa_asian_handicap": 0.05,  # Strict Edge > 5% on Asian Handicap
    "fifa_money_line": 0.05,      # Strict Edge > 5% on FIFA Money Line
    "ebasket_money_line": 0.02,   # Unchanged: eBasket Money Line as is (2%)
    "ebasket_ou": 0.02,           # Unchanged: eBasket O/U as is (2%)
}

CHANNEL_TARGET_VIG = {
    "fifa_goals_ou": 1.06,
    "fifa_asian_handicap": 1.06,
    "fifa_money_line": 1.07,
    "ebasket_money_line": 1.05,
    "ebasket_ou": 1.05,
}

MIN_ODDS_THRESHOLD = float(os.getenv("SHADOW_MIN_ODDS", "1.60"))
CHANNEL_MIN_ODDS = {
    "fifa_goals_ou": MIN_ODDS_THRESHOLD,
    "fifa_asian_handicap": MIN_ODDS_THRESHOLD,
    "fifa_money_line": MIN_ODDS_THRESHOLD,
    "ebasket_money_line": MIN_ODDS_THRESHOLD,
    "ebasket_ou": MIN_ODDS_THRESHOLD,
}

SHADOW_ABANDONED_HOURS = float(os.getenv("SHADOW_ABANDONED_HOURS", "4.0"))

SHADOW_ENFORCE_CIRCUIT_BREAKER = os.getenv("SHADOW_ENFORCE_CIRCUIT_BREAKER", "false").lower() == "true"
SHADOW_CIRCUIT_BREAKER_MAX_DRAWDOWN = float(os.getenv("SHADOW_CIRCUIT_BREAKER_MAX_DRAWDOWN", "-20.0"))

def regularize_calibrated_prob(p: float, min_p: float = 0.05, max_p: float = 0.85) -> float:
    """Clamps isotonic calibrator step-function plateaus away from 0.0 and 1.0 to reflect sports variance."""
    return float(np.clip(p, min_p, max_p))

def get_complementary_odds(odds: float, target_vig: float = 1.06) -> float:
    """Calculates opposing market odds dynamically from the line's implied vig."""
    if odds <= 1.0:
        return round(1.0 / 0.04, 3)
    return round(1.0 / max(0.04, target_vig - 1.0 / odds), 3)

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
    """Loads and runs inference using the re-evaluated models with dynamically computed features."""

    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self.bundles: Dict[str, Any] = {}
        self.player_history: Dict[Tuple[str, str], List[Tuple[float, float, int, bool, Any]]] = defaultdict(list)
        self.h2h_history: Dict[Tuple[str, str, str], List[Tuple[float, float, int]]] = defaultdict(list)
        self.league_averages: Dict[str, Tuple[float, float]] = {}
        self.league_stats: Dict[str, Dict[str, float]] = {}
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
        """Refreshes chronological match history and player profiles from database (read-only)."""
        now = time.time()
        if now - self.last_cache_refresh < 300 and self.player_history:
            return

        try:
            conn = psycopg2.connect(DB_URL, connect_timeout=5)
            cur = conn.cursor()

            cur.execute("""
                SELECT m.sport, 
                       LOWER(TRIM(m.home_player)) as h_p, 
                       LOWER(TRIM(m.away_player)) as a_p, 
                       r.final_home_score as h_s, 
                       r.final_away_score as a_s,
                       m.match_start_time
                FROM core.results r 
                JOIN core.matches m ON r.match_id = m.match_id
                WHERE r.final_home_score IS NOT NULL 
                  AND r.final_away_score IS NOT NULL
                  AND m.home_player IS NOT NULL 
                  AND m.away_player IS NOT NULL
                ORDER BY m.match_start_time ASC;
            """)
            rows = cur.fetchall()
            conn.close()

            p_hist = defaultdict(list)
            h2h_hist = defaultdict(list)
            leg_h = defaultdict(list)
            leg_a = defaultdict(list)
            leg_results = defaultdict(lambda: {"wins": 0, "draws": 0, "losses": 0, "scores": []})

            for sport, hp, ap, hs, as_, dt in rows:
                if not hp or not ap or hs is None or as_ is None:
                    continue
                hs_f, as_f = float(hs), float(as_)
                h_res = 1 if hs_f > as_f else (0 if hs_f == as_f else -1)
                a_res = 1 if as_f > hs_f else (0 if as_f == hs_f else -1)

                p_hist[(sport, hp)].append((hs_f, as_f, h_res, True, dt))
                p_hist[(sport, ap)].append((as_f, hs_f, a_res, False, dt))
                h2h_hist[(sport, hp, ap)].append((hs_f, as_f, h_res))

                leg_h[sport].append(hs_f)
                leg_a[sport].append(as_f)
                leg_results[sport]["scores"].append(hs_f + as_f)
                if hs_f > as_f:
                    leg_results[sport]["wins"] += 1
                elif hs_f == as_f:
                    leg_results[sport]["draws"] += 1
                else:
                    leg_results[sport]["losses"] += 1

            for sport in leg_h:
                if leg_h[sport]:
                    self.league_averages[sport] = (float(np.mean(leg_h[sport])), float(np.mean(leg_a[sport])))
                    tot_g = len(leg_h[sport])
                    res = leg_results[sport]
                    self.league_stats[sport] = {
                        "home_win_rate": res["wins"] / tot_g if tot_g > 0 else 0.50,
                        "draw_rate": res["draws"] / tot_g if tot_g > 0 else 0.0,
                        "away_win_rate": res["losses"] / tot_g if tot_g > 0 else 0.50,
                        "pts_std": float(np.std(res["scores"])) if len(res["scores"]) > 1 else 0.0,
                        "scores": res["scores"],
                    }

            if not self.league_averages or not self.league_stats:
                logger.error("Mandatory database stats check failed: league_averages or league_stats could not be computed from database.")
                raise RuntimeError("Empirical database stats mandatory: cannot evaluate without dynamic league statistics from core.results.")

            self.player_history = p_hist
            self.h2h_history = h2h_hist
            self.last_cache_refresh = now
            logger.info(f"Dynamically indexed {len(p_hist)} player profiles, {len(h2h_hist)} H2H matchups, {len(self.league_averages)} league averages, and {len(self.league_stats)} league statistics.")
        except Exception as e:
            logger.error(f"Player stats refresh failed: {e}")
            raise

    @staticmethod
    def get_clean_player_name(player: str) -> str:
        if not player:
            return ""
        clean_p = str(player).strip().lower()
        m_handle = re.search(r"\(([^)]+)\)", clean_p)
        if m_handle:
            return m_handle.group(1).strip()
        return clean_p

    def get_player_profile(self, sport: str, player: str) -> Dict[str, Any]:
        p_clean = self.get_clean_player_name(player)
        hist = self.player_history.get((sport, p_clean), [])
        
        if sport not in self.league_averages or sport not in self.league_stats:
            raise RuntimeError(f"Missing empirical league statistics for sport '{sport}'. Dynamic stats are mandatory.")

        leg_avg = self.league_averages[sport]
        def_sc = float((leg_avg[0] + leg_avg[1]) / 2.0)
        def_cc = float((leg_avg[0] + leg_avg[1]) / 2.0)

        l_stat = self.league_stats[sport]
        def_hw = l_stat["home_win_rate"]
        def_dr = l_stat["draw_rate"]
        def_aw = l_stat["away_win_rate"]
        def_std = l_stat["pts_std"]

        if not hist or len(hist) < 3:
            return {
                'sc_5': def_sc, 'sc_10': def_sc,
                'cc_5': def_cc, 'cc_10': def_cc,
                'win_rate_5': def_hw, 'win_rate_10': def_hw,
                'draw_rate_5': def_dr, 'draw_rate_10': def_dr,
                'loss_rate_5': def_aw, 'loss_rate_10': def_aw,
                'win_rate_home': def_hw, 'win_rate_away': def_aw,
                'form_streak': 0.0, 'total_pts_std_10': def_std,
                'bayesian_mean': 1500.0, 'bayesian_std': 45.0,
                'reliable_5': False, 'reliable_10': False,
                'matches_count': len(hist), 'history': hist
            }

        last_5 = hist[-5:]
        last_10 = hist[-10:]

        sc_5 = float(np.mean([x[0] for x in last_5]))
        sc_10 = float(np.mean([x[0] for x in last_10]))
        cc_5 = float(np.mean([x[1] for x in last_5]))
        cc_10 = float(np.mean([x[1] for x in last_10]))

        w_5 = sum(1 for x in last_5 if x[2] == 1) / len(last_5)
        w_10 = sum(1 for x in last_10 if x[2] == 1) / len(last_10)
        d_5 = sum(1 for x in last_5 if x[2] == 0) / len(last_5)
        d_10 = sum(1 for x in last_10 if x[2] == 0) / len(last_10)
        l_5 = sum(1 for x in last_5 if x[2] == -1) / len(last_5)
        l_10 = sum(1 for x in last_10 if x[2] == -1) / len(last_10)

        home_matches = [x for x in last_10 if x[3]]
        w_home = (sum(1 for x in home_matches if x[2] == 1) / len(home_matches)) if home_matches else w_10
        away_matches = [x for x in last_10 if not x[3]]
        w_away = (sum(1 for x in away_matches if x[2] == 1) / len(away_matches)) if away_matches else w_10

        # Form streak: count consecutive wins (+) or losses (-)
        streak = 0
        for x in reversed(hist):
            if streak == 0:
                streak = x[2]
            elif (streak > 0 and x[2] == 1) or (streak < 0 and x[2] == -1):
                streak += x[2]
            else:
                break

        pts = [x[0] + x[1] for x in last_10]
        total_pts_std_10 = float(np.std(pts)) if len(pts) > 1 else def_std

        scale = 20.0 if sport == "fifa" else 5.0
        bayesian_mean = 1500.0 + (sc_10 - cc_10) * scale
        bayesian_std = max(15.0, 50.0 - min(len(hist), 30) * 1.0)

        return {
            'sc_5': sc_5, 'sc_10': sc_10,
            'cc_5': cc_5, 'cc_10': cc_10,
            'win_rate_5': w_5, 'win_rate_10': w_10,
            'draw_rate_5': d_5, 'draw_rate_10': d_10,
            'loss_rate_5': l_5, 'loss_rate_10': l_10,
            'win_rate_home': w_home, 'win_rate_away': w_away,
            'form_streak': float(streak), 'total_pts_std_10': total_pts_std_10,
            'bayesian_mean': bayesian_mean, 'bayesian_std': bayesian_std,
            'reliable_5': len(hist) >= 3, 'reliable_10': len(hist) >= 5,
            'matches_count': len(hist), 'history': hist
        }

    def get_h2h_stats(self, sport: str, p1: str, p2: str, default_exp_tot: float) -> Tuple[float, float, float, float]:
        p1_clean = self.get_clean_player_name(p1)
        p2_clean = self.get_clean_player_name(p2)

        m1 = self.h2h_history.get((sport, p1_clean, p2_clean), [])
        m2 = [(x[1], x[0], -x[2]) for x in self.h2h_history.get((sport, p2_clean, p1_clean), [])]
        all_m = m1 + m2

        if not all_m:
            l_stat = self.league_stats.get(sport, {})
            def_aw = l_stat["away_win_rate"]
            return 0.0, def_aw, default_exp_tot, 0.0

        cnt = float(len(all_m))
        win_rate_away = sum(1 for x in all_m if x[2] == -1) / cnt
        mean_combined = float(np.mean([x[0] + x[1] for x in all_m]))
        mean_diff = float(np.mean([x[0] - x[1] for x in all_m]))
        return cnt, win_rate_away, mean_combined, mean_diff

    def get_line_hit_rate(self, sport: str, hp: Dict[str, Any], ap: Dict[str, Any], line_val: float) -> Optional[float]:
        h_pts = [x[0] + x[1] for x in hp.get('history', [])[-10:]]
        a_pts = [x[0] + x[1] for x in ap.get('history', [])[-10:]]
        tot_games = len(h_pts) + len(a_pts)
        if tot_games == 0:
            scores = self.league_stats.get(sport, {}).get("scores", [])
            if scores:
                return float(sum(1 for s in scores if s > line_val) / len(scores))
            return None
        overs = sum(1 for p in h_pts if p > line_val) + sum(1 for p in a_pts if p > line_val)
        return float(overs / tot_games)

    def get_gamer_intraday_loss_streak(self, sport: str, player: str, ko_dt: Optional[datetime]) -> float:
        """Calculates consecutive losses by player within the same ongoing session (<= 6 hours before kickoff)."""
        if not ko_dt:
            return 0.0
        p_clean = self.get_clean_player_name(player)
        hist = self.player_history.get((sport, p_clean), [])
        if not hist:
            return 0.0
        streak = 0
        for x in reversed(hist):
            m_dt = x[4]
            if m_dt is None:
                continue
            if ko_dt.tzinfo is not None and m_dt.tzinfo is None:
                m_dt = m_dt.replace(tzinfo=timezone.utc)
            elif ko_dt.tzinfo is None and m_dt.tzinfo is not None:
                m_dt = m_dt.replace(tzinfo=None)
            if m_dt >= ko_dt:
                continue
            gap_seconds = (ko_dt - m_dt).total_seconds()
            if gap_seconds > 21600.0:  # Gap > 6 hours breaks session
                break
            if x[2] == -1:  # Loss
                streak += 1
            else:  # Win or draw breaks loss streak
                break
        return float(streak)

    @staticmethod
    def get_tournament_duration(fixture: str, league: str = "", sport: str = "fifa", duration_minutes: Optional[float] = None) -> float:
        """Reconstructs scheduled match duration dynamically from core.matches or fixture/league text."""
        if duration_minutes is not None and float(duration_minutes) > 0:
            return float(duration_minutes)
        combined = f"{fixture} {league}".lower()
        m = re.search(r'\b(6|8|10|12|16|20)\s*(?:mins?|minutes?|m)\b', combined)
        if m:
            return float(m.group(1))
        if "4x5" in combined:
            return 20.0
        if "4x4" in combined:
            return 16.0
        return 25.0 if (sport == "ebasket" or "ebasket" in combined) else 15.0

    def get_player_stats(self, sport: str, player: str) -> Tuple[float, float, bool]:
        prof = self.get_player_profile(sport, player)
        return prof['sc_10'], prof['cc_10'], prof['reliable_5']

    def build_feature_vector(
        self,
        ch_key: str,
        sport: str,
        h_player: str,
        a_player: str,
        line_val: float,
        odds_info: Dict[str, Any],
        ko_dt: Optional[datetime] = None,
        fixture: str = "",
        league: str = "",
        duration_minutes: Optional[float] = None
    ) -> Optional[pd.DataFrame]:
        if not ko_dt:
            return None

        hp = self.get_player_profile(sport, h_player)
        ap = self.get_player_profile(sport, a_player)

        h_sc, h_cc = hp['sc_10'], hp['cc_10']
        a_sc, a_cc = ap['sc_10'], ap['cc_10']
        h_sc_5, h_cc_5 = hp['sc_5'], hp['cc_5']
        a_sc_5, a_cc_5 = ap['sc_5'], ap['cc_5']

        diff_exp = (h_sc - h_cc) - (a_sc - a_cc)
        exp_tot = (h_sc + a_cc) / 2.0 + (a_sc + h_cc) / 2.0
        h2h_cnt, h2h_win_a, h2h_mean_comb, h2h_mean_diff = self.get_h2h_stats(sport, h_player, a_player, exp_tot)
        hour_val = float(ko_dt.hour)

        if ch_key == "fifa_goals_ou":
            target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.06)
            o_odds = float(odds_info.get("over_odds") or 0.0)
            u_odds = float(odds_info.get("under_odds") or 0.0)
            if o_odds > 1.0:
                imp_p_over = 1.0 / o_odds
            elif u_odds > 1.0:
                imp_p_over = 1.0 / get_complementary_odds(u_odds, target_vig)
            else:
                return None
            hit_rate = self.get_line_hit_rate(sport, hp, ap, line_val)
            if hit_rate is None:
                return None
            dur_mins = float(duration_minutes or odds_info.get('duration_minutes') or self.get_tournament_duration(fixture, league, sport, duration_minutes))
            loss_streak = self.get_gamer_intraday_loss_streak(sport, h_player, ko_dt)
            feat_vec = {
                'is_reliable_5': 1.0 if (hp['reliable_5'] and ap['reliable_5']) else 0.0,
                'is_reliable_10': 1.0 if (hp['reliable_10'] and ap['reliable_10']) else 0.0,
                'home_scored_roll_mean_5': h_sc_5, 'home_scored_roll_mean_10': h_sc,
                'home_conceded_roll_mean_5': h_cc_5, 'home_conceded_roll_mean_10': h_cc,
                'away_scored_roll_mean_5': a_sc_5, 'away_scored_roll_mean_10': a_sc,
                'away_conceded_roll_mean_5': a_cc_5, 'away_conceded_roll_mean_10': a_cc,
                'expected_total_goals': exp_tot,
                'h2h_matches_count': h2h_cnt, 'h2h_mean_combined_goals': h2h_mean_comb if h2h_cnt > 0 else exp_tot,
                'ou_line_value': line_val, 'ou_line_diff': exp_tot - line_val,
                'ou_line_hit_rate_roll': hit_rate, 'ht_ft_goal_ratio_league': 0.45,
                'odds_implied_prob': imp_p_over,
                'implied_vs_hist_divergence': imp_p_over - hit_rate,
                'tournament_duration_minutes': dur_mins,
                'is_whole_line': 1.0 if abs(line_val - round(line_val)) < 1e-4 else 0.0,
                'gamer_intraday_loss_streak': loss_streak,
            }

        elif ch_key == "fifa_asian_handicap":
            target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.06)
            h_odds = float(odds_info.get("home_odds") or 0.0)
            a_odds = float(odds_info.get("away_odds") or 0.0)
            if h_odds > 1.0:
                imp_p_home = 1.0 / h_odds
            elif a_odds > 1.0:
                imp_p_home = 1.0 / get_complementary_odds(a_odds, target_vig)
            else:
                return None

            if a_odds > 1.0:
                imp_p_away = 1.0 / a_odds
            elif h_odds > 1.0:
                imp_p_away = 1.0 / get_complementary_odds(h_odds, target_vig)
            else:
                return None

            ml_h_odds = float(odds_info.get("ml_home_odds", 0.0))
            ml_a_odds = float(odds_info.get("ml_away_odds", 0.0))
            if ml_h_odds > 1.0 and ml_a_odds > 1.0:
                ml_imp_h = 1.0 / ml_h_odds
                ml_imp_a = 1.0 / ml_a_odds
            else:
                ml_imp_h = hp['win_rate_10']
                ml_imp_a = ap['win_rate_10']
            ml_diff = ml_imp_h - ml_imp_a
            cross_div = ml_imp_h - imp_p_home

            feat_vec = {
                'is_reliable_5': 1.0 if (hp['reliable_5'] and ap['reliable_5']) else 0.0,
                'is_reliable_10': 1.0 if (hp['reliable_10'] and ap['reliable_10']) else 0.0,
                'home_scored_roll_mean_5': h_sc_5, 'home_scored_roll_mean_10': h_sc,
                'home_conceded_roll_mean_5': h_cc_5, 'home_conceded_roll_mean_10': h_cc,
                'away_scored_roll_mean_5': a_sc_5, 'away_scored_roll_mean_10': a_sc,
                'away_conceded_roll_mean_5': a_cc_5, 'away_conceded_roll_mean_10': a_cc,
                'home_net_gd_10': h_sc - h_cc, 'away_net_gd_10': a_sc - a_cc,
                'net_gd_diff_10': diff_exp,
                'net_gd_margin_vs_line': diff_exp + line_val,
                'handicap_line_value': line_val,
                'ml_implied_prob_home': ml_imp_h, 'ml_implied_prob_away': ml_imp_a, 'ml_implied_diff': ml_diff,
                'ah_odds_implied_prob': imp_p_home,
                'cross_market_divergence': cross_div,
                'h2h_matches_count': h2h_cnt, 'h2h_mean_combined_goals': h2h_mean_comb if h2h_cnt > 0 else exp_tot,
                'ht_ft_goal_ratio_league': 0.45
            }

        elif ch_key == "fifa_money_line":
            target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.07)
            h_odds = float(odds_info.get("home_odds") or 0.0)
            a_odds = float(odds_info.get("away_odds") or 0.0)
            if h_odds > 1.0:
                imp_p_h = 1.0 / h_odds
            elif a_odds > 1.0:
                imp_p_h = 1.0 / get_complementary_odds(a_odds, target_vig)
            else:
                return None

            if a_odds > 1.0:
                imp_p_a = 1.0 / a_odds
            elif h_odds > 1.0:
                imp_p_a = 1.0 / get_complementary_odds(h_odds, target_vig)
            else:
                return None

            feat_vec = {
                'is_reliable_5': 1.0 if (hp['reliable_5'] and ap['reliable_5']) else 0.0,
                'is_reliable_10': 1.0 if (hp['reliable_10'] and ap['reliable_10']) else 0.0,
                'home_win_rate_roll_5': hp['win_rate_5'], 'home_win_rate_roll_10': hp['win_rate_10'],
                'home_draw_rate_roll_5': hp['draw_rate_5'], 'home_draw_rate_roll_10': hp['draw_rate_10'],
                'home_loss_rate_roll_5': hp['loss_rate_5'], 'home_loss_rate_roll_10': hp['loss_rate_10'],
                'away_win_rate_roll_5': ap['win_rate_5'], 'away_win_rate_roll_10': ap['win_rate_10'],
                'away_draw_rate_roll_5': ap['draw_rate_5'], 'away_draw_rate_roll_10': ap['draw_rate_10'],
                'away_loss_rate_roll_5': ap['loss_rate_5'], 'away_loss_rate_roll_10': ap['loss_rate_10'],
                'home_net_gd_10': h_sc - h_cc, 'away_net_gd_10': a_sc - a_cc,
                'net_gd_diff_10': diff_exp,
                'home_win_rate_home_games': hp['win_rate_home'], 'away_win_rate_away_games': ap['win_rate_away'],
                'home_form_streak': hp['form_streak'], 'away_form_streak': ap['form_streak'],
                'draw_prob_roll_10': (hp['draw_rate_10'] + ap['draw_rate_10']) / 2.0,
                'h2h_matches_count': h2h_cnt, 'h2h_win_rate_a': h2h_win_a,
                'odds_implied_prob_home': imp_p_h, 'odds_implied_prob_away': imp_p_a,
                'implied_vs_hist_divergence': imp_p_h - hp['win_rate_10'],
                'home_bayesian_rating_mean': hp['bayesian_mean'], 'home_bayesian_rating_std': hp['bayesian_std'],
                'away_bayesian_rating_mean': ap['bayesian_mean'], 'away_bayesian_rating_std': ap['bayesian_std'],
                'bayesian_rating_diff': hp['bayesian_mean'] - ap['bayesian_mean']
            }

        elif ch_key == "ebasket_money_line":
            target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.05)
            h_odds = float(odds_info.get("home_odds") or 0.0)
            a_odds = float(odds_info.get("away_odds") or 0.0)
            if h_odds > 1.0:
                imp_p_h = 1.0 / h_odds
            elif a_odds > 1.0:
                imp_p_h = 1.0 / get_complementary_odds(a_odds, target_vig)
            else:
                return None

            if a_odds > 1.0:
                imp_p_a = 1.0 / a_odds
            elif h_odds > 1.0:
                imp_p_a = 1.0 / get_complementary_odds(h_odds, target_vig)
            else:
                return None

            vig = (imp_p_h + imp_p_a) - 1.0 if (imp_p_h + imp_p_a) > 1.0 else abs(imp_p_h + imp_p_a - 1.0)
            ratio = imp_p_h / imp_p_a if imp_p_a > 0 else 1.0
            feat_vec = {
                'is_reliable_5': 1.0 if (hp['reliable_5'] and ap['reliable_5']) else 0.0,
                'is_reliable_10': 1.0 if (hp['reliable_10'] and ap['reliable_10']) else 0.0,
                'home_win_rate_roll_5': hp['win_rate_5'], 'home_win_rate_roll_10': hp['win_rate_10'],
                'away_win_rate_roll_5': ap['win_rate_5'], 'away_win_rate_roll_10': ap['win_rate_10'],
                'win_rate_diff_10': hp['win_rate_10'] - ap['win_rate_10'],
                'home_points_scored_roll_10': h_sc, 'home_points_conceded_roll_10': h_cc,
                'away_points_scored_roll_10': a_sc, 'away_points_conceded_roll_10': a_cc,
                'home_net_point_diff_10': h_sc - h_cc, 'away_net_point_diff_10': a_sc - a_cc,
                'net_point_diff_delta_10': diff_exp,
                'home_form_streak': hp['form_streak'], 'away_form_streak': ap['form_streak'],
                'h2h_matches_count': h2h_cnt, 'h2h_win_rate_a': h2h_win_a, 'h2h_mean_point_diff': h2h_mean_diff,
                'odds_implied_prob_home': imp_p_h, 'odds_implied_prob_away': imp_p_a,
                'market_vig': vig, 'implied_prob_ratio': ratio, 'implied_vs_hist_divergence': imp_p_h - hp['win_rate_10'],
                'home_bayesian_rating_mean': hp['bayesian_mean'], 'home_bayesian_rating_std': hp['bayesian_std'],
                'away_bayesian_rating_mean': ap['bayesian_mean'], 'away_bayesian_rating_std': ap['bayesian_std'],
                'bayesian_rating_diff': hp['bayesian_mean'] - ap['bayesian_mean'], 'hour_of_day_utc': hour_val
            }

        elif ch_key == "ebasket_ou":
            target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.05)
            o_odds = float(odds_info.get("over_odds") or 0.0)
            u_odds = float(odds_info.get("under_odds") or 0.0)
            if o_odds > 1.0:
                imp_p_o = 1.0 / o_odds
            elif u_odds > 1.0:
                imp_p_o = 1.0 / get_complementary_odds(u_odds, target_vig)
            else:
                return None

            if u_odds > 1.0:
                imp_p_u = 1.0 / u_odds
            elif o_odds > 1.0:
                imp_p_u = 1.0 / get_complementary_odds(o_odds, target_vig)
            else:
                return None

            exp_pts_5 = (h_sc_5 + a_cc_5) / 2.0 + (a_sc_5 + h_cc_5) / 2.0
            exp_conc_10 = h_cc + a_cc
            blended = (exp_tot + exp_conc_10) / 2.0
            vig = (imp_p_o + imp_p_u) - 1.0 if (imp_p_o + imp_p_u) > 1.0 else abs(imp_p_o + imp_p_u - 1.0)
            ratio_o = imp_p_o / imp_p_u if imp_p_u > 0 else 1.0
            feat_vec = {
                'is_reliable_5': 1.0 if (hp['reliable_5'] and ap['reliable_5']) else 0.0,
                'is_reliable_10': 1.0 if (hp['reliable_10'] and ap['reliable_10']) else 0.0,
                'home_scored_roll_mean_5': h_sc_5, 'home_scored_roll_mean_10': h_sc,
                'home_conceded_roll_mean_5': h_cc_5, 'home_conceded_roll_mean_10': h_cc,
                'away_scored_roll_mean_5': a_sc_5, 'away_scored_roll_mean_10': a_sc,
                'away_conceded_roll_mean_5': a_cc_5, 'away_conceded_roll_mean_10': a_cc,
                'expected_total_points_5': exp_pts_5, 'expected_total_points_10': exp_tot,
                'expected_total_conceded_10': exp_conc_10, 'blended_projected_points_10': blended,
                'ou_line_value': line_val, 'ou_line_diff_10': exp_tot - line_val,
                'home_total_pts_std_10': hp['total_pts_std_10'], 'away_total_pts_std_10': ap['total_pts_std_10'],
                'odds_implied_prob_over': imp_p_o, 'odds_implied_prob_under': imp_p_u,
                'market_vig': vig, 'implied_prob_ratio_over': ratio_o,
                'home_bayesian_rating_mean': hp['bayesian_mean'], 'home_bayesian_rating_std': hp['bayesian_std'],
                'away_bayesian_rating_mean': ap['bayesian_mean'], 'away_bayesian_rating_std': ap['bayesian_std'],
                'bayesian_total_points': exp_tot, 'bayesian_line_diff': exp_tot - line_val,
                'h2h_matches_count': h2h_cnt, 'h2h_mean_total_score': h2h_mean_comb if h2h_cnt > 0 else exp_tot,
                'hour_of_day_utc': hour_val
            }

        feat_names = self.bundles[ch_key]["feature_names"]
        return pd.DataFrame([feat_vec])[feat_names]

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

def evaluate_shadow_opportunities(matches: List[Dict[str, Any]], min_odds: Optional[float] = None):
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
        h_team = str(home_info.get("teamName") or "").strip()
        a_team = str(away_info.get("teamName") or "").strip()
        h_player = str(home_info.get("name") or "").strip()
        a_player = str(away_info.get("name") or "").strip()
        if not h_player or not a_player or not h_team or not a_team:
            continue
        fixture = f"{h_team} ({h_player}) vs {a_team} ({a_player})"

        ko_str = match.get("startedAt")
        ko_dt = None
        if ko_str:
            try:
                ko_dt = datetime.fromisoformat(ko_str.replace("Z", "+00:00"))
            except Exception:
                pass
        if not ko_dt:
            continue

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
            min_odds_val = min_odds if min_odds is not None else CHANNEL_MIN_ODDS.get(ch_key, MIN_ODDS_THRESHOLD)
            target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.06)

            pick = None

            # 1. FIFA Goals O/U (Strict Edge >= 3%, OVER-Only)
            if ch_key == "fifa_goals_ou":
                ou = odds_dict.get("over_under", {}) if isinstance(odds_dict.get("over_under"), dict) else {}
                raw_line = ou.get("line")
                if raw_line is None or float(raw_line) <= 0.0:
                    continue
                line_val = float(raw_line)
                over_odds = float(ou.get("over", 0.0))
                under_odds = float(ou.get("under", 0.0))
                if over_odds <= 1.05 and under_odds <= 1.05:
                    continue

                if over_odds > 1.05 and under_odds <= 1.05:
                    under_odds = get_complementary_odds(over_odds, target_vig)
                elif under_odds > 1.05 and over_odds <= 1.05:
                    over_odds = get_complementary_odds(under_odds, target_vig)

                dur_mins = float(match.get("duration_minutes") or odds_dict.get('duration_minutes') or mgr.get_tournament_duration(fixture, league, sport, match.get("duration_minutes")))
                odds_info = {"over_odds": over_odds, "under_odds": under_odds, "duration_minutes": dur_mins}
                X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_dt, fixture=fixture, league=league, duration_minutes=dur_mins)
                if X is None:
                    continue
                raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
                cal_p = float(calibrator.predict([raw_p])[0])
                imp_p_over = 1.0 / over_odds

                edge_o = cal_p - imp_p_over

                # Enforce Specification Rule: OVER-Only
                if edge_o >= min_edge and over_odds >= min_odds_val:
                    pick = ("over", line_val, over_odds, cal_p, edge_o, f"Mais de {line_val} Gols")

            # 2. FIFA Asian Handicap (Strict Edge > 5%)
            elif ch_key == "fifa_asian_handicap":
                ah = odds_dict.get("asian_handicap", {}) if isinstance(odds_dict.get("asian_handicap"), dict) else {}
                raw_line = ah.get("line")
                if raw_line is None:
                    continue
                line_val = float(raw_line)
                h_odds = float(ah.get("home", 0.0))
                a_odds = float(ah.get("away", 0.0))
                if h_odds <= 1.05 and a_odds <= 1.05:
                    continue

                if h_odds > 1.05 and a_odds <= 1.05:
                    a_odds = get_complementary_odds(h_odds, target_vig)
                elif a_odds > 1.05 and h_odds <= 1.05:
                    h_odds = get_complementary_odds(a_odds, target_vig)

                ml = odds_dict.get("money_line", odds_dict.get("draw_no_bet", {})) if isinstance(odds_dict.get("money_line", odds_dict.get("draw_no_bet", {})), dict) else {}
                odds_info = {
                    "home_odds": h_odds, "away_odds": a_odds,
                    "ml_home_odds": float(ml.get("home", 0.0)), "ml_away_odds": float(ml.get("away", 0.0))
                }
                X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_dt, fixture=fixture, league=league)
                if X is None:
                    continue
                raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
                cal_p = float(calibrator.predict([raw_p])[0])

                imp_p_home = 1.0 / h_odds
                imp_p_away = 1.0 / a_odds
                edge_h = cal_p - imp_p_home
                edge_a = (1.0 - cal_p) - imp_p_away

                if edge_h >= min_edge and h_odds >= min_odds_val and edge_h >= edge_a:
                    pick = ("home", line_val, h_odds, cal_p, edge_h, f"{h_team} (Handicap {line_val:+.1f})")
                elif edge_a >= min_edge and a_odds >= min_odds_val and edge_a > edge_h:
                    pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Handicap {-line_val:+.1f})")

            # 3. FIFA Money Line (Draw No Bet, Strict Edge > 5%)
            elif ch_key == "fifa_money_line":
                ml = odds_dict.get("money_line", odds_dict.get("draw_no_bet", {})) if isinstance(odds_dict.get("money_line", odds_dict.get("draw_no_bet", {})), dict) else {}
                h_odds = float(ml.get("home", 0.0))
                a_odds = float(ml.get("away", 0.0))
                if h_odds <= 1.05 and a_odds <= 1.05:
                    continue

                if h_odds > 1.05 and a_odds <= 1.05:
                    a_odds = get_complementary_odds(h_odds, target_vig)
                elif a_odds > 1.05 and h_odds <= 1.05:
                    h_odds = get_complementary_odds(a_odds, target_vig)

                odds_info = {"home_odds": h_odds, "away_odds": a_odds}
                X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, 0.0, odds_info, ko_dt, fixture=fixture, league=league)
                if X is None:
                    continue
                if hasattr(model, "model") and hasattr(model.model, "predict_proba"):
                    raw_p = model.model.predict_proba(X)[0]
                else:
                    raw_p = model.predict_proba(X)[0]

                cal_h, cal_a = calibrator
                p_h = float(cal_h.predict([raw_p[0]])[0])
                p_a = float(cal_a.predict([raw_p[2] if len(raw_p) > 2 else raw_p[1]])[0])

                imp_p_h = 1.0 / h_odds
                imp_p_a = 1.0 / a_odds
                edge_h = p_h - imp_p_h
                edge_a = p_a - imp_p_a

                if edge_h >= min_edge and h_odds >= min_odds_val and edge_h >= edge_a:
                    pick = ("home", 0.0, h_odds, p_h, edge_h, f"{h_team} (Empate Anula)")
                elif edge_a >= min_edge and a_odds >= min_odds_val and edge_a > edge_h:
                    pick = ("away", 0.0, a_odds, p_a, edge_a, f"{a_team} (Empate Anula)")

            # 4. eBasket Money Line (Unchanged Edge >= 2%)
            elif ch_key == "ebasket_money_line":
                ml = odds_dict.get("money_line", {}) if isinstance(odds_dict.get("money_line"), dict) else {}
                h_odds = float(ml.get("home", 0.0))
                a_odds = float(ml.get("away", 0.0))
                if h_odds <= 1.05 and a_odds <= 1.05:
                    continue

                if h_odds > 1.05 and a_odds <= 1.05:
                    a_odds = get_complementary_odds(h_odds, target_vig)
                elif a_odds > 1.05 and h_odds <= 1.05:
                    h_odds = get_complementary_odds(a_odds, target_vig)

                odds_info = {"home_odds": h_odds, "away_odds": a_odds}
                X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, 0.0, odds_info, ko_dt, fixture=fixture, league=league)
                if X is None:
                    continue
                raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
                cal_p = float(calibrator.predict([raw_p])[0])

                imp_p_h = 1.0 / h_odds
                imp_p_a = 1.0 / a_odds
                edge_h = cal_p - imp_p_h
                edge_a = (1.0 - cal_p) - imp_p_a

                if edge_h >= min_edge and h_odds >= min_odds_val and edge_h >= edge_a:
                    pick = ("home", 0.0, h_odds, cal_p, edge_h, f"{h_team} (Vencedor)")
                elif edge_a >= min_edge and a_odds >= min_odds_val and edge_a > edge_h:
                    pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Vencedor)")

            # 5. eBasket O/U (Unchanged Edge >= 2%)
            elif ch_key == "ebasket_ou":
                ou = odds_dict.get("over_under", {}) if isinstance(odds_dict.get("over_under"), dict) else {}
                raw_line = ou.get("line")
                if raw_line is None or float(raw_line) <= 0.0:
                    continue
                line_val = float(raw_line)
                over_odds = float(ou.get("over", 0.0))
                under_odds = float(ou.get("under", 0.0))
                if over_odds <= 1.05 and under_odds <= 1.05:
                    continue

                if over_odds > 1.05 and under_odds <= 1.05:
                    under_odds = get_complementary_odds(over_odds, target_vig)
                elif under_odds > 1.05 and over_odds <= 1.05:
                    over_odds = get_complementary_odds(under_odds, target_vig)

                odds_info = {"over_odds": over_odds, "under_odds": under_odds}
                X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_dt, fixture=fixture, league=league)
                if X is None:
                    continue
                raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
                cal_p = regularize_calibrated_prob(float(calibrator.predict([raw_p])[0]))

                imp_p_o = 1.0 / over_odds
                imp_p_u = 1.0 / under_odds
                edge_o = cal_p - imp_p_o
                edge_u = (1.0 - cal_p) - imp_p_u

                if edge_o >= min_edge and over_odds >= min_odds_val and edge_o >= edge_u:
                    pick = ("over", line_val, over_odds, cal_p, edge_o, f"Mais de {line_val} Pontos")
                elif edge_u >= min_edge and under_odds >= min_odds_val and edge_u > edge_o:
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

    # Find pending matches where match duration has elapsed post-kickoff
    cur.execute("""
        SELECT DISTINCT s.match_id, s.bet365_id, s.sport, s.fixture, s.kickoff_at_utc
        FROM core.shadow_tips_eval s
        LEFT JOIN core.matches m ON s.match_id = m.match_id
        WHERE s.status = 'PENDING'
          AND NOW() >= (s.kickoff_at_utc + (INTERVAL '1 minute' * CASE WHEN s.sport = 'ebasket' THEN 25 ELSE 15 END))
        ORDER BY s.kickoff_at_utc DESC
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
                    is_in_play_or_break = m_status in [
                        "LIVE", "IN_PLAY", "HT", "HALF_TIME", "BREAK", "PAUSED",
                        "1H", "2H", "1Q", "2Q", "3Q", "4Q", "OT"
                    ]
                    h_obj = m.get("home", {}) if isinstance(m.get("home"), dict) else {}
                    a_obj = m.get("away", {}) if isinstance(m.get("away"), dict) else {}
                    hg = h_obj.get("goals") if h_obj.get("goals") is not None else h_obj.get("score")
                    ag = a_obj.get("goals") if a_obj.get("goals") is not None else a_obj.get("score")

                    if hg is not None and ag is not None and is_fin and not is_in_play_or_break:
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
                    m_status = str(m.get("status") or m.get("state") or "").upper()
                    is_fin = m.get("isFinished") is True or m_status in ["ENDED", "FINISHED", "FT", "CLOSED", ""]
                    is_in_play_or_break = m_status in [
                        "LIVE", "IN_PLAY", "HT", "HALF_TIME", "BREAK", "PAUSED",
                        "1H", "2H", "1Q", "2Q", "3Q", "4Q", "OT"
                    ]

                    if (m_id in pending_ids or b_id in pending_ids) and is_fin and not is_in_play_or_break:
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

def settle_shadow_tips():
    """Settles pending shadow tips against core.shadow_results (and fallback core.results)."""
    fetch_scores_for_pending_shadow_matches()

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT s.id, s.match_id, s.bet365_id, s.sport, s.channel_key, s.side, s.line, s.odds,
               sr.final_home_score,
               sr.final_away_score
        FROM core.shadow_tips_eval s
        LEFT JOIN core.shadow_results sr ON (s.match_id = sr.match_id OR s.bet365_id = sr.bet365_id OR s.match_id = sr.bet365_id)
        WHERE s.status = 'PENDING'
          AND sr.final_home_score IS NOT NULL;
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

        outcome, net_units = calculate_single_settlement(ch, side, line, odds, int(fh), int(fa))

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
    # Auto-void stale pending fixtures (> SHADOW_ABANDONED_HOURS post-kickoff)
    # -----------------------------------------------------------------------
    update_cur.execute("""
        UPDATE core.shadow_tips_eval
        SET status = 'SETTLED',
            final_score = 'ABANDONED',
            outcome = 'VOID',
            net_units = 0.000,
            pending_reason = 'ABANDONED_FIXTURE (Exceeded ' || %s::text || 'h whistle window)',
            source = COALESCE(source, 'shadow_api_fetcher'),
            time_pending = ROUND(EXTRACT(EPOCH FROM (NOW() - kickoff_at_utc))/3600.0, 1)::text || 'h (Exceeded limit)',
            settled_at_utc = COALESCE(kickoff_at_utc + (INTERVAL '1 hour' * %s), NOW())
        WHERE status = 'PENDING'
          AND kickoff_at_utc < NOW() - (INTERVAL '1 hour' * %s);
    """, (SHADOW_ABANDONED_HOURS, SHADOW_ABANDONED_HOURS, SHADOW_ABANDONED_HOURS))
    abandoned_now = update_cur.rowcount
    if abandoned_now > 0:
        logger.info(f"Abandonment Rule applied: Auto-voided {abandoned_now} stale fixtures as ABANDONED_FIXTURE (exceeded {SHADOW_ABANDONED_HOURS}h).")

    # Update active fresh pending tips with real-time pending tracking fields
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

def load_jsonl_candidates(start_date: str = "2026-09-10", end_date: str = "2026-09-30") -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Loads historical match opportunities and verified scores directly from formatted JSONL feeds
    for dates prior to live database tables (e.g. Sept 10 to Sept 30).
    """
    jsonl_opps = []
    jsonl_results = {}

    file_configs = [
        ("fifa", os.path.join(SCRIPT_DIR, "data", "formatted_data", "fifa_matches_formatted.jsonl"), ["fifa_goals_ou", "fifa_asian_handicap", "fifa_money_line"]),
        ("ebasket", os.path.join(SCRIPT_DIR, "data", "formatted_data", "ebasket_matches_formatted.jsonl"), ["ebasket_money_line", "ebasket_ou"])
    ]

    for sport, path, channels in file_configs:
        if not os.path.exists(path):
            alt_path = os.path.join(r"d:\Mario AI Code", "data", "formatted_data", os.path.basename(path))
            if os.path.exists(alt_path):
                path = alt_path
            else:
                continue

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                st = m.get("startedAt", "")
                if not (start_date <= st < end_date):
                    continue

                raw_mid = str(m.get("_id") or "")
                b365_id = str(m.get("idMatchBet365") or raw_mid)
                h_obj = m.get("home", {})
                a_obj = m.get("away", {})
                hp = h_obj.get("name", "")
                ap = a_obj.get("name", "")
                ht = h_obj.get("teamName", "")
                at = a_obj.get("teamName", "")
                fixture = f"{ht} ({hp}) vs {at} ({ap})"
                ko_time = datetime.fromisoformat(st.replace("Z", "+00:00"))
                eval_time = ko_time - timedelta(minutes=15)
                odds = m.get("odds", {})

                hg = h_obj.get("goals")
                ag = a_obj.get("goals")
                if hg is not None and ag is not None:
                    res_obj = {
                        "match_id": raw_mid, "bet365_id": b365_id,
                        "final_home_score": int(hg), "final_away_score": int(ag),
                        "sport": sport, "settled_at_utc": ko_time + timedelta(minutes=20)
                    }
                    jsonl_results[raw_mid] = res_obj
                    jsonl_results[b365_id] = res_obj

                for ch_key in channels:
                    if ch_key == "fifa_goals_ou":
                        ou = odds.get("over_under", {})
                        line_val = float(ou.get("line") or 0.0)
                        o_odds = float(ou.get("over") or 0.0)
                        u_odds = float(ou.get("under") or 0.0)
                        if line_val > 0 and (o_odds > 1.05 or u_odds > 1.05):
                            odds_val = o_odds if o_odds > 1.05 else get_complementary_odds(u_odds, 1.06)
                            jsonl_opps.append({
                                "match_id": raw_mid, "bet365_id": b365_id, "channel_key": ch_key,
                                "sport": sport, "fixture": fixture, "side": "over",
                                "line": line_val, "odds": odds_val, "kickoff_at_utc": ko_time,
                                "eval_time": eval_time
                            })
                    elif ch_key == "fifa_asian_handicap":
                        ah = odds.get("asian_handicap", {})
                        line_val = float(ah.get("line") or 0.0)
                        h_odds = float(ah.get("home") or 0.0)
                        a_odds = float(ah.get("away") or 0.0)
                        if h_odds > 1.05 or a_odds > 1.05:
                            odds_val = h_odds if h_odds > 1.05 else get_complementary_odds(a_odds, 1.06)
                            jsonl_opps.append({
                                "match_id": raw_mid, "bet365_id": b365_id, "channel_key": ch_key,
                                "sport": sport, "fixture": fixture, "side": "home",
                                "line": line_val, "odds": odds_val, "kickoff_at_utc": ko_time,
                                "eval_time": eval_time
                            })
                    elif ch_key == "fifa_money_line":
                        ml = odds.get("money_line", {})
                        h_odds = float(ml.get("home") or 0.0)
                        a_odds = float(ml.get("away") or 0.0)
                        if h_odds > 1.05 or a_odds > 1.05:
                            odds_val = h_odds if h_odds > 1.05 else get_complementary_odds(a_odds, 1.07)
                            jsonl_opps.append({
                                "match_id": raw_mid, "bet365_id": b365_id, "channel_key": ch_key,
                                "sport": sport, "fixture": fixture, "side": "home",
                                "line": 0.0, "odds": odds_val, "kickoff_at_utc": ko_time,
                                "eval_time": eval_time
                            })
                    elif ch_key == "ebasket_money_line":
                        ml = odds.get("money_line", {})
                        h_odds = float(ml.get("home") or 0.0)
                        a_odds = float(ml.get("away") or 0.0)
                        if h_odds > 1.05 or a_odds > 1.05:
                            odds_val = h_odds if h_odds > 1.05 else get_complementary_odds(a_odds, 1.05)
                            jsonl_opps.append({
                                "match_id": raw_mid, "bet365_id": b365_id, "channel_key": ch_key,
                                "sport": sport, "fixture": fixture, "side": "home",
                                "line": 0.0, "odds": odds_val, "kickoff_at_utc": ko_time,
                                "eval_time": eval_time
                            })
                    elif ch_key == "ebasket_ou":
                        ou = odds.get("over_under", {})
                        line_val = float(ou.get("line") or 0.0)
                        o_odds = float(ou.get("over") or 0.0)
                        u_odds = float(ou.get("under") or 0.0)
                        if line_val > 0 and (o_odds > 1.05 or u_odds > 1.05):
                            odds_val = o_odds if o_odds > 1.05 else get_complementary_odds(u_odds, 1.05)
                            jsonl_opps.append({
                                "match_id": raw_mid, "bet365_id": b365_id, "channel_key": ch_key,
                                "sport": sport, "fixture": fixture, "side": "over",
                                "line": line_val, "odds": odds_val, "kickoff_at_utc": ko_time,
                                "eval_time": eval_time
                            })

    return jsonl_opps, jsonl_results

def clean_and_sync_oct5_shadow_data(clean: bool = True):
    """
    Cleans shadow tables (if requested) and reseeds all match opportunities from SHADOW_START_DATE onwards
    evaluating them exclusively with the re-evaluated models (*_final.joblib) and high edge filters.
    All data is strictly saved to core.shadow_tips_eval and core.shadow_results (core.results is UNTOUCHED).
    """
    logger.info("=" * 80)
    logger.info(f"SYNCING SHADOW DATA FROM {SHADOW_START_DATE} (Clean={clean}) WITH RE-EVALUATED MODELS")
    logger.info("=" * 80)

    init_shadow_db()
    mgr = get_shadow_model_manager()
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Fetch candidate match opportunities since SHADOW_START_DATE from both published_tips and shadow_tips_eval
    cur.execute("""
        WITH raw_opps AS (
            SELECT p.match_id, p.match_id as bet365_id, p.channel_key, p.sport, 
                   m.league as league,
                   p.fixture, 
                   COALESCE(p.home_player, m.home_player) as home_player,
                   COALESCE(p.away_player, m.away_player) as away_player,
                   p.side, p.line, p.odds, p.kickoff_at_utc, p.published_at_utc as eval_time,
                   m.duration_minutes
            FROM core.published_tips p
            LEFT JOIN core.matches m ON p.match_id = m.match_id
            WHERE p.published_at_utc >= %s
            UNION
            SELECT s.match_id, s.bet365_id, s.channel_key, s.sport, 
                   COALESCE(s.league, m.league) as league,
                   s.fixture, 
                   m.home_player,
                   m.away_player,
                   s.side, s.line, s.odds, s.kickoff_at_utc, s.evaluated_at_utc as eval_time,
                   m.duration_minutes
            FROM core.shadow_tips_eval s
            LEFT JOIN core.matches m ON s.match_id = m.match_id
            WHERE s.kickoff_at_utc >= %s
        )
        SELECT DISTINCT ON (COALESCE(NULLIF(bet365_id, ''), match_id), channel_key)
            match_id, bet365_id, channel_key, sport, league, fixture, home_player, away_player, side, line, odds, kickoff_at_utc, eval_time, duration_minutes
        FROM raw_opps
        ORDER BY COALESCE(NULLIF(bet365_id, ''), match_id), channel_key, eval_time ASC;
    """, (SHADOW_START_DATE, SHADOW_START_DATE))
    opps = [dict(r) for r in cur.fetchall()]
    logger.info(f"Loaded {len(opps)} candidate match opportunities from database since {SHADOW_START_DATE}.")

    # 2. Load verified scores from core.shadow_results AND core.results
    results_map = {}
    try:
        cur.execute("""
            SELECT match_id, bet365_id, final_home_score, final_away_score, sport, settled_at_utc
            FROM core.shadow_results
            WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
        """)
        for r in cur.fetchall():
            mid = str(r["match_id"])
            results_map[mid] = r
            if r.get("bet365_id"):
                results_map[str(r["bet365_id"])] = r
    except Exception as e:
        logger.debug(f"shadow_results load note: {e}")

    try:
        cur.execute("""
            SELECT match_id, match_id as bet365_id, final_home_score, final_away_score, 'fifa' as sport, settled_at as settled_at_utc
            FROM core.results
            WHERE final_home_score IS NOT NULL AND final_away_score IS NOT NULL;
        """)
        for r in cur.fetchall():
            mid = str(r["match_id"])
            if mid not in results_map:
                results_map[mid] = r
    except Exception as e:
        logger.debug(f"core.results load note: {e}")

    # 3. Load historical candidate matches from JSONL formatted datasets only if requested range covers prior dates
    if SHADOW_START_DATE < "2026-10-01":
        jsonl_opps, jsonl_results = load_jsonl_candidates("2026-09-10", "2026-09-30")
        logger.info(f"Loaded {len(jsonl_opps)} historical candidate opportunities from JSONL feeds.")
        results_map.update(jsonl_results)

        seen_opps = {
            (str(o.get("bet365_id") or o["match_id"]), o["channel_key"]) for o in opps
        }
        for jo in jsonl_opps:
            k = (str(jo.get("bet365_id") or jo["match_id"]), jo["channel_key"])
            if k not in seen_opps:
                seen_opps.add(k)
                opps.append(jo)

    # Sort chronologically by kickoff time
    opps.sort(key=lambda x: x["kickoff_at_utc"] if x.get("kickoff_at_utc") else datetime.min.replace(tzinfo=timezone.utc))
    logger.info(f"Consolidated total candidate opportunities: {len(opps)}.")
    logger.info(f"Total verified final scores available: {len(results_map)}.")

    # 4. Clean shadow_tips_eval if requested
    if clean:
        logger.info("Cleaning core.shadow_tips_eval...")
        cur.execute("TRUNCATE TABLE core.shadow_tips_eval RESTART IDENTITY;")
        conn.commit()

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
        league_name = str(row.get("league") or "").strip()
        if not league_name or league_name.lower() in ("none", "null"):
            continue
        orig_side = str(row["side"] or "home").lower()
        if row.get("line") is None:
            if ch_key in ("fifa_goals_ou", "fifa_asian_handicap", "ebasket_ou"):
                continue
            orig_line = 0.0
        else:
            orig_line = float(row["line"])

        if ch_key in ("fifa_goals_ou", "ebasket_ou") and orig_line <= 0.0:
            continue
        if row.get("odds") is None or float(row["odds"]) <= 1.0:
            continue
        orig_odds = float(row["odds"])
        ko_time = row["kickoff_at_utc"]
        if not ko_time:
            continue
        eval_time = row["eval_time"] or ko_time

        min_odds = CHANNEL_MIN_ODDS.get(ch_key, MIN_ODDS_THRESHOLD)
        min_edge = CHANNEL_MIN_EDGE.get(ch_key, 0.05)
        target_vig = CHANNEL_TARGET_VIG.get(ch_key, 1.06)
        dur_mins_row = row.get("duration_minutes")
        dur_mins = float(dur_mins_row) if (dur_mins_row is not None and float(dur_mins_row) > 0) else mgr.get_tournament_duration(fixture, league_name, sport, dur_mins_row)

        bundle = mgr.bundles[ch_key]
        model = bundle["model"]
        calibrator = bundle.get("calibrator") or bundle.get("calibrators")
        feat_names = bundle["feature_names"]

        h_player = row.get("home_player")
        a_player = row.get("away_player")
        if not h_player or not a_player:
            players = re.findall(r'\(([^)]+)\)', fixture)
            if len(players) >= 2:
                h_player = h_player or players[0].strip()
                a_player = a_player or players[1].strip()
        if not h_player or not a_player:
            continue

        if " (" in fixture:
            h_team = fixture.split(" (")[0].strip()
        else:
            continue

        if " vs " in fixture:
            a_part = fixture.split(" vs ")[1]
            a_team = a_part.split(" (")[0].strip() if " (" in a_part else a_part.strip()
        elif " x " in fixture:
            a_part = fixture.split(" x ")[1]
            a_team = a_part.split(" (")[0].strip() if " (" in a_part else a_part.strip()
        else:
            continue

        if not h_team or not a_team:
            continue

        pick = None

        # 1. FIFA Goals O/U (Strict Edge >= 3%, OVER-Only)
        if ch_key == "fifa_goals_ou":
            if orig_line <= 0.0:
                continue
            line_val = orig_line
            if orig_side == "over":
                o_odds = orig_odds
                u_odds = get_complementary_odds(orig_odds, target_vig)
            else:
                u_odds = orig_odds
                o_odds = get_complementary_odds(orig_odds, target_vig)

            odds_info = {"over_odds": o_odds, "under_odds": u_odds, "duration_minutes": dur_mins}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_time, fixture=fixture, league=league_name, duration_minutes=dur_mins)
            if X is None:
                continue
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            imp_p_over = 1.0 / o_odds
            edge_o = cal_p - imp_p_over

            # Enforce Specification Rule: OVER-Only
            if edge_o >= min_edge and o_odds >= min_odds:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Gols")

        # 2. FIFA Asian Handicap (Strict Edge >= 5%)
        elif ch_key == "fifa_asian_handicap":
            line_val = orig_line
            if orig_side == "home":
                h_odds = orig_odds
                a_odds = get_complementary_odds(orig_odds, target_vig)
            else:
                a_odds = orig_odds
                h_odds = get_complementary_odds(orig_odds, target_vig)

            odds_info = {"home_odds": h_odds, "away_odds": a_odds, "duration_minutes": dur_mins}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_time, fixture=fixture, league=league_name, duration_minutes=dur_mins)
            if X is None:
                continue
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            imp_p_home = 1.0 / h_odds
            imp_p_away = 1.0 / a_odds
            edge_h = cal_p - imp_p_home
            edge_a = (1.0 - cal_p) - imp_p_away

            if edge_h >= min_edge and h_odds >= min_odds and edge_h >= edge_a:
                pick = ("home", line_val, h_odds, cal_p, edge_h, f"{h_team} (Handicap {line_val:+.1f})")
            elif edge_a >= min_edge and a_odds >= min_odds and edge_a > edge_h:
                pick = ("away", -line_val, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Handicap {-line_val:+.1f})")

        # 3. FIFA Money Line (Strict Edge >= 5%)
        elif ch_key == "fifa_money_line":
            if orig_side == "home":
                h_odds = orig_odds
                a_odds = get_complementary_odds(orig_odds, target_vig)
            else:
                a_odds = orig_odds
                h_odds = get_complementary_odds(orig_odds, target_vig)

            odds_info = {"home_odds": h_odds, "away_odds": a_odds, "duration_minutes": dur_mins}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, 0.0, odds_info, ko_time, fixture=fixture, league=league_name, duration_minutes=dur_mins)
            if X is None:
                continue
            if hasattr(model, "model") and hasattr(model.model, "predict_proba"):
                raw_p = model.model.predict_proba(X)[0]
            else:
                raw_p = model.predict_proba(X)[0]

            cal_h, cal_a = calibrator
            p_h = float(cal_h.predict([raw_p[0]])[0])
            p_a = float(cal_a.predict([raw_p[2] if len(raw_p) > 2 else raw_p[1]])[0])
            imp_p_h = 1.0 / h_odds
            imp_p_a = 1.0 / a_odds
            edge_h = p_h - imp_p_h
            edge_a = p_a - imp_p_a

            if edge_h >= min_edge and h_odds >= min_odds and edge_h >= edge_a:
                pick = ("home", 0.0, h_odds, p_h, edge_h, f"{h_team} (Empate Anula)")
            elif edge_a >= min_edge and a_odds >= min_odds and edge_a > edge_h:
                pick = ("away", 0.0, a_odds, p_a, edge_a, f"{a_team} (Empate Anula)")

        # 4. eBasket Money Line (Edge >= 2%)
        elif ch_key == "ebasket_money_line":
            if orig_side == "home":
                h_odds = orig_odds
                a_odds = get_complementary_odds(orig_odds, target_vig)
            else:
                a_odds = orig_odds
                h_odds = get_complementary_odds(orig_odds, target_vig)

            odds_info = {"home_odds": h_odds, "away_odds": a_odds, "duration_minutes": dur_mins}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, 0.0, odds_info, ko_time, fixture=fixture, league=league_name, duration_minutes=dur_mins)
            if X is None:
                continue
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = float(calibrator.predict([raw_p])[0])
            imp_p_h = 1.0 / h_odds
            imp_p_a = 1.0 / a_odds
            edge_h = cal_p - imp_p_h
            edge_a = (1.0 - cal_p) - imp_p_a

            if edge_h >= min_edge and h_odds >= min_odds and edge_h >= edge_a:
                pick = ("home", 0.0, h_odds, cal_p, edge_h, f"{h_team} (Vencedor)")
            elif edge_a >= min_edge and a_odds >= min_odds and edge_a > edge_h:
                pick = ("away", 0.0, a_odds, 1.0 - cal_p, edge_a, f"{a_team} (Vencedor)")

        # 5. eBasket O/U (Edge >= 2%)
        elif ch_key == "ebasket_ou":
            if orig_line <= 0.0:
                continue
            line_val = orig_line
            if orig_side == "over":
                o_odds = orig_odds
                u_odds = get_complementary_odds(orig_odds, target_vig)
            else:
                u_odds = orig_odds
                o_odds = get_complementary_odds(orig_odds, target_vig)

            odds_info = {"over_odds": o_odds, "under_odds": u_odds, "duration_minutes": dur_mins}
            X = mgr.build_feature_vector(ch_key, sport, h_player, a_player, line_val, odds_info, ko_time, fixture=fixture, league=league_name, duration_minutes=dur_mins)
            if X is None:
                continue
            raw_p = model.predict_proba(X)[0, 1] if hasattr(model, "predict_proba") else model.model.predict_proba(X)[0, 1]
            cal_p = regularize_calibrated_prob(float(calibrator.predict([raw_p])[0]))
            imp_p_o = 1.0 / o_odds
            imp_p_u = 1.0 / u_odds
            edge_o = cal_p - imp_p_o
            edge_u = (1.0 - cal_p) - imp_p_u

            if edge_o >= min_edge and o_odds >= min_odds and edge_o >= edge_u:
                pick = ("over", line_val, o_odds, cal_p, edge_o, f"Mais de {line_val} Pontos")
            elif edge_u >= min_edge and u_odds >= min_odds and edge_u > edge_o:
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
                    if sport == "ebasket":
                        duration = timedelta(minutes=dur_mins + 15.0) if dur_mins else timedelta(minutes=35)
                    else:
                        duration = timedelta(minutes=dur_mins + 3.0)
                    settled_at = (ko_time + duration) if ko_time else (eval_time + duration)
                pending_reason = "NONE (Fully Settled)"
                src = "shadow_api_fetcher"
                time_pending = "0.0h (Resolved)"
                if raw_match_id not in shadow_results_to_save:
                    shadow_results_to_save[raw_match_id] = (
                        raw_match_id, bet365_id, sport, fh, fa, settled_at, "historic_sync"
                    )
            else:
                now_utc = datetime.now(timezone.utc)
                age_hrs = (now_utc - ko_time).total_seconds() / 3600.0 if ko_time else 0.0
                if age_hrs >= SHADOW_ABANDONED_HOURS:
                    status = "SETTLED"
                    final_score = "ABANDONED"
                    outcome = "VOID"
                    net_units = 0.000
                    settled_at = ko_time + timedelta(hours=SHADOW_ABANDONED_HOURS) if ko_time else now_utc
                    pending_reason = f"ABANDONED_FIXTURE (Exceeded {SHADOW_ABANDONED_HOURS}h whistle window)"
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
                raw_match_id, bet365_id, sport, ch_key, league_name, fixture,
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
    try:
        from scripts.generate_canonical_shadow_reconciliation import generate_reconciliation
        generate_reconciliation()
    except Exception as e:
        logger.debug(f"Canonical export note: {e}")
    print_shadow_telemetry()

def print_shadow_telemetry():
    """Prints live performance telemetry from core.shadow_tips_eval for SHADOW_START_DATE onwards."""
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
        WHERE kickoff_at_utc >= %s
        GROUP BY channel_key;
    """, (SHADOW_START_DATE,))
    rows = cur.fetchall()
    conn.close()

    start_label = SHADOW_START_DATE.split()[0]
    print("\n" + "=" * 92)
    print(f" SHADOW MODE TELEMETRY (RE-EVALUATED MODELS | {start_label} - PRESENT)")
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
            clean_and_sync_oct5_shadow_data(clean=True)
