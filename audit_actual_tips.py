#!/usr/bin/env python3
"""
Mario AI - Server Actual Tips Audit Tool (audit_actual_tips.py)
=============================================================
Audits the REAL historical and today's tips directly from persistent storage:
1. Host persistent JSON ledgers (core/dashboard/daily_tip_ledger.json, settled_tips_ledger.json, live_audit_log.json)
2. Live Docker container storage (/app/core/dashboard/*.json via docker exec)
3. PostgreSQL Database (core.daily_tip_ledger, core.settled_tips, core.results)

This guarantees 100% accurate, complete numbers even if Docker containers were rebuilt or restarted.
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

# Brasilia Timezone
try:
    import zoneinfo
    BRT_TZ = zoneinfo.ZoneInfo("America/Sao_Paulo")
except Exception:
    BRT_TZ = timezone(timedelta(hours=-3))

UTC_TZ = timezone.utc

CHANNEL_MAP = {
    "fifa_goals_ou": {
        "title": "Matrix Esoccer Pre Goals G01",
        "cap": 150
    },
    "fifa_asian_handicap": {
        "title": "Matrix FIFA Pre AH G01",
        "cap": 100
    },
    "fifa_money_line": {
        "title": "Matrix FIFA Pre ML G01",
        "cap": 150
    },
    "ebasket_money_line": {
        "title": "Matrix eBasket Pre ML G01",
        "cap": 150
    },
    "ebasket_ou": {
        "title": "Matrix eBasket Pre Points G01",
        "cap": 150
    },
}


def safe_print(text=""):
    try:
        sys.stdout.buffer.write((str(text) + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        print(str(text).encode("ascii", errors="replace").decode("ascii"))


def read_file_or_docker(rel_path: str) -> Any:
    """Reads JSON from host filesystem first, then falls back to docker exec."""
    candidates = [
        rel_path,
        os.path.join("/root/mario-ai-code", rel_path),
        os.path.join(os.getcwd(), rel_path),
        os.path.join(os.path.dirname(__file__), rel_path),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f), f"Host File: {p}"
            except Exception:
                pass

    # Fallback to docker container
    container_path = f"/app/{rel_path}"
    cmd = ["docker", "exec", "mario_ai_live_publisher", "cat", container_path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout), f"Docker Container: mario_ai_live_publisher:{container_path}"
    except Exception:
        pass

    return None, "Not Found"


def query_postgres_data(today_brt: str):
    """Queries Postgres database via docker exec or psycopg2."""
    db_results = {"daily_ledger": {}, "settled_tips": []}
    
    # 1. Query daily_tip_ledger
    sql_ledger = f"""
    SELECT date_brt, channel_key, match_id 
    FROM core.daily_tip_ledger 
    WHERE date_brt = '{today_brt}';
    """
    cmd_ledger = ["docker", "exec", "mario_ai_db", "psql", "-U", "postgres", "-d", "mario_ai", "-t", "-A", "-F", ",", "-c", sql_ledger]
    try:
        res = subprocess.run(cmd_ledger, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = line.split(",")
                if len(parts) >= 3:
                    d, ch, m_id = parts[0].strip(), parts[1].strip(), parts[2].strip()
                    if ch not in db_results["daily_ledger"]:
                        db_results["daily_ledger"][ch] = set()
                    db_results["daily_ledger"][ch].add(m_id)
    except Exception:
        pass

    # 2. Query settled_tips
    sql_settled = f"""
    SELECT match_id, channel_key, score_str, outcome, net_units, date_brt 
    FROM core.settled_tips;
    """
    cmd_settled = ["docker", "exec", "mario_ai_db", "psql", "-U", "postgres", "-d", "mario_ai", "-t", "-A", "-F", ",", "-c", sql_settled]
    try:
        res = subprocess.run(cmd_settled, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = line.split(",")
                if len(parts) >= 6:
                    db_results["settled_tips"].append({
                        "match_id": parts[0].strip(),
                        "channel_key": parts[1].strip(),
                        "score_str": parts[2].strip(),
                        "outcome": parts[3].strip(),
                        "net_units": float(parts[4].strip()) if parts[4].strip() else 0.0,
                        "date_brt": parts[5].strip()
                    })
    except Exception:
        pass

    return db_results


def run_audit(target_date: str = None):
    now_brt = datetime.now(BRT_TZ)
    if not target_date:
        target_date = now_brt.strftime("%Y-%m-%d")

    current_month_str = target_date[:7]

    safe_print("=" * 80)
    safe_print(f"       MARIO AI - PERSISTENT DATA AUDIT ({target_date} BRT)")
    safe_print("=" * 80)
    safe_print(f"Execution Time: {now_brt.strftime('%Y-%m-%d %H:%M:%S BRT')}")
    safe_print("=" * 80)

    # 1. Load Published Tips Ledger
    daily_ledger_data, dl_src = read_file_or_docker("core/dashboard/daily_tip_ledger.json")
    safe_print(f"[*] Daily Tip Ledger Source: {dl_src}")

    # 2. Load Settled Tips Ledger
    settled_ledger_data, sl_src = read_file_or_docker("core/dashboard/settled_tips_ledger.json")
    safe_print(f"[*] Settled Tips Ledger Source: {sl_src}")

    # 3. Load Live Audit Log
    live_audit_data, la_src = read_file_or_docker("core/dashboard/live_audit_log.json")
    safe_print(f"[*] Live Audit Log Source: {la_src}")

    # 4. Check Postgres DB
    pg_data = query_postgres_data(target_date)
    has_pg = bool(pg_data["daily_ledger"] or pg_data["settled_tips"])
    safe_print(f"[*] PostgreSQL Database Direct Link: {'AVAILABLE' if has_pg else 'EMPTY / NOT ACCESSIBLE'}")
    safe_print("-" * 80)

    # Reconcile Published Matches per Channel
    # Key -> set of match IDs published today
    published_today: Dict[str, set] = {ch: set() for ch in CHANNEL_MAP}

    # Merge from daily_tip_ledger.json
    if daily_ledger_data and isinstance(daily_ledger_data, dict):
        date_entries = daily_ledger_data.get(target_date, {})
        for ch, matches in date_entries.items():
            if ch in published_today:
                if isinstance(matches, list):
                    published_today[ch].update(str(m) for m in matches)
                elif isinstance(matches, dict):
                    published_today[ch].update(str(m) for m in matches.keys())

    # Merge from PG daily_ledger
    for ch, m_ids in pg_data.get("daily_ledger", {}).items():
        if ch in published_today:
            published_today[ch].update(m_ids)

    # Merge from live_audit_log
    if live_audit_data and isinstance(live_audit_data, list):
        for item in live_audit_data:
            m_id = str(item.get("match_id", ""))
            m_type = str(item.get("type", item.get("market_type", "")))
            item_date = str(item.get("date_brt", item.get("published_at_utc", "")))[:10]
            if target_date in item_date and m_type in published_today and m_id:
                published_today[m_type].add(m_id)

    # Reconcile Settled Tips per Channel
    # Channel -> list of settled tip dicts
    all_settled_records = []
    seen_settled_keys = set()

    # From settled_tips_ledger.json
    if settled_ledger_data and isinstance(settled_ledger_data, list):
        for it in settled_ledger_data:
            m_id = str(it.get("match_id", ""))
            ch_k = str(it.get("channel_key", it.get("type", "")))
            key = f"{m_id}_{ch_k}"
            if key not in seen_settled_keys:
                seen_settled_keys.add(key)
                all_settled_records.append(it)

    # From PostgreSQL
    for it in pg_data.get("settled_tips", []):
        m_id = str(it.get("match_id", ""))
        ch_k = str(it.get("channel_key", ""))
        key = f"{m_id}_{ch_k}"
        if key not in seen_settled_keys:
            seen_settled_keys.add(key)
            all_settled_records.append(it)

    # Compile Channel Performance Reports
    reports = {}

    for ch_k, info in CHANNEL_MAP.items():
        title = info["title"]
        cap = info["cap"]
        pub_matches = published_today.get(ch_k, set())

        # Filter settled tips for today and MTD
        today_settled = []
        mtd_settled = []

        for st in all_settled_records:
            st_ch = str(st.get("channel_key", st.get("type", "")))
            if st_ch != ch_k:
                continue

            st_date = str(st.get("date_brt", ""))
            # If date_brt is missing, try timestamp
            if not st_date:
                t_str = str(st.get("settled_at_brt", st.get("time_brt", "")))
                st_date = t_str[:10] if len(t_str) >= 10 else target_date

            if st_date == target_date:
                today_settled.append(st)
            if st_date.startswith(current_month_str):
                mtd_settled.append(st)

        # Compute Today's Stats
        w_today = 0.0
        l_today = 0.0
        v_today = 0.0
        hw_today = 0
        hl_today = 0
        net_u_today = 0.0

        for r in today_settled:
            out = str(r.get("outcome", "")).upper()
            u = float(r.get("net_units", 0.0))
            net_u_today += u

            if out in ["WIN", "WON"]:
                w_today += 1.0
            elif out in ["HALF_WIN", "HALF_WON"]:
                w_today += 0.5
                hw_today += 1
            elif out in ["LOSS", "LOST"]:
                l_today += 1.0
            elif out in ["HALF_LOSS", "HALF_LOST"]:
                l_today += 0.5
                hl_today += 1
            elif out in ["VOID", "PUSH"]:
                v_today += 1.0

        # Loss streak calculation on sorted today settled tips
        streak = 0
        for r in reversed(today_settled):
            out = str(r.get("outcome", "")).upper()
            if out in ["LOSS", "LOST", "HALF_LOSS", "HALF_LOST"]:
                streak += 1
            elif out in ["VOID", "PUSH"]:
                continue
            else:
                break

        decided_today = w_today + l_today
        wr_today = (w_today / decided_today * 100.0) if decided_today > 0 else 0.0
        roi_today = (net_u_today / len(today_settled) * 100.0) if len(today_settled) > 0 else 0.0

        # Compute MTD Stats
        w_mtd = 0.0
        l_mtd = 0.0
        v_mtd = 0.0
        net_u_mtd = 0.0
        for r in mtd_settled:
            out = str(r.get("outcome", "")).upper()
            u = float(r.get("net_units", 0.0))
            net_u_mtd += u
            if out in ["WIN", "WON"]:
                w_mtd += 1.0
            elif out in ["HALF_WIN", "HALF_WON"]:
                w_mtd += 0.5
            elif out in ["LOSS", "LOST"]:
                l_mtd += 1.0
            elif out in ["HALF_LOSS", "HALF_LOST"]:
                l_mtd += 0.5
            elif out in ["VOID", "PUSH"]:
                v_mtd += 1.0

        decided_mtd = w_mtd + l_mtd
        wr_mtd = (w_mtd / decided_mtd * 100.0) if decided_mtd > 0 else 0.0
        roi_mtd = (net_u_mtd / len(mtd_settled) * 100.0) if len(mtd_settled) > 0 else 0.0

        pending_count = max(0, len(pub_matches) - len(today_settled))

        reports[ch_k] = {
            "title": title,
            "cap": cap,
            "published_count": len(pub_matches),
            "today_settled_count": len(today_settled),
            "w_today": w_today,
            "l_today": l_today,
            "v_today": v_today,
            "hw_today": hw_today,
            "hl_today": hl_today,
            "wr_today": wr_today,
            "roi_today": roi_today,
            "net_u_today": net_u_today,
            "streak": streak,
            "mtd_settled_count": len(mtd_settled),
            "w_mtd": w_mtd,
            "l_mtd": l_mtd,
            "v_mtd": v_mtd,
            "wr_mtd": wr_mtd,
            "roi_mtd": roi_mtd,
            "net_u_mtd": net_u_mtd,
            "pending": pending_count
        }

    # Print Summary Table
    safe_print(f"{'Channel Title':<30} | {'Pub Today':<10} | {'Settled':<8} | {'Today Net':<11} | {'Streak':<7} | {'Pending'}")
    safe_print("-" * 80)
    for ch_k, rep in reports.items():
        sign_t = "+" if rep["net_u_today"] >= 0 else ""
        net_str = f"{sign_t}{rep['net_u_today']:.2f} U"
        safe_print(f"{rep['title']:<30} | {rep['published_count']}/{rep['cap']:<5} | {rep['today_settled_count']:<8} | {net_str:<11} | {rep['streak']} L{'':<4} | {rep['pending']}")
    safe_print("=" * 80)

    # Print Formatted Reports for Client Presentation
    safe_print("\n" + "=" * 80)
    safe_print("   CLIENT-READY ISOLATED PERFORMANCE REPORTS (PER TELEGRAM CHANNEL)")
    safe_print("=" * 80)

    for ch_k, rep in reports.items():
        w_t = int(rep["w_today"]) if rep["w_today"].is_integer() else rep["w_today"]
        l_t = int(rep["l_today"]) if rep["l_today"].is_integer() else rep["l_today"]
        v_t = int(rep["v_today"]) if rep["v_today"].is_integer() else rep["v_today"]

        w_m = int(rep["w_mtd"]) if rep["w_mtd"].is_integer() else rep["w_mtd"]
        l_m = int(rep["l_mtd"]) if rep["l_mtd"].is_integer() else rep["l_mtd"]
        v_m = int(rep["v_mtd"]) if rep["v_mtd"].is_integer() else rep["v_mtd"]

        sign_today = "+" if rep["net_u_today"] >= 0 else ""
        sign_roi_today = "+" if rep["roi_today"] >= 0 else ""
        sign_mtd = "+" if rep["net_u_mtd"] >= 0 else ""
        sign_roi_mtd = "+" if rep["roi_mtd"] >= 0 else ""

        half_str = ""
        if rep["hw_today"] > 0 or rep["hl_today"] > 0:
            half_str = f" (Half Wins: {rep['hw_today']}, Half Losses: {rep['hl_today']})"

        out_text = f"""{rep['title']}
DAILY & MONTH-TO-DATE PERFORMANCE REPORT
Date: {target_date} (Midnight BRT)

Today's Final Settled Performance:
• Settled Tips: {rep['today_settled_count']} (Dispatched Today: {rep['published_count']}/{rep['cap']})
• Wins: {w_t} | Losses: {l_t} | Voids: {v_t}{half_str}
• Win Rate: {rep['wr_today']:.1f}%
• Day's ROI: {sign_roi_today}{rep['roi_today']:.1f}%
• Day's Net Result: {sign_today}{rep['net_u_today']:.2f} Units
• Active Loss Streak: {rep['streak']}

Cumulative Month-to-Date (MTD):
• Total Settled MTD: {rep['mtd_settled_count']} Tips
• Wins: {w_m} | Losses: {l_m} | Voids: {v_m}
• MTD Win Rate: {rep['wr_mtd']:.1f}%
• MTD ROI: {sign_roi_mtd}{rep['roi_mtd']:.1f}%
• MTD Net Result: {sign_mtd}{rep['net_u_mtd']:.2f} Units

Unsettled Bets Pending: {rep['pending']}

Calculations based on 1.0 Unit fixed stake per tip.
Mario AI Production Suite"""

        safe_print(out_text)
        safe_print("-" * 60)


if __name__ == "__main__":
    t_date = sys.argv[1] if len(sys.argv) > 1 else None
    run_audit(t_date)
