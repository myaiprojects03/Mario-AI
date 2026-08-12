import os
import sys
import site
from datetime import datetime

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

import polars as pl
from sqlalchemy import create_engine, text

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from markets.fifa_goals_ou.features import build_fifa_goals_ou_features, FEATURE_COLUMNS
from markets.fifa_asian_handicap.features import build_fifa_asian_handicap_features, AH_FEATURE_COLUMNS


def main():
    print(f"Connecting to PostgreSQL database at {settings.DATABASE_URL.split('@')[-1]}...")
    engine = create_engine(settings.DATABASE_URL)

    query = """
    SELECT DISTINCT ON (m.match_id)
        m.match_id,
        m.home_player,
        m.away_player,
        m.match_start_time AS "startedAt",
        m.league,
        r.final_home_score AS "home.goals",
        r.final_away_score AS "away.goals",
        o_ou.line_value AS "odds.over_under.line",
        o_ou.odds_open AS "odds.over_under.over",
        o_ou.odds_close AS "closingOdds.over_under.over",
        o_ah.line_value AS "odds.asian_handicap.line"
    FROM core.matches m
    LEFT JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o_ou ON m.match_id = o_ou.match_id AND o_ou.market_type = 'fifa_goals_ou' AND o_ou.side = 'over'
    LEFT JOIN core.odds o_ah ON m.match_id = o_ah.match_id AND o_ah.market_type = 'fifa_asian_handicap' AND o_ah.side = 'home'
    WHERE m.sport = 'fifa' AND m.source = 'csv_backfill'
    ORDER BY m.match_id, m.match_start_time ASC
    """

    print("Fetching real FIFA matches from core.matches / core.results / core.odds...")
    with engine.connect() as conn:
        df_raw = pl.read_database(query, connection=conn)

    total_input_rows = len(df_raw)
    print(f"Loaded {total_input_rows} rows from PostgreSQL.")

    # 1. Run build_fifa_goals_ou_features()
    print("\n--- Running build_fifa_goals_ou_features() ---")
    try:
        ou_features = build_fifa_goals_ou_features(df_raw)
        ou_error = None
        print(f"Successfully produced O/U features with shape {ou_features.shape}.")
    except Exception as e:
        ou_features = None
        ou_error = str(e)
        print(f"ERROR in build_fifa_goals_ou_features(): {e}")

    # 2. Run build_fifa_asian_handicap_features()
    print("\n--- Running build_fifa_asian_handicap_features() ---")
    try:
        ah_features = build_fifa_asian_handicap_features(df_raw)
        ah_error = None
        print(f"Successfully produced Asian Handicap features with shape {ah_features.shape}.")
    except Exception as e:
        ah_features = None
        ah_error = str(e)
        print(f"ERROR in build_fifa_asian_handicap_features(): {e}")

    # 3. Analyze reliability flags
    if ou_features is not None:
        unreliable_5_cnt = ou_features.filter(pl.col("is_reliable_5") == False).height
        unreliable_10_cnt = ou_features.filter(pl.col("is_reliable_10") == False).height

        pct_unreliable_5 = (unreliable_5_cnt / total_input_rows) * 100.0
        pct_unreliable_10 = (unreliable_10_cnt / total_input_rows) * 100.0

        print(f"\n--- Reliability Flag Analysis ---")
        print(f"Rows with is_reliable_5 = False: {unreliable_5_cnt} / {total_input_rows} ({pct_unreliable_5:.2f}%)")
        print(f"Rows with is_reliable_10 = False: {unreliable_10_cnt} / {total_input_rows} ({pct_unreliable_10:.2f}%)")

        # 4. Null / NaN rates per column
        print(f"\n--- Null/NaN Rate Analysis (FIFA Goals O/U) ---")
        ou_nulls = {}
        for col in FEATURE_COLUMNS:
            cnt = ou_features[col].null_count()
            rate = (cnt / total_input_rows) * 100.0
            ou_nulls[col] = (cnt, rate)
            flag = " ⚠️ HIGH NULLS" if rate > 5.0 else ""
            print(f"Column '{col}': {cnt} nulls ({rate:.2f}%){flag}")

        print(f"\n--- Null/NaN Rate Analysis (FIFA Asian Handicap) ---")
        ah_nulls = {}
        for col in AH_FEATURE_COLUMNS:
            cnt = ah_features[col].null_count()
            rate = (cnt / total_input_rows) * 100.0
            ah_nulls[col] = (cnt, rate)
            flag = " ⚠️ HIGH NULLS" if rate > 5.0 else ""
            print(f"Column '{col}': {cnt} nulls ({rate:.2f}%){flag}")

        # 5. Save sample of 20 feature rows
        os.makedirs("markets/fifa_goals_ou", exist_ok=True)
        sample_path = "markets/fifa_goals_ou/sample_output.csv"
        sample_df = ou_features.head(20)
        sample_df.write_csv(sample_path)
        print(f"\nSaved 20 sample feature rows to {sample_path}.")


if __name__ == "__main__":
    main()
