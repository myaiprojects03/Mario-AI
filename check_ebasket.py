#!/usr/bin/env python3
"""
Quick eBasketball Diagnostic Utility (check_ebasket.py)
"""

import os
import sys
import json
import urllib.request
import urllib.parse

print("\n" + "=" * 75)
print("       EBASKETBALL CHANNEL & API DIAGNOSTIC")
print("=" * 75 + "\n")

# 1. Check Channel IDs in Environment
print("[1] Checking Environment Variables...")
bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

eb_ml_channel = (
    os.getenv("TELEGRAM_CHANNEL_EBASKET_ML")
    or os.getenv("TELEGRAM_CHANNEL_EBASKET_MONEY_LINE")
    or os.getenv("TELEGRAM_CHANNEL_EBASKETBALL_ML")
    or ""
).strip()

eb_ou_channel = (
    os.getenv("TELEGRAM_CHANNEL_EBASKET_OU")
    or os.getenv("TELEGRAM_CHANNEL_EBASKET_OVER_UNDER")
    or os.getenv("TELEGRAM_CHANNEL_EBASKETBALL_OU")
    or ""
).strip()

print(f" - TELEGRAM_BOT_TOKEN: {'[SET]' if bot_token else '[MISSING - check .env]'}")
print(f" - eBasket Money Line Channel: {eb_ml_channel if eb_ml_channel else '[MISSING - not found in .env]'}")
print(f" - eBasket Over/Under Channel:  {eb_ou_channel if eb_ou_channel else '[MISSING - not found in .env]'}")

# 2. Check Live JarBet API Pre-Match Fixtures
print("\n[2] Checking Live JarBet API for eBasketball pre-match fixtures...")
try:
    from core.ingestion.jarbet_client import JarBetClient
    client = JarBetClient()
    matches = client.get_ebasket_pre() or []
    print(f" [OK] Retrieved {len(matches)} live eBasketball pre-match fixtures from JarBet API.")
    if matches:
        print("\n Upcoming Matches:")
        for idx, m in enumerate(matches[:3], 1):
            h_obj = m.get("home", {}) if isinstance(m.get("home"), dict) else {}
            a_obj = m.get("away", {}) if isinstance(m.get("away"), dict) else {}
            h_name = h_obj.get("teamName") or h_obj.get("name") or m.get("homeTeam") or "Home"
            a_name = a_obj.get("teamName") or a_obj.get("name") or m.get("awayTeam") or "Away"
            odds = m.get("odds", {})
            print(f"   {idx}. {h_name} vs {a_name} | Start: {m.get('startedAt', 'N/A')}")
            print(f"      Odds: {odds if odds else 'No odds payload'}")
    else:
        print(" [NOTE] No live eBasketball matches currently scheduled in API right now.")
except Exception as e:
    print(f" [ERROR] Failed to query JarBet API: {e}")

# 3. Test Telegram Bot Connection to Channels
print("\n[3] Testing Telegram Bot Channel Connectivity...")
if not bot_token:
    print(" [SKIP] Cannot test Telegram channels without TELEGRAM_BOT_TOKEN.")
else:
    channels_to_test = [
        ("eBasket Money Line", eb_ml_channel),
        ("eBasket Over/Under", eb_ou_channel)
    ]
    for name, ch_id in channels_to_test:
        if not ch_id:
            print(f" [SKIP] {name}: Channel ID is not configured.")
            continue
        
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getChat"
            data = urllib.parse.urlencode({"chat_id": ch_id}).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if res_data.get("ok"):
                    title = res_data.get("result", {}).get("title", "Unknown Title")
                    print(f" [OK] {name} ({ch_id}): Bot has access to '{title}'!")
                else:
                    print(f" [FAIL] {name} ({ch_id}): {res_data}")
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="ignore")
            print(f" [FAIL] {name} ({ch_id}): HTTP {he.code} - {err_body}")
        except Exception as ex:
            print(f" [ERROR] {name} ({ch_id}): {ex}")

print("\n" + "=" * 75)
print(" Diagnostic Complete.")
print("=" * 75 + "\n")
