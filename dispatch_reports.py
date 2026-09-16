import os
import sys
import argparse
import logging
from core.live_publisher import (
    generate_performance_report_text,
    send_telegram_tip,
    BOT_TOKENS,
    CHANNEL_MAP,
    TELEGRAM_BOT_TOKEN
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dispatch_reports")

def parse_args():
    parser = argparse.ArgumentParser(description="Dispatch Performance Reports to Telegram Channels")
    parser.add_argument("--type", choices=["partial", "midnight", "both"], default="partial", help="Type of report to send (partial, midnight, both)")
    parser.add_argument("--date", type=str, default=None, help="Target date in YYYY-MM-DD format (Optional)")
    parser.add_argument("--channel", type=str, default="all_channels", help="Specific channel key or all_channels")
    return parser.parse_args()

def dispatch_report(is_midnight: bool, target_date: str = None, target_channel: str = "all_channels"):
    report_name = "Midnight Final & MTD Performance Report" if is_midnight else "Partial (12:00 BRT) Performance Report"
    logger.info(f"Generating {report_name} across channels...")

    default_token = os.getenv("TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
    sent_count = 0

    target_map = CHANNEL_MAP if target_channel in ["all_channels", "all"] else {target_channel: CHANNEL_MAP.get(target_channel)}

    for m_key, ch_id in target_map.items():
        if ch_id:
            token = BOT_TOKENS.get(m_key, default_token)
            if token:
                report_text = generate_performance_report_text(is_midnight=is_midnight, target_date_str=target_date, channel_key=m_key)
                print("\n" + "=" * 60)
                print(f"       DISPATCHING {report_name.upper()} TO {m_key.upper()}")
                print("=" * 60)
                print(report_text)
                print("=" * 60 + "\n")
                logger.info(f"Sending {report_name} to {m_key} (Channel: {ch_id})...")
                msg_id = send_telegram_tip(token, ch_id, report_text, m_key)
                if msg_id:
                    sent_count += 1
                    logger.info(f"Successfully posted report to {m_key} (Message ID: {msg_id})")
                else:
                    logger.warning(f"Failed to post report to {m_key}")
            else:
                logger.warning(f"No bot token found for {m_key}")
        else:
            logger.warning(f"No channel ID configured for {m_key}")

    print(f"\nDispatched {report_name} to {sent_count}/{len(target_map)} channels successfully!\n")

def main():
    args = parse_args()
    if args.type in ["partial", "both"]:
        dispatch_report(is_midnight=False, target_date=args.date, target_channel=args.channel)
    if args.type in ["midnight", "both"]:
        dispatch_report(is_midnight=True, target_date=args.date, target_channel=args.channel)

if __name__ == "__main__":
    main()
