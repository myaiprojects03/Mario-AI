"""
Empirical Investigation Script:
1. August test window breakdown by source (csv_backfill vs jarbet_history).
2. Inspection of odds timestamp capture timing for jarbet_history matches.
3. Complete backtest performance breakdown by source (csv_backfill vs jarbet_history) across June/July/August.
"""

import sys
import site
import pandas as pd
import numpy as np
import polars as pl
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from core.validation.walk_forward import WalkForwardSplitter
from core.validation.backtest_engine import BacktestEngine
from markets.fifa_goals_ou.models import XGBoostGoalsOUModel


def run_investigation():
    engine = create_engine(settings.DATABASE_URL)

    # 1. Query matches including source and raw_data metadata
    print("\n==========================================================================")
    print(" 1. DATA SOURCE COMPOSITION OF TRAIN / TEST MATCHES OVER TIME")
    print("==========================================================================")

    query_cols = text("""
        SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' AND table_name = 'matches';
    """)
    with engine.connect() as conn:
        cols = [r[0] for r in conn.execute(query_cols).fetchall()]
    print(f"Columns in core.matches: {cols}")

    query = text("""
        SELECT match_id, league, home_player, away_player, match_start_time, source
        FROM core.matches
        WHERE source IN ('csv_backfill', 'jarbet_history')
          AND sport = 'fifa'
        ORDER BY match_start_time ASC;
    """)

    with engine.connect() as conn:
        df_raw = pd.read_sql(query, conn)

    print(f"Total FIFA matches loaded: {len(df_raw):,}")
    print("\nSource breakdown across all loaded FIFA matches:")
    print(df_raw["source"].value_counts())

    df_raw["month"] = pd.to_datetime(df_raw["match_start_time"]).dt.to_period("M")
    print("\nMonthly count by data source:")
    monthly_source_counts = pd.crosstab(df_raw["month"], df_raw["source"])
    print(monthly_source_counts)

    # Convert to Polars for feature pipeline and backtesting
    # We will build features using the existing model pipeline
    from markets.fifa_goals_ou.model import load_training_dataset
    df_polars = load_training_dataset(engine)

    # Ensure source column is preserved in polars dataset
    # Merge source back by match_id if missing
    if "source" not in df_polars.columns:
        source_map = dict(zip(df_raw["match_id"].astype(str), df_raw["source"]))
        source_list = [source_map.get(str(m), "unknown") for m in df_polars["match_id"].to_list()]
        df_polars = df_polars.with_columns(pl.Series("source", source_list))

    splitter = WalkForwardSplitter(
        train_days=45,
        test_days=7,
        step_days=7,
        time_col="match_start_time",
    )

    test_records = []
    xgb_preds = []

    for train_idx, test_idx in splitter.split(df_polars):
        df_train = df_polars[train_idx]
        df_test = df_polars[test_idx]

        xgb_model = XGBoostGoalsOUModel()
        xgb_model.fit(df_train)
        p_xgb = xgb_model.predict_probs(df_test)

        df_test_pd = df_test.to_pandas()
        line_col_test = "odds.over_under.line" if "odds.over_under.line" in df_test_pd.columns else "line_value"
        lines_test = df_test_pd[line_col_test].fillna(2.5).values.astype(float) if line_col_test in df_test_pd.columns else np.full(len(df_test_pd), 2.5)
        totals_test = (df_test_pd["home.goals"].values + df_test_pd["away.goals"].values).astype(float)
        is_win = (totals_test > lines_test).astype(float)

        for idx in range(len(df_test_pd)):
            t_val = df_test_pd["match_start_time"].iloc[idx] if "match_start_time" in df_test_pd.columns else df_test_pd["startedAt"].iloc[idx]
            
            odds_val = None
            for col_candidate in ["closingOdds.over_under.over", "odds.over_under.over", "odds_close"]:
                if col_candidate in df_test_pd.columns:
                    val = df_test_pd[col_candidate].iloc[idx]
                    if pd.notna(val) and float(val) > 1.0:
                        odds_val = float(val)
                        break
            if odds_val is None:
                odds_val = 1.90

            src_val = df_test_pd["source"].iloc[idx] if "source" in df_test_pd.columns else "unknown"

            test_records.append({
                "match_id": df_test_pd["match_id"].iloc[idx],
                "startedAt": t_val,
                "odds_close": odds_val,
                "is_win": is_win[idx],
                "line_value": lines_test[idx],
                "source": src_val,
            })
            xgb_preds.append(p_xgb[idx])

    df_eval_all = pl.DataFrame(test_records).with_columns(
        pl.Series("confidence", xgb_preds),
        (pl.Series("confidence", xgb_preds) - (1.0 / pl.col("odds_close"))).alias("edge")
    ).filter(pl.col("edge") > 0.0)

    engine_eval = BacktestEngine(global_odds_floor=1.60, min_confidence=0.0)

    print("\n==========================================================================")
    print(" 2. BACKTEST PERFORMANCE BREAKDOWN BY DATA SOURCE (csv_backfill VS jarbet_history)")
    print("==========================================================================")

    df_csv_only = df_eval_all.filter(pl.col("source") == "csv_backfill")
    res_csv = engine_eval.evaluate_tips(df_csv_only, is_money_line=False)
    print(f"\nA. csv_backfill matches ONLY across entire backtest:")
    print(f"   Net Units: {res_csv['total_units']:,.2f} | ROI: {res_csv['roi_pct']:.2f}% | Hit Rate: {res_csv['hit_rate']*100:.2f}% | Tips: {res_csv['tips_evaluated']:,}")
    if res_csv["per_window_breakdown"]:
        for m in res_csv["per_window_breakdown"]:
            print(f"     Month: {m['window']} | Tips: {m['tips']:,} | Units: {m['units']:+,.2f} | ROI: {m['roi_pct']:+.2f}% | Hit Rate: {m['hit_rate']*100:.2f}%")

    df_jarbet_only = df_eval_all.filter(pl.col("source") == "jarbet_history")
    res_jarbet = engine_eval.evaluate_tips(df_jarbet_only, is_money_line=False)
    print(f"\nB. jarbet_history matches ONLY across entire backtest:")
    print(f"   Net Units: {res_jarbet['total_units']:,.2f} | ROI: {res_jarbet['roi_pct']:.2f}% | Hit Rate: {res_jarbet['hit_rate']*100:.2f}% | Tips: {res_jarbet['tips_evaluated']:,}")
    if res_jarbet["per_window_breakdown"]:
        for m in res_jarbet["per_window_breakdown"]:
            print(f"     Month: {m['window']} | Tips: {m['tips']:,} | Units: {m['units']:+,.2f} | ROI: {m['roi_pct']:+.2f}% | Hit Rate: {m['hit_rate']*100:.2f}%")

    print("\n==========================================================================")
    print(" 3. AUGUST TEST WINDOW SOURCE BREAKDOWN (csv_backfill vs jarbet_history)")
    print("==========================================================================")

    df_august = df_eval_all.filter(pl.col("startedAt").dt.month() == 8)
    print(f"Total August test tips evaluated by Strategy D: {len(df_august):,}")
    aug_counts = df_august.group_by("source").len().to_dicts()
    for row in aug_counts:
        print(f"  Source '{row['source']}': {row['len']:,} tips")

    df_aug_csv = df_august.filter(pl.col("source") == "csv_backfill")
    if len(df_aug_csv) > 0:
        res_aug_csv = engine_eval.evaluate_tips(df_aug_csv, is_money_line=False)
        print(f"\n  August csv_backfill subset:")
        print(f"  Net Units: {res_aug_csv['total_units']:,.2f} | ROI: {res_aug_csv['roi_pct']:.2f}% | Hit Rate: {res_aug_csv['hit_rate']*100:.2f}% | Tips: {res_aug_csv['tips_evaluated']:,}")

    df_aug_jarbet = df_august.filter(pl.col("source") == "jarbet_history")
    if len(df_aug_jarbet) > 0:
        res_aug_jarbet = engine_eval.evaluate_tips(df_aug_jarbet, is_money_line=False)
        print(f"\n  August jarbet_history subset:")
        print(f"  Net Units: {res_aug_jarbet['total_units']:,.2f} | ROI: {res_aug_jarbet['roi_pct']:.2f}% | Hit Rate: {res_aug_jarbet['hit_rate']*100:.2f}% | Tips: {res_aug_jarbet['tips_evaluated']:,}")

    print("\n==========================================================================")
    print(" 4. ODDS TIMESTAMPS & PAYLOAD INSPECTION FOR jarbet_history")
    print("==========================================================================")

    # Check core.odds table columns
    query_odds_cols = text("""
        SELECT column_name FROM information_schema.columns WHERE table_schema = 'core' AND table_name = 'odds';
    """)
    with engine.connect() as conn:
        odds_cols = [r[0] for r in conn.execute(query_odds_cols).fetchall()]
    print(f"Columns in core.odds: {odds_cols}")

    query_odds_sample = text("""
        SELECT m.match_id, m.match_start_time, m.source, o.market_type, o.odds_open, o.odds_close
        FROM core.matches m
        JOIN core.odds o ON m.match_id = o.match_id
        WHERE m.source = 'jarbet_history'
        LIMIT 10;
    """)
    with engine.connect() as conn:
        df_odds_sample = pd.read_sql(query_odds_sample, conn)

    print("\nSample 10 jarbet_history records in core.odds:")
    for idx, r in df_odds_sample.iterrows():
        print(f"Match {r['match_id']}: start={r['match_start_time']} | market={r['market_type']} | odds_open={r['odds_open']} | odds_close={r['odds_close']}")

    # Check raw_payload structure for jarbet_history
    query_payload = text("""
        SELECT match_id, match_start_time, raw_payload
        FROM core.matches
        WHERE source = 'jarbet_history'
        LIMIT 5;
    """)
    with engine.connect() as conn:
        df_payload_sample = pd.read_sql(query_payload, conn)

    print("\nSample 5 raw_payload JSON structures in core.matches for jarbet_history:")
    for idx, r in df_payload_sample.iterrows():
        payload_str = str(r['raw_payload'])[:400]
        print(f"Match {r['match_id']} (Start: {r['match_start_time']}):\n  {payload_str}\n")


if __name__ == "__main__":
    run_investigation()
