#!/usr/bin/env python3
"""
Get Today's FIFA Tip Counts (get_today_fifa_counts.py)
======================================================
Prints the total number of tips generated and published today (Brazil Time)
for each of the three FIFA groups, checking both PostgreSQL and the disk ledger.
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta

BRT_TZ = timezone(timedelta(hours=-3))

FIFA_GROUPS = {
    "fifa_goals_ou": {
        "title": "FIFA Goals O/U",
        "aliases": ["fifa_goals_ou", "fifa_ou", "fifa_goals", "goals_ou"],
        "cap": 150
    },
    "fifa_asian_handicap": {
        "title": "FIFA Asian Handicap",
        "aliases": ["fifa_asian_handicap", "fifa_ah", "asian_handicap"],
        "cap": 100
    },
    "fifa_money_line": {
        "title": "FIFA Money Line",
        "aliases": ["fifa_money_line", "fifa_ml", "money_line"],
        "cap": 150
    }
}


def query_postgres(sql: str):
    cmd = ["docker", "exec", "mario_ai_db", "psql", "-U", "postgres", "-d", "mario_ai", "-t", "-A", "-F", ",", "-c", sql]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
    except Exception:
        pass
    return []


def load_json(filepath: str, default=None):
    candidates = [
        filepath,
        os.path.join(os.path.dirname(__file__), filepath),
        os.path.join("/root/mario-ai-code", filepath)
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return default or {}


def main():
    now_brt = datetime.now(BRT_TZ)
    today_str = now_brt.strftime("%Y-%m-%d")

    # 1. Query PostgreSQL core.daily_tip_ledger for today
    sql_ledger = f"""
    SELECT channel_key, match_id 
    FROM core.daily_tip_ledger 
    WHERE date_brt = '{today_str}';
    """
    pg_ledger_rows = query_postgres(sql_ledger)

    # 2. Query PostgreSQL core.settled_tips for today
    sql_settled = f"""
    SELECT channel_key, match_id 
    FROM core.settled_tips 
    WHERE date_brt = '{today_str}';
    """
    pg_settled_rows = query_postgres(sql_settled)

    # 3. Load daily_tip_ledger.json
    daily_json = load_json("core/dashboard/daily_tip_ledger.json", {})
    today_json = daily_json.get(today_str, {})

    # 4. Load published_tips_cache.json
    cache_json = load_json("core/dashboard/published_tips_cache.json", {})

    print("=" * 65)
    print(f"       TODAY'S PUBLISHED FIFA TIPS ({today_str} BRT)")
    print("=" * 65)
    print(f"Current Server Time: {now_brt.strftime('%Y-%m-%d %H:%M:%S BRT')}")
    print("-" * 65)

    for ch_k, meta in FIFA_GROUPS.items():
        aliases = set(meta["aliases"])
        seen_matches = set()

        # From Postgres daily ledger
        for line in pg_ledger_rows:
            parts = line.split(",")
            if len(parts) >= 2 and parts[0].strip() in aliases:
                seen_matches.add(parts[1].strip())

        # From Postgres settled
        for line in pg_settled_rows:
            parts = line.split(",")
            if len(parts) >= 2 and parts[0].strip() in aliases:
                seen_matches.add(parts[1].strip())

        # From JSON daily ledger
        for alias in aliases:
            for m in today_json.get(alias, []):
                seen_matches.add(str(m))

        # From active published cache
        if isinstance(cache_json, dict):
            for k, it in cache_json.items():
                if isinstance(it, dict):
                    t = str(it.get("type", "")).lower()
                    if t in aliases:
                        pub_utc = str(it.get("published_at_utc", ""))
                        if pub_utc:
                            try:
                                dt = datetime.fromisoformat(pub_utc.replace("Z", "+00:00")).astimezone(BRT_TZ)
                                if dt.strftime("%Y-%m-%d") == today_str:
                                    seen_matches.add(str(it.get("match_id") or k))
                            except Exception:
                                pass

        count = len(seen_matches)
        cap = meta["cap"]
        print(f"{meta['title']:<24}: {count} tips (Daily Cap: {cap})")

    print("=" * 65)


if __name__ == "__main__":
    main()
