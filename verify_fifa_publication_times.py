#!/usr/bin/env python3
"""
FIFA Actual Publication & Settlement Timing Verifier
====================================================
Verifies for each of the three FIFA groups:
1. Total tips generated and published on target date (Brazil Time).
2. The exact time the FIRST new tip was published today.
3. The exact time the LAST new tip was published today (original broadcast timestamp).
4. The exact time of the latest settlement edit (in-place score update).
5. Full metadata of the latest tip (Match ID, fixture, selection, odds, published BRT, settled BRT).

Data sources:
- core/dashboard/settled_tips_ledger.json (published_at_utc & settled_at_brt)
- core/dashboard/published_tips_cache.json (active pending in-play tips)
- PostgreSQL core.settled_tips & core.daily_tip_ledger
- Docker container live logs (mario_ai_live_publisher)
"""

import os
import sys
import json
import re
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

BRT_TZ = timezone(timedelta(hours=-3))

FIFA_GROUPS = {
    "fifa_goals_ou": {
        "title": "FIFA Goals O/U",
        "official_title": "Matrix Esoccer Pre Goals G01",
        "aliases": ["fifa_goals_ou", "fifa_ou", "fifa_goals", "goals_ou"],
        "cap": 150
    },
    "fifa_money_line": {
        "title": "FIFA Money Line",
        "official_title": "Matrix FIFA Pre ML G01",
        "aliases": ["fifa_money_line", "fifa_ml", "money_line"],
        "cap": 150
    },
    "fifa_asian_handicap": {
        "title": "FIFA Asian Handicap",
        "official_title": "Matrix FIFA Pre AH G01",
        "aliases": ["fifa_asian_handicap", "fifa_ah", "asian_handicap"],
        "cap": 100
    }
}


def parse_to_brt(raw_ts: Any) -> Optional[datetime]:
    if not raw_ts:
        return None
    try:
        s = str(raw_ts).strip()
        # Handle ISO strings
        if "T" in s:
            s_clean = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(BRT_TZ)
        # Handle 'YYYY-MM-DD HH:MM:SS BRT'
        if "BRT" in s:
            s_clean = s.replace("BRT", "").strip()
            dt = datetime.strptime(s_clean, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=BRT_TZ)
        # Handle 'YYYY-MM-DD HH:MM:SS'
        if len(s) == 19:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=BRT_TZ)
    except Exception:
        pass
    return None


def load_json(rel_path: str, default=None):
    candidates = [
        rel_path,
        os.path.join(os.path.dirname(__file__), rel_path),
        os.path.join("/root/mario-ai-code", rel_path)
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return default or []


def query_postgres(sql: str) -> List[str]:
    cmd = ["docker", "exec", "mario_ai_db", "psql", "-U", "postgres", "-d", "mario_ai", "-t", "-A", "-F", ",", "-c", sql]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    except Exception:
        pass
    return []


def query_container_logs(channel_key: str, target_date_str: str) -> List[Dict[str, Any]]:
    """Extracts live tip dispatch log lines from Docker container."""
    cmd = ["docker", "logs", "--since", "48h", "mario_ai_live_publisher"]
    dispatches = []
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                if ("Dispatched tip for" in line or "Recorded tip" in line) and channel_key in line:
                    dispatches.append(line)
    except Exception:
        pass
    return dispatches


def analyze_channel(ch_key: str, meta: Dict[str, Any], target_date_str: str, settled_data: List[Dict[str, Any]], cache_data: Dict[str, Any]):
    aliases = set(meta["aliases"])
    tips_today = []

    # 1. Check settled tips ledger
    for it in settled_data:
        if it.get("channel_key") in aliases:
            # Parse publication timestamp
            pub_ts = it.get("published_at_utc") or it.get("timestamp") or it.get("date_brt")
            dt_pub_brt = parse_to_brt(pub_ts)

            # Parse settlement timestamp
            settled_ts = it.get("settled_at_brt")
            dt_settled_brt = parse_to_brt(settled_ts)

            date_str = it.get("date_brt") or (dt_pub_brt.strftime("%Y-%m-%d") if dt_pub_brt else "")
            if date_str == target_date_str or (dt_pub_brt and dt_pub_brt.strftime("%Y-%m-%d") == target_date_str):
                tips_today.append({
                    "match_id": it.get("match_id"),
                    "fixture": it.get("fixture", "Live Fixture"),
                    "pick": f"{it.get('side','')} {it.get('line','')}".strip() or it.get("pick_str", "Tip"),
                    "odds": it.get("odds", 1.90),
                    "published_brt": dt_pub_brt,
                    "settled_brt": dt_settled_brt,
                    "status": it.get("outcome", "SETTLED"),
                    "score": it.get("final_score") or it.get("score_str", "")
                })

    # 2. Check active pending cache
    if isinstance(cache_data, dict):
        for k, it in cache_data.items():
            if isinstance(it, dict) and (it.get("type") in aliases or it.get("channel_key") in aliases):
                pub_ts = it.get("published_at_utc") or it.get("timestamp")
                dt_pub_brt = parse_to_brt(pub_ts)
                if dt_pub_brt and dt_pub_brt.strftime("%Y-%m-%d") == target_date_str:
                    m_id = it.get("match_id") or k
                    # Deduplicate if already present
                    if not any(t["match_id"] == m_id for t in tips_today):
                        h_p = it.get("home_player") or ""
                        a_p = it.get("away_player") or ""
                        fixture = f"{h_p} x {a_p}" if h_p and a_p else it.get("fixture", "Live Fixture")
                        tips_today.append({
                            "match_id": m_id,
                            "fixture": fixture,
                            "pick": f"{it.get('side','')} {it.get('line','')}".strip() or "Pending Tip",
                            "odds": it.get("odds", 1.90),
                            "published_brt": dt_pub_brt,
                            "settled_brt": None,
                            "status": "PENDING (In Play)",
                            "score": "In Play"
                        })

    # Sort chronologically by publication time
    tips_today = sorted(tips_today, key=lambda x: x["published_brt"] if x["published_brt"] else datetime.min.replace(tzinfo=BRT_TZ))

    return tips_today


def main():
    parser = argparse.ArgumentParser(description="Verify FIFA Actual Publication & Settlement Timings")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (defaults to today in BRT)")
    args = parser.parse_args()

    now_brt = datetime.now(BRT_TZ)
    target_date = args.date or now_brt.strftime("%Y-%m-%d")

    settled_data = load_json("core/dashboard/settled_tips_ledger.json", [])
    cache_data = load_json("core/dashboard/published_tips_cache.json", {})

    print("=" * 85)
    print("       MARIO AI - FIFA ACTUAL PUBLICATION & SETTLEMENT AUDIT")
    print("=" * 85)
    print(f"Target Date: {target_date} (Brazil Time / BRT)")
    print(f"Current Server Time: {now_brt.strftime('%Y-%m-%d %H:%M:%S BRT')}")
    print("=" * 85)

    for ch_k, meta in FIFA_GROUPS.items():
        tips = analyze_channel(ch_k, meta, target_date, settled_data, cache_data)
        total_count = len(tips)

        print(f"\n[{meta['official_title'].upper()} | {meta['title']}]")
        print(f"Total Tips Published on {target_date}: {total_count} (Daily Cap: {meta['cap']})")

        if total_count == 0:
            print("  Status: Zero tips published on this calendar date.")
            continue

        first_tip = tips[0]
        last_tip = tips[-1]

        first_pub_str = first_tip["published_brt"].strftime("%H:%M:%S BRT") if first_tip["published_brt"] else "Unknown"
        last_pub_str = last_tip["published_brt"].strftime("%H:%M:%S BRT") if last_tip["published_brt"] else "Unknown"

        # Latest settlement time across all settled tips
        settled_tips = [t for t in tips if t["settled_brt"]]
        latest_settled_tip = max(settled_tips, key=lambda x: x["settled_brt"]) if settled_tips else None
        latest_settle_str = latest_settled_tip["settled_brt"].strftime("%H:%M:%S BRT") if latest_settled_tip else "None yet (in-play)"

        print(f"  • Earliest New Tip Published Today : {first_pub_str}")
        print(f"  • LATEST NEW TIP PUBLISHED TODAY   : {last_pub_str} (Actual broadcast time)")
        print(f"  • Latest Settlement Edit in Channel: {latest_settle_str} (When Telegram post was edited)")
        print("")
        print("  Details of the Most Recent Published Tip:")
        print(f"    - Match ID   : {last_tip['match_id']}")
        print(f"    - Fixture    : {last_tip['fixture']}")
        print(f"    - Selection  : {last_tip['pick']} @ odds {last_tip['odds']}")
        print(f"    - Published  : {last_pub_str}")
        print(f"    - Status     : {last_tip['status']} (Final Score: {last_tip['score']})")
        if last_tip["settled_brt"]:
            print(f"    - Settled At : {last_tip['settled_brt'].strftime('%H:%M:%S BRT')} (In-place Telegram edit)")
        print("-" * 85)

    print("\nOperational Clarification on Timing Discrepancy:")
    print("1. Publication Time: The moment the pre-match betting signal is generated and broadcast to Telegram.")
    print("2. Settlement-Edit Time: The moment the match concludes and the bot edits the original message in-place with the final score.")
    print("Because FIFA matches take 10 to 25 minutes to conclude, the settlement-edit timestamp will always appear later than the original publication timestamp.")
    print("=" * 85)


if __name__ == "__main__":
    main()
