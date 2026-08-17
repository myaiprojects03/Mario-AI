import sys
import site
import polars as pl
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    engine = create_engine(settings.DATABASE_URL)
    
    print("--- 1. Querying core.odds Breakdown in PostgreSQL ---")
    query_counts = """
    SELECT market_type, side, COUNT(*) AS total_rows, COUNT(odds_open) AS open_cnt, COUNT(odds_close) AS close_cnt
    FROM core.odds
    GROUP BY market_type, side;
    """
    with engine.connect() as conn:
        res = conn.execute(text(query_counts)).fetchall()
        for row in res:
            print(f"market_type: '{row[0]}', side: '{row[1]}', total: {row[2]}, open_cnt: {row[3]}, close_cnt: {row[4]}")

    print("\n--- 2. Checking Raw CSV File Columns in history_pre_fifa.csv ---")
    fifa_csv_path = "data/raw/history_pre_fifa.csv"
    if pl.os.path.exists(fifa_csv_path):
        df_csv = pl.read_csv(fifa_csv_path)
        ml_open_cnt = df_csv["odds.money_line.home"].is_not_null().sum()
        ml_close_cnt = df_csv["closingOdds.money_line.home"].is_not_null().sum()
        ah_open_cnt = df_csv["odds.asian_handicap.home"].is_not_null().sum()
        ah_close_cnt = df_csv["closingOdds.asian_handicap.home"].is_not_null().sum()

        print(f"history_pre_fifa.csv total rows: {len(df_csv)}")
        print(f"odds.money_line.home non-nulls: {ml_open_cnt} (null rate: {((len(df_csv)-ml_open_cnt)/len(df_csv))*100:.2f}%)")
        print(f"closingOdds.money_line.home non-nulls: {ml_close_cnt} (null rate: {((len(df_csv)-ml_close_cnt)/len(df_csv))*100:.2f}%)")
        print(f"odds.asian_handicap.home non-nulls: {ah_open_cnt} (null rate: {((len(df_csv)-ah_open_cnt)/len(df_csv))*100:.2f}%)")
        print(f"closingOdds.asian_handicap.home non-nulls: {ah_close_cnt} (null rate: {((len(df_csv)-ah_close_cnt)/len(df_csv))*100:.2f}%)")


if __name__ == "__main__":
    main()
