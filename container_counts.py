#!/usr/bin/env python3
"""
Container-Only 24-Hour Production Audit Utility (container_counts.py)
=====================================================================
Pulls telemetry and published tips STRICTLY from the active container
(mario_ai_live_publisher) via docker logs and container internal cache.

Outputs the EXACT same 2-table audit format and Markdown ledger as count_logs.py.
Usage:
  python3 container_counts.py auto
  python3 container_counts.py 15
  python3 container_counts.py today
"""

import os
import sys
import json
import re
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
try:
    import zoneinfo
    BRT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")
except Exception:
    BRT_TZ = timezone(timedelta(hours=-3))

UTC_TZ = timezone.utc

CHANNEL_CONFIG = {
    "fifa_goals_ou": {
        "name": "FIFA Goals Over/Under",
        "short_code": "FIFA-GOALS",
        "channel_ids": ["-1004313543662", "fifa_goals_ou", "fifa_goals"],
        "keywords": ["fifa goals", "goals over/under", "over/under", "goals ou", "fifa_goals_ou", "fifa_goals", "gols", "matrix fifa goals"],
        "daily_cap": 150,
        "min_odds": 1.70
    },
    "fifa_asian_handicap": {
        "name": "FIFA Asian Handicap",
        "short_code": "FIFA-AH",
        "channel_ids": ["-1004348571185", "fifa_asian_handicap", "fifa_ah"],
        "keywords": ["fifa asian handicap", "asian handicap", "fifa ah", "asian_handicap", "fifa_asian_handicap", "handicap", "matrix fifa pre ah"],
        "daily_cap": 100,
        "min_odds": 1.70
    },
    "fifa_money_line": {
        "name": "FIFA Money Line",
        "short_code": "FIFA-ML",
        "channel_ids": ["-1003923100342", "fifa_money_line", "fifa_ml"],
        "keywords": ["fifa money line", "fifa ml", "money line", "1x2", "match winner", "fifa_money_line", "fifa_ml", "matrix fifa pre ml"],
        "daily_cap": 150,
        "min_odds": 1.70
    },
    "ebasket_money_line": {
        "name": "eBasket Money Line",
        "short_code": "EBASKET-ML",
        "channel_ids": ["-1004263450744", "ebasket_money_line", "ebasket_ml", "ebasketball_ml"],
        "keywords": ["ebasketball money line", "ebasket ml", "ebasketball ml", "ebasket_money_line", "matrix ebasket pre ml"],
        "daily_cap": 150,
        "min_odds": 1.70
    },
    "ebasket_ou": {
        "name": "eBasket Over/Under",
        "short_code": "EBASKET-OU",
        "channel_ids": ["-1004452838653", "ebasket_ou", "ebasket_over_under", "ebasketball_ou"],
        "keywords": ["ebasketball over/under", "ebasket ou", "ebasketball ou", "ebasket_ou", "pontos", "points", "matrix ebasket pre o/u"],
        "daily_cap": 150,
        "min_odds": 1.70
    }
}

def normalize_target_date(user_input: str, available_dates: set) -> str:
    now_brt = datetime.now(BRT_TZ)
    current_year = now_brt.strftime("%Y")
    current_month = now_brt.strftime("%m")
    
    if not user_input or user_input.lower() in ["auto", "latest"]:
        if available_dates:
            return sorted(list(available_dates), reverse=True)[0]
        return now_brt.strftime("%Y-%m-%d")
        
    if user_input.lower() == "today":
        return now_brt.strftime("%Y-%m-%d")
        
    if user_input.lower() == "yesterday":
        return (now_brt - timedelta(days=1)).strftime("%Y-%m-%d")

    clean_inp = user_input.strip()
    if clean_inp.isdigit() and 1 <= int(clean_inp) <= 31:
        day_str = f"{int(clean_inp):02d}"
        matching = [d for d in available_dates if d.endswith(f"-{day_str}")]
        if matching:
            return sorted(matching, reverse=True)[0]
        return f"{current_year}-{current_month}-{day_str}"

    if re.match(r"^\d{2}-\d{2}$", clean_inp):
        return f"{current_year}-{clean_inp}"

    if re.match(r"^\d{4}-\d{2}-\d{2}$", clean_inp):
        return clean_inp

    return now_brt.strftime("%Y-%m-%d")

def parse_timestamp_to_brt(ts_val) -> datetime:
    if not ts_val:
        return datetime.now(BRT_TZ)
    if isinstance(ts_val, (int, float)):
        return datetime.fromtimestamp(ts_val, tz=UTC_TZ).astimezone(BRT_TZ)
    
    ts_str = str(ts_val).strip()
    if ts_str.endswith("Z"):
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(BRT_TZ)
        except Exception:
            pass
            
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
                dt = dt.replace(tzinfo=UTC_TZ if ("T" in ts_str or "UTC" in ts_str) else BRT_TZ).astimezone(BRT_TZ)
            else:
                dt = dt.astimezone(BRT_TZ)
            return dt
        except Exception:
            continue
            
    return datetime.now(BRT_TZ)

def match_channel_key(text: str) -> str:
    t_low = str(text).lower()
    for key, cfg in CHANNEL_CONFIG.items():
        if any(cid in t_low for cid in cfg.get("channel_ids", [])):
            return key
        if key in t_low or any(kw in t_low for kw in cfg["keywords"]):
            return key
            
    if "goals" in t_low or "over" in t_low or "under" in t_low or "gols" in t_low:
        return "ebasket_ou" if ("ebasket" in t_low or "basketball" in t_low) else "fifa_goals_ou"
    if "handicap" in t_low or "ah" in t_low:
        return "fifa_asian_handicap"
    if "money" in t_low or "ml" in t_low or "winner" in t_low or "1x2" in t_low:
        return "ebasket_money_line" if ("ebasket" in t_low or "basketball" in t_low) else "fifa_money_line"
    return "fifa_goals_ou"

def load_container_only_sources():
    container_items = []
    docker_log_lines = []
    
    # 1. Pull published_tips_cache.json strictly from active container
    try:
        cmd = "docker exec mario_ai_live_publisher cat /app/core/dashboard/published_tips_cache.json 2>/dev/null"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            cache_data = json.loads(res.stdout)
            if isinstance(cache_data, dict):
                for k, v in cache_data.items():
                    if isinstance(v, dict):
                        v["match_id"] = v.get("match_id") or k
                        container_items.append(v)
    except Exception:
        pass

    # 2. Pull live_audit_log.json strictly from active container
    try:
        cmd = "docker exec mario_ai_live_publisher cat /app/core/dashboard/live_audit_log.json 2>/dev/null"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, list):
                container_items.extend(data)
    except Exception:
        pass

    # 3. Pull docker logs strictly from active container
    try:
        cmd = "docker logs mario_ai_live_publisher 2>&1"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, text=True, errors="replace", timeout=10)
        if res.returncode == 0 and res.stdout:
            docker_log_lines = res.stdout.splitlines()
    except Exception:
        pass

    return container_items, docker_log_lines

def analyze_container_cycle(target_date_input: str = "auto"):
    raw_items, docker_lines = load_container_only_sources()
    
    available_dates = set()
    for item in raw_items:
        ts = str(item.get("timestamp") or item.get("published_at_utc") or item.get("published_at") or item.get("created_at") or "")
        if ts:
            dt = parse_timestamp_to_brt(ts)
            available_dates.add(dt.strftime("%Y-%m-%d"))
            
    for line in docker_lines:
        match = re.search(r"\b(202[0-9]-[0-1][0-9]-[0-3][0-9])\b", line)
        if match:
            dt_utc = parse_timestamp_to_brt(match.group(1))
            available_dates.add(dt_utc.strftime("%Y-%m-%d"))
            available_dates.add(match.group(1))

    target_date_str = normalize_target_date(target_date_input, available_dates)
    target_month_str = target_date_str[:7]
    
    stats = {}
    for k, cfg in CHANNEL_CONFIG.items():
        stats[k] = {
            "name": cfg["name"],
            "short_code": cfg["short_code"],
            "daily_cap": cfg["daily_cap"],
            "min_odds": cfg["min_odds"],
            
            "new_tips": 0,
            "result_edits": 0,
            "duplicates_prevented": 0,
            "test_messages": 0,
            "scheduled_reports": 0,
            "other_notifications": 0,
            "total_telegram_messages": 0,
            
            "min_odds_rejected": 0,
            "first_blocked_tip": None,
            
            "wins": 0.0,
            "losses": 0.0,
            "voids": 0.0,
            "half_wins": 0.0,
            "half_losses": 0.0,
            "daily_net_units": 0.0,
            "daily_staked_units": 0.0,
            "pending_count": 0,
            
            "mtd_wins": 0.0,
            "mtd_losses": 0.0,
            "mtd_voids": 0.0,
            "mtd_net_units": 0.0,
            "mtd_staked_units": 0.0,
            
            "ledger": [],
            "pending_examples": [],
            "settled_examples": []
        }

    midnight_resets = []
    settled_from_logs = {}
    
    # Process docker logs
    for line in docker_lines:
        line_low = line.lower()
        has_target_date = (target_date_str in line)
        if not has_target_date:
            ts_m = re.search(r"(202[0-9]-[0-1][0-9]-[0-3][0-9][T\s][0-9:]{5,8})", line)
            if ts_m:
                dt_line = parse_timestamp_to_brt(ts_m.group(1))
                if dt_line.strftime("%Y-%m-%d") == target_date_str:
                    has_target_date = True

        if has_target_date:
            for k, cfg in CHANNEL_CONFIG.items():
                if k in line_low or any(kw in line_low for kw in cfg["keywords"]) or any(cid in line for cid in cfg.get("channel_ids", [])):
                    if "daily limit reached" in line_low or "cap reached" in line_low or "skipping tip due to cap" in line_low:
                        if not stats[k]["first_blocked_tip"]:
                            stats[k]["first_blocked_tip"] = {
                                "timestamp_brt": f"{target_date_str} (From Container Log)",
                                "match_id": "Detected in Live Engine Log",
                                "market": cfg["name"],
                                "raw": line.strip()
                            }
                    if "odds" in line_low and ("below floor" in line_low or "below minimum" in line_low or "rejected" in line_low):
                        stats[k]["min_odds_rejected"] += 1
                    if "duplicate tip" in line_low or "already published" in line_low:
                        stats[k]["duplicates_prevented"] += 1

            if "settled tip:" in line_low or "updated telegram tip" in line_low:
                m_match = re.search(r"match\s+([0-9a-zA-Z_-]+)", line, re.IGNORECASE)
                m_id = m_match.group(1) if m_match else "LOG_MATCH"
                c_key = match_channel_key(line)
                stats[c_key]["result_edits"] += 1
                
                res_type = "PENDING"
                if "won" in line_low or "✅" in line or "win" in line_low:
                    res_type = "HALF_WIN" if "half" in line_low else "WIN"
                elif "lost" in line_low or "❌" in line or "loss" in line_low:
                    res_type = "HALF_LOSS" if "half" in line_low else "LOSS"
                elif "void" in line_low or "push" in line_low:
                    res_type = "VOID"
                    
                if res_type != "PENDING":
                    settled_from_logs[m_id] = {"channel": c_key, "result": res_type}

            if "midnight brt reset" in line_low or "daily counters reset" in line_low:
                midnight_resets.append(line.strip())
                
            if "performance report" in line_low or "report dispatch" in line_low:
                for k in stats:
                    stats[k]["scheduled_reports"] += 1
                    stats[k]["total_telegram_messages"] += 1

    seen_tips = {k: set() for k in CHANNEL_CONFIG}
    
    for item in raw_items:
        raw_ts = item.get("timestamp") or item.get("published_at_utc") or item.get("published_at") or item.get("created_at") or ""
        dt_brt = parse_timestamp_to_brt(raw_ts)
        brt_date = dt_brt.strftime("%Y-%m-%d")
        brt_time_str = dt_brt.strftime("%Y-%m-%d %H:%M:%S BRT")
        
        fix = str(item.get("fixture") or item.get("match") or item.get("home_team", "") + " vs " + item.get("away_team", "") or "Live Match")
        m_name = str(item.get("market_name") or item.get("market") or item.get("header_title") or item.get("title") or item.get("type") or "")
        channel_ref = str(item.get("channel") or item.get("channel_id") or "")
        msg_text = str(item.get("msg_text") or "")
        
        if "Performance Report" in fix or "summary" in m_name.lower():
            if brt_date == target_date_str:
                for k in stats:
                    stats[k]["scheduled_reports"] += 1
                    stats[k]["total_telegram_messages"] += 1
            continue
            
        c_key = match_channel_key(f"{m_name} {channel_ref} {msg_text}")
        s = stats[c_key]
        
        match_id = str(item.get("match_id") or item.get("id") or "N/A")
        msg_id = str(item.get("msg_id") or item.get("message_id") or "N/A")
        pick = str(item.get("pick") or item.get("selection") or item.get("side") or "Selection")
        
        # Determine settled outcome
        if match_id in settled_from_logs:
            res = settled_from_logs[match_id]["result"]
        else:
            res = str(item.get("result") or item.get("status") or "").strip().upper()
            if not res or res in ["PUBLISHED", "PENDING", "ACTIVE"]:
                if "✅" in msg_text or "won" in msg_text.lower():
                    res = "WIN"
                elif "❌" in msg_text or "lost" in msg_text.lower():
                    res = "LOSS"
                elif "void" in msg_text.lower():
                    res = "VOID"
                else:
                    res = "PENDING"

        try:
            odds_val = float(item.get("odds", 1.90))
        except Exception:
            odds_val = 1.90
            
        stake = 1.0
        net = 0.0
        
        if any(w in res for w in ["WIN", "WON"]):
            if "HALF" in res:
                net = 0.5 * (odds_val - 1.0)
                if brt_date == target_date_str:
                    s["half_wins"] += 1
                    s["wins"] += 0.5
            else:
                net = 1.0 * (odds_val - 1.0)
                if brt_date == target_date_str:
                    s["wins"] += 1
        elif any(w in res for w in ["LOSS", "LOST"]):
            if "HALF" in res:
                net = -0.5
                if brt_date == target_date_str:
                    s["half_losses"] += 1
                    s["losses"] += 0.5
            else:
                net = -1.0
                if brt_date == target_date_str:
                    s["losses"] += 1
        elif any(w in res for w in ["VOID", "PUSH"]):
            net = 0.0
            if brt_date == target_date_str:
                s["voids"] += 1
        else:
            if brt_date == target_date_str:
                s["pending_count"] += 1

        if brt_date == target_date_str:
            tip_sig = f"{match_id}_{pick}_{odds_val:.2f}"
            if tip_sig in seen_tips[c_key]:
                s["duplicates_prevented"] += 1
                continue
            seen_tips[c_key].add(tip_sig)
            
            s["new_tips"] += 1
            s["total_telegram_messages"] += 1
            s["daily_net_units"] += net
            
            if "PENDING" not in res:
                s["daily_staked_units"] += stake
                s["result_edits"] += 1
                
            entry = {
                "timestamp_brt": brt_time_str,
                "msg_id": msg_id,
                "match_id": match_id,
                "fixture": fix if fix and fix != "vs" else "Match",
                "market_type": s["name"],
                "pick": pick,
                "odds": f"{odds_val:.2f}",
                "result_status": res,
                "log_id": f"CONT-{match_id[:8]}"
            }
            s["ledger"].append(entry)
            
            if s["new_tips"] > s["daily_cap"] and not s["first_blocked_tip"]:
                s["first_blocked_tip"] = {
                    "timestamp_brt": brt_time_str,
                    "match_id": match_id,
                    "market": s["name"],
                    "action": "BLOCKED_BY_LIMIT"
                }

        if brt_date.startswith(target_month_str) and "PENDING" not in res:
            s["mtd_net_units"] += net
            s["mtd_staked_units"] += stake
            if any(w in res for w in ["WIN", "WON"]):
                s["mtd_wins"] += 0.5 if "HALF" in res else 1.0
            elif any(w in res for w in ["LOSS", "LOST"]):
                s["mtd_losses"] += 0.5 if "HALF" in res else 1.0
            elif any(w in res for w in ["VOID", "PUSH"]):
                s["mtd_voids"] += 1.0

    return {
        "target_date": target_date_str,
        "available_dates": sorted(list(available_dates)),
        "stats": stats,
        "midnight_resets": midnight_resets
    }

def print_audit_terminal(data: dict):
    target_date = data["target_date"]
    stats = data["stats"]
    avail = data.get("available_dates", [])
    
    print("\n" + "=" * 110)
    print(f"       24-HOUR BRAZIL-TIME PRODUCTION AUDIT REPORT ({target_date} 00:00:00 - 23:59:59 BRT)")
    print(f"       [Strictly From Container: mario_ai_live_publisher | Active Dates: {', '.join(avail)}]")
    print("=" * 110)
    print(f"{'Channel Name':<24} | {'Daily Cap':<9} | {'1. New Tips':<11} | {'2. Edits':<10} | {'3. Dups':<8} | {'5. Reports':<10} | {'Total Msgs':<10}")
    print("-" * 110)
    for k, s in stats.items():
        print(f"{s['name']:<24} | {s['daily_cap']:<9} | {s['new_tips']:<11} | {s['result_edits']:<10} | {s['duplicates_prevented']:<8} | {s['scheduled_reports']:<10} | {s['total_telegram_messages']:<10}")
    print("=" * 110 + "\n")

    print("=" * 110)
    print(f"       PERFORMANCE & ODDS FILTER METRICS (24H BRT & MTD: {target_date[:7]})")
    print("=" * 110)
    print(f"{'Channel Name':<24} | {'Min Odds':<8} | {'Odds Rej':<8} | {'Settled':<7} | {'Won':<5} | {'Lost':<5} | {'Win Rate':<8} | {'Daily Units':<11} | {'MTD Units':<10}")
    print("-" * 110)
    for k, s in stats.items():
        settled = int(s['wins'] + s['losses'] + s['voids'])
        wr = (s['wins'] / (s['wins'] + s['losses']) * 100.0) if (s['wins'] + s['losses']) > 0 else 0.0
        sign = "+" if s['daily_net_units'] >= 0 else ""
        mtd_sign = "+" if s['mtd_net_units'] >= 0 else ""
        print(f"{s['name']:<24} | {s['min_odds']:<8.2f} | {s['min_odds_rejected']:<8} | {settled:<7} | {int(s['wins']):<5} | {int(s['losses']):<5} | {wr:<7.1f}% | {sign}{s['daily_net_units']:<10.2f}u | {mtd_sign}{s['mtd_net_units']:<9.2f}u")
    print("=" * 110 + "\n")

def export_markdown_report(data: dict, filename: str = "container_audit_report.md"):
    target_date = data["target_date"]
    stats = data["stats"]
    
    lines = []
    lines.append(f"# Container-Only 24-Hour Production Audit Report (`mario_ai_live_publisher`)")
    lines.append(f"**Audit Period:** `{target_date} 00:00:00 BRT` to `{target_date} 23:59:59 BRT`  ")
    lines.append(f"**Timezone:** `America/Sao_Paulo` (BRT / UTC-3)  \n")
    
    lines.append("## 1. Summary Audit Table\n")
    lines.append("| Channel Name | Configured Daily Cap | 1. Newly Published Tips | 2. In-Place Result Updates | 3. Duplicates Blocked | 4. Test Messages | 5. Scheduled Reports | 6. Other Alerts | 7. Total Telegram Messages |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for k, s in stats.items():
        lines.append(f"| **{s['name']}** | **{s['daily_cap']}** | **{s['new_tips']}** | {s['result_edits']} | {s['duplicates_prevented']} | {s['test_messages']} | {s['scheduled_reports']} | {s['other_notifications']} | **{s['total_telegram_messages']}** |")

    lines.append("\n## 2. Performance Metrics\n")
    lines.append("| Channel Name | Min Odds | Settled Tips | Wins | Losses | Voids | Daily Net Units | Win Rate | Daily ROI | MTD Units |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for k, s in stats.items():
        settled = int(s['wins'] + s['losses'] + s['voids'])
        wr = (s['wins'] / (s['wins'] + s['losses']) * 100.0) if (s['wins'] + s['losses']) > 0 else 0.0
        roi = (s['daily_net_units'] / s['daily_staked_units'] * 100.0) if s['daily_staked_units'] > 0 else 0.0
        sign = "+" if s['daily_net_units'] >= 0 else ""
        mtd_sign = "+" if s['mtd_net_units'] >= 0 else ""
        lines.append(f"| **{s['name']}** | `{s['min_odds']:.2f}` | {settled} | {int(s['wins'])} | {int(s['losses'])} | {int(s['voids'])} | **{sign}{s['daily_net_units']:.2f}u** | **{wr:.1f}%** | **{roi:+.1f}%** | **{mtd_sign}{s['mtd_net_units']:.2f}u** |")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Container Markdown Audit Report written to: {os.path.abspath(filename)}\n")

def main():
    parser = argparse.ArgumentParser(description="Container-Only Production Audit Utility")
    parser.add_argument("date", nargs="?", default="auto", help="Target Date ('15', '2026-09-15', 'auto', 'today')")
    parser.add_argument("--save-md", type=str, default="container_audit_report.md", help="Export Markdown report filename")
    args = parser.parse_args()

    data = analyze_container_cycle(args.date)
    print_audit_terminal(data)
    if args.save_md:
        export_markdown_report(data, args.save_md)

if __name__ == "__main__":
    main()
