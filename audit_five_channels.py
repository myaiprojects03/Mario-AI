#!/usr/bin/env python3
"""
Comprehensive 5-Channel Tip Settlement Audit Tool
Audits published tips across all 5 Telegram channels against official results:
1. fifa_goals_ou (FIFA Goals Over/Under)
2. fifa_asian_handicap (FIFA Asian Handicap)
3. fifa_money_line (FIFA Money Line)
4. ebasket_money_line (eBasketball Money Line)
5. ebasket_ou (eBasketball Points Over/Under)

Supports running directly on server (Bare-metal, Systemd, or Docker).
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

# Optional dotenv loading if available
try:
    from dotenv import load_dotenv
    load_dotenv()
    if os.path.exists("d:/Mario AI Code/.env"):
        load_dotenv("d:/Mario AI Code/.env")
    elif os.path.exists(".env"):
        load_dotenv(".env")
except ImportError:
    pass

import psycopg2

CHANNEL_NAMES = {
    "fifa_goals_ou": "FIFA Goals Over/Under",
    "fifa_asian_handicap": "FIFA Asian Handicap",
    "fifa_money_line": "FIFA Money Line",
    "ebasket_money_line": "eBasketball Money Line",
    "ebasket_ou": "eBasketball Over/Under",
}

def get_db_connection():
    """Connects to PostgreSQL using environment or standard fallback strings."""
    candidates = []
    if os.getenv("DATABASE_URL"):
        candidates.append(os.getenv("DATABASE_URL"))
    candidates.extend([
        "postgresql://postgres:postgrespassword@db:5432/mario_ai",
        "postgresql://postgres:sudouser@localhost:5432/Mario_AI",
        "postgresql://postgres:postgrespassword@localhost:5432/mario_ai",
        "postgresql://postgres:postgres@localhost:5432/mario_ai"
    ])
    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        try:
            conn = psycopg2.connect(url, connect_timeout=3)
            return conn
        except Exception:
            continue
    return None

def normalize_match_id(mid: Any) -> str:
    """Normalizes match ID by stripping leading 'E'/'e' prefixes and whitespace."""
    if not mid:
        return ""
    s = str(mid).strip()
    if re.match(r'^[eE]\d+$', s):
        return s[1:]
    return s

def parse_tip_selection_from_msg(msg_text: str, pick_str: str, channel_key: str) -> Tuple[str, float]:
    """Extracts (side, line) using exact Portuguese and market parsing rules."""
    text_to_search = f"{pick_str}\n{msg_text}".lower()

    # 1. Over / Under (Goals or Points)
    if "mais de" in text_to_search or "over" in text_to_search:
        m = re.search(r'(?:mais de|over)\s*([0-9.]+)', text_to_search)
        if m:
            return "over", float(m.group(1))
    elif "menos de" in text_to_search or "under" in text_to_search:
        m = re.search(r'(?:menos de|under)\s*([0-9.]+)', text_to_search)
        if m:
            return "under", float(m.group(1))

    # 2. Asian Handicap
    if "handicap" in text_to_search or "asiático" in text_to_search or "asiatico" in text_to_search or re.search(r'\([+-]?[0-9.]+\)', pick_str):
        m_ah = re.search(r'([+-]?[0-9.]+)\s*\)?$', pick_str.strip())
        if not m_ah:
            m_ah = re.search(r'\(\s*(?:handicap\s+asi[aá]tico\s*)?([+-]?[0-9.]+)\s*\)', pick_str, re.IGNORECASE)
        line_val = float(m_ah.group(1)) if m_ah else 0.0
        # Determine side (home vs away)
        fixture_line = ""
        for line in msg_text.splitlines():
            if line.startswith("Teams/Match:"):
                fixture_line = line.replace("Teams/Match:", "").strip().lower()
        if " x " in fixture_line:
            hp, ap = fixture_line.split(" x ", 1)
            cleaned_pick = re.split(r'\(|\bhandicap\b', pick_str, flags=re.IGNORECASE)[0].strip().lower()
            if hp and (cleaned_pick in hp or hp in cleaned_pick):
                return "home", line_val
            elif ap and (cleaned_pick in ap or ap in cleaned_pick):
                return "away", line_val
        return "home", line_val

    # 3. Money Line / 1X2 / Draw No Bet
    fixture_line = ""
    for line in msg_text.splitlines():
        if line.startswith("Teams/Match:"):
            fixture_line = line.replace("Teams/Match:", "").strip().lower()
    if " x " in fixture_line:
        hp, ap = fixture_line.split(" x ", 1)
        cleaned_team = pick_str.lower()
        for qual in ["(resultado final)", "resultado final", "(empate anula)", "empate anula", "(dnb)", "dnb", "(money line)", "money line"]:
            cleaned_team = cleaned_team.replace(qual, "").strip()
        cleaned_team = cleaned_team.strip(" ()").strip()
        if hp and (cleaned_team in hp or hp in cleaned_team):
            return "home", 0.0
        elif ap and (cleaned_team in ap or ap in cleaned_team):
            return "away", 0.0

    return "home" if "ml" in channel_key else "over", 2.5 if "fifa" in channel_key else 145.5

def evaluate_true_outcome(channel_key: str, side: str, line: float, h_score: float, a_score: float) -> str:
    """Calculates ground truth outcome matching exact betting rules."""
    t_type = str(channel_key).lower()
    side = str(side).lower()

    if "ou" in t_type or "points" in t_type or "goals" in t_type:
        total = h_score + a_score
        diff = (total - line) if side == "over" else (line - total)
        if diff > 0.25 + 1e-5:
            return "WIN"
        elif abs(diff - 0.25) <= 1e-4:
            return "HALF_WIN"
        elif abs(diff) <= 1e-4:
            return "VOID"
        elif abs(diff + 0.25) <= 1e-4:
            return "HALF_LOSS"
        else:
            return "LOSS"

    elif "ah" in t_type or "handicap" in t_type:
        diff = (h_score - a_score + line) if side == "home" else (a_score - h_score + line)
        if diff > 0.25 + 1e-5:
            return "WIN"
        elif abs(diff - 0.25) <= 1e-4:
            return "HALF_WIN"
        elif abs(diff) <= 1e-4:
            return "VOID"
        elif abs(diff + 0.25) <= 1e-4:
            return "HALF_LOSS"
        else:
            return "LOSS"

    elif "ml" in t_type or "money_line" in t_type:
        if side == "home":
            return "WIN" if h_score > a_score else ("VOID" if h_score == a_score else "LOSS")
        else:
            return "WIN" if a_score > h_score else ("VOID" if h_score == a_score else "LOSS")

    return "LOSS"

def load_audit_data():
    """Loads all published tips and cross-references with official results."""
    conn = get_db_connection()
    if not conn:
        print("[ERROR] Could not connect to PostgreSQL database. Check DATABASE_URL.")
        return {}

    tips_by_channel = {k: [] for k in CHANNEL_NAMES.keys()}

    with conn.cursor() as cur:
        # Load all official results mapped by both raw ID and normalized ID
        cur.execute("""
            SELECT r.match_id, 
                   COALESCE(m.raw_payload->>'idMatchBet365', ''),
                   r.final_home_score, 
                   r.final_away_score,
                   COALESCE(m.sport, ''),
                   COALESCE(m.home_player, m.home_team, ''),
                   COALESCE(m.away_player, m.away_team, '')
            FROM core.results r
            LEFT JOIN core.matches m ON r.match_id = m.match_id
            WHERE r.final_home_score IS NOT NULL AND r.final_away_score IS NOT NULL
        """)
        results_map = {}
        for r_mid, b365_id, h, a, sport, hp, ap in cur.fetchall():
            score_data = {
                "home_score": float(h),
                "away_score": float(a),
                "sport": sport,
                "feed_home": hp,
                "feed_away": ap
            }
            if r_mid:
                results_map[str(r_mid)] = score_data
                results_map[normalize_match_id(r_mid)] = score_data
            if b365_id:
                results_map[str(b365_id)] = score_data
                results_map[normalize_match_id(b365_id)] = score_data

        # Load published tips
        cur.execute("""
            SELECT id, match_id, channel_key, fixture, pick_str, side, line, odds, 
                   msg_text, status, outcome, final_score, published_at_utc, kickoff_at_utc, msg_id
            FROM core.published_tips
            WHERE match_id NOT LIKE '%%test%%'
            ORDER BY id ASC
        """)
        rows = cur.fetchall()

        for r in rows:
            tip_id, m_id, ch_key, fixture, pick_str, side, line, odds, msg_text, status, outcome, final_score_str, pub_at, ko_at, msg_id = r
            if ch_key not in tips_by_channel:
                continue

            # Look up verified official score
            norm_id = normalize_match_id(m_id)
            score_data = (
                results_map.get(str(m_id)) 
                or results_map.get(norm_id) 
                or results_map.get(f"E{norm_id}")
            )

            # Fallback to score string recorded in tip if match finished
            official_h = None
            official_a = None
            feed_hp = ""
            feed_ap = ""

            if score_data:
                official_h = score_data["home_score"]
                official_a = score_data["away_score"]
                feed_hp = score_data.get("feed_home", "")
                feed_ap = score_data.get("feed_away", "")
            elif final_score_str and "-" in str(final_score_str):
                try:
                    parts = str(final_score_str).split("-")
                    official_h = float(parts[0])
                    official_a = float(parts[1])
                except Exception:
                    pass

            # Ground truth selection
            parsed_side, parsed_line = parse_tip_selection_from_msg(msg_text or "", pick_str or "", ch_key)
            eff_side = parsed_side or str(side or "home")
            eff_line = parsed_line if parsed_line is not None else float(line or 0.0)

            # Plausibility & Swapped feed alignment check
            swapped = False
            true_outcome = None
            audit_status = "PENDING"
            reason = ""

            if official_h is not None and official_a is not None:
                # Check for feed team swap
                tip_fixture_l = str(fixture or "").lower()
                if feed_hp and feed_ap and " x " in tip_fixture_l:
                    t_hp, t_ap = tip_fixture_l.split(" x ", 1)
                    if (feed_hp.lower() in t_ap and feed_ap.lower() in t_hp):
                        swapped = True
                        official_h, official_a = official_a, official_h

                # Check plausibility
                is_eb = "ebasket" in ch_key
                tot_score = official_h + official_a
                if is_eb and (tot_score < 45.0 or official_h < 15.0 or official_a < 15.0):
                    audit_status = "REJECTED_IMPLAUSIBLE_SCORE"
                    reason = f"Implausible basketball score ({official_h}-{official_a} < 45 pts). Must remain Pending."
                elif not is_eb and (tot_score > 30.0 or official_h > 20.0 or official_a > 20.0):
                    audit_status = "REJECTED_IMPLAUSIBLE_SCORE"
                    reason = f"Implausible FIFA score ({official_h}-{official_a} > 30 goals). Must remain Pending."
                else:
                    true_outcome = evaluate_true_outcome(ch_key, eff_side, eff_line, official_h, official_a)
                    rec_out = str(outcome or status or "").upper()

                    if not rec_out or rec_out == "PENDING":
                        audit_status = "PENDING"
                        reason = "Match not yet settled in system."
                    elif rec_out == true_outcome or (rec_out in ["WIN", "WON"] and true_outcome in ["WIN", "WON"]):
                        audit_status = "CORRECT"
                        reason = "Recorded outcome exactly matches official score and settlement rules."
                    else:
                        audit_status = "INCORRECT_SETTLEMENT"
                        reason = f"Recorded as {rec_out}, but official score {int(official_h)}-{int(official_a)} evaluates to {true_outcome}."
            else:
                audit_status = "PENDING"
                reason = "Official full-time score not yet confirmed by provider."

            score_str_repr = f"{int(official_h)}-{int(official_a)}" if (official_h is not None and official_a is not None) else "Pending"

            tips_by_channel[ch_key].append({
                "tip_id": tip_id,
                "msg_id": msg_id,
                "match_id": m_id,
                "fixture": fixture,
                "pick_str": pick_str,
                "market": CHANNEL_NAMES.get(ch_key, ch_key),
                "side": eff_side,
                "line": eff_line,
                "odds": float(odds or 1.90),
                "recorded_status": outcome or status or "PENDING",
                "official_score": score_str_repr,
                "correct_outcome": true_outcome or "PENDING",
                "audit_status": audit_status,
                "swapped_score_aligned": swapped,
                "reason": reason,
                "published_at": pub_at.strftime("%Y-%m-%d %H:%M UTC") if pub_at else "N/A"
            })

    conn.close()
    return tips_by_channel

def print_and_save_audit_report(tips_by_channel: Dict[str, List[Dict[str, Any]]]):
    """Prints terminal summary and generates AUDIT_REPORT_5_CHANNELS.md / .txt."""
    total_reviewed = 0
    total_correct = 0
    total_incorrect = 0
    total_pending = 0

    lines = []
    lines.append("# AUDIT REPORT: 5 TELEGRAM GROUPS / CHANNELS")
    lines.append(f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("**Status**: Official Verification Against PostgreSQL Source-of-Truth & Verified Feeds\n")
    lines.append("---\n")

    lines.append("## 1. Executive Summary Across All 5 Channels\n")
    lines.append("| Channel / Group | Reviewed | Correct | Incorrect | Pending | Accuracy % |")
    lines.append("|---|---|---|---|---|---|")

    summary_terminal = []

    for ch_key, ch_name in CHANNEL_NAMES.items():
        tips = tips_by_channel.get(ch_key, [])
        n_rev = len(tips)
        n_corr = sum(1 for t in tips if t["audit_status"] == "CORRECT")
        n_inc = sum(1 for t in tips if t["audit_status"] == "INCORRECT_SETTLEMENT")
        n_pend = sum(1 for t in tips if t["audit_status"] in ["PENDING", "REJECTED_IMPLAUSIBLE_SCORE"])

        acc = (n_corr / (n_corr + n_inc) * 100.0) if (n_corr + n_inc) > 0 else 100.0

        total_reviewed += n_rev
        total_correct += n_corr
        total_incorrect += n_inc
        total_pending += n_pend

        lines.append(f"| **{ch_name}** | {n_rev} | {n_corr} | {n_inc} | {n_pend} | {acc:.1f}% |")
        summary_terminal.append({
            "channel": ch_name,
            "reviewed": n_rev,
            "correct": n_corr,
            "incorrect": n_inc,
            "pending": n_pend,
            "acc": acc
        })

    overall_acc = (total_correct / (total_correct + total_incorrect) * 100.0) if (total_correct + total_incorrect) > 0 else 100.0
    lines.append(f"| **TOTAL / OVERALL** | **{total_reviewed}** | **{total_correct}** | **{total_incorrect}** | **{total_pending}** | **{overall_acc:.1f}%** |\n")

    lines.append("---\n")
    lines.append("## 2. Detailed Per-Channel Audit & Tip Verification\n")

    for ch_key, ch_name in CHANNEL_NAMES.items():
        tips = tips_by_channel.get(ch_key, [])
        lines.append(f"### Channel: {ch_name} (`{ch_key}`)")
        lines.append(f"Total tips in this channel: **{len(tips)}**\n")

        if not tips:
            lines.append("_No published tips recorded for this channel yet._\n")
            continue

        lines.append("| Tip ID | Match ID | Fixture | Selection | Line | Odds | Official Score | Recorded | Correct | Audit Status |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for t in tips:
            lines.append(
                f"| #{t['tip_id']} | `{t['match_id']}` | {t['fixture']} | {t['pick_str']} | {t['line']} | {t['odds']:.2f} | "
                f"**{t['official_score']}** | {t['recorded_status']} | **{t['correct_outcome']}** | `{t['audit_status']}` |"
            )
        lines.append("\n")

    # Affected / Discrepancy section
    lines.append("## 3. Discrepancies & Required Corrections (Audit Trail)\n")
    all_affected = []
    for ch_key, tips in tips_by_channel.items():
        for t in tips:
            if t["audit_status"] == "INCORRECT_SETTLEMENT":
                all_affected.append(t)

    lines.append(f"Total Affected Tips Requiring Correction: **{len(all_affected)}**\n")

    if all_affected:
        lines.append("| Tip ID | Match ID | Channel | Fixture | Selection | Recorded Result | Official Score | Correct Result | Reason |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for a in all_affected:
            lines.append(
                f"| #{a['tip_id']} | `{a['match_id']}` | {a['market']} | {a['fixture']} | {a['pick_str']} | "
                f"~~{a['recorded_status']}~~ | **{a['official_score']}** | **{a['correct_outcome']}** | {a['reason']} |"
            )
        lines.append("\n")
    else:
        lines.append("✅ **No settlement discrepancies found. 100% of finished tips match official scores.**\n")

    report_content = "\n".join(lines)

    # Save to Markdown and Text
    for fname in ["AUDIT_REPORT_5_CHANNELS.md", "AUDIT_REPORT_5_CHANNELS.txt"]:
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report_content)

    # Save JSON for automated dashboard/API ingestion
    with open("AUDIT_REPORT_5_CHANNELS.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_reviewed": total_reviewed,
                "total_correct": total_correct,
                "total_incorrect": total_incorrect,
                "total_pending": total_pending,
                "accuracy_percent": overall_acc
            },
            "channels": tips_by_channel
        }, f, indent=2)

    # Print Terminal Dashboard
    print("\n" + "=" * 80)
    print("           5-CHANNEL AUDIT SUMMARY REPORT")
    print("=" * 80)
    print(f"{'Channel':<30} | {'Reviewed':<8} | {'Correct':<8} | {'Incorrect':<9} | {'Pending':<8} | {'Accuracy':<8}")
    print("-" * 80)
    for s in summary_terminal:
        print(f"{s['channel']:<30} | {s['reviewed']:<8} | {s['correct']:<8} | {s['incorrect']:<9} | {s['pending']:<8} | {s['acc']:<6.1f}%")
    print("-" * 80)
    print(f"{'TOTAL / OVERALL':<30} | {total_reviewed:<8} | {total_correct:<8} | {total_incorrect:<9} | {total_pending:<8} | {overall_acc:<6.1f}%")
    print("=" * 80)
    print(f"Generated Audit Reports:\n  -> AUDIT_REPORT_5_CHANNELS.md\n  -> AUDIT_REPORT_5_CHANNELS.txt\n  -> AUDIT_REPORT_5_CHANNELS.json")
    print("=" * 80 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Audit all 5 Telegram channels against official results.")
    args = parser.parse_args()

    print("[1/2] Connecting to PostgreSQL database and scanning all 5 channels...")
    tips_by_channel = load_audit_data()

    if not tips_by_channel:
        print("[ERROR] No tip data loaded. Ensure PostgreSQL service is reachable.")
        sys.exit(1)

    print("[2/2] Reconciling selections, official full-time scores, and generating reports...")
    print_and_save_audit_report(tips_by_channel)

if __name__ == "__main__":
    main()
