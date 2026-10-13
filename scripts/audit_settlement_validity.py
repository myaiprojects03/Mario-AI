import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect("postgresql://postgres:postgrespassword@24.199.87.126:5432/mario_ai")
cur = conn.cursor(cursor_factory=RealDictCursor)

# 1. Premature settlement check
cur.execute("""
    SELECT 
        COUNT(*) as total_tips,
        COUNT(*) FILTER (WHERE status = 'SETTLED') as total_settled,
        COUNT(*) FILTER (WHERE status = 'PENDING') as pending_count,
        COUNT(*) FILTER (WHERE status = 'SETTLED' AND settled_at_utc < kickoff_at_utc) as settled_before_kickoff,
        COUNT(*) FILTER (WHERE status = 'SETTLED' AND settled_at_utc >= kickoff_at_utc) as settled_after_kickoff
    FROM core.shadow_tips_eval
    WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00';
""")
print("=== TIMING AUDIT ===")
row1 = cur.fetchone()
print(dict(row1))

# 2. Time delta check in minutes
cur.execute("""
    SELECT 
        ROUND(AVG(EXTRACT(EPOCH FROM (settled_at_utc - kickoff_at_utc))/60.0)::numeric, 1) as avg_mins_after_ko,
        ROUND(MIN(EXTRACT(EPOCH FROM (settled_at_utc - kickoff_at_utc))/60.0)::numeric, 1) as min_mins_after_ko,
        ROUND(MAX(EXTRACT(EPOCH FROM (settled_at_utc - kickoff_at_utc))/60.0)::numeric, 1) as max_mins_after_ko
    FROM core.shadow_tips_eval
    WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00' AND status = 'SETTLED' AND settled_at_utc >= kickoff_at_utc;
""")
print("=== KICKOFF TO SETTLEMENT DELTA (MINUTES) ===")
print(dict(cur.fetchone()))

# 3. Pull 2 concrete examples from each channel
cur.execute("""
    WITH ranked_tips AS (
        SELECT 
            channel_key, match_id, bet365_id, fixture, side, line, odds,
            kickoff_at_utc, settled_at_utc, final_score, outcome, net_units,
            ROW_NUMBER() OVER(PARTITION BY channel_key ORDER BY kickoff_at_utc DESC) as rn
        FROM core.shadow_tips_eval
        WHERE kickoff_at_utc >= '2026-10-05 00:00:00+00' AND status = 'SETTLED'
    )
    SELECT * FROM ranked_tips WHERE rn <= 2 ORDER BY channel_key, rn;
""")
examples = cur.fetchall()
print("\n=== CONCRETE SETTLED EXAMPLES ===")
for ex in examples:
    print(f"[{ex['channel_key']}] Match ID: {ex['match_id']} | Fixture: {ex['fixture']}")
    print(f"  Kickoff UTC:  {ex['kickoff_at_utc']}")
    print(f"  Settled UTC:  {ex['settled_at_utc']}")
    print(f"  Pick Details: Side={ex['side']}, Line={ex['line']}, Odds={ex['odds']}")
    print(f"  Whistle Score: {ex['final_score']} -> Outcome: {ex['outcome']}, Net Units: {ex['net_units']}")
    print("-" * 75)

# 4. Check if match_id maps to identical fixture and score in core.results
print("\n=== CROSS-SCHEMA INTEGRITY CHECK (Match ID & Score Matching) ===")
cur.execute("""
    SELECT 
        s.match_id, s.fixture, s.final_score as shadow_score,
        r.final_home_score, r.final_away_score,
        m.home_player, m.away_player
    FROM core.shadow_tips_eval s
    JOIN core.results r ON s.match_id = r.match_id
    LEFT JOIN core.matches m ON s.match_id = m.match_id
    WHERE s.kickoff_at_utc >= '2026-10-05 00:00:00+00' AND s.status = 'SETTLED'
    LIMIT 5;
""")
for cross in cur.fetchall():
    print(f"Match ID: {cross['match_id']}")
    print(f"  Shadow Fixture: {cross['fixture']}")
    print(f"  Match Table Players: {cross['home_player']} vs {cross['away_player']}")
    print(f"  Shadow Final Score: {cross['shadow_score']} vs Results Score: {cross['final_home_score']}-{cross['final_away_score']}")
    print("-" * 75)

conn.close()
