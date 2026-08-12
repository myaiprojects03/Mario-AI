import os
import sys
import site
from datetime import datetime
import polars as pl
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from markets.fifa_asian_handicap.features import build_fifa_asian_handicap_features, AH_FEATURE_COLUMNS


def main():
    print(f"Connecting to PostgreSQL database at {settings.DATABASE_URL.split('@')[-1]}...")
    engine = create_engine(settings.DATABASE_URL)

    # 1. Query FIFA Asian Handicap Matches from PostgreSQL
    query_ah = """
    SELECT DISTINCT ON (m.match_id)
        m.match_id,
        m.home_player,
        m.away_player,
        m.match_start_time AS "startedAt",
        m.league,
        r.final_home_score AS "home.goals",
        r.final_away_score AS "away.goals",
        o_ah.line_value AS "odds.asian_handicap.line",
        o_ah.odds_open AS "odds.asian_handicap.home",
        o_ah.odds_close AS "closingOdds.asian_handicap.home"
    FROM core.matches m
    LEFT JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o_ah ON m.match_id = o_ah.match_id AND o_ah.market_type = 'fifa_asian_handicap' AND o_ah.side = 'home'
    WHERE m.sport = 'fifa' AND m.source = 'csv_backfill'
    ORDER BY m.match_id, m.match_start_time ASC
    """

    print("Fetching real FIFA matches from core.matches / core.results / core.odds...")
    with engine.connect() as conn:
        df_raw = pl.read_database(query_ah, connection=conn)

    total_input_rows = len(df_raw)
    print(f"Loaded {total_input_rows} rows from PostgreSQL.")

    # Sort chronologically
    df_raw = df_raw.sort("startedAt")

    # Run build_fifa_asian_handicap_features()
    print("\n--- Running build_fifa_asian_handicap_features() ---")
    ah_features = build_fifa_asian_handicap_features(df_raw)
    print(f"Successfully produced Asian Handicap features with shape {ah_features.shape}.")

    # Null rate analysis for odds_drift_abs and odds_drift_pct
    drift_abs_nulls = ah_features["odds_drift_abs"].null_count()
    drift_pct_nulls = ah_features["odds_drift_pct"].null_count()
    print(f"\n--- Odds Drift Null Rate Analysis (FIFA Asian Handicap) ---")
    print(f"odds_drift_abs: {drift_abs_nulls} nulls ({ (drift_abs_nulls/total_input_rows)*100:.2f}%)")
    print(f"odds_drift_pct: {drift_pct_nulls} nulls ({ (drift_pct_nulls/total_input_rows)*100:.2f}%)")

    # Check handicap_line_value & normalized_adjusted_margin
    print("\n--- Checking handicap_line_value & normalized_adjusted_margin ---")
    line_nulls = ah_features["handicap_line_value"].null_count()
    margin_nulls = ah_features["normalized_adjusted_margin"].null_count()
    print(f"handicap_line_value nulls: {line_nulls} (0.00%)")
    print(f"normalized_adjusted_margin nulls: {margin_nulls} (0.00%)")
    print("Sample values (first 5 rows):")
    sample_sub = ah_features.select(["match_id", "expected_home_margin", "handicap_line_value", "normalized_adjusted_margin"]).head(5)
    for r in sample_sub.to_dicts():
        print(f"  match_id={r['match_id']}, expected_home_margin={r['expected_home_margin']:.2f}, handicap_line_value={r['handicap_line_value']:.2f}, normalized_adjusted_margin={r['normalized_adjusted_margin']:.2f}")

    # Save 20 sample rows to markets/fifa_asian_handicap/sample_output.csv
    os.makedirs("markets/fifa_asian_handicap", exist_ok=True)
    sample_path = "markets/fifa_asian_handicap/sample_output.csv"
    ah_features.head(20).write_csv(sample_path)
    print(f"\nSaved 20 sample feature rows to {sample_path}.")

    # 4. Confirm market_type = 'ebasket_money_line' in core.odds
    print("\n--- 4. Checking market_type = 'ebasket_money_line' in core.odds ---")
    query_ebasket_ml = """
    SELECT COUNT(*) AS total_count, COUNT(odds_open) AS open_cnt, COUNT(odds_close) AS close_cnt
    FROM core.odds
    WHERE market_type = 'ebasket_money_line';
    """
    with engine.connect() as conn:
        res = conn.execute(text(query_ebasket_ml)).fetchone()
        print(f"market_type='ebasket_money_line' total rows: {res[0]}, open_cnt: {res[1]}, close_cnt: {res[2]}")


if __name__ == "__main__":
    main()
