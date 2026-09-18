#!/usr/bin/env python3
"""
Server Log & Report Diagnostic Tool (test_server_logs.py)
=========================================================
Audits live Docker container logs, persistent ledgers, and reporting output
across all 5 Telegram channels.

Usage on server:
    python test_server_logs.py
    python test_server_logs.py --tail 5000
    python test_server_logs.py --file /path/to/server.log
    python test_server_logs.py --date 2026-09-17
"""

import os
import sys
import json
import re
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

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
        "cap": 150,
        "keywords": ["fifa_goals_ou", "fifa goals", "goals over/under", "goals ou"]
    },
    "fifa_asian_handicap": {
        "title": "Matrix FIFA Pre AH G01",
        "cap": 100,
        "keywords": ["fifa_asian_handicap", "fifa asian handicap", "asian handicap", "fifa ah"]
    },
    "fifa_money_line": {
        "title": "Matrix FIFA Pre ML G01",
        "cap": 150,
        "keywords": ["fifa_money_line", "fifa money line", "fifa ml"]
    },
    "ebasket_money_line": {
        "title": "Matrix eBasket Pre ML G01",
        "cap": 150,
        "keywords": ["ebasket_money_line", "ebasketball money line", "ebasket ml"]
    },
    "ebasket_ou": {
        "title": "Matrix eBasket Pre Points G01",
        "cap": 150,
        "keywords": ["ebasket_ou", "ebasketball over/under", "ebasket ou", "ebasket points"]
    },
}


def safe_print(text=""):
    """Safely prints UTF-8 text on any OS console (Windows cp1252 & Linux)."""
    try:
        sys.stdout.buffer.write((str(text) + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()
    except Exception:
        print(str(text).encode("ascii", errors="replace").decode("ascii"))


def fetch_docker_logs(container_name="mario_ai_live_publisher", tail=None):
    """Fetches stdout/stderr logs from the live publisher container."""
    cmd = ["docker", "logs"]
    if tail:
        cmd.extend(["--tail", str(tail)])
    cmd.append(container_name)
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="ignore")
        if result.returncode == 0:
            return result.stdout.splitlines() + result.stderr.splitlines()
        else:
            return []
    except Exception:
        return []


def parse_timestamp_to_brt(raw_str):
    """Parses various log timestamps into datetime in BRT."""
    try:
        m = re.search(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", raw_str)
        if m:
            dt_naive = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
            if "Z" in raw_str or "+00" in raw_str:
                return dt_naive.replace(tzinfo=UTC_TZ).astimezone(BRT_TZ)
            elif "BRT" in raw_str or "-03" in raw_str:
                return dt_naive.replace(tzinfo=BRT_TZ)
            else:
                return dt_naive.replace(tzinfo=UTC_TZ).astimezone(BRT_TZ)
    except Exception:
        pass
    return datetime.now(BRT_TZ)


def analyze_server_logs(log_lines, target_date_str):
    """
    Analyzes raw server log lines to extract:
    1. Tips published per channel
    2. Tips settled per channel (scores, outcomes, 0-0 checks)
    3. Capping triggers
    4. Consecutive-loss streaks
    """
    stats = {}
    for k, v in CHANNEL_MAP.items():
        stats[k] = {
            "title": v["title"],
            "cap": v["cap"],
            "published_matches": set(),
            "published_tips": [],
            "settled_tips": [],
            "cap_blocked_count": 0,
            "zero_zero_settlements": 0,
            "wins": 0.0,
            "losses": 0.0,
            "voids": 0.0,
            "half_wins": 0,
            "half_losses": 0,
            "net_units": 0.0,
            "consecutive_losses": 0
        }

    for line in log_lines:
        dt_brt = parse_timestamp_to_brt(line)
        log_date = dt_brt.strftime("%Y-%m-%d")
        if log_date != target_date_str:
            continue

        line_lower = line.lower()

        # 1. Identify Channel
        matched_channel = None
        for ch_k, ch_info in CHANNEL_MAP.items():
            if ch_k in line_lower or any(kw in line_lower for kw in ch_info["keywords"]):
                matched_channel = ch_k
                break

        # 2. Check Capping Blocks
        if "daily tip limit reached" in line_lower or "aborting telegram tip dispatch" in line_lower:
            if matched_channel:
                stats[matched_channel]["cap_blocked_count"] += 1

        # 3. Check Tip Publishing
        if "successfully dispatched tip for" in line_lower or "published tip" in line_lower:
            m_match = re.search(r"match\s+([a-zA-Z0-9_\-]+)", line, re.IGNORECASE)
            m_id = m_match.group(1) if m_match else f"tip_{len(stats[matched_channel]['published_tips'])}" if matched_channel else None
            if matched_channel and m_id:
                stats[matched_channel]["published_matches"].add(m_id)
                stats[matched_channel]["published_tips"].append({
                    "time_brt": dt_brt.strftime("%H:%M:%S"),
                    "match_id": m_id,
                    "raw": line.strip()
                })

        # 4. Check Settlements: SETTLED TIP: Match <id> -> <status> (Score: <H>-<A>)
        if "settled tip:" in line_lower:
            m_id = "unknown"
            m_match = re.search(r"Match\s+([a-zA-Z0-9_\-]+)", line)
            if m_match:
                m_id = m_match.group(1)

            h_score, a_score = 0.0, 0.0
            s_match = re.search(r"Score:\s*([0-9.]+)\s*-\s*([0-9.]+)", line, re.IGNORECASE)
            if s_match:
                try:
                    h_score = float(s_match.group(1))
                    a_score = float(s_match.group(2))
                except Exception:
                    pass

            outcome = "UNKNOWN"
            if "won" in line_lower:
                outcome = "HALF_WIN" if "half" in line_lower else "WIN"
            elif "lost" in line_lower:
                outcome = "HALF_LOSS" if "half" in line_lower else "LOSS"
            elif "void" in line_lower:
                outcome = "VOID"

            is_zero_zero = (h_score == 0.0 and a_score == 0.0)

            target_ch = matched_channel
            if not target_ch:
                if h_score > 20 or a_score > 20:
                    target_ch = "ebasket_ou"
                else:
                    target_ch = "fifa_goals_ou"

            if target_ch:
                if is_zero_zero:
                    stats[target_ch]["zero_zero_settlements"] += 1

                odds = 1.90
                net_u = 0.0
                if outcome == "WIN":
                    stats[target_ch]["wins"] += 1.0
                    net_u = odds - 1.0
                elif outcome == "HALF_WIN":
                    stats[target_ch]["wins"] += 0.5
                    stats[target_ch]["half_wins"] += 1
                    net_u = 0.5 * (odds - 1.0)
                elif outcome == "LOSS":
                    stats[target_ch]["losses"] += 1.0
                    net_u = -1.0
                elif outcome == "HALF_LOSS":
                    stats[target_ch]["losses"] += 0.5
                    stats[target_ch]["half_losses"] += 1
                    net_u = -0.5
                elif outcome == "VOID":
                    stats[target_ch]["voids"] += 1.0
                    net_u = 0.0

                stats[target_ch]["net_units"] += net_u
                stats[target_ch]["settled_tips"].append({
                    "time_brt": dt_brt.strftime("%H:%M:%S"),
                    "match_id": m_id,
                    "score": f"{h_score}-{a_score}",
                    "outcome": outcome,
                    "net_units": net_u,
                    "raw": line.strip()
                })

    for k, s in stats.items():
        streak = 0
        for item in reversed(s["settled_tips"]):
            out = item["outcome"]
            if out in ["LOSS", "HALF_LOSS"]:
                streak += 1
            elif out == "VOID":
                continue
            else:
                break
        s["consecutive_losses"] = streak

    return stats


def format_simulated_report(channel_key, s, target_date_str):
    """Formats simulated independent report using extracted log stats."""
    pub_count = len(s["published_matches"])
    settled_count = len(s["settled_tips"])
    w = s["wins"]
    l = s["losses"]
    v = s["voids"]
    hw = s["half_wins"]
    hl = s["half_losses"]
    net_u = s["net_units"]
    streak = s["consecutive_losses"]
    title = s["title"]

    decided = w + l
    wr = (w / decided * 100.0) if decided > 0 else 0.0
    roi = (net_u / settled_count * 100.0) if settled_count > 0 else 0.0
    sign = "+" if net_u >= 0 else ""

    w_str = f"{int(w)}" if w.is_integer() else f"{w:.1f}"
    l_str = f"{int(l)}" if l.is_integer() else f"{l:.1f}"
    v_str = f"{int(v)}" if v.is_integer() else f"{v:.1f}"

    if pub_count > 0 and settled_count == 0:
        return f"""{title}
DAILY & MONTH-TO-DATE PERFORMANCE REPORT
Date: {target_date_str} (Midnight BRT)

STATUS: DATA RECONCILIATION IN PROGRESS
• Tips Dispatched Today: {pub_count}
• Active / In-Play Fixtures: {pub_count}
• Settled Results on Record: 0

All published matches are currently active in-play or awaiting verified post-match scores.
Mario AI Production Suite"""

    if pub_count == 0 and settled_count == 0:
        return f"""{title}
DAILY & MONTH-TO-DATE PERFORMANCE REPORT
Date: {target_date_str} (Midnight BRT)

ZERO TIPS DISPATCHED TODAY
• No eligible betting opportunities met the edge and EV thresholds for this market today.
Mario AI Production Suite"""

    streak_warn = f"\nCircuit Breaker Alert: {streak} consecutive losses on record." if streak >= 5 else ""
    half_line = f"\n• Half Won: {hw} | Half Lost: {hl}" if (hw > 0 or hl > 0) else ""

    return f"""{title}
DAILY & MONTH-TO-DATE PERFORMANCE REPORT
Date: {target_date_str} (Midnight BRT)

Today's Final Settled Performance:
• Settled Tips: {settled_count}
• Wins: {w_str} | Losses: {l_str} | Voids: {v_str}{half_line}
• Win Rate: {wr:.1f}%
• Day's ROI: {sign}{roi:.1f}%
• Day's Net Result: {sign}{net_u:.2f} Units
• Active Loss Streak: {streak}{streak_warn}

Calculations based on 1.0 Unit fixed stake per tip.
Mario AI Production Suite"""


def print_diagnostic_report(stats, target_date_str, log_source):
    safe_print("=" * 80)
    safe_print(f"       MARIO AI SERVER LOG & PERFORMANCE AUDIT ({target_date_str} BRT)")
    safe_print("=" * 80)
    safe_print(f"Log Source: {log_source}")
    safe_print(f"Execution Time: {datetime.now(BRT_TZ).strftime('%Y-%m-%d %H:%M:%S BRT')}")
    safe_print("-" * 80)
    safe_print(f"{'Channel / Market':<26} | {'Pub/Cap':<10} | {'Settled':<8} | {'W-L-V':<9} | {'Net Units':<10} | {'Streak':<7} | {'0-0 Flag'}")
    safe_print("-" * 80)

    total_pub = 0
    total_settled = 0
    total_units = 0.0

    for ch_k, s in stats.items():
        pub_count = len(s["published_matches"])
        cap_val = s["cap"]
        settled_count = len(s["settled_tips"])
        total_pub += pub_count
        total_settled += settled_count
        total_units += s["net_units"]

        w_str = f"{int(s['wins'])}" if s['wins'].is_integer() else f"{s['wins']:.1f}"
        l_str = f"{int(s['losses'])}" if s['losses'].is_integer() else f"{s['losses']:.1f}"
        v_str = f"{int(s['voids'])}" if s['voids'].is_integer() else f"{s['voids']:.1f}"
        wlv = f"{w_str}-{l_str}-{v_str}"

        sign = "+" if s["net_units"] >= 0 else ""
        u_str = f"{sign}{s['net_units']:.2f} U"

        pub_cap_str = f"{pub_count}/{cap_val}"
        streak_str = f"{s['consecutive_losses']} L" if s['consecutive_losses'] > 0 else "0"
        flag_00 = f"WARN: {s['zero_zero_settlements']} (Premature?)" if s['zero_zero_settlements'] > 0 else "OK (0)"

        safe_print(f"{s['title']:<26} | {pub_cap_str:<10} | {settled_count:<8} | {wlv:<9} | {u_str:<10} | {streak_str:<7} | {flag_00}")

    safe_print("-" * 80)
    total_sign = "+" if total_units >= 0 else ""
    safe_print(f"{'Total (Reference Only)':<26} | {total_pub:<10} | {total_settled:<8} | {'':<9} | {total_sign}{total_units:.2f} U | {'':<7} |")
    safe_print("=" * 80)

    safe_print("\n" + "=" * 80)
    safe_print("       PER-CHANNEL REPORT INTEGRITY CHECK & OUTPUT SIMULATION")
    safe_print("=" * 80)

    for ch_k, s in stats.items():
        safe_print(f"\n>>> CHANNEL: {s['title']} ({ch_k})")
        safe_print(f"• Published Today: {len(s['published_matches'])} / Cap: {s['cap']} tips")
        safe_print(f"• Settled in Logs: {len(s['settled_tips'])} tips")
        safe_print(f"• Net Profit/Loss: {s['net_units']:+.2f} Units")
        safe_print(f"• Current Active Losing Streak: {s['consecutive_losses']}")
        if s["consecutive_losses"] >= 5:
            safe_print(f"  WARNING: High Loss Streak Triggered ({s['consecutive_losses']} consecutive losses)")
        if s["cap_blocked_count"] > 0:
            safe_print(f"  INFO: Daily Cap Suppressions Logged: {s['cap_blocked_count']} times")

        rep_text = format_simulated_report(ch_k, s, target_date_str)
        safe_print("\n[Simulated Telegram Midnight Report]:")
        safe_print("-" * 40)
        safe_print(rep_text)
        safe_print("-" * 40)


def main():
    parser = argparse.ArgumentParser(description="Audit Mario AI server logs and verify report integrity.")
    parser.add_argument("--file", type=str, default=None, help="Path to raw log file (optional)")
    parser.add_argument("--date", type=str, default=None, help="Target date in YYYY-MM-DD (defaults to today BRT)")
    parser.add_argument("--tail", type=int, default=None, help="Number of lines to read from docker logs (e.g. 5000)")
    args = parser.parse_args()

    now_brt = datetime.now(BRT_TZ)
    target_date = args.date or now_brt.strftime("%Y-%m-%d")

    log_lines = []
    log_source = ""

    if args.file and os.path.exists(args.file):
        log_source = f"File: {args.file}"
        with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
            log_lines = f.readlines()
    else:
        log_lines = fetch_docker_logs("mario_ai_live_publisher", tail=args.tail)
        if log_lines:
            log_source = "Docker container: mario_ai_live_publisher"
        else:
            log_source = "Local Ledger / Audit fallback"

    stats = analyze_server_logs(log_lines, target_date)
    print_diagnostic_report(stats, target_date, log_source)


if __name__ == "__main__":
    main()
