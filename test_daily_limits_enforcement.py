#!/usr/bin/env python3
"""
Unit & Integration Test for Channel Daily Limits
================================================
Validates that:
1. FIFA Asian Handicap enforces strict cap of 100 tips.
2. FIFA Goals O/U, Money Line, and eBasket enforce strict cap of 150 tips.
3. Pre-dispatch check is_daily_limit_reached() blocks new tips immediately once the cap is reached.
4. Suppressed tips are never sent to Telegram.
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

import core.live_publisher as lp
from core.live_publisher import (
    DAILY_TIP_LIMITS,
    is_daily_limit_reached,
    get_today_published_tip_count,
    BRT_TZ,
    load_daily_tip_ledger,
    ChannelDispatchRateLimiter
)

def run_daily_limit_tests():
    print("=" * 110)
    print(" MARIO AI CHANNEL DAILY LIMITS ENFORCEMENT TEST")
    print("=" * 110)

    # 1. Verify configured limits
    expected_limits = {
        "fifa_asian_handicap": 100,
        "fifa_goals_ou": 150,
        "fifa_money_line": 150,
        "ebasket_money_line": 150,
        "ebasket_ou": 150,
    }

    print("\n[STEP 1: VERIFYING CONFIGURED CHANNEL CAPS]")
    print("-" * 110)
    for ch, exp_lim in expected_limits.items():
        actual_lim = DAILY_TIP_LIMITS.get(ch)
        status = "PASS" if actual_lim == exp_lim else "FAIL"
        print(f"• {ch:<25} : Configured Cap = {actual_lim:<3} (Expected: {exp_lim:<3}) -> [{status}]")
        assert actual_lim == exp_lim, f"Mismatch for {ch}: got {actual_lim}, expected {exp_lim}"

    # 2. Test pre-dispatch blocking on Asian Handicap (100 Cap)
    print("\n[STEP 2: TESTING ASIAN HANDICAP CAP SUPPRESSION (100 LIMIT)]")
    print("-" * 110)
    today_str = datetime.now(BRT_TZ).strftime("%Y-%m-%d")

    # Mock daily ledger with 99 tips (Under limit)
    mock_ledger = {
        today_str: {
            "fifa_asian_handicap": [f"M_{i}" for i in range(99)],
            "fifa_goals_ou": [f"G_{i}" for i in range(149)]
        }
    }
    lp.load_daily_tip_ledger = lambda: mock_ledger
    lp.load_settled_tips_ledger = lambda: []
    lp.load_published_tips_cache = lambda: {}

    # Under limit check
    assert is_daily_limit_reached("fifa_asian_handicap") == False, "At 99/100, Asian Handicap must NOT be blocked"
    assert is_daily_limit_reached("fifa_goals_ou") == False, "At 149/150, Goals O/U must NOT be blocked"
    print("• Under Cap Check (99/100 for AH, 149/150 for Goals) : PASS (Allowed for dispatch)")

    # Reached limit check (100 for AH, 150 for Goals)
    mock_ledger[today_str]["fifa_asian_handicap"].append("M_99")
    mock_ledger[today_str]["fifa_goals_ou"].append("G_149")

    assert is_daily_limit_reached("fifa_asian_handicap") == True, "At 100/100, Asian Handicap MUST be blocked"
    assert is_daily_limit_reached("fifa_goals_ou") == True, "At 150/150, Goals O/U MUST be blocked"
    print("• At Cap Check (100/100 for AH, 150/150 for Goals)    : PASS (Strictly BLOCKED & Suppressed)")

    # 3. Test RateLimiter Queue Dropping
    print("\n[STEP 3: TESTING RATELIMITER QUEUE SUPPRESSION]")
    print("-" * 110)
    limiter = ChannelDispatchRateLimiter()
    intercepted_dispatches = []
    lp.send_telegram_tip = lambda *args: intercepted_dispatches.append(args)

    cand = {
        "match_id": "999999",
        "fixture": "Test AH Team A x Team B",
        "kickoff_at_utc": datetime.now(timezone.utc) + timedelta(minutes=10),
        "eligible_at_brt": datetime.now(BRT_TZ),
        "odds_val": 1.90,
        "line": -0.5,
        "side": "home",
        "pick_str": "Team A -0.5",
        "est_prob_str": "60%",
        "edge_str": "+10%",
        "msg_text": "Test Tip",
        "link_url": "https://www.bet365.com/#/IP/EV999999"
    }
    limiter.enqueue_candidate("fifa_asian_handicap", cand)
    limiter.process_queues("tok", {})

    assert len(intercepted_dispatches) == 0, "No telegram message should be sent when cap is reached!"
    assert len(limiter.get_channel_state("fifa_asian_handicap")["queue"]) == 0, "Candidate must be popped and dropped from queue!"
    print("• RateLimiter Cap Drop Execution                     : PASS (Candidate dropped, 0 messages sent)")

    print("\n" + "=" * 110)
    print(" [ALL DAILY CAP TESTS PASSED: 100% SUCCESS]")
    print("=" * 110)

if __name__ == "__main__":
    run_daily_limit_tests()
