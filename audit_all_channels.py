#!/usr/bin/env python3
"""
Master Audit Runner: Executes and generates separate audit reports for all 5 Telegram channels.
Evaluates each channel 100% independently (zero cross-portfolio blending).
"""

import sys
from audit_engine import CHANNEL_METADATA, audit_channel_data, format_markdown_report, safe_print


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    safe_print("=" * 80)
    safe_print("    MARIO AI - 5 INDEPENDENT TELEGRAM CHANNEL AUDIT SUITE")
    safe_print("=" * 80)

    for ch_key, info in CHANNEL_METADATA.items():
        safe_print(f"\n>>> Running Isolated Audit for: {info['title']} ({ch_key})...")
        report = audit_channel_data(ch_key, target_date)
        md_content = format_markdown_report(report)
        out_file = f"audit_report_{ch_key}.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        safe_print(f"    [OK] Saved isolated report to {out_file}")

    safe_print("\n" + "=" * 80)
    safe_print("All 5 isolated channel reports generated successfully!")
    safe_print("=" * 80)


if __name__ == "__main__":
    main()
