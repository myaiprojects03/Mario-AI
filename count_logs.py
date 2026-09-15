import sys
import subprocess
from collections import defaultdict

target_date = sys.argv[1] if len(sys.argv) > 1 else "2026-09-14"

counts = defaultdict(lambda: {"new_tips": 0, "result_edits": 0, "reports": 0})
channels = ["fifa_goals_ou", "fifa_asian_handicap", "fifa_money_line", "ebasket_money_line", "ebasket_ou"]

try:
    proc = subprocess.Popen(["docker", "logs", "mario_ai_live_publisher"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in proc.stdout:
        if target_date not in line:
            continue
        for ch in channels:
            if ch in line:
                if "Successfully dispatched" in line:
                    counts[ch]["new_tips"] += 1
                elif "Updated Telegram tip" in line:
                    counts[ch]["result_edits"] += 1
        if "Performance Report dispatched" in line:
            for ch in channels:
                counts[ch]["reports"] += 1
    proc.wait()
except Exception as e:
    print(f"Error reading docker logs: {e}")

print("\n" + "=" * 75)
print(f"       TOTAL AUDIT COUNTS FOR {target_date}")
print("=" * 75)
print(f"{'Channel Name':<26} | {'New Tips':<10} | {'Result Edits':<14} | {'Reports':<9} | {'Total Msgs':<10}")
print("-" * 75)
for ch in channels:
    c = counts[ch]
    total = c["new_tips"] + c["reports"]
    print(f"{ch:<26} | {c['new_tips']:<10} | {c['result_edits']:<14} | {c['reports']:<9} | {total:<10}")
print("=" * 75 + "\n")
