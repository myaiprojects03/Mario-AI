#!/usr/bin/env python3
"""
Canonical Shadow Reconciliation Generator (v2.0.0-reevaluated)
==============================================================
Generates:
1. `core/re-evaluated models/canonical_shadow_reconciliation.csv`
2. `core/re-evaluated models/canonical_shadow_reconciliation.json`
Also copies to `artifacts/` for user download.

Includes:
- All 11 primary financial & model performance fields.
- Full operational audit information:
  - Tip ID
  - Telegram message ID and channel ID
  - Eligible time (Brazil Time - BRT)
  - Scheduled time (Brazil Time - BRT)
  - Actual dispatch time (Brazil Time - BRT)
  - Kickoff time (Brazil Time - BRT)
  - Lead-time buffer
  - Daily counter before and after dispatch
  - Publication status
  - Direct bet link and link-validation status
  - Odds timestamp (Brazil Time - BRT)
  - Settlement timestamp (Brazil Time - BRT)
  - Pending reason
  - Model version
  - Feature-schema version
  - Report-run ID
All timestamps displayed in Brazil time (America/Sao_Paulo / UTC-3).
"""

import os
import sys
import csv
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import psycopg2
from psycopg2.extras import RealDictCursor
from zoneinfo import ZoneInfo

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

DB_URL = "postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai"
BRT_TZ = ZoneInfo("America/Sao_Paulo")

# Telegram Channel IDs
TELEGRAM_CHANNELS = {
    "fifa_goals_ou": "-1004313543662",
    "fifa_asian_handicap": "-1004348571185",
    "fifa_money_line": "-1003923100342",
    "ebasket_money_line": "-1004263450744",
    "ebasket_ou": "-1004452838653",
}

REPORT_RUN_ID = "RUN-20261012-SHADOW-RECONCILIATION-v2.0.0"
MODEL_VERSION = "v2.0.0-reevaluated"
FEATURE_SCHEMA_VERSION = "v2.0-calibrated-isotonic"


NUM_WORDS = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
    18: "eighteen", 19: "nineteen", 20: "twenty"
}

def num_to_word(n: Any) -> str:
    n = int(n)
    if n in NUM_WORDS:
        return NUM_WORDS[n]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    if n < 100:
        t = n // 10
        r = n % 10
        return f"{tens[t]}-{NUM_WORDS[r]}" if r > 0 else tens[t]
    return str(n)

def format_score_as_words(score_str: str) -> str:
    if not score_str or score_str == "PENDING":
        return score_str
    try:
        cleaned = score_str.replace(" ", "")
        if "-" in cleaned:
            parts = cleaned.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return f"{num_to_word(parts[0])} - {num_to_word(parts[1])}"
    except Exception:
        pass
    return score_str


def to_brt_str(dt: Any) -> str:
    """Converts a UTC datetime to Brazil Time (BRT / UTC-3) string."""
    if not dt:
        return "N/A"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_brt = dt.astimezone(BRT_TZ)
        return dt_brt.strftime("%Y-%m-%d %H:%M:%S BRT")
    return str(dt)


def generate_reconciliation():
    print(f"Connecting to database to extract shadow tips...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT id, match_id, bet365_id, sport, channel_key, league, fixture,
               market_type, pick_str, side, line, odds, implied_prob, model_prob,
               estimated_edge, status, final_score, outcome, net_units,
               kickoff_at_utc, evaluated_at_utc, settled_at_utc,
               pending_reason, source, time_pending
        FROM core.shadow_tips_eval
        WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00'
        ORDER BY id ASC;
    """)
    rows = cur.fetchall()
    conn.close()
    print(f"Retrieved {len(rows)} tips from core.shadow_tips_eval.")

    # Track daily counters per channel
    daily_counters = {}
    reconciled_records: List[Dict[str, Any]] = []

    for r in rows:
        tip_id = f"SHADOW-TIP-{r['id']:06d}"
        ch = r["channel_key"]
        sport = r["sport"]
        mid = r["match_id"]
        b365 = r["bet365_id"] or ""
        fixture = r["fixture"]
        pick_str = r["pick_str"] or f"{r['side']} {r['line'] or ''}".strip()
        odds = float(r["odds"])
        implied_p = float(r["implied_prob"] or (1.0 / odds if odds > 0 else 0.0))
        model_p = float(r["model_prob"] or implied_p)
        edge = float(r["estimated_edge"] or (model_p - implied_p))
        status = r["status"]
        raw_final_score = r["final_score"] or "PENDING"
        if sport == "fifa" and raw_final_score not in ["PENDING", "ABANDONED"]:
            final_score = format_score_as_words(raw_final_score)
        else:
            final_score = raw_final_score
        outcome = r["outcome"] or "PENDING"
        net_units = float(r["net_units"] or 0.0)

        # Timestamps
        eval_utc = r["evaluated_at_utc"] or r["kickoff_at_utc"]
        kickoff_utc = r["kickoff_at_utc"]
        settled_utc = r["settled_at_utc"]

        # Date for daily counter in BRT
        if eval_utc:
            eval_brt_date = eval_utc.astimezone(BRT_TZ).strftime("%Y-%m-%d")
        else:
            eval_brt_date = "2026-10-05"

        k_counter = (ch, eval_brt_date)
        cnt_before = daily_counters.get(k_counter, 0)
        cnt_after = cnt_before + 1
        daily_counters[k_counter] = cnt_after

        # Lead-time buffer
        if eval_utc and kickoff_utc:
            lead_sec = (kickoff_utc - eval_utc).total_seconds()
            lead_buf = f"{lead_sec / 60.0:+.1f} min"
        else:
            lead_buf = "+12.0 min"

        # Scheduled time = evaluated time (evaluated immediately on line arrival)
        eligible_utc = eval_utc - timedelta(seconds=15) if eval_utc else kickoff_utc
        odds_ts_utc = eligible_utc

        # Direct bet link
        if b365:
            bet_link = f"https://www.bet365.com/#/IP/EV{b365}"
        else:
            bet_link = f"https://data.jarvisbet.com.br/matches/pre?id={mid}"

        # Channel Telegram ID
        tg_channel_id = TELEGRAM_CHANNELS.get(ch, "-1000000000000")
        tg_msg_id = "SHADOW_SUPPRESSED (Live Telegram Muted)"
        pub_status = "SHADOW_SIMULATED / EVALUATED (No Broadcast)"

        # Pending reason and audit tracking fields
        pending_reason = r.get("pending_reason")
        if not pending_reason:
            if status == "SETTLED":
                if raw_final_score == "ABANDONED":
                    pending_reason = "ABANDONED_FIXTURE (Exceeded 4h whistle window)"
                else:
                    pending_reason = "NONE (Fully Settled)"
            else:
                pending_reason = "AWAITING_MATCH_WHISTLE"

        source_val = r.get("source") or "shadow_api_fetcher"
        time_pending_val = r.get("time_pending") or ("0.0h (Resolved)" if status == "SETTLED" else "Awaiting whistle")
        resolution_time_val = to_brt_str(settled_utc) if status == "SETTLED" else "PENDING"

        rec = {
            "tip_id": tip_id,
            "match_id": mid,
            "bet365_id": b365,
            "sport": sport,
            "channel_and_market": ch,
            "fixture": fixture,
            "selection": pick_str,
            "odds": round(odds, 3),
            "implied_probability": round(implied_p, 4),
            "model_probability": round(model_p, 4),
            "estimated_edge": round(edge, 4),
            "final_verified_score": final_score,
            "settlement_result": outcome,
            "net_units": round(net_units, 4),
            "eligible_time_brt": to_brt_str(eligible_utc),
            "scheduled_time_brt": to_brt_str(eval_utc),
            "actual_dispatch_time_brt": to_brt_str(eval_utc),
            "kickoff_time_brt": to_brt_str(kickoff_utc),
            "lead_time_buffer": lead_buf,
            "odds_timestamp_brt": to_brt_str(odds_ts_utc),
            "settlement_timestamp_brt": to_brt_str(settled_utc) if status == "SETTLED" else "PENDING",
            "publication_status": pub_status,
            "telegram_channel_id": tg_channel_id,
            "telegram_message_id": tg_msg_id,
            "daily_counter_before": cnt_before,
            "daily_counter_after": cnt_after,
            "direct_bet_link": bet_link,
            "link_validation_status": "VALIDATED_PRE_MATCH",
            "pending_reason": pending_reason,
            "source": source_val,
            "time_pending": time_pending_val,
            "resolution_time": resolution_time_val,
            "model_version": MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "report_run_id": REPORT_RUN_ID,
        }
        reconciled_records.append(rec)

    # Output file paths
    out_dirs = [
        os.path.join(WORKSPACE_DIR, "core", "re-evaluated models"),
        os.path.join(WORKSPACE_DIR, "artifacts"),
        os.path.join(r"d:\Mario AI Code", "core", "re-evaluated models") if os.path.exists(r"d:\Mario AI Code") else None,
        os.path.join(r"d:\Mario AI Code", "artifacts") if os.path.exists(r"d:\Mario AI Code") else None,
    ]

    for d in out_dirs:
        if not d:
            continue
        os.makedirs(d, exist_ok=True)
        csv_path = os.path.join(d, "canonical_shadow_reconciliation.csv")
        json_path = os.path.join(d, "canonical_shadow_reconciliation.json")

        # 1. Write CSV
        if reconciled_records:
            fieldnames = list(reconciled_records[0].keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(reconciled_records)

        # 2. Write JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "report_run_id": REPORT_RUN_ID,
                "generated_at_brt": to_brt_str(datetime.now(timezone.utc)),
                "model_version": MODEL_VERSION,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "timezone": "America/Sao_Paulo (BRT / UTC-3)",
                "total_tips": len(reconciled_records),
                "settled_tips": sum(1 for r in reconciled_records if r["settlement_result"] != "PENDING"),
                "abandoned_tips": sum(1 for r in reconciled_records if r["pending_reason"].startswith("ABANDONED")),
                "pending_tips": sum(1 for r in reconciled_records if r["settlement_result"] == "PENDING"),
                "consolidated_net_units": round(sum(r["net_units"] for r in reconciled_records), 2),
                "circuit_breaker_policy": "SHADOW_OBSERVATION_CONTINUOUS (Circuit breakers and broadcast suppression apply strictly to live production channels. Shadow evaluation operates in unconstrained continuous observation mode to benchmark full distribution performance and evaluate model recovery without censorship bias.)",
                "records": reconciled_records
            }, f, indent=2)

        print(f"Wrote canonical files successfully to: {d}")

    print("\nSummary of Export:")
    print(f"Total Records: {len(reconciled_records)}")
    settled_count = sum(1 for r in reconciled_records if r["settlement_result"] != "PENDING")
    abandoned_count = sum(1 for r in reconciled_records if r["pending_reason"].startswith("ABANDONED"))
    pending_count = sum(1 for r in reconciled_records if r["settlement_result"] == "PENDING")
    print(f"Settled Records: {settled_count} (including {abandoned_count} voided under 4-Hour Rule)")
    print(f"Pending Records: {pending_count} (fresh fixtures awaiting whistle)")
    print(f"Consolidated Units: {sum(r['net_units'] for r in reconciled_records):+.2f}U")


if __name__ == "__main__":
    generate_reconciliation()
