#!/usr/bin/env python3
"""
Container-Only Tips Counter (container_counts.py)
=================================================
Parses stdout/stderr logs and internal cache ONLY from the active
Docker container (mario_ai_live_publisher).

Displays exact counts per channel, broken down by date (BRT timezone).
Usage:
  python3 container_counts.py        (Shows all active dates)
  python3 container_counts.py 15     (Filters to the 15th)
  python3 container_counts.py today  (Filters to today)
"""

import sys
import re
import json
import subprocess
from datetime import datetime, timezone, timedelta
try:
    import zoneinfo
    BRT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")
except Exception:
    BRT_TZ = timezone(timedelta(hours=-3))

UTC_TZ = timezone.utc

CHANNELS = {
    "fifa_goals_ou": {
        "name": "FIFA Goals O/U",
        "cap": 150,
        "ids": ["-1004313543662", "fifa_goals_ou", "fifa_goals"]
    },
    "fifa_asian_handicap": {
        "name": "FIFA Asian Hand.",
        "cap": 100,
        "ids": ["-1004348571185", "fifa_asian_handicap", "fifa_ah"]
    },
    "fifa_money_line": {
        "name": "FIFA Money Line",
        "cap": 150,
        "ids": ["-1003923100342", "fifa_money_line", "fifa_ml"]
    },
    "ebasket_money_line": {
        "name": "eBasket Money Line",
        "cap": 150,
        "ids": ["-1004263450744", "ebasket_money_line", "ebasket_ml"]
    },
    "ebasket_ou": {
        "name": "eBasket Over/Under",
        "cap": 150,
        "ids": ["-1004452838653", "ebasket_ou", "ebasket_over_under"]
    }
}

def parse_ts_to_brt(ts_str):
    if not ts_str:
        return None
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d"
    ]:
        try:
            dt = datetime.strptime(ts_str[:26], fmt[:len(ts_str[:26])])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC_TZ).astimezone(BRT_TZ)
            else:
                dt = dt.astimezone(BRT_TZ)
            return dt
        except Exception:
            continue
    return None

def match_channel(text):
    t_low = str(text).lower()
    for k, cfg in CHANNELS.items():
        if any(cid in t_low for cid in cfg["ids"]):
            return k
        if k in t_low:
            return k
    if "asian" in t_low or "handicap" in t_low:
        return "fifa_asian_handicap"
    if "money" in t_low or "ml" in t_low:
        return "ebasket_money_line" if "basket" in t_low else "fifa_money_line"
    if "goal" in t_low or "over" in t_low or "under" in t_low:
        return "ebasket_ou" if "basket" in t_low else "fifa_goals_ou"
    return None

def collect_container_tips():
    tips = []
    seen_sigs = set()

    # 1. Pull internal container cache
    try:
        cmd = "docker exec mario_ai_live_publisher cat /app/core/dashboard/published_tips_cache.json 2>/dev/null"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            cache_data = json.loads(res.stdout)
            if isinstance(cache_data, dict):
                for k, info in cache_data.items():
                    if not isinstance(info, dict):
                        continue
                    ts = info.get("published_at_utc") or info.get("published_at") or info.get("timestamp")
                    dt_brt = parse_ts_to_brt(ts)
                    date_str = dt_brt.strftime("%Y-%m-%d") if dt_brt else "Unknown"
                    ch_ref = info.get("channel") or info.get("channel_id") or info.get("type") or ""
                    c_key = match_channel(ch_ref)
                    if c_key:
                        sig = f"{date_str}_{c_key}_{info.get('match_id')}_{info.get('msg_id')}"
                        if sig not in seen_sigs:
                            seen_sigs.add(sig)
                            tips.append((date_str, c_key, info.get("match_id", "CACHE")))
    except Exception:
        pass

    # 2. Pull container stdout/stderr logs
    try:
        cmd = "docker logs mario_ai_live_publisher 2>&1"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True, errors="replace", timeout=10)
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                line_low = line.lower()
                if "published live tip" in line_low or "published tip for" in line_low or "successfully dispatched tip" in line_low:
                    ts_m = re.search(r"(202[0-9]-[0-1][0-9]-[0-3][0-9][T\s][0-9:]{5,8})", line)
                    if ts_m:
                        dt_brt = parse_ts_to_brt(ts_m.group(1))
                        date_str = dt_brt.strftime("%Y-%m-%d") if dt_brt else ts_m.group(1)[:10]
                    else:
                        date_str = datetime.now(BRT_TZ).strftime("%Y-%m-%d")
                    
                    c_key = match_channel(line)
                    if c_key:
                        m_m = re.search(r"(?:match\s+|ev)([0-9a-zA-Z_-]+)", line, re.IGNORECASE)
                        m_id = m_m.group(1) if m_m else line[-15:]
                        sig = f"{date_str}_{c_key}_{m_id}"
                        if sig not in seen_sigs:
                            seen_sigs.add(sig)
                            tips.append((date_str, c_key, m_id))
    except Exception:
        pass

    return tips

def main():
    target_filter = sys.argv[1].strip() if len(sys.argv) > 1 else None
    tips = collect_container_tips()
    
    dates_grouped = {}
    for d, ch, m_id in tips:
        if d not in dates_grouped:
            dates_grouped[d] = {k: 0 for k in CHANNELS}
        dates_grouped[d][ch] += 1

    sorted_dates = sorted(dates_grouped.keys())

    if target_filter:
        clean_f = target_filter.lower()
        if clean_f.isdigit():
            day_fmt = f"-{int(clean_f):02d}"
            sorted_dates = [d for d in sorted_dates if d.endswith(day_fmt)]
        elif clean_f == "today":
            now_str = datetime.now(BRT_TZ).strftime("%Y-%m-%d")
            sorted_dates = [d for d in sorted_dates if d == now_str]
        else:
            sorted_dates = [d for d in sorted_dates if clean_f in d.lower()]

    print("\n" + "=" * 105)
    print("      TIPS GENERATED STRICTLY BY CONTAINER: mario_ai_live_publisher")
    print("      (Timezone: America/Sao_Paulo BRT 00:00:00 - 23:59:59)")
    print("=" * 105)
    print(f"{'Date (BRT)':<12} | {'FIFA Goals':<15} | {'FIFA Asian Hand.':<18} | {'FIFA Money Line':<16} | {'eBasket ML':<12} | {'eBasket O/U':<12} | {'Total':<8}")
    print(f"{'':<12} | {'(Cap: 150)':<15} | {'(Cap: 100)':<18} | {'(Cap: 150)':<16} | {'(Cap: 150)':<12} | {'(Cap: 150)':<12} | {'':<8}")
    print("-" * 105)

    if not sorted_dates:
        print("  No tips found for the specified date filter in this container's logs/cache.")
    else:
        for d in sorted_dates:
            c = dates_grouped[d]
            tot = sum(c.values())
            
            ah_str = f"{c['fifa_asian_handicap']}" + (" [CAP]" if c['fifa_asian_handicap'] >= 100 else "")
            goals_str = f"{c['fifa_goals_ou']}" + (" [CAP]" if c['fifa_goals_ou'] >= 150 else "")
            ml_str = f"{c['fifa_money_line']}" + (" [CAP]" if c['fifa_money_line'] >= 150 else "")

            print(f"{d:<12} | {goals_str:<15} | {ah_str:<18} | {ml_str:<16} | {c['ebasket_money_line']:<12} | {c['ebasket_ou']:<12} | {tot:<8}")

    print("=" * 105 + "\n")

if __name__ == "__main__":
    main()
