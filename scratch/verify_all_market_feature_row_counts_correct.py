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


def load_distinct_match_data(engine, sport: str, ou_market: str, ah_market: str = None, ml_market: str = None):
    sql = f"""
    SELECT DISTINCT ON (m.match_id)
        m.match_id,
        m.league,
        m.home_player,
        m.away_player,
        m.home_team,
        m.away_team,
        m.match_start_time,
        m.match_start_time AS "startedAt",
        m.duration_minutes,
        m.source,
        r.final_home_score AS "home.goals",
        r.final_away_score AS "away.goals",
        r.final_home_score,
        r.final_away_score,
        CAST(o_ou.line_value AS FLOAT) AS "odds.over_under.line",
        CAST(o_ou.odds_open AS FLOAT) AS "odds.over_under.over",
        CAST(o_ou.odds_close AS FLOAT) AS "closingOdds.over_under.over",
        CAST(o_ah.line_value AS FLOAT) AS "odds.asian_handicap.line",
        CAST(o_ah.odds_open AS FLOAT) AS "odds.asian_handicap.home",
        CAST(o_ah.odds_close AS FLOAT) AS "closingOdds.asian_handicap.home",
        CAST(o_ml.odds_open AS FLOAT) AS "odds.money_line.home",
        CAST(o_ml.odds_close AS FLOAT) AS "closingOdds.money_line.home"
    FROM core.matches m
    LEFT JOIN core.results r ON m.match_id = r.match_id
    LEFT JOIN core.odds o_ou ON m.match_id = o_ou.match_id AND o_ou.market_type = '{ou_market}' AND o_ou.side = 'over'
    LEFT JOIN core.odds o_ah ON m.match_id = o_ah.match_id AND o_ah.market_type = '{ah_market or "none"}' AND o_ah.side = 'home'
    LEFT JOIN core.odds o_ml ON m.match_id = o_ml.match_id AND o_ml.market_type = '{ml_market or "none"}' AND o_ml.side = 'home'
    WHERE m.sport = '{sport}' AND m.source = 'csv_backfill'
    ORDER BY m.match_id, m.match_start_time ASC
    """
    import pandas as pd
    with engine.connect() as conn:
        df_pd = pd.read_sql(sql, conn)
        return pl.from_pandas(df_pd)


def main():
    print("==========================================================================")
    print("      VERIFYING FEATURE BUILDER OUTPUT ROW COUNTS FOR SOURCE='csv_backfill'")
    print("==========================================================================")
    print(f"Target Database URL: {settings.DATABASE_URL}\n")

    engine = create_engine(settings.DATABASE_URL)

    # 1. Fetch FIFA distinct match dataframe (source='csv_backfill')
    print("Fetching distinct FIFA matches dataframe from DB (source='csv_backfill')...")
    df_fifa = load_distinct_match_data(engine, "fifa", "fifa_goals_ou", "fifa_asian_handicap", "fifa_money_line")
    fifa_distinct_count = len(df_fifa)
    print(f"-> Loaded FIFA distinct match dataframe with {fifa_distinct_count:,} rows.\n")

    # a) FIFA Goals O/U
    print("[1/5] Running build_fifa_goals_ou_features()...")
    df_fifa_ou = build_fifa_goals_ou_features(df_fifa)
    count_fifa_ou = len(df_fifa_ou)
    print(f"  FIFA Goals O/U Output Row Count: {count_fifa_ou:,} | Target: 93,663 | Match: {count_fifa_ou == 93663}")

    # b) FIFA Asian Handicap
    print("\n[2/5] Running build_fifa_asian_handicap_features()...")
    df_fifa_ah = build_fifa_asian_handicap_features(df_fifa)
    count_fifa_ah = len(df_fifa_ah)
    print(f"  FIFA Asian Handicap Output Row Count: {count_fifa_ah:,} | Target: 93,663 | Match: {count_fifa_ah == 93663}")

    # c) FIFA Money Line
    print("\n[3/5] Running build_fifa_money_line_features()...")
    df_fifa_ml = build_fifa_money_line_features(df_fifa)
    count_fifa_ml = len(df_fifa_ml)
    print(f"  FIFA Money Line Output Row Count: {count_fifa_ml:,} | Target: 93,663 | Match: {count_fifa_ml == 93663}")

    # 2. Fetch eBasketball distinct match dataframe (source='csv_backfill')
    print("\nFetching distinct eBasketball matches dataframe from DB (source='csv_backfill')...")
    df_ebasket = load_distinct_match_data(engine, "ebasket", "ebasket_ou", "ebasket_asian_handicap", "ebasket_money_line")
    ebasket_distinct_count = len(df_ebasket)
    print(f"-> Loaded eBasketball distinct match dataframe with {ebasket_distinct_count:,} rows.\n")

    # d) eBasketball O/U
    print("[4/5] Running build_ebasket_ou_features()...")
    df_ebasket_ou = build_ebasket_ou_features(df_ebasket)
    count_ebasket_ou = len(df_ebasket_ou)
    print(f"  eBasketball O/U Output Row Count: {count_ebasket_ou:,} | Target: 19,246 | Match: {count_ebasket_ou == 19246}")

    # e) eBasketball Money Line
    print("\n[5/5] Running build_ebasket_money_line_features()...")
    df_ebasket_ml = build_ebasket_money_line_features(df_ebasket)
    count_ebasket_ml = len(df_ebasket_ml)
    print(f"  eBasketball Money Line Output Row Count: {count_ebasket_ml:,} | Target: 19,246 | Match: {count_ebasket_ml == 19246}")

    print("\n==========================================================================")
    print("                    FINAL FEATURE BUILDER ROW COUNT VERIFICATION")
    print("==========================================================================")
    print(f"1. fifa_goals_ou:          {count_fifa_ou:,} rows (Expected: 93,663) -> {'✅ MATCH' if count_fifa_ou == 93663 else '❌ MISMATCH'}")
    print(f"2. fifa_asian_handicap:    {count_fifa_ah:,} rows (Expected: 93,663) -> {'✅ MATCH' if count_fifa_ah == 93663 else '❌ MISMATCH'}")
    print(f"3. fifa_money_line:        {count_fifa_ml:,} rows (Expected: 93,663) -> {'✅ MATCH' if count_fifa_ml == 93663 else '❌ MISMATCH'}")
    print(f"4. ebasket_ou:             {count_ebasket_ou:,} rows (Expected: 19,246) -> {'✅ MATCH' if count_ebasket_ou == 19246 else '❌ MISMATCH'}")
    print(f"5. ebasket_money_line:     {count_ebasket_ml:,} rows (Expected: 19,246) -> {'✅ MATCH' if count_ebasket_ml == 19246 else '❌ MISMATCH'}")


if __name__ == "__main__":
    main()
