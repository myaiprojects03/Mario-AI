#!/usr/bin/env python3
"""
Self-Contained eBasketball Diagnostic Utility (check_ebasket.py)
==============================================================
Pure Python (zero external dependencies like sqlalchemy or dotenv needed).
Works directly on host and inside Docker container.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import subprocess

print("\n" + "=" * 75)
print("       EBASKETBALL CHANNEL & API DIAGNOSTIC")
print("=" * 75 + "\n")

# 1. Parse .env file manually from disk or Docker container
env_vars = {}

# Check common .env locations
env_candidates = [
    ".env",
    "/root/mario-ai-code/.env",
    "/root/mario-ai-code/core/.env",
    "/app/.env"
]
for path in env_candidates:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        env_vars[k] = v
            print(f"[OK] Successfully loaded environment settings from: {path}")
            break
        except Exception:
            pass

# Also pull from active docker container env if available
if not env_vars.get("TELEGRAM_BOT_TOKEN"):
    try:
        res = subprocess.run("docker exec mario_ai_live_publisher env 2>/dev/null", shell=True, stdout=subprocess.PIPE, text=True, timeout=5)
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")
            print("[OK] Loaded environment settings directly from running Docker container.")
    except Exception:
        pass

# Merge with os.environ
for k, v in os.environ.items():
    if k not in env_vars and v:
        env_vars[k] = v

# 2. Inspect Telegram Bot Token & Channel IDs
print("\n[1] Telegram Configuration:")
bot_token = env_vars.get("TELEGRAM_BOT_TOKEN", "").strip()

# Check all possible alias names for eBasket channels
eb_ml_channel = (
    env_vars.get("TELEGRAM_CHANNEL_EBASKET_ML")
    or env_vars.get("TELEGRAM_CHANNEL_EBASKET_MONEY_LINE")
    or env_vars.get("TELEGRAM_CHANNEL_EBASKETBALL_ML")
    or env_vars.get("TELEGRAM_CHANNEL_EBASKET")
    or ""
).strip()

eb_ou_channel = (
    env_vars.get("TELEGRAM_CHANNEL_EBASKET_OU")
    or env_vars.get("TELEGRAM_CHANNEL_EBASKET_OVER_UNDER")
    or env_vars.get("TELEGRAM_CHANNEL_EBASKETBALL_OU")
    or env_vars.get("TELEGRAM_CHANNEL_EBASKET_POINTS")
    or ""
).strip()

fifa_goals_ch = env_vars.get("TELEGRAM_CHANNEL_FIFA_GOALS_OU") or env_vars.get("TELEGRAM_CHANNEL_FIFA_GOALS", "")
fifa_ah_ch = env_vars.get("TELEGRAM_CHANNEL_FIFA_ASIAN_HANDICAP") or env_vars.get("TELEGRAM_CHANNEL_FIFA_AH", "")
fifa_ml_ch = env_vars.get("TELEGRAM_CHANNEL_FIFA_MONEY_LINE") or env_vars.get("TELEGRAM_CHANNEL_FIFA_ML", "")

print(f" - Bot Token:                     {'[CONFIGURED]' if bot_token else '[MISSING in .env]'}")
print(f" - FIFA Goals O/U Channel:        {fifa_goals_ch if fifa_goals_ch else '[NOT SET]'}")
print(f" - FIFA Asian Handicap Channel:   {fifa_ah_ch if fifa_ah_ch else '[NOT SET]'}")
print(f" - FIFA Money Line Channel:       {fifa_ml_ch if fifa_ml_ch else '[NOT SET]'}")
print(f" - eBasket Money Line Channel:    {eb_ml_channel if eb_ml_channel else '[MISSING / NOT SET in .env]'}")
print(f" - eBasket Over/Under Channel:     {eb_ou_channel if eb_ou_channel else '[MISSING / NOT SET in .env]'}")

# 3. Check Live JarBet API for eBasketball Fixtures (Pure HTTP request)
print("\n[2] Live JarBet API Check:")
jarbet_key = env_vars.get("JARBET_API_KEY", "b365_live_api_token_2026_prod")
jarbet_base = env_vars.get("JARBET_BASE_URL", "https://data.jarvisbet.com.br")

print(f" - JarBet Base URL: {jarbet_base}")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}
if jarbet_key:
    headers["Authorization"] = f"Bearer {jarbet_key}"
    headers["x-api-key"] = jarbet_key

ebasket_matches = []
for endpoint in ["/ebasket/pre", "/fixtures/ebasket/pre", "/pre"]:
    try:
        url = f"{jarbet_base.rstrip('/')}{endpoint}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                ebasket_matches = data
            elif isinstance(data, dict):
                ebasket_matches = data.get("data") or data.get("matches") or data.get("fixtures") or []
            if ebasket_matches:
                print(f" [OK] Retrieved {len(ebasket_matches)} live fixtures from {endpoint}!")
                break
    except Exception as api_err:
        continue

if ebasket_matches:
    print("\n Sample Upcoming eBasketball Matches:")
    for idx, m in enumerate(ebasket_matches[:3], 1):
        h_obj = m.get("home", {}) if isinstance(m.get("home"), dict) else {}
        a_obj = m.get("away", {}) if isinstance(m.get("away"), dict) else {}
        h_name = h_obj.get("teamName") or h_obj.get("name") or m.get("homeTeam") or "Home"
        a_name = a_obj.get("teamName") or a_obj.get("name") or m.get("awayTeam") or "Away"
        odds = m.get("odds", {})
        print(f"   {idx}. {h_name} vs {a_name} | Started/Starts: {m.get('startedAt', 'N/A')}")
        print(f"      Odds: {odds if odds else 'No odds payload'}")
else:
    print(" [NOTE] No live eBasketball matches returned from API right now.")

# 4. Test Telegram Connectivity & Admin Permissions
print("\n[3] Testing Telegram Bot Connectivity to eBasket Channels:")
if not bot_token:
    print(" [FAIL] Cannot test Telegram channels because TELEGRAM_BOT_TOKEN is missing.")
else:
    channels = [
        ("eBasket Money Line", eb_ml_channel, "TELEGRAM_CHANNEL_EBASKET_ML"),
        ("eBasket Over/Under", eb_ou_channel, "TELEGRAM_CHANNEL_EBASKET_OU")
    ]
    for name, ch_id, var_name in channels:
        if not ch_id:
            print(f" [FAIL] {name}: '{var_name}' is not set in your .env file!")
            print(f"        -> Fix: Add '{var_name}=-100xxxxxxxxxx' to your .env file.")
            continue
            
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getChat"
            data = urllib.parse.urlencode({"chat_id": ch_id}).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=6) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                if res_json.get("ok"):
                    chat_title = res_json.get("result", {}).get("title", "Unknown Title")
                    print(f" [OK] {name} ({ch_id}): Bot is connected to '{chat_title}'!")
                else:
                    print(f" [FAIL] {name} ({ch_id}): Telegram returned: {res_json}")
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            print(f" [FAIL] {name} ({ch_id}): HTTP {he.code} -> {err_body}")
            print("        -> Ensure bot is added as an Administrator in this channel.")
        except Exception as ex:
            print(f" [ERROR] {name} ({ch_id}): {ex}")

print("\n" + "=" * 75)
print(" Diagnostic Complete.")
print("=" * 75 + "\n")
