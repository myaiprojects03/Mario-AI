import os
import sys
import site
import polars as pl
from sqlalchemy import create_engine

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from markets.ebasket_ou.features import build_ebasket_ou_features, EBASKET_OU_FEATURE_COLUMNS
from markets.ebasket_money_line.features import build_ebasket_money_line_features, EBASKET_ML_FEATURE_COLUMNS


def main():
    print(f"Connecting to PostgreSQL database at {settings.DATABASE_URL.split('@')[-1]}...")
    engine = create_engine(settings.DATABASE_URL)

    # 1. Fetch real eBasketball matches for Over/Under
    query_ou = """
    SELECT DISTINCT ON (m.match_id)
        m.match_id,
        m.home_player,
        m.away_player,
        m.match_start_time AS "startedAt",
        m.league,
        r.final_home_score AS "home.goals",
        r.final_away_score AS "away.goals",
        o.line_value AS "odds.over_under.line",
        o.odds_open AS "odds.over_under.over",
        o.odds_close AS "closingOdds.over_under.over"
    FROM core.matches m
    LEFT JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = 'ebasket_ou' AND o.side = 'over'
    WHERE m.sport = 'ebasket' AND m.source = 'csv_backfill'
    ORDER BY m.match_id, m.match_start_time ASC
    """

    print("Fetching eBasketball O/U matches from PostgreSQL...")
    with engine.connect() as conn:
        df_ou_raw = pl.read_database(query_ou, connection=conn)

    total_rows = len(df_ou_raw)
    print(f"Loaded {total_rows} eBasketball rows from PostgreSQL.")

    # Sort chronologically
    df_ou_raw = df_ou_raw.sort("startedAt")

    # Run build_ebasket_ou_features()
    print("\n--- Running build_ebasket_ou_features() ---")
    ebasket_ou_df = build_ebasket_ou_features(df_ou_raw)
    print(f"Successfully produced eBasketball Over/Under features with shape {ebasket_ou_df.shape}.")

    # Reliability flag breakdown
    unrel_5_ou = ebasket_ou_df.filter(pl.col("is_reliable_5") == False).height
    unrel_10_ou = ebasket_ou_df.filter(pl.col("is_reliable_10") == False).height
    print(f"\n--- eBasketball O/U Reliability Flag Breakdown ---")
    print(f"is_reliable_5 = False: {unrel_5_ou} / {total_rows} ({ (unrel_5_ou/total_rows)*100:.2f}%)")
    print(f"is_reliable_10 = False: {unrel_10_ou} / {total_rows} ({ (unrel_10_ou/total_rows)*100:.2f}%)")

    # Null rate analysis for O/U
    print(f"\n--- Null/NaN Rate Analysis (eBasketball O/U) ---")
    for col in EBASKET_OU_FEATURE_COLUMNS:
        cnt = ebasket_ou_df[col].null_count()
        rate = (cnt / total_rows) * 100.0
        flag = " [WARNING: HIGH NULLS]" if rate > 5.0 else ""
        print(f"Column '{col}': {cnt} nulls ({rate:.2f}%){flag}")

    # Save sample output
    os.makedirs("markets/ebasket_ou", exist_ok=True)
    ou_sample_path = "markets/ebasket_ou/sample_output.csv"
    ebasket_ou_df.head(20).write_csv(ou_sample_path)
    print(f"Saved 20 sample feature rows to {ou_sample_path}.")

    # 2. Fetch real eBasketball matches for Money Line
    query_ml = """
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
    LEFT JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = 'ebasket_money_line' AND o.side = 'home'
    WHERE m.sport = 'ebasket' AND m.source = 'csv_backfill'
    ORDER BY m.match_id, m.match_start_time ASC
    """

    print("\nFetching eBasketball Money Line matches from PostgreSQL...")
    with engine.connect() as conn:
        df_ml_raw = pl.read_database(query_ml, connection=conn)

    df_ml_raw = df_ml_raw.sort("startedAt")

    print("\n--- Running build_ebasket_money_line_features() ---")
    ebasket_ml_df = build_ebasket_money_line_features(df_ml_raw)
    print(f"Successfully produced eBasketball Money Line features with shape {ebasket_ml_df.shape}.")

    # Reliability flag breakdown
    unrel_5_ml = ebasket_ml_df.filter(pl.col("is_reliable_5") == False).height
    unrel_10_ml = ebasket_ml_df.filter(pl.col("is_reliable_10") == False).height
    print(f"\n--- eBasketball Money Line Reliability Flag Breakdown ---")
    print(f"is_reliable_5 = False: {unrel_5_ml} / {total_rows} ({ (unrel_5_ml/total_rows)*100:.2f}%)")
    print(f"is_reliable_10 = False: {unrel_10_ml} / {total_rows} ({ (unrel_10_ml/total_rows)*100:.2f}%)")

    # Null rate analysis for Money Line
    print(f"\n--- Null/NaN Rate Analysis (eBasketball Money Line) ---")
    for col in EBASKET_ML_FEATURE_COLUMNS:
        cnt = ebasket_ml_df[col].null_count()
        rate = (cnt / total_rows) * 100.0
        flag = " [WARNING: HIGH NULLS]" if rate > 5.0 else ""
        print(f"Column '{col}': {cnt} nulls ({rate:.2f}%){flag}")

    # Save sample output
    os.makedirs("markets/ebasket_money_line", exist_ok=True)
    ml_sample_path = "markets/ebasket_money_line/sample_output.csv"
    ebasket_ml_df.head(20).write_csv(ml_sample_path)
    print(f"Saved 20 sample feature rows to {ml_sample_path}.")


if __name__ == "__main__":
    main()
