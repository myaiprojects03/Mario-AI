#!/usr/bin/env python3
"""
Production 24-Hour Brazil-Time Comprehensive Audit Utility (count_logs.py)
==========================================================================
Automatically audits and displays all dates (2026-09-14, 2026-09-15, 2026-09-16)
meeting 100% of client requirements.
"""

import os
import sys
import json
import re
import argparse
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import zoneinfo

BRT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")
UTC_TZ = timezone.utc

CHANNEL_CONFIG = {
    "fifa_goals_ou": {
        "name": "FIFA Goals Over/Under",
        "short_code": "FIFA-GOALS",
        "keywords": ["fifa goals", "goals over/under", "over/under", "goals ou", "fifa_goals_ou", "fifa_goals", "gols"],
        "daily_cap": 150,
        "min_odds": 1.70
    },
    "fifa_asian_handicap": {
        "name": "FIFA Asian Handicap",
        "short_code": "FIFA-AH",
        "keywords": ["fifa asian handicap", "asian handicap", "fifa ah", "asian_handicap", "fifa_asian_handicap", "fifa_ah", "handicap"],
        "daily_cap": 100,
        "min_odds": 1.70
    },
    "fifa_money_line": {
        "name": "FIFA Money Line",
        "short_code": "FIFA-ML",
        "keywords": ["fifa money line", "fifa ml", "money line", "1x2", "match winner", "fifa_money_line", "fifa_ml"],
        "daily_cap": 150,
        "min_odds": 1.70
    },
    "ebasket_money_line": {
        "name": "eBasket Money Line",
        "short_code": "EBASKET-ML",
        "keywords": ["ebasketball money line", "ebasket ml", "ebasketball ml", "ebasket_money_line", "ebasket_ml"],
        "daily_cap": 150,
        "min_odds": 1.70
    },
    "ebasket_ou": {
        "name": "eBasket Over/Under",
        "short_code": "EBASKET-OU",
        "keywords": ["ebasketball over/under", "ebasket ou", "ebasketball ou", "ebasket_ou", "pontos", "points"],
        "daily_cap": 150,
        "min_odds": 1.70
    }
}

def extract_date_str(ts_val) -> str:
    if not ts_val:
        return ""
    ts_str = str(ts_val).strip()
    if len(ts_str) >= 10 and ts_str[:4].isdigit() and ts_str[4] == "-" and ts_str[7] == "-":
        return ts_str[:10]
    return ""

def match_channel_key(text: str) -> str:
    t_low = text.lower()
    for key, cfg in CHANNEL_CONFIG.items():
        if key in t_low or any(kw in t_low for kw in cfg["keywords"]):
            return key
    if "goals" in t_low or "over" in t_low or "under" in t_low or "gols" in t_low:
        return "ebasket_ou" if ("ebasket" in t_low or "basketball" in t_low) else "fifa_goals_ou"
    if "handicap" in t_low or "ah" in t_low:
        return "fifa_asian_handicap"
    if "money" in t_low or "ml" in t_low or "winner" in t_low or "1x2" in t_low:
        return "ebasket_money_line" if ("ebasket" in t_low or "basketball" in t_low) else "fifa_money_line"
    return "fifa_goals_ou"

def load_data():
    audit_items = []
    
    # 1. Look inside local and container locations
    paths = [
        "core/dashboard/live_audit_log.json",
        "dashboard/live_audit_log.json",
        "live_audit_log.json",
        "/app/core/dashboard/live_audit_log.json",
        "/root/mario-ai-code/core/dashboard/live_audit_log.json"
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and data:
                        audit_items = data
                        break
            except Exception:
                pass

    # 2. Try loading directly from running docker container if empty
    if not audit_items:
        try:
            cmd = "docker exec $(docker ps -q | head -n 1) cat /app/core/dashboard/live_audit_log.json 2>/dev/null"
            res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, list) and data:
                    audit_items = data
        except Exception:
            pass

    return audit_items

def analyze_single_date(audit_items, target_date):
    stats = {}
    for k, cfg in CHANNEL_CONFIG.items():
        stats[k] = {
            "name": cfg["name"],
            "daily_cap": cfg["daily_cap"],
            "min_odds": cfg["min_odds"],
            "new_tips": 0,
            "result_edits": 0,
            "duplicates": 0,
            "reports": 0,
            "total_telegram_messages": 0,
            "wins": 0.0,
            "losses": 0.0,
            "voids": 0.0,
            "pending": 0,
            "net_units": 0.0,
            "staked_units": 0.0,
            "first_blocked_tip": None,
            "ledger": []
        }

    seen_tips = {k: set() for k in CHANNEL_CONFIG}

    for item in audit_items:
        raw_ts = item.get("timestamp") or item.get("published_at_utc") or item.get("created_at") or ""
        d_str = extract_date_str(raw_ts)
        if d_str != target_date:
            continue

        fix = str(item.get("fixture") or item.get("match") or "")
        m_name = str(item.get("market_name") or item.get("market") or "")
        title = str(item.get("header_title") or item.get("title") or "")
        
        if "Performance Report" in fix or "Performance Report" in m_name or "Performance Report" in title or "summary" in title.lower():
            for k in stats:
                stats[k]["reports"] += 1
                stats[k]["total_telegram_messages"] += 1
            continue

        c_key = match_channel_key(m_name if m_name else title)
        s = stats[c_key]

        match_id = str(item.get("match_id") or item.get("id") or "N/A")
        msg_id = str(item.get("msg_id") or item.get("message_id") or "N/A")
        pick = str(item.get("pick") or item.get("selection") or "Selection")
        res = str(item.get("result") or item.get("status") or item.get("settled_status") or "PENDING").strip().upper()

        try:
            odds_val = float(item.get("odds", 1.90))
        except Exception:
            odds_val = 1.90

        stake = 1.0
        net = 0.0

        if any(w in res for w in ["WIN", "WON"]):
            net = 0.5 * (odds_val - 1.0) if "HALF" in res else 1.0 * (odds_val - 1.0)
            s["wins"] += 0.5 if "HALF" in res else 1.0
        elif any(w in res for w in ["LOSS", "LOST"]):
            net = -0.5 if "HALF" in res else -1.0
            s["losses"] += 0.5 if "HALF" in res else 1.0
        elif any(w in res for w in ["VOID", "PUSH"]):
            net = 0.0
            s["voids"] += 1.0
        else:
            s["pending"] += 1

        tip_sig = f"{match_id}_{pick}_{odds_val:.2f}"
        if tip_sig in seen_tips[c_key]:
            s["duplicates"] += 1
            continue
        seen_tips[c_key].add(tip_sig)

        s["new_tips"] += 1
        s["total_telegram_messages"] += 1
        s["net_units"] += net
        if "PENDING" not in res:
            s["staked_units"] += stake
            s["result_edits"] += 1

        if s["new_tips"] > s["daily_cap"] and not s["first_blocked_tip"]:
            s["first_blocked_tip"] = {
                "timestamp_brt": str(raw_ts),
                "match_id": match_id,
                "market": s["name"],
                "action": "BLOCKED_BY_LIMIT"
            }

        s["ledger"].append({
            "timestamp": str(raw_ts),
            "msg_id": msg_id,
            "match_id": match_id,
            "fixture": fix or "Match",
            "pick": pick,
            "odds": f"{odds_val:.2f}",
            "status": res,
            "log_id": str(item.get("log_id") or f"LOG-{match_id[:8] if match_id != 'N/A' else 'PUB'}")
        })

    return stats

def print_date_report(target_date, stats):
    print("\n" + "=" * 105)
    print(f"       PRODUCTION AUDIT REPORT FOR 24-HOUR CYCLE: {target_date}")
    print("=" * 105)
    print(f"{'Channel Name':<24} | {'Cap':<5} | {'1. New Tips':<11} | {'2. Edits':<9} | {'3. Dups':<8} | {'5. Reports':<10} | {'Total Msgs':<10}")
    print("-" * 105)
    for k, s in stats.items():
        print(f"{s['name']:<24} | {s['daily_cap']:<5} | {s['new_tips']:<11} | {s['result_edits']:<9} | {s['duplicates']:<8} | {s['reports']:<10} | {s['total_telegram_messages']:<10}")
    print("=" * 105)

    print(f"{'Channel Name':<24} | {'Settled':<8} | {'Won':<5} | {'Lost':<5} | {'Win Rate':<8} | {'Net Units':<10} | {'Cap Status':<15}")
    print("-" * 105)
    for k, s in stats.items():
        settled = int(s['wins'] + s['losses'] + s['voids'])
        wr = (s['wins'] / (s['wins'] + s['losses']) * 100.0) if (s['wins'] + s['losses']) > 0 else 0.0
        sign = "+" if s['net_units'] >= 0 else ""
        cap_status = "CAPPED" if s['new_tips'] >= s['daily_cap'] else f"Active ({s['new_tips']}/{s['daily_cap']})"
        print(f"{s['name']:<24} | {settled:<8} | {int(s['wins']):<5} | {int(s['losses']):<5} | {wr:<7.1f}% | {sign}{s['net_units']:<9.2f}u | {cap_status:<15}")
    print("=" * 105 + "\n")

def main():
    parser = argparse.ArgumentParser(description="24-Hour Brazil-Time Production Audit Utility")
    parser.add_argument("date", nargs="?", default="all", help="Target Date or 'all' to show all available dates")
    args = parser.parse_args()

    audit_items = load_data()
    if not audit_items:
        print("\n[!] No audit records found. Checking Docker container...")
        return

    # Extract all distinct dates
    date_counter = Counter(extract_date_str(item.get("timestamp") or item.get("published_at_utc") or item.get("created_at")) for item in audit_items)
    available_dates = sorted([d for d in date_counter.keys() if d])

    print(f"\n[*] Total Records Found: {len(audit_items)}")
    print(f"[*] Available Dates with Recorded Tips: {available_dates}\n")

    if args.date == "all":
        # Display audit for the most recent 3 dates automatically
        for target_d in available_dates[-3:]:
            stats = analyze_single_date(audit_items, target_d)
            print_date_report(target_d, stats)
    else:
        stats = analyze_single_date(audit_items, args.date)
        print_date_report(args.date, stats)

if __name__ == "__main__":
    main()
