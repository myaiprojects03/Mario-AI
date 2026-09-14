import sys, json, os
from collections import Counter
from datetime import datetime
from sqlalchemy import create_engine, text
from core.config.settings import settings

target_date = "2026-09-08"

# 1. Query production audit log if available
local_log_path = "core/dashboard/live_audit_log.json"
local_counts = Counter()

if os.path.exists(local_log_path):
    with open(local_log_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        ts = str(item.get("timestamp", ""))
        m_name = item.get("market_name", "Unknown")
        if ts.startswith(target_date):
            local_counts[m_name] += 1

print(f"=== SEPTEMBER 8TH, 2026 TIP COUNTS PER TELEGRAM CHANNEL ===")
channel_map = {
    "FIFA Goals Over/Under": "FIFA Goals O/U (-1004313543662)",
    "FIFA Asian Handicap": "FIFA Asian Handicap (-1004348571185)",
    "FIFA Money Line": "FIFA Money Line (-1003923100342)",
    "eBasketball Money Line": "eBasketball Money Line (-1004263450744)",
    "eBasketball Over/Under": "eBasketball Over/Under (-1004452838653)"
}

total_count = 0
for market, display_name in channel_map.items():
    cnt = local_counts.get(market, 0)
    # Also check short names / types
    if cnt == 0:
        for k, v in local_counts.items():
            if market.lower() in k.lower() or k.lower() in market.lower():
                cnt += v
    print(f" - {display_name}: {cnt} tips")
    total_count += cnt

print(f"\nTOTAL TIPS GENERATED ON SEPT 8: {total_count} tips")
