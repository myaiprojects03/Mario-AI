#!/usr/bin/env python3
"""
Direct Telegram Live Publisher Audit Utility (count_logs.py)
============================================================
Parses live Docker logs and audit logs to display the exact tips
sent to the Telegram channels in real time.
"""

import os
import sys
import json
import re
import argparse
import subprocess
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import zoneinfo

BRT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")
UTC_TZ = timezone.utc

CHANNEL_CONFIG = {
    "fifa_goals_ou": {
        "name": "FIFA Goals Over/Under",
        "short_code": "FIFA-GOALS",
        "keywords": ["fifa_goals", "goals", "over/under", "gols"],
        "daily_cap": 150
    },
    "fifa_asian_handicap": {
        "name": "FIFA Asian Handicap",
        "short_code": "FIFA-AH",
        "keywords": ["fifa_asian", "asian_handicap", "fifa_ah", "handicap"],
        "daily_cap": 100
    },
    "fifa_money_line": {
        "name": "FIFA Money Line",
        "short_code": "FIFA-ML",
        "keywords": ["fifa_money", "fifa_ml", "money_line", "1x2"],
        "daily_cap": 150
    },
    "ebasket_money_line": {
        "name": "eBasket Money Line",
        "short_code": "EBASKET-ML",
        "keywords": ["ebasket_money", "ebasket_ml", "ebasketball money"],
        "daily_cap": 150
    },
    "ebasket_ou": {
        "name": "eBasket Over/Under",
        "short_code": "EBASKET-OU",
        "keywords": ["ebasket_ou", "ebasketball over", "points", "pontos"],
        "daily_cap": 150
    }
}

def get_docker_logs():
    """Fetches all recent logs from running docker containers."""
    try:
        # Get active container IDs
        res = subprocess.run("docker ps -q", shell=True, stdout=subprocess.PIPE, text=True)
        cids = res.stdout.strip().split()
        all_logs = []
        for cid in cids:
            proc = subprocess.run(f"docker logs {cid} 2>&1", shell=True, stdout=subprocess.PIPE, text=True, errors="replace")
            if proc.stdout:
                all_logs.extend(proc.stdout.splitlines())
        return all_logs
    except Exception as e:
        print(f"Docker read error: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Live Telegram Published Tips Counter")
    parser.add_argument("date", nargs="?", default="auto", help="Date in YYYY-MM-DD or 'auto'")
    args = parser.parse_args()

    lines = get_docker_logs()
    
    # Also check local / container JSON file
    json_items = []
    for path in ["core/dashboard/live_audit_log.json", "/app/core/dashboard/live_audit_log.json"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    json_items = json.load(f)
                    break
            except Exception:
                pass

    now_brt = datetime.now(BRT_TZ)
    target_date = args.date
    if target_date == "auto":
        target_date = now_brt.strftime("%Y-%m-%d")

    channel_tips = defaultdict(list)
    channel_edits = defaultdict(int)
    channel_reports = defaultdict(int)

    # 1. Parse Docker log lines
    for line in lines:
        if target_date not in line:
            continue
        line_low = line.lower()

        # Check for tip dispatch
        if any(w in line_low for w in ["published live tip", "dispatched tip", "published tip", "telegram tip"]):
            for ch_key, cfg in CHANNEL_CONFIG.items():
                if ch_key in line_low or any(kw in line_low for kw in cfg["keywords"]):
                    channel_tips[ch_key].append(line.strip())
                    break
        elif "updated telegram tip" in line_low or "edited tip" in line_low:
            for ch_key, cfg in CHANNEL_CONFIG.items():
                if ch_key in line_low or any(kw in line_low for kw in cfg["keywords"]):
                    channel_edits[ch_key] += 1
                    break
        elif "performance report" in line_low or "report dispatched" in line_low:
            for ch_key in CHANNEL_CONFIG:
                channel_reports[ch_key] += 1

    # 2. Also incorporate JSON items if available
    for item in json_items:
        ts = str(item.get("timestamp") or item.get("created_at") or "")
        if not ts.startswith(target_date):
            continue
        m_name = str(item.get("market_name") or item.get("market") or "").lower()
        title = str(item.get("header_title") or "").lower()
        fix = str(item.get("fixture") or "")

        if "performance report" in m_name or "performance report" in title or "performance report" in fix:
            for ch_key in CHANNEL_CONFIG:
                channel_reports[ch_key] += 1
            continue

        for ch_key, cfg in CHANNEL_CONFIG.items():
            if ch_key in m_name or any(kw in m_name for kw in cfg["keywords"]) or any(kw in title for kw in cfg["keywords"]):
                msg_id = item.get("msg_id") or "N/A"
                tip_desc = f"{ts} | Match: {fix} | Pick: {item.get('pick')} @ {item.get('odds')} | TG Msg ID: {msg_id}"
                channel_tips[ch_key].append(tip_desc)
                if item.get("result") in ["WIN", "LOSS", "VOID", "WON", "LOST"]:
                    channel_edits[ch_key] += 1
                break

    # Deduplicate entries per channel
    deduped_tips = {}
    for ch_key in CHANNEL_CONFIG:
        deduped_tips[ch_key] = list(dict.fromkeys(channel_tips[ch_key]))

    print("\n" + "=" * 95)
    print(f"       LIVE TELEGRAM CHANNELS PUBLISHED TIPS AUDIT ({target_date})")
    print("=" * 95)
    print(f"{'Channel Name':<24} | {'Daily Cap':<9} | {'1. New Tips':<11} | {'2. Edits':<9} | {'5. Reports':<10} | {'Total Msgs':<10}")
    print("-" * 95)
    
    for ch_key, cfg in CHANNEL_CONFIG.items():
        new_cnt = len(deduped_tips[ch_key])
        edits_cnt = channel_edits[ch_key]
        rpts_cnt = channel_reports[ch_key]
        total_msgs = new_cnt + rpts_cnt
        print(f"{cfg['name']:<24} | {cfg['daily_cap']:<9} | {new_cnt:<11} | {edits_cnt:<9} | {rpts_cnt:<10} | {total_msgs:<10}")
    print("=" * 95 + "\n")

    # Display recent live tip examples
    print("=" * 95)
    print("       RECENT TELEGRAM DISPATCHES PER CHANNEL")
    print("=" * 95)
    for ch_key, cfg in CHANNEL_CONFIG.items():
        tips = deduped_tips[ch_key]
        print(f"\n[+] Channel: {cfg['name']} (Total Dispatched Today: {len(tips)})")
        if not tips:
            print("    * No tips dispatched yet for this date *")
        else:
            for t in tips[-5:]:
                print(f"    • {t}")
    print("\n" + "=" * 95 + "\n")

if __name__ == "__main__":
    main()
