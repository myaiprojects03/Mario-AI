import os
import sys
import site
from datetime import datetime
import polars as pl
from sqlalchemy import create_engine

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from markets.fifa_money_line.features import build_fifa_money_line_features, ML_FEATURE_COLUMNS


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
        o.odds_open AS "odds.money_line.home",
        o.odds_close AS "closingOdds.money_line.home"
    FROM core.matches m
    LEFT JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = 'fifa_money_line' AND o.side = 'home'
    WHERE m.sport = 'fifa' AND m.source = 'csv_backfill'
    ORDER BY m.match_id, m.match_start_time ASC
    """

    print("Fetching real FIFA matches from core.matches / core.results / core.odds...")
    with engine.connect() as conn:
        df_raw = pl.read_database(query, connection=conn)

    total_input_rows = len(df_raw)
    print(f"Loaded {total_input_rows} rows from PostgreSQL.")

    # Sort chronologically by match start time
    df_raw = df_raw.sort("startedAt")

    # Run build_fifa_money_line_features()
    print("\n--- Running build_fifa_money_line_features() ---")
    try:
        ml_features = build_fifa_money_line_features(df_raw)
        print(f"Successfully produced FIFA 1X2 Money Line features with shape {ml_features.shape}.")
    except Exception as e:
        ml_features = None
        print(f"ERROR in build_fifa_money_line_features(): {e}")
        return

    # Reliability flag breakdown
    unreliable_5_cnt = ml_features.filter(pl.col("is_reliable_5") == False).height
    unreliable_10_cnt = ml_features.filter(pl.col("is_reliable_10") == False).height
    pct_unreliable_5 = (unreliable_5_cnt / total_input_rows) * 100.0
    pct_unreliable_10 = (unreliable_10_cnt / total_input_rows) * 100.0

    print(f"\n--- Reliability Flag Analysis ---")
    print(f"Rows with is_reliable_5 = False: {unreliable_5_cnt} / {total_input_rows} ({pct_unreliable_5:.2f}%)")
    print(f"Rows with is_reliable_10 = False: {unreliable_10_cnt} / {total_input_rows} ({pct_unreliable_10:.2f}%)")

    # Null / NaN rates per column
    print(f"\n--- Null/NaN Rate Analysis (FIFA 1X2 Money Line) ---")
    for col in ML_FEATURE_COLUMNS:
        cnt = ml_features[col].null_count()
        rate = (cnt / total_input_rows) * 100.0
        flag = " [WARNING: HIGH NULLS]" if rate > 5.0 else ""
        print(f"Column '{col}': {cnt} nulls ({rate:.2f}%){flag}")

    # Save sample of 20 real feature rows
    os.makedirs("markets/fifa_money_line", exist_ok=True)
    sample_path = "markets/fifa_money_line/sample_output.csv"
    sample_df = ml_features.head(20)
    sample_df.write_csv(sample_path)
    print(f"\nSaved 20 sample feature rows to {sample_path}.")


if __name__ == "__main__":
    main()
