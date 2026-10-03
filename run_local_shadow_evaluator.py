#!/usr/bin/env python3
"""
Mario AI - Standalone Local Shadow Evaluator & Performance Pipeline
====================================================================
Features:
1. 100% Isolated: Stores predictions and settlements exclusively in `core.shadow_tips_eval`.
   Does NOT write to `core.published_tips`, `core.tip_audit_log`, or any production table.
2. ZERO Telegram Impact: No messages are ever sent to Telegram.
3. Live Data Ingestion: Connects directly to the live match feed API (`/matches/pre` and `/matches/ebasket/pre`).
4. In-Memory ML Model Evaluation: Evaluates all 5 markets using production models.
5. Automated Whistle Settlement: Polls official match results and updates shadow records with exact unit settlements.
6. Real-Time Telemetry: Tracks Sample Size, Decided Win Rate, Net Units, ROI, and Drawdown.
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
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load local environment
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SHADOW-PIPELINE] %(message)s"
)
logger = logging.getLogger("shadow_pipeline")

DB_URL = os.getenv("DATABASE_URL") or "postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai"
JARBET_BASE_URL = os.getenv("JARBET_BASE_URL", "https://data.jarvisbet.com.br").rstrip("/")
JARBET_API_KEY = os.getenv("JARBET_API_KEY", "")

# Import model manager and evaluator from core without initializing publisher
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.live_publisher import evaluate_market_opportunity, get_model_manager

BRT_TZ = timezone(timedelta(hours=-3))

def init_shadow_db():
    """Ensures the isolated shadow evaluation table exists in PostgreSQL."""
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
    """)
    conn.commit()
    conn.close()
    logger.info("Initialized isolated shadow table: core.shadow_tips_eval")

def fetch_live_matches() -> List[Dict[str, Any]]:
    """Fetches upcoming live matches from the live API for FIFA and eBasketball."""
    headers = {"x-api-key": JARBET_API_KEY, "Accept": "application/json"}
    all_matches = []

    # 1. FIFA / Esoccer
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

def evaluate_shadow_opportunities(matches: List[Dict[str, Any]], min_edge: float = 0.02, min_odds: float = 1.60):
    """Evaluates upcoming matches and logs shadow predictions without Telegram dispatch."""
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
        raw_mid = str(match.get("_id") or match.get("idMatchBet365") or "").strip()
        b365_id = str(match.get("idMatchBet365") or "").strip()
        league = str(match.get("league") or "")
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

        for ch_key, ch_sport in channel_list:
            if ch_sport != sport:
                continue

            # Evaluate with model manager
            eval_res = evaluate_market_opportunity(
                m_key=ch_key,
                match=match,
                odds_dict=odds_dict,
                h_player=h_player,
                a_player=a_player,
                home_team=h_team,
                away_team=a_team,
                min_odds=min_odds,
                min_edge=min_edge
            )

            if not eval_res:
                continue

            side = eval_res.get("side")
            line_val = eval_res.get("line")
            odds_val = eval_res.get("odds")
            pick_str = eval_res.get("pick_str")
            prob_str = eval_res.get("prob_str", "0%").rstrip("%")
            edge_str = eval_res.get("edge_str", "0%").rstrip("%").lstrip("+")

            try:
                model_prob = float(prob_str) / 100.0
                edge_val = float(edge_str) / 100.0
                imp_prob = 1.0 / odds_val if odds_val > 1.0 else 0.5
            except Exception:
                continue

            # Insert into isolated shadow table (ON CONFLICT DO NOTHING ensures strict deduplication)
            try:
                cur.execute("""
                    INSERT INTO core.shadow_tips_eval (
                        match_id, bet365_id, sport, channel_key, league, fixture,
                        market_type, pick_str, side, line, odds, implied_prob,
                        model_prob, estimated_edge, status, kickoff_at_utc
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, 'PENDING', %s
                    ) ON CONFLICT (channel_key, match_id) DO NOTHING;
                """, (
                    raw_mid, b365_id, sport, ch_key, league, fixture,
                    ch_key, pick_str, side, line_val, odds_val, imp_prob,
                    model_prob, edge_val, ko_dt
                ))
                if cur.rowcount > 0:
                    new_shadow_count += 1
                    logger.info(f"  [SHADOW PICK LOGGED] {ch_key.upper()} | {fixture} | Pick: {pick_str} @ {odds_val:.2f} (Prob: {prob_str}%, Edge: +{edge_str}%)")
            except Exception as ins_err:
                logger.debug(f"Insert error for shadow match {raw_mid}: {ins_err}")

    conn.commit()
    conn.close()
    if new_shadow_count > 0:
        logger.info(f"Recorded {new_shadow_count} new shadow predictions into core.shadow_tips_eval.")

def settle_shadow_tips():
    """Polls official match results from core.results and history feed, settling shadow tips mathematically."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT s.id, s.match_id, s.bet365_id, s.sport, s.channel_key, s.side, s.line, s.odds,
               r.final_home_score, r.final_away_score
        FROM core.shadow_tips_eval s
        JOIN core.results r ON (s.match_id = r.match_id OR s.bet365_id = r.match_id)
        WHERE s.status = 'PENDING'
          AND r.final_home_score IS NOT NULL AND r.final_away_score IS NOT NULL;
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

        # Exact Mathematical Settlement Formula
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
                settled_at_utc = NOW()
            WHERE id = %s;
        """, (final_str, outcome, round(net_units, 3), tip["id"]))
        settled_now += 1

    conn.commit()
    conn.close()
    if settled_now > 0:
        logger.info(f"Settled {settled_now} shadow tips against verified whistle results.")

def print_shadow_telemetry():
    """Prints live performance telemetry from core.shadow_tips_eval."""
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
        GROUP BY channel_key;
    """)
    rows = cur.fetchall()
    conn.close()

    print("\n" + "=" * 90)
    print(" SHADOW MODE TELEMETRY (ISOLATED LIVE EVALUATION)")
    print("=" * 90)
    print(f"{'Channel':<22} | {'Total':<6} | {'W-L-V (HW/HL)':<18} | {'Net Units':<10} | {'Win Rate':<10} | {'ROI':<8} | {'Pending'}")
    print("-" * 90)

    tot_tips = 0
    tot_net = 0.0
    tot_decided = 0
    tot_wins = 0

    for r in sorted(rows, key=lambda x: x["channel_key"]):
        w, l, v, hw, hl = r["wins"], r["losses"], r["voids"], r["half_wins"], r["half_losses"]
        decided = w + l + hw + hl
        wr = ((w + 0.5 * hw) / decided * 100.0) if decided > 0 else 0.0
        roi = (float(r["net_units"]) / r["total_tips"] * 100.0) if r["total_tips"] > 0 else 0.0

        tot_tips += r["total_tips"]
        tot_net += float(r["net_units"])
        tot_decided += decided
        tot_wins += (w + 0.5 * hw)

        rec_str = f"{w}-{l}-{v} ({hw}/{hl})"
        print(f"{r['channel_key']:<22} | {r['total_tips']:<6} | {rec_str:<18} | {float(r['net_units']):+9.2f}U | {wr:8.1f}% | {roi:+6.1f}% | {r['pending_count']}")

    print("-" * 90)
    overall_wr = (tot_wins / tot_decided * 100.0) if tot_decided > 0 else 0.0
    overall_roi = (tot_net / tot_tips * 100.0) if tot_tips > 0 else 0.0
    print(f"{'CONSOLIDATED':<22} | {tot_tips:<6} | {'-':<18} | {tot_net:+9.2f}U | {overall_wr:8.1f}% | {overall_roi:+6.1f}% |")
    print("=" * 90 + "\n")

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
    args = parser.parse_args()

    init_shadow_db()

    if args.loop:
        logger.info(f"Starting continuous shadow monitoring (polling every {args.interval}s)... Press Ctrl+C to stop.")
        try:
            while True:
                run_shadow_cycle()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("Shadow pipeline stopped by user.")
    else:
        run_shadow_cycle()
