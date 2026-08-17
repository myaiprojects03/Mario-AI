import sys
import site
import json
from datetime import timedelta
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    print("==========================================================================")
    print("           PRE-TRAINING DATA INTEGRITY & DE-DUPLICATION AUDIT")
    print("==========================================================================")
    print(f"Target Database URL: {settings.DATABASE_URL}")

    engine = create_engine(settings.DATABASE_URL)
    conn = engine.connect()

    # -------------------------------------------------------------------
    # ITEM 1: Date ranges for source='csv_backfill' (fifa vs ebasket)
    # -------------------------------------------------------------------
    print("\n--- 1. CSV BACKFILL DATE RANGES ---")
    query_csv_fifa = text("""
        SELECT MIN(match_start_time), MAX(match_start_time), COUNT(*)
        FROM core.matches
        WHERE source = 'csv_backfill' AND sport = 'fifa'
    """)
    res_csv_fifa = conn.execute(query_csv_fifa).fetchone()
    min_csv_fifa, max_csv_fifa, count_csv_fifa = res_csv_fifa

    query_csv_ebasket = text("""
        SELECT MIN(match_start_time), MAX(match_start_time), COUNT(*)
        FROM core.matches
        WHERE source = 'csv_backfill' AND sport = 'ebasket'
    """)
    res_csv_ebasket = conn.execute(query_csv_ebasket).fetchone()
    min_csv_ebasket, max_csv_ebasket, count_csv_ebasket = res_csv_ebasket

    print(f"FIFA (csv_backfill): {count_csv_fifa:,} rows | Range: {min_csv_fifa} to {max_csv_fifa}")
    print(f"eBasketball (csv_backfill): {count_csv_ebasket:,} rows | Range: {min_csv_ebasket} to {max_csv_ebasket}")

    # Query source='jarbet_history' date ranges
    query_jhist_fifa = text("""
        SELECT MIN(match_start_time), MAX(match_start_time), COUNT(*)
        FROM core.matches
        WHERE source = 'jarbet_history' AND sport = 'fifa'
    """)
    res_jhist_fifa = conn.execute(query_jhist_fifa).fetchone()
    min_jhist_fifa, max_jhist_fifa, count_jhist_fifa = res_jhist_fifa

    query_jhist_ebasket = text("""
        SELECT MIN(match_start_time), MAX(match_start_time), COUNT(*)
        FROM core.matches
        WHERE source = 'jarbet_history' AND sport = 'ebasket'
    """)
    res_jhist_ebasket = conn.execute(query_jhist_ebasket).fetchone()
    min_jhist_ebasket, max_jhist_ebasket, count_jhist_ebasket = res_jhist_ebasket

    print(f"FIFA (jarbet_history): {count_jhist_fifa:,} rows | Range: {min_jhist_fifa} to {max_jhist_fifa}")
    print(f"eBasketball (jarbet_history): {count_jhist_ebasket:,} rows | Range: {min_jhist_ebasket} to {max_jhist_ebasket}")

    # -------------------------------------------------------------------
    # ITEM 2: Date overlap window between csv_backfill and jarbet_history
    # -------------------------------------------------------------------
    print("\n--- 2. DATE OVERLAP WINDOW ANALYSIS ---")
    overlap_start_fifa = max(min_csv_fifa, min_jhist_fifa) if min_csv_fifa and min_jhist_fifa else None
    overlap_end_fifa = min(max_csv_fifa, max_jhist_fifa) if max_csv_fifa and max_jhist_fifa else None

    if overlap_start_fifa and overlap_end_fifa and overlap_start_fifa <= overlap_end_fifa:
        duration_fifa = overlap_end_fifa - overlap_start_fifa
        print(f"FIFA Overlap Window: {overlap_start_fifa} to {overlap_end_fifa} ({duration_fifa.days} days, {duration_fifa.seconds // 3600} hours)")
    else:
        print(f"FIFA Overlap Window: NONE (CSV max {max_csv_fifa} < JarBet min {min_jhist_fifa})")

    overlap_start_ebasket = max(min_csv_ebasket, min_jhist_ebasket) if min_csv_ebasket and min_jhist_ebasket else None
    overlap_end_ebasket = min(max_csv_ebasket, max_jhist_ebasket) if max_csv_ebasket and max_jhist_ebasket else None

    if overlap_start_ebasket and overlap_end_ebasket and overlap_start_ebasket <= overlap_end_ebasket:
        duration_ebasket = overlap_end_ebasket - overlap_start_ebasket
        print(f"eBasketball Overlap Window: {overlap_start_ebasket} to {overlap_end_ebasket} ({duration_ebasket.days} days, {duration_ebasket.seconds // 3600} hours)")
    else:
        print(f"eBasketball Overlap Window: NONE (CSV max {max_csv_ebasket} < JarBet min {min_jhist_ebasket})")

    # -------------------------------------------------------------------
    # ITEM 3: Looser Match Overlap Detection (+/- 5 min tolerance, same league, home_player, away_player)
    # -------------------------------------------------------------------
    print("\n--- 3. LOOSER MATCH OVERLAP DETECTION (+/- 5 MIN TOLERANCE) ---")
    looser_overlap_query = text("""
        SELECT m1.sport, COUNT(DISTINCT m1.match_id)
        FROM core.matches m1
        JOIN core.matches m2 ON m1.league = m2.league
            AND LOWER(COALESCE(m1.home_player, '')) = LOWER(COALESCE(m2.home_player, ''))
            AND LOWER(COALESCE(m1.away_player, '')) = LOWER(COALESCE(m2.away_player, ''))
            AND m2.match_start_time >= m1.match_start_time - INTERVAL '5 minutes'
            AND m2.match_start_time <= m1.match_start_time + INTERVAL '5 minutes'
        WHERE m1.source = 'csv_backfill' AND m2.source = 'jarbet_history'
        GROUP BY m1.sport
    """)
    res_looser = conn.execute(looser_overlap_query).fetchall()
    looser_dict = {r[0]: r[1] for r in res_looser}

    fifa_looser = looser_dict.get("fifa", 0)
    ebasket_looser = looser_dict.get("ebasket", 0)

    print(f"FIFA Looser Overlaps (+/- 5 min window): {fifa_looser:,} matches")
    print(f"eBasketball Looser Overlaps (+/- 5 min window): {ebasket_looser:,} matches")

    # Also check without player name restriction (same league + home_team + away_team + 5 min window)
    looser_team_query = text("""
        SELECT m1.sport, COUNT(DISTINCT m1.match_id)
        FROM core.matches m1
        JOIN core.matches m2 ON m1.league = m2.league
            AND LOWER(m1.home_team) = LOWER(m2.home_team)
            AND LOWER(m1.away_team) = LOWER(m2.away_team)
            AND m2.match_start_time >= m1.match_start_time - INTERVAL '5 minutes'
            AND m2.match_start_time <= m1.match_start_time + INTERVAL '5 minutes'
        WHERE m1.source = 'csv_backfill' AND m2.source = 'jarbet_history'
        GROUP BY m1.sport
    """)
    res_team_looser = conn.execute(looser_team_query).fetchall()
    team_looser_dict = {r[0]: r[1] for r in res_team_looser}
    print(f"FIFA Team-Level Looser Overlaps (+/- 5 min window): {team_looser_dict.get('fifa', 0):,} matches")
    print(f"eBasketball Team-Level Looser Overlaps (+/- 5 min window): {team_looser_dict.get('ebasket', 0):,} matches")

    # -------------------------------------------------------------------
    # ITEM 4: Internal Duplication Check within jarbet_history
    # -------------------------------------------------------------------
    print("\n--- 4. INTERNAL DEDUPLICATION CHECK (jarbet_history) ---")
    query_internal_fifa = text("""
        SELECT COUNT(*), COUNT(DISTINCT match_id)
        FROM core.matches
        WHERE source = 'jarbet_history' AND sport = 'fifa'
    """)
    fifa_count_total, fifa_count_distinct = conn.execute(query_internal_fifa).fetchone()

    query_internal_ebasket = text("""
        SELECT COUNT(*), COUNT(DISTINCT match_id)
        FROM core.matches
        WHERE source = 'jarbet_history' AND sport = 'ebasket'
    """)
    ebasket_count_total, ebasket_count_distinct = conn.execute(query_internal_ebasket).fetchone()

    print(f"FIFA (jarbet_history): COUNT(*) = {fifa_count_total:,} | COUNT(DISTINCT match_id) = {fifa_count_distinct:,} | Match = {fifa_count_total == fifa_count_distinct}")
    print(f"eBasketball (jarbet_history): COUNT(*) = {ebasket_count_total:,} | COUNT(DISTINCT match_id) = {ebasket_count_distinct:,} | Match = {ebasket_count_total == ebasket_count_distinct}")

    # Also check if any natural key duplicates (same league, home_player, away_player, match_start_time) exist inside jarbet_history
    query_internal_triplet = text("""
        SELECT sport, COUNT(*) - COUNT(DISTINCT (league, LOWER(COALESCE(home_player,'')), LOWER(COALESCE(away_player,'')), match_start_time))
        FROM core.matches
        WHERE source = 'jarbet_history'
        GROUP BY sport
    """)
    triplet_dups = conn.execute(query_internal_triplet).fetchall()
    for sp, dup_cnt in triplet_dups:
        print(f"Internal natural key duplicate triplets inside jarbet_history ({sp}): {dup_cnt:,}")

    # -------------------------------------------------------------------
    # ITEM 5: Final Verified Counts across BOTH sources combined
    # -------------------------------------------------------------------
    print("\n--- 5. FINAL VERIFIED COMBINED MATCH COUNTS ---")
    query_total_fifa = text("""
        SELECT COUNT(DISTINCT match_id)
        FROM core.matches
        WHERE sport = 'fifa' AND source IN ('csv_backfill', 'jarbet_history')
    """)
    total_unique_fifa = conn.execute(query_total_fifa).scalar()

    query_total_ebasket = text("""
        SELECT COUNT(DISTINCT match_id)
        FROM core.matches
        WHERE sport = 'ebasket' AND source IN ('csv_backfill', 'jarbet_history')
    """)
    total_unique_ebasket = conn.execute(query_total_ebasket).scalar()

    print(f"FIFA Total Truly Unique Matches (Combined): {total_unique_fifa:,}")
    print(f"eBasketball Total Truly Unique Matches (Combined): {total_unique_ebasket:,}")
    print(f"ALL SPORTS TOTAL COMBINED UNIQUE MATCHES: {total_unique_fifa + total_unique_ebasket:,}")

    conn.close()


if __name__ == "__main__":
    main()
