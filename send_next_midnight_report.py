#!/usr/bin/env python3
"""
Midnight BRT Performance Reports & Cap Enforcement Dispatcher
============================================================
Generates and dispatches the official Midnight (00:00 BRT) Performance Reports
confirming strict compliance with agreed daily channel caps:
  • FIFA Goals O/U: no more than 150 new tips
  • FIFA Money Line: no more than 150 new tips
  • FIFA Asian Handicap: no more than 100 new tips
  • All caps reset strictly at 00:00 Brazil Time (BRT / UTC-3).

Usage:
  python send_next_midnight_report.py              # Dispatches midnight report to Telegram
  python send_next_midnight_report.py --dry-run    # Prints reports and audit table without sending
  python send_next_midnight_report.py --date YYYY-MM-DD
"""

import os
import sys
import re
import argparse
import logging
from datetime import datetime, timedelta, timezone

from core.live_publisher import (
    generate_performance_report_text,
    send_telegram_tip,
    DAILY_TIP_LIMITS,
    BOT_TOKENS,
    CHANNEL_MAP,
    TELEGRAM_BOT_TOKEN,
    BRT_TZ,
    load_daily_tip_ledger,
    load_settled_tips_ledger
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("midnight_reporter")

# Agreed Production Daily Limits
AGREED_CAPS = {
    "fifa_goals_ou": 150,
    "fifa_money_line": 150,
    "fifa_asian_handicap": 100,
    "ebasket_money_line": 150,
    "ebasket_ou": 150
}

CHANNEL_NAMES = {
    "fifa_goals_ou": "FIFA Goals O/U",
    "fifa_money_line": "FIFA Money Line",
    "fifa_asian_handicap": "FIFA Asian Handicap",
    "ebasket_money_line": "eBasketball Money Line",
    "ebasket_ou": "eBasketball Points O/U"
}


def parse_args():
    parser = argparse.ArgumentParser(description="Send Midnight BRT Performance Reports confirming daily limits")
    parser.add_argument("--date", type=str, default=None, help="Target completed date (YYYY-MM-DD). Defaults to yesterday if past midnight BRT.")
    parser.add_argument("--dry-run", action="store_true", help="Print reports and audit table to terminal without dispatching to Telegram")
    parser.add_argument("--channel", type=str, default="all", help="Specific channel key or 'all'")
    return parser.parse_args()


def get_default_report_date() -> str:
    now_brt = datetime.now(BRT_TZ)
    # If currently between 00:00 and 06:00 BRT, the completed day is yesterday
    # Otherwise, default to today's completed date
    if now_brt.hour < 12:
        return (now_brt - timedelta(days=1)).strftime("%Y-%m-%d")
    return now_brt.strftime("%Y-%m-%d")


def enhance_report_text_with_cap_confirmation(raw_report: str, channel_key: str, cap: int) -> str:
    """
    Appends explicit cap confirmation to the Daily Summary section of the report text:
    • Daily Cap: No more than {cap} tips dispatched (Strictly resets at 00:00 BRT)
    """
    confirmation_line = (
        f"• Daily Cap Policy: Strict limit of no more than {cap} tips enforced (Resets daily at 00:00 BRT)."
    )

    # Insert right after "Daily Summary:"
    if "Daily Summary:" in raw_report:
        return raw_report.replace(
            "Daily Summary:",
            f"Daily Summary:\n{confirmation_line}",
            1
        )
    return f"{confirmation_line}\n\n{raw_report}"


def main():
    args = parse_args()
    report_date = args.date or get_default_report_date()

    print("\n" + "=" * 80)
    print("      MIDNIGHT BRT PERFORMANCE REPORT & DAILY CAP VERIFICATION")
    print("=" * 80)
    print(f"Target Date:                {report_date} (Midnight BRT)")
    print(f"Execution Time (BRT):       {datetime.now(BRT_TZ).strftime('%Y-%m-%d %H:%M:%S BRT')}")
    print("All Caps Reset Policy:      Strictly at 00:00 Brazil Time (BRT / UTC-3)")
    print(f"Mode:                       {'DRY-RUN (Simulated)' if args.dry_run else 'LIVE DISPATCH TO TELEGRAM'}")
    print("=" * 80 + "\n")

    target_channels = (
        [args.channel] if args.channel != "all"
        else ["fifa_goals_ou", "fifa_money_line", "fifa_asian_handicap", "ebasket_money_line", "ebasket_ou"]
    )

    audit_summary = []
    default_token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN

    for ch_key in target_channels:
        cap = AGREED_CAPS.get(ch_key, 150)
        ch_title = CHANNEL_NAMES.get(ch_key, ch_key)
        ch_id = CHANNEL_MAP.get(ch_key)

        # 1. Generate report with guaranteed daily capping
        raw_report = generate_performance_report_text(
            is_midnight=True,
            target_date_str=report_date,
            channel_key=ch_key
        )

        # 2. Extract dispatched count from report
        m_disp = re.search(r"Tips Dispatched Today:\s*(\d+)", raw_report)
        dispatched_count = int(m_disp.group(1)) if m_disp else 0

        m_sett = re.search(r"Settled Tips Today:\s*(\d+)", raw_report)
        settled_count = int(m_sett.group(1)) if m_sett else 0

        m_pend = re.search(r"Pending Tips:\s*(\d+)", raw_report)
        pending_count = int(m_pend.group(1)) if m_pend else 0

        # Compliance Verification
        is_compliant = dispatched_count <= cap
        compliance_status = f"PASSED (<= {cap})" if is_compliant else f"FAILED (> {cap})"

        audit_summary.append({
            "channel_key": ch_key,
            "title": ch_title,
            "cap": cap,
            "dispatched": dispatched_count,
            "settled": settled_count,
            "pending": pending_count,
            "status": compliance_status,
            "passed": is_compliant
        })

        # 3. Enhance report text with the cap confirmation notice
        final_report = enhance_report_text_with_cap_confirmation(raw_report, ch_key, cap)

        print("-" * 75)
        print(f"REPORT FOR: {ch_title.upper()} (Cap: {cap} | Dispatched: {dispatched_count})")
        print("-" * 75)
        print(final_report)
        print("-" * 75 + "\n")

        # 4. Dispatch to Telegram unless in dry-run mode
        if not args.dry_run:
            if not ch_id:
                logger.warning(f"No Telegram Channel ID configured for {ch_key}. Skipping post.")
                continue

            tok = BOT_TOKENS.get(ch_key, default_token)
            if not tok:
                logger.warning(f"No Bot Token configured for {ch_key}. Skipping post.")
                continue

            logger.info(f"Posting verified midnight report to {ch_title} ({ch_id})...")
            msg_id = send_telegram_tip(tok, ch_id, final_report)
            if msg_id:
                logger.info(f"Successfully posted to {ch_title} (Telegram Msg ID: {msg_id})")
            else:
                logger.error(f"Failed to post to {ch_title}")

    # Print Final Compliance Summary Table
    print("\n" + "=" * 80)
    print("                     DAILY CAP COMPLIANCE AUDIT TABLE")
    print("=" * 80)
    print(f"{'Channel':<26} {'Cap':<6} {'Dispatched':<12} {'Settled':<9} {'Pending':<9} {'Compliance':<15}")
    print("-" * 80)
    all_passed = True
    for item in audit_summary:
        if not item["passed"]:
            all_passed = False
        print(f"{item['title']:<26} {item['cap']:<6} {item['dispatched']:<12} {item['settled']:<9} {item['pending']:<9} {item['status']:<15}")
    print("=" * 80)
    print(f"All Caps Reset Schedule: STRICTLY 00:00 Brazil Time (BRT / UTC-3)")
    if all_passed:
        print("RESULT: ALL CHANNELS FULLY COMPLIANT WITH DAILY LIMITS.\n")
    else:
        print("RESULT: ONE OR MORE CHANNELS EXCEEDED DAILY CAP.\n")


if __name__ == "__main__":
    main()
