import sys
import site
import polars as pl
from sqlalchemy import create_engine

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from markets.fifa_goals_ou.features import build_fifa_goals_ou_features
from markets.fifa_asian_handicap.features import build_fifa_asian_handicap_features
from markets.fifa_money_line.features import build_fifa_money_line_features
from markets.ebasket_ou.features import build_ebasket_ou_features
from markets.ebasket_money_line.features import build_ebasket_money_line_features


def load_market_match_data(engine, sport: str, market_type: str):
    sql = f"""
    SELECT 
        m.match_id, m.league, m.home_player, m.away_player, m.home_team, m.away_team,
        m.match_start_time, m.match_start_time AS "startedAt", m.duration_minutes, m.source,
        r.final_home_score, r.final_away_score,
        o.market_type, o.line_value, o.odds_open, o.odds_close, o.odds_snapshot_time, o.side
    FROM core.matches m
    LEFT JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o ON m.match_id = o.match_id AND o.market_type = '{market_type}'
    WHERE m.sport = '{sport}' AND m.source = 'csv_backfill'
    """
    return pl.read_database(sql, connection=engine)


def main():
    print("==========================================================================")
    print("     FAST FEATURE BUILDER ROW COUNT VERIFICATION (SOURCE='csv_backfill')")
    print("==========================================================================")
    print(f"Target Database URL: {settings.DATABASE_URL}\n")

    engine = create_engine(settings.DATABASE_URL)

    # 1. FIFA Goals O/U
    print("[1/5] Running build_fifa_goals_ou_features()...")
    df_fifa_ou_raw = load_market_match_data(engine, "fifa", "fifa_goals_ou")
    df_fifa_ou = build_fifa_goals_ou_features(df_fifa_ou_raw)
    count_fifa_ou = len(df_fifa_ou)
    print(f"  FIFA Goals O/U Output Row Count: {count_fifa_ou:,} | Target: 93,663 | Match: {count_fifa_ou == 93663}")

    # 2. FIFA Asian Handicap
    print("\n[2/5] Running build_fifa_asian_handicap_features()...")
    df_fifa_ah_raw = load_market_match_data(engine, "fifa", "fifa_asian_handicap")
    df_fifa_ah = build_fifa_asian_handicap_features(df_fifa_ah_raw)
    count_fifa_ah = len(df_fifa_ah)
    print(f"  FIFA Asian Handicap Output Row Count: {count_fifa_ah:,} | Target: 93,663 | Match: {count_fifa_ah == 93663}")

    # 3. FIFA Money Line
    print("\n[3/5] Running build_fifa_money_line_features()...")
    df_fifa_ml_raw = load_market_match_data(engine, "fifa", "fifa_money_line")
    df_fifa_ml = build_fifa_money_line_features(df_fifa_ml_raw)
    count_fifa_ml = len(df_fifa_ml)
    print(f"  FIFA Money Line Output Row Count: {count_fifa_ml:,} | Target: 93,663 | Match: {count_fifa_ml == 93663}")

    # 4. eBasketball O/U
    print("\n[4/5] Running build_ebasket_ou_features()...")
    df_ebasket_ou_raw = load_market_match_data(engine, "ebasket", "ebasket_ou")
    df_ebasket_ou = build_ebasket_ou_features(df_ebasket_ou_raw)
    count_ebasket_ou = len(df_ebasket_ou)
    print(f"  eBasketball O/U Output Row Count: {count_ebasket_ou:,} | Target: 19,246 | Match: {count_ebasket_ou == 19246}")

    # 5. eBasketball Money Line
    print("\n[5/5] Running build_ebasket_money_line_features()...")
    df_ebasket_ml_raw = load_market_match_data(engine, "ebasket", "ebasket_money_line")
    df_ebasket_ml = build_ebasket_money_line_features(df_ebasket_ml_raw)
    count_ebasket_ml = len(df_ebasket_ml)
    print(f"  eBasketball Money Line Output Row Count: {count_ebasket_ml:,} | Target: 19,246 | Match: {count_ebasket_ml == 19246}")

    print("\n==========================================================================")
    print("                    FEATURE BUILDER ROW COUNT SUMMARY")
    print("==========================================================================")
    print(f"1. fifa_goals_ou:          {count_fifa_ou:,} rows (Expected: 93,663)")
    print(f"2. fifa_asian_handicap:    {count_fifa_ah:,} rows (Expected: 93,663)")
    print(f"3. fifa_money_line:        {count_fifa_ml:,} rows (Expected: 93,663)")
    print(f"4. ebasket_ou:             {count_ebasket_ou:,} rows (Expected: 19,246)")
    print(f"5. ebasket_money_line:     {count_ebasket_ml:,} rows (Expected: 19,246)")


if __name__ == "__main__":
    main()
