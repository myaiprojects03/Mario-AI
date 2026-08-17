import sys
import site
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    print("==========================================================================")
    print("      CRITICAL DATA INTEGRITY INVESTIGATION: SOURCE OVERWRITE AUDIT")
    print("==========================================================================")

    engine = create_engine(settings.DATABASE_URL)
    conn = engine.connect()

    # 1. Breakdown of core.matches GROUP BY source, sport
    print("\n--- 1. Current core.matches breakdown GROUP BY source, sport ---")
    query_group = text("""
        SELECT sport, source, COUNT(*)
        FROM core.matches
        GROUP BY sport, source
        ORDER BY sport, source
    """)
    rows_group = conn.execute(query_group).fetchall()
    for sp, src, cnt in rows_group:
        print(f"  Sport: {sp:<10} | Source: {src:<18} | Count: {cnt:,}")

    # Total matches per sport
    query_totals = text("""
        SELECT sport, COUNT(*)
        FROM core.matches
        GROUP BY sport
    """)
    rows_totals = conn.execute(query_totals).fetchall()
    print("\n--- Total matches in database per sport ---")
    for sp, cnt in rows_totals:
        print(f"  Sport: {sp:<10} | Total Matches in DB: {cnt:,}")

    # 2. Check core.results and core.odds breakdown GROUP BY settlement_source / market_type
    print("\n--- 2. Breakdown of core.results GROUP BY settlement_source ---")
    query_res = text("""
        SELECT settlement_source, COUNT(*)
        FROM core.results
        GROUP BY settlement_source
    """)
    for src, cnt in conn.execute(query_res).fetchall():
        print(f"  Settlement Source: {src:<18} | Count: {cnt:,}")

    print("\n--- Breakdown of core.odds GROUP BY market_type ---")
    query_odds = text("""
        SELECT market_type, COUNT(*)
        FROM core.odds
        GROUP BY market_type
    """)
    for mkt, cnt in conn.execute(query_odds).fetchall():
        print(f"  Market: {mkt:<25} | Count: {cnt:,}")

    # 3. Check data integrity: verify goals, odds, start times are 100% intact
    print("\n--- 3. Checking data integrity of overwritten matches ---")
    query_sample = text("""
        SELECT m.match_id, m.sport, m.league, m.home_player, m.away_player, m.source,
               r.final_home_score, r.final_away_score, COUNT(o.id) as odds_count
        FROM core.matches m
        LEFT JOIN core.results r ON m.match_id = r.match_id
        LEFT JOIN core.odds o ON m.match_id = o.match_id
        WHERE m.source = 'jarbet_history'
        GROUP BY m.match_id, m.sport, m.league, m.home_player, m.away_player, m.source, r.final_home_score, r.final_away_score
        LIMIT 5
    """)
    for row in conn.execute(query_sample).fetchall():
        print(f"  Sample Record: ID={row[0]} | Sport={row[1]} | Players={row[3]} vs {row[4]} | Score={row[6]}-{row[7]} | Odds Count={row[8]}")

    conn.close()


if __name__ == "__main__":
    main()
