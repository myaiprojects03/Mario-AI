#!/usr/bin/env python3
"""
Diagnostic & Settle Script for Specific Match (core/diagnose_tip_settlement.py)
Checks why BKN Nets (COMBO) x CHI Bulls (UNFORGIVEN) hasn't settled yet.
"""

import os
import sys
import json
import re
import psycopg2
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from dotenv import load_dotenv
    load_dotenv('.env')
    load_dotenv('/app/.env')
except Exception:
    pass

import core.live_publisher as lp
from core.ingestion.jarbet_client import JarBetClient


def diagnose():
    print("=" * 80)
    print("      DIAGNOSING EBASKETBALL TIP SETTLEMENT: COMBO x UNFORGIVEN")
    print("=" * 80)

    # 1. Check PostgreSQL Database for the Published Tip
    conn = lp.get_db_connection()
    if not conn:
        print("[FAIL] Cannot connect to database!")
        return

    tip_record = None
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, match_id, channel_key, channel_id, msg_id, fixture, pick_str, status, outcome, final_score, published_at_utc, msg_text
            FROM core.published_tips
            WHERE fixture ILIKE '%COMBO%' OR fixture ILIKE '%UNFORGIVEN%' OR match_id LIKE '%26858304%' OR msg_text LIKE '%26858304%'
            ORDER BY id DESC
            LIMIT 5;
        """)
        rows = cur.fetchall()

    if rows:
        print(f"[FOUND] {len(rows)} matching published tip(s) in PostgreSQL:")
        for r in rows:
            print(f"  • ID: {r[0]} | Match ID: {r[1]} | Msg ID: {r[4]} | Status: {r[7]} | Outcome: {r[8]} | Score: {r[9]}")
            print(f"    Fixture: {r[5]} | Pick: {r[6]} | Published UTC: {r[10]}")
            tip_record = r
    else:
        print("[WARNING] No tip matching 'COMBO' / '26858304' found in core.published_tips.")
        # Check published_tips_cache.json
        cache = lp.load_published_tips_cache()
        for k, v in cache.items():
            if "COMBO" in str(v) or "26858304" in str(v):
                print(f"[FOUND IN CACHE] Key: {k} -> {v}")

    # 2. Query the JarvisBet API directly for COMBO and UNFORGIVEN
    print("\n--- Querying JarvisBet API Results Feed (/history/ebasket/pre) ---")
    try:
        client = JarBetClient()
    except Exception as e:
        print(f"[FAIL] Could not initialize JarBetClient: {e}")
        return

    found_matches = []
    # 2a. Check /history/ebasket/pre
    for player in ["COMBO", "UNFORGIVEN"]:
        for param in ["homeName", "awayName"]:
            try:
                resp = client._execute_request("GET", "/history/ebasket/pre", params={param: player})
                if resp.status_code == 200:
                    data = resp.json()
                    matches = data.get("matches", data) if isinstance(data, dict) else data
                    if isinstance(matches, list):
                        for m in matches:
                            b365 = str(m.get("idMatchBet365") or m.get("bet365_id") or "")
                            mid = str(m.get("_id") or m.get("id") or "")
                            if "202091064" in b365 or "202091064" in mid or "26858304" in b365 or "26858304" in mid:
                                m["_source_endpoint"] = f"/history/ebasket/pre ({param}={player})"
                                found_matches.append(m)
            except Exception as ex:
                print(f"  • API error for {player} ({param}): {ex}")

    # 2b. Check /matches/ebasket/pre (live / recent matches)
    try:
        live_pre = client.get_ebasket_pre()
        if isinstance(live_pre, list):
            for m in live_pre:
                b365 = str(m.get("idMatchBet365") or m.get("bet365_id") or "")
                mid = str(m.get("_id") or m.get("id") or "")
                if "202091064" in b365 or "202091064" in mid or "26858304" in b365 or "26858304" in mid:
                    m["_source_endpoint"] = "/matches/ebasket/pre"
                    found_matches.append(m)
    except Exception as e:
        print(f"  • Error querying /matches/ebasket/pre: {e}")

    # 2c. Check /matches/ebasket/history
    try:
        hist = client.get_ebasket_history()
        if isinstance(hist, list):
            for m in hist:
                b365 = str(m.get("idMatchBet365") or m.get("bet365_id") or "")
                mid = str(m.get("_id") or m.get("id") or "")
                if "202091064" in b365 or "202091064" in mid or "26858304" in b365 or "26858304" in mid:
                    m["_source_endpoint"] = "/matches/ebasket/history"
                    found_matches.append(m)
    except Exception as e:
        print(f"  • Error querying /matches/ebasket/history: {e}")

    if found_matches:
        print(f"[API MATCH FOUND] Found {len(found_matches)} match entry in API feed:")
        for idx, m in enumerate(found_matches, 1):
            h_obj = m.get("home", {})
            a_obj = m.get("away", {})
            h_score = h_obj.get("score") if h_obj.get("score") is not None else h_obj.get("goals")
            a_score = a_obj.get("score") if a_obj.get("score") is not None else a_obj.get("goals")
            if h_score is None: h_score = m.get("home_score") or m.get("final_home_score")
            if a_score is None: a_score = m.get("away_score") or m.get("final_away_score")

            print(f"  Match #{idx}:")
            print(f"    - ID: {m.get('_id')} | Bet365 ID: {m.get('idMatchBet365')}")
            print(f"    - Status: {m.get('status')} | State: {m.get('state')} | isFinished: {m.get('isFinished')}")
            print(f"    - StartedAt: {m.get('startedAt')} | SettledAt: {m.get('settledAt')}")
            print(f"    - Home: {h_obj.get('teamName')} ({h_obj.get('name')}) -> Score: {h_score}")
            print(f"    - Away: {a_obj.get('teamName')} ({a_obj.get('name')}) -> Score: {a_score}")
            
            if h_score is not None and a_score is not None:
                tot = float(h_score) + float(a_score)
                print(f"    - Total Points: {tot} (Line was 104.5 -> Result: {'WIN (Mais de 104.5)' if tot > 104.5 else 'LOSS'})")
    else:
        print("[API NOTE] Match 26858304 (COMBO x UNFORGIVEN) is not yet present in /history/ebasket/pre.")
        print("  -> This means the upstream JarvisBet API has not yet released the post-match box score for this game.")

    # 3. Trigger Settlement Cycle
    print("\n--- Triggering Live Settlement Cycle ---")
    cache = lp.load_published_tips_cache()
    lp.settle_pending_tips(os.getenv("TELEGRAM_BOT_TOKEN") or lp.TELEGRAM_BOT_TOKEN, cache, client=client)

    # 4. Check if Status Changed
    with conn.cursor() as cur:
        cur.execute("""
            SELECT status, outcome, final_score FROM core.published_tips
            WHERE fixture ILIKE '%COMBO%' OR match_id LIKE '%26858304%'
            ORDER BY id DESC LIMIT 1;
        """)
        row = cur.fetchone()
        if row:
            print(f"[FINAL DB STATUS] Status: {row[0]} | Outcome: {row[1]} | Final Score: {row[2]}")

    conn.close()


if __name__ == "__main__":
    diagnose()
