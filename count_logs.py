#!/usr/bin/env python3
"""
Production Brazil-Time Live Span Audit Utility (count_logs.py)
==============================================================
Calculates live counts from when the day/counter starts (00:00:00 BRT)
up to the exact second this file is executed.

Pulls live audit data dynamically from:
1. Active Docker Container Cache (/app/core/dashboard/published_tips_cache.json)
2. Active Docker Container Audit Log (/app/core/dashboard/live_audit_log.json)
3. Live Docker stdout/stderr logs (docker logs mario_ai_live_publisher)
4. PostgreSQL database (mario_ai_db)
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
        "%Y-%m-%d %H:%M",
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

def load_data_from_all_sources():
    audit_items = []
    cache_dict = {}
    report_cache = {}
    docker_log_lines = []
    
    # 1. Pull published_tips_cache.json from running Docker container
    try:
        cmd = "docker exec mario_ai_live_publisher cat /app/core/dashboard/published_tips_cache.json 2>/dev/null"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                cache_dict.update(data)
    except Exception:
        pass

    # Fallback to local files
    if not cache_dict:
        for p in [
            "core/dashboard/published_tips_cache.json",
            "/root/mario-ai-code/core/dashboard/published_tips_cache.json",
            "published_tips_cache.json"
        ]:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            cache_dict.update(data)
                            break
                except Exception:
                    pass

    # 2. Pull live_audit_log.json from running Docker container
    try:
        cmd = "docker exec mario_ai_live_publisher cat /app/core/dashboard/live_audit_log.json 2>/dev/null"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, list):
                audit_items.extend(data)
    except Exception:
        pass

    # Fallback to local live_audit_log.json
    for p in [
        "core/dashboard/live_audit_log.json",
        "/root/mario-ai-code/core/dashboard/live_audit_log.json",
        "live_audit_log.json"
    ]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        audit_items.extend(data)
                        break
            except Exception:
                pass

    seen_ids = {str(item.get("match_id") or item.get("id")) for item in audit_items}
    for m_id, tip_data in cache_dict.items():
        if isinstance(tip_data, dict):
            if str(m_id) not in seen_ids:
                tip_data["match_id"] = tip_data.get("match_id") or m_id
                audit_items.append(tip_data)
                seen_ids.add(str(m_id))

    # 3. Pull Docker stdout logs directly
    try:
        cmd = "docker logs mario_ai_live_publisher 2>&1"
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", timeout=10)
        if res.returncode == 0 and res.stdout:
            docker_log_lines = res.stdout.splitlines()
    except Exception:
        pass

    return audit_items, cache_dict, report_cache, docker_log_lines

def analyze_span(target_date_input: str = "today"):
    execution_time_brt = datetime.now(BRT_TZ)
    today_str = execution_time_brt.strftime("%Y-%m-%d")

    audit_items, cache_dict, report_cache, docker_lines = load_data_from_all_sources()

    # Discover available dates
    available_dates = set()
    for item in audit_items:
        ts = str(item.get("timestamp") or item.get("published_at_utc") or item.get("created_at") or "")
        if ts:
            available_dates.add(parse_timestamp_to_brt(ts).strftime("%Y-%m-%d"))
    for line in docker_lines:
        match = re.search(r"\b(202[0-9]-[0-1][0-9]-[0-3][0-9])\b", line)
        if match:
            available_dates.add(match.group(1))

    # Resolve Target Date
    if not target_date_input or target_date_input.lower() in ["today", "auto", "latest"]:
        target_date_str = today_str
    elif target_date_input.isdigit() and 1 <= int(target_date_input) <= 31:
        target_date_str = f"{execution_time_brt.strftime('%Y-%m')}-{int(target_date_input):02d}"
    else:
        target_date_str = target_date_input

    # Set the Timer from when the day starts to execution
    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").replace(tzinfo=BRT_TZ)
    span_start_brt = target_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    if target_date_str == today_str:
        span_end_brt = execution_time_brt
    else:
        span_end_brt = target_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

    elapsed_delta = span_end_brt - span_start_brt
    total_sec = int(elapsed_delta.total_seconds())
    hours, remainder = divmod(total_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    elapsed_str = f"{hours}h {minutes:02d}m {seconds:02d}s"

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
            "daily_net_units": 0.0,
            "daily_staked_units": 0.0,
            "pending_count": 0,
            "mtd_wins": 0.0,
            "mtd_losses": 0.0,
            "mtd_voids": 0.0,
            "mtd_net_units": 0.0,
            "mtd_staked_units": 0.0,
            "ledger": []
        }

    # Extract Settled Outcomes from live Docker logs within span
    settled_from_logs = {}
    for line in docker_lines:
        line_low = line.lower()
        ts_m = re.search(r"(202[0-9]-[0-1][0-9]-[0-3][0-9][T\s][0-9:]{5,8})", line)
        dt_line = parse_timestamp_to_brt(ts_m.group(1)) if ts_m else None
        
        in_span = (span_start_brt <= dt_line <= span_end_brt) if dt_line else (target_date_str in line)

        if in_span:
            for k, cfg in CHANNEL_CONFIG.items():
                if k in line_low or any(kw in line_low for kw in cfg["keywords"]) or any(cid in line for cid in cfg.get("channel_ids", [])):
                    if "daily limit reached" in line_low or "cap reached" in line_low:
                        if not stats[k]["first_blocked_tip"]:
                            stats[k]["first_blocked_tip"] = {
                                "timestamp_brt": dt_line.strftime("%Y-%m-%d %H:%M:%S BRT") if dt_line else span_start_brt.strftime("%Y-%m-%d %H:%M:%S BRT"),
                                "match_id": "Engine Limit Cap",
                                "market": cfg["name"]
                            }
                    if "odds" in line_low and ("below floor" in line_low or "rejected" in line_low or "skipping tip" in line_low):
                        stats[k]["min_odds_rejected"] += 1
                    if "duplicate" in line_low:
                        stats[k]["duplicates_prevented"] += 1

            if "settled tip:" in line_low or "updated telegram tip" in line_low:
                m_match = re.search(r"match\s+([0-9a-zA-Z_-]+)", line, re.IGNORECASE)
                m_id = m_match.group(1) if m_match else "MATCH"
                c_key = match_channel_key(line)
                stats[c_key]["result_edits"] += 1

                res_type = "PENDING"
                if "won" in line_low or "✅" in line or "win" in line_low:
                    res_type = "WIN"
                elif "lost" in line_low or "❌" in line or "loss" in line_low:
                    res_type = "LOSS"
                elif "void" in line_low:
                    res_type = "VOID"

                if res_type != "PENDING":
                    settled_from_logs[m_id] = {"channel": c_key, "result": res_type}

    # Merge settled results into audit items
    for item in audit_items:
        m_id = str(item.get("match_id") or item.get("id") or "")
        if m_id in settled_from_logs:
            item["result"] = settled_from_logs[m_id]["result"]

    seen_tips = {k: set() for k in CHANNEL_CONFIG}

    for item in audit_items:
        raw_ts = item.get("timestamp") or item.get("published_at_utc") or item.get("created_at") or ""
        dt_brt = parse_timestamp_to_brt(raw_ts)

        # Strictly filter by the live timer span
        if not (span_start_brt <= dt_brt <= span_end_brt):
            # Still record MTD stats if in the same month
            if dt_brt.strftime("%Y-%m") == target_date_str[:7]:
                res = str(item.get("result") or "").upper()
                c_key = match_channel_key(f"{item.get('market_name', '')} {item.get('channel_id', '')}")
                odds_val = float(item.get("odds", 1.90))
                if "WIN" in res:
                    stats[c_key]["mtd_wins"] += 1
                    stats[c_key]["mtd_net_units"] += (odds_val - 1.0)
                elif "LOSS" in res:
                    stats[c_key]["mtd_losses"] += 1
                    stats[c_key]["mtd_net_units"] -= 1.0
            continue

        c_key = match_channel_key(f"{item.get('market_name', '')} {item.get('channel_id', '')} {item.get('msg_text', '')}")
        s = stats[c_key]

        match_id = str(item.get("match_id") or item.get("id") or "N/A")
        msg_id = str(item.get("msg_id") or item.get("message_id") or "N/A")
        pick = str(item.get("pick") or item.get("selection") or item.get("side") or "Selection")
        fix = str(item.get("fixture") or item.get("match") or "Live Match")
        msg_text = str(item.get("msg_text") or "")

        res = str(item.get("result") or "").strip().upper()
        if not res or res in ["PUBLISHED", "PENDING"]:
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

        net = 0.0
        if "WIN" in res:
            net = (odds_val - 1.0)
            s["wins"] += 1
        elif "LOSS" in res:
            net = -1.0
            s["losses"] += 1
        elif "VOID" in res:
            s["voids"] += 1
        else:
            s["pending_count"] += 1

        tip_sig = f"{match_id}_{pick}_{odds_val:.2f}"
        if tip_sig in seen_tips[c_key]:
            s["duplicates_prevented"] += 1
            continue
        seen_tips[c_key].add(tip_sig)

        s["new_tips"] += 1
        s["total_telegram_messages"] += 1
        s["daily_net_units"] += net
        if res != "PENDING":
            s["daily_staked_units"] += 1.0
            s["result_edits"] += 1

        entry = {
            "timestamp_brt": dt_brt.strftime("%Y-%m-%d %H:%M:%S BRT"),
            "msg_id": msg_id,
            "match_id": match_id,
            "fixture": fix if fix and fix != "vs" else "Match",
            "market_type": s["name"],
            "pick": pick,
            "odds": f"{odds_val:.2f}",
            "result_status": res,
            "log_id": str(item.get("log_id") or f"LOG-{match_id[:8]}")
        }
        s["ledger"].append(entry)

        if s["new_tips"] > s["daily_cap"] and not s["first_blocked_tip"]:
            s["first_blocked_tip"] = {
                "timestamp_brt": dt_brt.strftime("%Y-%m-%d %H:%M:%S BRT"),
                "match_id": match_id,
                "market": s["name"]
            }

    return {
        "target_date": target_date_str,
        "span_start": span_start_brt.strftime("%Y-%m-%d %H:%M:%S BRT"),
        "span_end": span_end_brt.strftime("%Y-%m-%d %H:%M:%S BRT"),
        "elapsed_str": elapsed_str,
        "available_dates": sorted(list(available_dates)),
        "stats": stats
    }

def print_audit_terminal(data: dict):
    stats = data["stats"]
    print("\n" + "=" * 110)
    print(f"       BRAZIL-TIME PRODUCTION AUDIT REPORT (LIVE TIMER SPAN)")
    print(f"       Day Start: {data['span_start']}  -->  Executed At: {data['span_end']}")
    print(f"       Total Elapsed Time: {data['elapsed_str']}")
    print("=" * 110)
    print(f"{'Channel Name':<24} | {'Daily Cap':<9} | {'1. New Tips':<11} | {'2. Edits':<10} | {'3. Dups':<8} | {'5. Reports':<10} | {'Total Msgs':<10}")
    print("-" * 110)
    for k, s in stats.items():
        print(f"{s['name']:<24} | {s['daily_cap']:<9} | {s['new_tips']:<11} | {s['result_edits']:<10} | {s['duplicates_prevented']:<8} | {s['scheduled_reports']:<10} | {s['total_telegram_messages']:<10}")
    print("=" * 110 + "\n")

    print("=" * 110)
    print(f"       PERFORMANCE & ODDS FILTER METRICS (SPAN: {data['elapsed_str']})")
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

def export_markdown_report(data: dict, filename: str = "production_audit_report.md"):
    stats = data["stats"]
    lines = []
    lines.append(f"# Production Brazil-Time Channel Audit Report")
    lines.append(f"**Counter/Day Start:** `{data['span_start']}`  ")
    lines.append(f"**Executed At:** `{data['span_end']}`  ")
    lines.append(f"**Elapsed Duration (Timer):** `{data['elapsed_str']}`  ")
    lines.append(f"**Timezone:** `America/Sao_Paulo` (BRT / UTC-3)  \n")
    
    lines.append("## 1. Summary Audit Table (Separating Message Types)\n")
    lines.append("| Channel Name | Configured Daily Cap | 1. Newly Published Tips | 2. In-Place Result Updates (Edits) | 3. Duplicates Blocked | 4. Test Messages | 5. Scheduled Reports | 6. Other Alerts | 7. Total Telegram Messages |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for k, s in stats.items():
        lines.append(f"| **{s['name']}** | **{s['daily_cap']}** | **{s['new_tips']}** | {s['result_edits']} | {s['duplicates_prevented']} | {s['test_messages']} | {s['scheduled_reports']} | {s['other_notifications']} | **{s['total_telegram_messages']}** |")
    lines.append("\n*Note: Result updates are in-place Telegram message edits using `editMessageText` and do not count toward new channel message quotas.*\n")

    lines.append("## 2. Limit Enforcement Status\n")
    lines.append("| Channel | Daily Cap | Published Tips | Status | First Blocked Tip After Limit Reached |")
    lines.append("| :--- | :---: | :---: | :---: | :--- |")
    for k, s in stats.items():
        status_str = "CAPPED (100% Reached)" if s['new_tips'] >= s['daily_cap'] else f"Active ({s['new_tips']}/{s['daily_cap']})"
        blocked = f"`{s['first_blocked_tip']['timestamp_brt']}` -> **BLOCKED**" if s['first_blocked_tip'] else "No tips exceeded cap"
        lines.append(f"| **{s['name']}** | {s['daily_cap']} | {s['new_tips']} | `{status_str}` | {blocked} |")

    lines.append("\n## 3. Minimum-Odds Rejection & Channel Performance Metrics\n")
    lines.append("| Channel Name | Min Odds | Rejected Candidate Tips | Settled Tips | Wins | Losses | Voids | Daily Net Units | Win Rate | Daily ROI | MTD Units |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for k, s in stats.items():
        settled = int(s['wins'] + s['losses'] + s['voids'])
        wr = (s['wins'] / (s['wins'] + s['losses']) * 100.0) if (s['wins'] + s['losses']) > 0 else 0.0
        roi = (s['daily_net_units'] / s['daily_staked_units'] * 100.0) if s['daily_staked_units'] > 0 else 0.0
        sign = "+" if s['daily_net_units'] >= 0 else ""
        mtd_sign = "+" if s['mtd_net_units'] >= 0 else ""
        lines.append(f"| **{s['name']}** | `{s['min_odds']:.2f}` | {s['min_odds_rejected']} | {settled} | {int(s['wins'])} | {int(s['losses'])} | {int(s['voids'])} | **{sign}{s['daily_net_units']:.2f}u** | **{wr:.1f}%** | **{roi:+.1f}%** | **{mtd_sign}{s['mtd_net_units']:.2f}u** |")

    lines.append("\n## 4. Message-by-Message Verification Ledger (Per Channel)\n")
    for k, s in stats.items():
        lines.append(f"### Channel: {s['name']} (Total Tips: {s['new_tips']})")
        if not s["ledger"]:
            lines.append("*No tips published for this channel during this span.*\n")
            continue
        lines.append("| Timestamp (BRT) | TG Msg ID | Match ID | Fixture / Players | Pick | Odds | Status | Log ID |")
        lines.append("| :--- | :---: | :---: | :--- | :--- | :---: | :---: | :---: |")
        for e in s["ledger"]:
            lines.append(f"| {e['timestamp_brt']} | `{e['msg_id']}` | `{e['match_id']}` | {e['fixture']} | **{e['pick']}** | `{e['odds']}` | `{e['result_status']}` | `{e['log_id']}` |")
        lines.append("")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Full Markdown Audit Report written to: {os.path.abspath(filename)}\n")

def main():
    parser = argparse.ArgumentParser(description="Brazil-Time Production Audit Utility with Live Execution Timer")
    parser.add_argument("date", nargs="?", default="today", help="Target Date ('today', '16', '2026-09-16')")
    parser.add_argument("--save-md", type=str, default="production_audit_report.md", help="Export Markdown report filename")
    args = parser.parse_args()

    data = analyze_span(args.date)
    print_audit_terminal(data)
    if args.save_md:
        export_markdown_report(data, args.save_md)

if __name__ == "__main__":
    main()
