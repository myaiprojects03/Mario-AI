#!/usr/bin/env python3
"""
Single-Channel Audit Runner: Matrix FIFA Pre ML G01
Market: FIFA Money Line / 1X2 (fifa_money_line)
"""

import sys
import os
from audit_engine import audit_channel_data, format_markdown_report, safe_print

CHANNEL_KEY = "fifa_money_line"
REPORT_OUTPUT_MD = "audit_report_fifa_money_line.md"


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else None
    safe_print(f"[*] Starting Isolated Channel Audit for: {CHANNEL_KEY}...")
    
    report = audit_channel_data(CHANNEL_KEY, target_date)
    md_content = format_markdown_report(report)
    
    # Save markdown report
    with open(REPORT_OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    # Print to console
    safe_print("\n" + md_content)
    safe_print(f"\n[+] Full isolated audit report saved to: {REPORT_OUTPUT_MD}")


if __name__ == "__main__":
    main()
