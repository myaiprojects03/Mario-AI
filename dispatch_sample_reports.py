#!/usr/bin/env python3
"""
Dispatch Sample Telegram Reports (Partial & Midnight)
=====================================================
Completely self-contained with ZERO external pip dependencies (no dotenv, no requests).
Runs natively on the host server or inside Docker using only standard Python 3 libraries.

Generates and sends:
1. Partial 12:00 BRT Performance Reports (Interim / Provisional).
2. Midnight 00:00 BRT Performance Reports (Final Reconciled).

Usage:
  python3 dispatch_sample_reports.py --dry-run
  python3 dispatch_sample_reports.py --type partial
  python3 dispatch_sample_reports.py --type midnight
  python3 dispatch_sample_reports.py --type both
  python3 dispatch_sample_reports.py --type partial --channel fifa_goals_ou
"""

import os
import sys
import json
import hashlib
import argparse
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("sample_report_dispatcher")

# Brazil Timezone (UTC-3)
BRT_TZ = timezone(timedelta(hours=-3))

DAILY_TIP_LIMITS = {
    "fifa_goals_ou": 150,
    "fifa_money_line": 150,
    "fifa_asian_handicap": 100,
    "ebasket_money_line": 150,
    "ebasket_ou": 150
}

CHANNEL_TITLES = {
    "fifa_goals_ou": "Matrix Esoccer Pre Goals G01",
    "fifa_asian_handicap": "Matrix FIFA Pre AH G01",
    "fifa_money_line": "Matrix FIFA Pre ML G01",
    "ebasket_money_line": "Matrix eBasket Pre ML G01",
    "ebasket_ou": "Matrix eBasket Pre Points G01",
}

CHANNEL_SHORT_CODES = {
    "fifa_goals_ou": "GOALS",
    "fifa_asian_handicap": "AH",
    "fifa_money_line": "ML",
    "ebasket_money_line": "EBML",
    "ebasket_ou": "EBOU",
}

CHANNEL_ALIASES = {
    "fifa_goals_ou": ["fifa_goals_ou", "fifa_goals", "fifa_ou", "goals_ou"],
    "fifa_asian_handicap": ["fifa_asian_handicap", "fifa_ah", "asian_handicap"],
    "fifa_money_line": ["fifa_money_line", "fifa_ml", "money_line"],
    "ebasket_money_line": ["ebasket_money_line", "ebasket_ml"],
    "ebasket_ou": ["ebasket_ou", "ebasket_points", "ebasket_points_ou"],
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_DIR = os.path.join(BASE_DIR, "core", "dashboard")
SETTLED_TIPS_LEDGER_FILE = os.path.join(DASHBOARD_DIR, "settled_tips_ledger.json")
PUBLISHED_TIPS_CACHE_FILE = os.path.join(DASHBOARD_DIR, "published_tips_cache.json")


def load_env_file():
    """Self-contained .env loader with zero external dependencies."""
    candidates = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.getcwd(), ".env"),
        "/root/mario-ai-code/.env"
    ]
    for env_path in candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            os.environ.setdefault(k, v)
                break
            except Exception:
                pass


load_env_file()


def get_channel_config() -> Tuple[Dict[str, str], Dict[str, str], str]:
    default_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    default_channel = os.getenv("TELEGRAM_CHANNEL_ID", "")

    channel_map = {
        "fifa_goals_ou": os.getenv("TELEGRAM_CHANNEL_FIFA_GOALS") or os.getenv("TELEGRAM_CHANNEL_ID_FIFA_GOALS_OU") or default_channel,
        "fifa_asian_handicap": os.getenv("TELEGRAM_CHANNEL_FIFA_AH") or os.getenv("TELEGRAM_CHANNEL_ID_FIFA_ASIAN_HANDICAP") or default_channel,
        "fifa_money_line": os.getenv("TELEGRAM_CHANNEL_FIFA_ML") or os.getenv("TELEGRAM_CHANNEL_ID_FIFA_MONEY_LINE") or default_channel,
        "ebasket_money_line": os.getenv("TELEGRAM_CHANNEL_EBASKET_ML") or os.getenv("TELEGRAM_CHANNEL_ID_EBASKET_MONEY_LINE") or default_channel,
        "ebasket_ou": os.getenv("TELEGRAM_CHANNEL_EBASKET_OU") or os.getenv("TELEGRAM_CHANNEL_EBASKET_POINTS") or os.getenv("TELEGRAM_CHANNEL_ID_EBASKET_OU") or os.getenv("TELEGRAM_CHANNEL_ID_EBASKET_POINTS") or default_channel,
    }

    bot_tokens = {
        "fifa_goals_ou": os.getenv("TELEGRAM_BOT_TOKEN_FIFA_GOALS_OU") or default_token,
        "fifa_asian_handicap": os.getenv("TELEGRAM_BOT_TOKEN_FIFA_ASIAN_HANDICAP") or default_token,
        "fifa_money_line": os.getenv("TELEGRAM_BOT_TOKEN_FIFA_MONEY_LINE") or default_token,
        "ebasket_money_line": os.getenv("TELEGRAM_BOT_TOKEN_EBASKET_MONEY_LINE") or default_token,
        "ebasket_ou": os.getenv("TELEGRAM_BOT_TOKEN_EBASKET_OU") or os.getenv("TELEGRAM_BOT_TOKEN_EBASKET_POINTS") or default_token,
    }

    return channel_map, bot_tokens, default_token


def load_json_file(filepath: str, default=None):
    candidates = [
        filepath,
        os.path.join(BASE_DIR, filepath),
        os.path.join("/root/mario-ai-code", filepath)
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return default if default is not None else []


def send_telegram_message(bot_token: str, channel_id: str, text: str) -> Optional[int]:
    """Sends a Telegram message using standard urllib with zero dependencies."""
    if not bot_token or not channel_id:
        return None
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": text,
        "disable_web_page_preview": True
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("ok"):
                    return body.get("result", {}).get("message_id")
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
    return None


def calculate_streak(settled_list: List[Dict[str, Any]]) -> str:
    if not settled_list:
        return "None"
    sorted_tips = sorted(settled_list, key=lambda x: str(x.get("settled_at_brt") or x.get("date_brt") or ""))
    streak_type = None
    streak_count = 0
    for it in reversed(sorted_tips):
        out = str(it.get("outcome", "")).upper()
        if out in ["VOID", "PUSH"]:
            continue
        elif out in ["WIN", "WON", "HALF_WIN"]:
            if streak_type is None:
                streak_type = "WIN"
            if streak_type == "WIN":
                streak_count += 1
            else:
                break
        elif out in ["LOSS", "LOST", "HALF_LOSS"]:
            if streak_type is None:
                streak_type = "LOSS"
            if streak_type == "LOSS":
                streak_count += 1
            else:
                break
    if streak_type == "WIN":
        return f"{streak_count} Win" if streak_count == 1 else f"{streak_count} Wins"
    elif streak_type == "LOSS":
        return f"{streak_count} Loss" if streak_count == 1 else f"{streak_count} Losses"
    return "None"


def generate_report_text(channel_key: str, target_date_str: str, is_midnight: bool) -> Tuple[str, str, str]:
    display_title = CHANNEL_TITLES.get(channel_key, channel_key.upper())
    report_title_type = "DAILY & MONTH-TO-DATE PERFORMANCE REPORT (00:00 BRT)" if is_midnight else "PARTIAL PERFORMANCE REPORT (12:00 BRT)"
    report_date_line = f"Date: {target_date_str} (Midnight BRT)" if is_midnight else f"Date: {target_date_str}"

    code_tag = CHANNEL_SHORT_CODES.get(channel_key, channel_key[:4].upper())
    clean_date = target_date_str.replace("-", "")
    run_seed = f"{channel_key}:{target_date_str}:{'MIDNIGHT' if is_midnight else 'PARTIAL'}"
    run_hash = hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:8].upper()
    run_id = f"RUN-{clean_date}-{code_tag}-{run_hash}"

    aliases = set(CHANNEL_ALIASES.get(channel_key, [channel_key]))
    daily_cap = DAILY_TIP_LIMITS.get(channel_key, 150)
    current_month_str = target_date_str[:7]

    # 1. Load settled tips
    all_settled = load_json_file(SETTLED_TIPS_LEDGER_FILE, [])
    today_settled_raw = [
        it for it in all_settled
        if it.get("channel_key") in aliases and str(it.get("date_brt", "")).startswith(target_date_str)
    ]
    today_settled = today_settled_raw[:daily_cap]
    today_settled_ids = {str(it.get("match_id")) for it in today_settled if it.get("match_id")}

    mtd_settled = [
        it for it in all_settled
        if it.get("channel_key") in aliases and str(it.get("date_brt", "")).startswith(current_month_str)
    ]

    # 2. Query active pending fixtures
    cache = load_json_file(PUBLISHED_TIPS_CACHE_FILE, {})
    now_utc = datetime.now(timezone.utc)
    real_pending = []
    if isinstance(cache, dict):
        for k, v in cache.items():
            if isinstance(v, dict) and (v.get("type") in aliases or v.get("channel_key") in aliases):
                m_id = str(v.get("match_id") or k)
                if m_id not in today_settled_ids:
                    pub_ts = v.get("published_at_utc") or v.get("timestamp")
                    if pub_ts:
                        try:
                            ts_str = str(pub_ts).replace("Z", "+00:00")
                            dt_tip = datetime.fromisoformat(ts_str).astimezone(BRT_TZ)
                            if dt_tip.strftime("%Y-%m-%d") == target_date_str:
                                dt_utc = dt_tip.astimezone(timezone.utc)
                                if (now_utc - dt_utc).total_seconds() <= 4 * 3600:
                                    real_pending.append(m_id)
                        except Exception:
                            pass

    max_allowed_pending = max(0, daily_cap - len(today_settled))
    pending_count = min(len(real_pending), max_allowed_pending)
    pending_exposure = float(pending_count) * 1.0

    # 3. Authentic Dispatched Count
    published_count = min(daily_cap, len(today_settled) + pending_count)

    # 4. Status Determination (Exact Client Specification)
    if pending_count > 0:
        report_status = f"Reconciled — Provisional ({pending_count} pending tips in-play / awaiting settlement)"
        status_tag = "Reconciled — Provisional"
    else:
        report_status = "Reconciled — Final"
        status_tag = "Reconciled — Final"

    # 5. Calculations
    today_wins = 0.0
    today_losses = 0.0
    today_voids = 0
    today_pushes = 0
    today_half_wins = 0
    today_half_losses = 0
    today_units = 0.0

    for it in today_settled:
        out = str(it.get("outcome", "")).upper()
        u = float(it.get("net_units", 0.0))
        today_units += u
        if out in ["WIN", "WON"]:
            today_wins += 1.0
        elif out == "HALF_WIN":
            today_wins += 0.5
            today_half_wins += 1
        elif out in ["LOSS", "LOST"]:
            today_losses += 1.0
        elif out == "HALF_LOSS":
            today_losses += 0.5
            today_half_losses += 1
        elif out == "PUSH":
            today_pushes += 1
        elif out == "VOID":
            today_voids += 1

    today_settled_count = len(today_settled)
    today_decided = today_wins + today_losses
    today_win_rate = (today_wins / today_decided * 100.0) if today_decided > 0 else 0.0
    today_roi = (today_units / today_settled_count * 100.0) if today_settled_count > 0 else 0.0

    current_streak_str = calculate_streak(today_settled if today_settled else mtd_settled)

    mtd_wins = 0.0
    mtd_losses = 0.0
    mtd_voids = 0
    mtd_pushes = 0
    mtd_half_wins = 0
    mtd_half_losses = 0
    mtd_units = 0.0

    for it in mtd_settled:
        out = str(it.get("outcome", "")).upper()
        u = float(it.get("net_units", 0.0))
        mtd_units += u
        if out in ["WIN", "WON"]:
            mtd_wins += 1.0
        elif out == "HALF_WIN":
            mtd_wins += 0.5
            mtd_half_wins += 1
        elif out in ["LOSS", "LOST"]:
            mtd_losses += 1.0
        elif out == "HALF_LOSS":
            mtd_losses += 0.5
            mtd_half_losses += 1
        elif out == "PUSH":
            mtd_pushes += 1
        elif out == "VOID":
            mtd_voids += 1

    mtd_settled_count = len(mtd_settled)
    mtd_decided = mtd_wins + mtd_losses
    mtd_win_rate = (mtd_wins / mtd_decided * 100.0) if mtd_decided > 0 else 0.0
    mtd_roi = (mtd_units / mtd_settled_count * 100.0) if mtd_settled_count > 0 else 0.0

    sign_today = "+" if today_units >= 0 else ""
    sign_today_roi = "+" if today_roi >= 0 else ""
    sign_mtd = "+" if mtd_units >= 0 else ""
    sign_mtd_roi = "+" if mtd_roi >= 0 else ""

    tw_str = f"{int(today_wins)}" if today_wins.is_integer() else f"{today_wins:.1f}"
    tl_str = f"{int(today_losses)}" if today_losses.is_integer() else f"{today_losses:.1f}"
    mw_str = f"{int(mtd_wins)}" if mtd_wins.is_integer() else f"{mtd_wins:.1f}"
    ml_str = f"{int(mtd_losses)}" if mtd_losses.is_integer() else f"{mtd_losses:.1f}"

    lines = []
    lines.append(display_title)
    lines.append(report_title_type)
    lines.append(report_date_line)
    lines.append(f"Report-Run ID: {run_id}")
    lines.append("")
    lines.append(f"STATUS: {report_status}")
    lines.append("")

    lines.append("Daily Summary:")
    lines.append(f"• Tips Dispatched Today: {published_count}")
    lines.append(f"• Settled Tips Today: {today_settled_count}")
    lines.append(f"• Pending Tips: {pending_count} (Pending Exposure: {pending_exposure:.2f} Units)")
    if published_count == 0 and today_settled_count == 0:
        lines.append("• Note: No eligible betting opportunities met edge and EV thresholds for this market today.")
    lines.append("")

    if today_settled_count > 0:
        section_label = "Today's Settled Performance:" if pending_count == 0 else "Today's Settled Performance (Interim):"
        lines.append(section_label)
        lines.append(f"• Wins: {tw_str} | Losses: {tl_str} | Voids: {today_voids} | Pushes: {today_pushes}")
        if today_half_wins > 0 or today_half_losses > 0:
            lines.append(f"• Half Won: {today_half_wins} | Half Lost: {today_half_losses}")
        lines.append(f"• Daily Win Rate: {today_win_rate:.1f}%")
        lines.append(f"• Daily ROI: {sign_today_roi}{today_roi:.1f}%")
        lines.append(f"• Daily Net Result: {sign_today}{today_units:.2f} Units")
        lines.append(f"• Current Streak: {current_streak_str}")
        lines.append("")
    elif published_count > 0 and today_settled_count == 0:
        lines.append("Today's Settled Performance:")
        lines.append(f"• All {published_count} dispatched tips are currently in-play or awaiting official scores.")
        lines.append("• Daily Net Result: +0.00 Units (Pending)")
        lines.append(f"• Current Streak: {current_streak_str}")
        lines.append("")

    if is_midnight:
        lines.append("Cumulative Month-to-Date (MTD):")
        lines.append(f"• Total Settled MTD: {mtd_settled_count} Tips")
        lines.append(f"• MTD Wins: {mw_str} | Losses: {ml_str} | Voids: {mtd_voids} | Pushes: {mtd_pushes}")
        if mtd_half_wins > 0 or mtd_half_losses > 0:
            lines.append(f"• MTD Half Won: {mtd_half_wins} | MTD Half Lost: {mtd_half_losses}")
        lines.append(f"• MTD Win Rate: {mtd_win_rate:.1f}%")
        lines.append(f"• MTD ROI: {sign_mtd_roi}{mtd_roi:.1f}%")
        lines.append(f"• MTD Net Result: {sign_mtd}{mtd_units:.2f} Units")
        lines.append("")

    if pending_count > 0:
        lines.append(f"Notice: {pending_count} tips are currently in-play or awaiting official score verification. Final figures will be compiled upon completed settlement.")
        lines.append("")

    lines.append("Calculations based on 1.0 Unit fixed stake per tip.")
    lines.append("Mario AI Production Suite")

    return "\n".join(lines), run_id, status_tag


def dispatch_sample(report_type: str = "both", target_channel: str = None, dry_run: bool = False, date_str: str = None):
    now_brt = datetime.now(BRT_TZ)
    today_str = date_str or now_brt.strftime("%Y-%m-%d")
    yesterday_str = (now_brt - timedelta(days=1)).strftime("%Y-%m-%d")

    channel_map, bot_tokens, default_token = get_channel_config()

    channels_to_test = {}
    if target_channel:
        if target_channel in channel_map:
            channels_to_test[target_channel] = channel_map[target_channel]
        else:
            logger.error(f"Channel {target_channel} not found in channel configuration.")
            return
    else:
        channels_to_test = channel_map

    types_to_run = []
    if report_type in ["partial", "both"]:
        types_to_run.append(("partial", today_str, False))
    if report_type in ["midnight", "both"]:
        types_to_run.append(("midnight", yesterday_str, True))

    logger.info("=" * 75)
    logger.info(f"STARTING SAMPLE REPORT DISPATCH (Mode: {'DRY-RUN' if dry_run else 'LIVE TELEGRAM SEND'})")
    logger.info(f"Server BRT Time: {now_brt.strftime('%Y-%m-%d %H:%M:%S BRT')}")
    logger.info("=" * 75)

    for r_type, d_str, is_mid in types_to_run:
        label = "MIDNIGHT REPORT (00:00 BRT)" if is_mid else "PARTIAL NOON REPORT (12:00 BRT)"
        logger.info(f"\n>>> PROCESSING {label} FOR TARGET DATE: {d_str} <<<\n")

        for ch_key, ch_id in channels_to_test.items():
            if not ch_id:
                logger.warning(f"No channel ID configured for {ch_key}. Skipping.")
                continue

            text, run_id, status_tag = generate_report_text(ch_key, d_str, is_midnight=is_mid)
            tok = bot_tokens.get(ch_key) or default_token

            if dry_run:
                print("-" * 75)
                print(f"[DRY-RUN] Target Channel: {ch_key} (ID: {ch_id}) | Run ID: {run_id} | Status: {status_tag}")
                print("-" * 75)
                print(text)
                print("-" * 75)
            else:
                logger.info(f"Sending {r_type} report to {ch_key} ({ch_id})...")
                msg_id = send_telegram_message(tok, ch_id, text)
                if msg_id:
                    logger.info(f"SUCCESS: Delivered {r_type} report to {ch_key} -> Telegram Msg ID: {msg_id} [Run ID: {run_id}]")
                else:
                    logger.error(f"FAILED to send {r_type} report to {ch_key}.")

    logger.info("\n" + "=" * 75)
    logger.info("SAMPLE REPORT DISPATCH COMPLETE")
    logger.info("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Dispatch Sample Performance Reports to Telegram (Zero Dependencies)")
    parser.add_argument("--type", choices=["partial", "midnight", "both"], default="both", help="Report type to send")
    parser.add_argument("--channel", type=str, default=None, help="Specific channel key (e.g. fifa_goals_ou)")
    parser.add_argument("--dry-run", action="store_true", help="Print reports to terminal without sending to Telegram")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    args = parser.parse_args()

    dispatch_sample(
        report_type=args.type,
        target_channel=args.channel,
        dry_run=args.dry_run,
        date_str=args.date
    )


if __name__ == "__main__":
    main()
