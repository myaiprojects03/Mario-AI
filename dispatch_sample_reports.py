#!/usr/bin/env python3
"""
Dispatch Sample Telegram Reports (Partial & Midnight)
=====================================================
Directly triggers and sends live sample performance reports to verify:
1. Exact status labels ("Reconciled — Final" vs "Reconciled — Provisional").
2. Clean delivery without being blocked by tip caps.
3. Accurate Daily & MTD figures and Report-Run IDs.

Usage:
  python dispatch_sample_reports.py --dry-run
  python dispatch_sample_reports.py --type partial
  python dispatch_sample_reports.py --type midnight
  python dispatch_sample_reports.py --type both
  python dispatch_sample_reports.py --type partial --channel fifa_goals_ou
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("sample_report_dispatcher")

# Import report engine from core.live_publisher
try:
    from core.live_publisher import (
        generate_performance_report_text,
        send_telegram_tip,
        CHANNEL_MAP,
        BOT_TOKENS,
        TELEGRAM_BOT_TOKEN,
        BRT_TZ
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.live_publisher import (
        generate_performance_report_text,
        send_telegram_tip,
        CHANNEL_MAP,
        BOT_TOKENS,
        TELEGRAM_BOT_TOKEN,
        BRT_TZ
    )


def dispatch_sample(report_type: str = "both", target_channel: str = None, dry_run: bool = False, date_str: str = None):
    now_brt = datetime.now(BRT_TZ)
    today_str = date_str or now_brt.strftime("%Y-%m-%d")
    yesterday_str = (now_brt - timedelta(days=1)).strftime("%Y-%m-%d")

    channels_to_test = {}
    if target_channel:
        if target_channel in CHANNEL_MAP:
            channels_to_test[target_channel] = CHANNEL_MAP[target_channel]
        else:
            logger.error(f"Channel {target_channel} not found in CHANNEL_MAP.")
            return
    else:
        channels_to_test = CHANNEL_MAP

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

            # Generate formatted text using the live authoritative engine
            text, run_id, status_tag = generate_performance_report_text(
                is_midnight=is_mid,
                target_date_str=d_str,
                channel_key=ch_key,
                return_meta=True
            )

            tok = BOT_TOKENS.get(ch_key) or TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN")

            if dry_run:
                print("-" * 75)
                print(f"[DRY-RUN] Target Channel: {ch_key} (ID: {ch_id}) | Run ID: {run_id} | Status: {status_tag}")
                print("-" * 75)
                print(text)
                print("-" * 75)
            else:
                logger.info(f"Sending {r_type} report to {ch_key} ({ch_id})...")
                msg_id = send_telegram_tip(tok, ch_id, text, channel_key=None)
                if msg_id:
                    logger.info(f"SUCCESS: Delivered {r_type} report to {ch_key} -> Telegram Msg ID: {msg_id} [Run ID: {run_id}]")
                else:
                    logger.error(f"FAILED to send {r_type} report to {ch_key}.")

    logger.info("\n" + "=" * 75)
    logger.info("SAMPLE REPORT DISPATCH COMPLETE")
    logger.info("=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Dispatch Sample Performance Reports to Telegram")
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
