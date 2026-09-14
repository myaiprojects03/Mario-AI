import subprocess

ssh_cmd = "docker exec mario_ai_live_publisher python -c \"import json, os, collections; path='core/dashboard/live_audit_log.json'; data=json.load(open(path)) if os.path.exists(path) else []; sep8=[i for i in data if str(i.get('timestamp','')).startswith('2026-09-08')]; print('=== SEPTEMBER 8TH PRODUCTION TIP COUNTS ==='); counts=collections.Counter(i.get('market_name') for i in sep8); [print(f' - {k}: {v} tips') for k, v in counts.items()]; print('Total Sept 8 Tips:', len(sep8))\""

try:
    res = subprocess.run(["ssh", "root@24.199.87.126", ssh_cmd], capture_output=True, text=True, timeout=15)
    print(res.stdout)
    if res.stderr:
        print("STDERR:", res.stderr)
except Exception as e:
    print("SSH execution failed:", e)
