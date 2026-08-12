import os
import sys
import site
import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

import polars as pl
from sqlalchemy.orm import Session

from core.config.settings import settings
from core.db import Match, Odds, Result

logger = logging.getLogger("core.ingestion.csv_loader")
logging.basicConfig(level=logging.INFO)

# Expected Column Schemas
EXPECTED_FIFA_COLUMNS = [
    "_id", "idMatchBet365", "league", "startedAt", "createdAt", "updatedAt",
    "home.name", "home.nameLower", "home.teamName", "home.teamNameLower", "home.goals", "home.goalsHT",
    "away.name", "away.nameLower", "away.teamName", "away.teamNameLower", "away.goals", "away.goalsHT",
    "odds.over_under.over", "odds.over_under.under", "odds.over_under.line",
    "odds.asian_handicap.home", "odds.asian_handicap.away", "odds.asian_handicap.line",
    "odds.money_line.home", "odds.money_line.away", "odds.money_line.draw",
    "odds.draw_no_bet.home", "odds.draw_no_bet.away",
    "closingOdds.over_under.over", "closingOdds.over_under.under", "closingOdds.over_under.line",
    "closingOdds.asian_handicap.home", "closingOdds.asian_handicap.away", "closingOdds.asian_handicap.line",
    "closingOdds.money_line.home", "closingOdds.money_line.away", "closingOdds.money_line.draw",
    "closingOdds.draw_no_bet.home", "closingOdds.draw_no_bet.away",
    "closingOdds.over_under_ht.over", "closingOdds.over_under_ht.under", "closingOdds.over_under_ht.line",
    "closingOdds.asian_handicap_ht.home", "closingOdds.asian_handicap_ht.away", "closingOdds.asian_handicap_ht.line",
    "odds.over_under_ht.over", "odds.over_under_ht.under", "odds.over_under_ht.line",
    "odds.asian_handicap_ht.home", "odds.asian_handicap_ht.away", "odds.asian_handicap_ht.line",
]

EXPECTED_EBASKET_COLUMNS = [
    "_id", "idMatchBet365", "league", "startedAt", "createdAt", "updatedAt",
    "home.name", "home.nameLower", "home.teamName", "home.teamNameLower", "home.goals", "home.goalsHT",
    "away.name", "away.nameLower", "away.teamName", "away.teamNameLower", "away.goals", "away.goalsHT",
    "odds.over_under.over", "odds.over_under.under", "odds.over_under.line",
    "odds.over_under_ht.over", "odds.over_under_ht.under", "odds.over_under_ht.line",
    "odds.asian_handicap.home", "odds.asian_handicap.away", "odds.asian_handicap.line",
    "odds.asian_handicap_ht.home", "odds.asian_handicap_ht.away", "odds.asian_handicap_ht.line",
    "odds.money_line.home", "odds.money_line.away", "odds.money_line.draw",
    "closingOdds.over_under.over", "closingOdds.over_under.under", "closingOdds.over_under.line",
    "closingOdds.over_under_ht.over", "closingOdds.over_under_ht.under", "closingOdds.over_under_ht.line",
    "closingOdds.asian_handicap.home", "closingOdds.asian_handicap.away", "closingOdds.asian_handicap.line",
    "closingOdds.asian_handicap_ht.home", "closingOdds.asian_handicap_ht.away", "closingOdds.asian_handicap_ht.line",
    "closingOdds.money_line.home", "closingOdds.money_line.away", "closingOdds.money_line.draw",
]

from core.config.leagues import get_duration_minutes


def validate_schema(df: pl.DataFrame, expected_columns: List[str]) -> bool:
    """
    Validate dataframe columns against expected schema.
    Fails loudly and prints column diff if columns do not match expectations.
    """
    actual_set = set(df.columns)
    expected_set = set(expected_columns)

    missing = expected_set - actual_set
    unexpected = actual_set - expected_set

    if missing or unexpected:
        diff_msg = (
            f"Schema Validation Failed!\n"
            f"  Missing columns ({len(missing)}): {sorted(list(missing))}\n"
            f"  Unexpected columns ({len(unexpected)}): {sorted(list(unexpected))}"
        )
        logger.error(diff_msg)
        raise ValueError(diff_msg)

    logger.info("Schema validation passed successfully.")
    return True


def filter_for_market(df: pl.DataFrame, market_type: str) -> pl.DataFrame:
    """
    Excludes rows missing core odds fields for a specific market from that market's training set.
    Per-market filter (never a single global drop across all markets).
    """
    if market_type in ("fifa_goals_ou", "ebasket_ou"):
        # Requires over/under odds (either open or close line)
        ou_col = "odds.over_under.over" if "odds.over_under.over" in df.columns else None
        close_ou = "closingOdds.over_under.over" if "closingOdds.over_under.over" in df.columns else None
        
        if ou_col and close_ou:
            return df.filter(pl.col(ou_col).is_not_null() | pl.col(close_ou).is_not_null())
        elif ou_col:
            return df.filter(pl.col(ou_col).is_not_null())
        elif close_ou:
            return df.filter(pl.col(close_ou).is_not_null())

    elif market_type == "fifa_asian_handicap":
        ah_col = "odds.asian_handicap.home" if "odds.asian_handicap.home" in df.columns else None
        close_ah = "closingOdds.asian_handicap.home" if "closingOdds.asian_handicap.home" in df.columns else None
        
        if ah_col and close_ah:
            return df.filter(pl.col(ah_col).is_not_null() | pl.col(close_ah).is_not_null())
        elif ah_col:
            return df.filter(pl.col(ah_col).is_not_null())

    elif market_type in ("fifa_money_line", "ebasket_money_line"):
        ml_col = "odds.money_line.home" if "odds.money_line.home" in df.columns else None
        close_ml = "closingOdds.money_line.home" if "closingOdds.money_line.home" in df.columns else None
        
        if ml_col and close_ml:
            return df.filter(pl.col(ml_col).is_not_null() | pl.col(close_ml).is_not_null())
        elif ml_col:
            return df.filter(pl.col(ml_col).is_not_null())

    return df


def parse_utc_timestamp(ts_val: Any) -> datetime:
    """Parse ISO string or timestamp object to UTC timezone-aware datetime."""
    if isinstance(ts_val, datetime):
        if ts_val.tzinfo is None:
            return ts_val.replace(tzinfo=timezone.utc)
        return ts_val.astimezone(timezone.utc)
    
    if isinstance(ts_val, str) and ts_val:
        try:
            dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

    return datetime.now(timezone.utc)


def generate_quality_report(df: pl.DataFrame, sport: str, output_path: str) -> Dict[str, Any]:
    """
    Computes data quality statistics, null rates, market exclusion counts, and
    distribution sanity checks, writing the report to output_path.
    """
    total_rows = len(df)
    
    # Null rates per column
    null_counts = df.null_count()
    null_rates = {col: (null_counts[col][0] / total_rows) * 100.0 for col in df.columns}

    # Per-market exclusion counts
    if sport == "fifa":
        markets = ["fifa_goals_ou", "fifa_asian_handicap", "fifa_money_line"]
    else:
        markets = ["ebasket_ou", "ebasket_money_line"]

    exclusion_counts = {}
    for m in markets:
        filtered_df = filter_for_market(df, m)
        exclusion_counts[m] = {
            "retained": len(filtered_df),
            "excluded": total_rows - len(filtered_df),
            "exclusion_rate": ((total_rows - len(filtered_df)) / total_rows) * 100.0 if total_rows > 0 else 0.0,
        }

    # Distribution sanity check (drop nulls for cancelled/unplayed matches)
    valid_goals_df = df.filter(pl.col("home.goals").is_not_null() & pl.col("away.goals").is_not_null())
    total_metric = (valid_goals_df["home.goals"] + valid_goals_df["away.goals"]).to_numpy()
    mean_val = float(total_metric.mean())
    std_val = float(total_metric.std())

    if sport == "fifa":
        bench_mean, bench_std = 4.56, 2.65
        metric_name = "Total Goals"
        tolerance_mean, tolerance_std = 0.5, 0.5
    else:
        bench_mean, bench_std = 111.8, 23.1
        metric_name = "Total Points"
        tolerance_mean, tolerance_std = 5.0, 5.0

    mean_diff = abs(mean_val - bench_mean)
    std_diff = abs(std_val - bench_std)
    flagged = (mean_diff > tolerance_mean) or (std_diff > tolerance_std)

    # Missing odds coverage by league
    leagues = df["league"].unique().to_list()
    odds_col = "odds.over_under.over" if "odds.over_under.over" in df.columns else df.columns[0]
    
    league_odds_summary = []
    for l in leagues:
        sub_df = df.filter(pl.col("league") == l)
        l_total = len(sub_df)
        l_missing = sub_df[odds_col].null_count()
        l_rate = (l_missing / l_total) * 100.0 if l_total > 0 else 0.0
        league_odds_summary.append((l, l_total, l_missing, l_rate))

    # Format Markdown Report
    lines = [
        f"# Data Quality & Distribution Sanity Report - {sport.upper()}",
        f"- **Total Input Rows**: {total_rows}",
        f"- **Generated At (UTC)**: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## 1. Distribution Sanity Check",
        f"- **Metric Analyzed**: {metric_name}",
        f"- **Actual Mean / Std**: {mean_val:.2f} / {std_val:.2f}",
        f"- **Spec Benchmark Mean / Std**: {bench_mean:.2f} / {bench_std:.2f}",
        f"- **Status**: {'⚠️ WARNING: SIGNIFICANT DEVIATION DETECTED' if flagged else '✅ PASSED SANITY CHECK'}",
        "",
        "## 2. Per-Market Exclusion Counts (Odds Coverage Filter)",
        "| Market Type | Retained Rows | Excluded Rows | Exclusion Rate (%) |",
        "|---|---|---|---|",
    ]

    for m, stat in exclusion_counts.items():
        lines.append(f"| {m} | {stat['retained']} | {stat['excluded']} | {stat['exclusion_rate']:.2f}% |")

    lines.extend([
        "",
        "## 3. Missing Odds Coverage by League",
        "| League | Total Matches | Missing Odds Rows | Missing Rate (%) |",
        "|---|---|---|---|",
    ])

    for l, l_total, l_missing, l_rate in league_odds_summary:
        lines.append(f"| {l} | {l_total} | {l_missing} | {l_rate:.2f}% |")

    lines.extend([
        "",
        "## 4. Column Null Rates",
        "| Column Name | Null Count | Null Rate (%) |",
        "|---|---|---|",
    ])

    for col in sorted(null_rates.keys()):
        lines.append(f"| `{col}` | {null_counts[col][0]} | {null_rates[col]:.2f}% |")

    report_content = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    logger.info(f"Wrote data quality report to {output_path}")
    return {
        "total_rows": total_rows,
        "mean_val": mean_val,
        "std_val": std_val,
        "flagged": flagged,
        "exclusion_counts": exclusion_counts,
    }


from sqlalchemy.dialects.postgresql import insert as pg_insert


def upsert_csv_to_db(df: pl.DataFrame, sport: str, db_session: Session, batch_size: int = 5000) -> int:
    """
    Parse cleaned records from Polars dataframe and bulk upsert into core.matches, core.odds, and core.results
    using fast batching and PostgreSQL ON CONFLICT DO UPDATE.
    """
    records = df.to_dicts()
    total_records = len(records)
    logger.info(f"Starting bulk DB upsert for {total_records} {sport} records...")

    for i in range(0, total_records, batch_size):
        chunk = records[i:i + batch_size]
        
        match_mappings = []
        result_mappings = []
        odds_mappings = []

        for row in chunk:
            # ASSUMPTION: Using '_id' or 'idMatchBet365' as the natural match_id key.
            # If missing, generate md5 natural key hash from home_player + away_player + startedAt.
            match_id = str(row.get("_id") or row.get("idMatchBet365") or "")
            home_player = row.get("home.name") or row.get("home.nameLower")
            away_player = row.get("away.name") or row.get("away.nameLower")
            started_at_raw = row.get("startedAt")

            if not match_id:
                raw_key = f"{home_player}:{away_player}:{started_at_raw}"
                match_id = hashlib.md5(raw_key.encode("utf-8")).hexdigest()

            league = row.get("league") or "Unknown League"
            home_team = row.get("home.teamName") or "Home Team"
            away_team = row.get("away.teamName") or "Away Team"
            match_start_time = parse_utc_timestamp(started_at_raw)
            duration_minutes = get_duration_minutes(league, sport)

            match_mappings.append({
                "match_id": match_id,
                "sport": sport,
                "league": league,
                "home_player": home_player,
                "away_player": away_player,
                "home_team": home_team,
                "away_team": away_team,
                "match_start_time": match_start_time,
                "duration_minutes": duration_minutes,
                "source": "csv_backfill",
                "game_version": None,
                "raw_payload": None,
            })

            home_goals = row.get("home.goals")
            away_goals = row.get("away.goals")
            if home_goals is not None and away_goals is not None:
                result_mappings.append({
                    "match_id": match_id,
                    "final_home_score": int(home_goals),
                    "final_away_score": int(away_goals),
                    "settled_at": match_start_time,
                    "settlement_source": "csv_backfill",
                })

            # 3. Upsert core.odds summary for all markets
            # a) Over/Under odds
            ou_line = row.get("odds.over_under.line") or row.get("closingOdds.over_under.line")
            ou_open = row.get("odds.over_under.over")
            ou_close = row.get("closingOdds.over_under.over")
            if ou_open is not None or ou_close is not None:
                market_name = "fifa_goals_ou" if sport == "fifa" else "ebasket_ou"
                odds_mappings.append({
                    "match_id": match_id,
                    "market_type": market_name,
                    "line_value": float(ou_line) if ou_line is not None else None,
                    "odds_open": float(ou_open) if ou_open is not None else None,
                    "odds_close": float(ou_close) if ou_close is not None else None,
                    "odds_snapshot_time": match_start_time,
                    "side": "over",
                })

            # b) Money Line odds
            ml_open = row.get("odds.money_line.home")
            ml_close = row.get("closingOdds.money_line.home")
            if ml_open is not None or ml_close is not None:
                market_name = "fifa_money_line" if sport == "fifa" else "ebasket_money_line"
                odds_mappings.append({
                    "match_id": match_id,
                    "market_type": market_name,
                    "line_value": None,
                    "odds_open": float(ml_open) if ml_open is not None else None,
                    "odds_close": float(ml_close) if ml_close is not None else None,
                    "odds_snapshot_time": match_start_time,
                    "side": "home",
                })

            # c) Asian Handicap odds (FIFA only)
            if sport == "fifa":
                ah_line = row.get("odds.asian_handicap.line") or row.get("closingOdds.asian_handicap.line")
                ah_open = row.get("odds.asian_handicap.home")
                ah_close = row.get("closingOdds.asian_handicap.home")
                if ah_open is not None or ah_close is not None:
                    odds_mappings.append({
                        "match_id": match_id,
                        "market_type": "fifa_asian_handicap",
                        "line_value": float(ah_line) if ah_line is not None else None,
                        "odds_open": float(ah_open) if ah_open is not None else None,
                        "odds_close": float(ah_close) if ah_close is not None else None,
                        "odds_snapshot_time": match_start_time,
                        "side": "home",
                    })

        # Execute PostgreSQL ON CONFLICT bulk upserts
        if db_session.bind.dialect.name == "postgresql":
            if match_mappings:
                stmt_m = pg_insert(Match).values(match_mappings)
                stmt_m = stmt_m.on_conflict_do_update(
                    index_elements=["match_id"],
                    set_={
                        "sport": stmt_m.excluded.sport,
                        "league": stmt_m.excluded.league,
                        "home_player": stmt_m.excluded.home_player,
                        "away_player": stmt_m.excluded.away_player,
                        "home_team": stmt_m.excluded.home_team,
                        "away_team": stmt_m.excluded.away_team,
                        "match_start_time": stmt_m.excluded.match_start_time,
                        "duration_minutes": stmt_m.excluded.duration_minutes,
                        "source": stmt_m.excluded.source,
                    },
                )
                db_session.execute(stmt_m)

            if result_mappings:
                stmt_r = pg_insert(Result).values(result_mappings)
                db_session.execute(stmt_r)

            if odds_mappings:
                stmt_o = pg_insert(Odds).values(odds_mappings)
                db_session.execute(stmt_o)
        else:
            # Fallback for non-PostgreSQL (SQLite in-memory unit tests)
            db_session.bulk_insert_mappings(Match, match_mappings)
            if result_mappings:
                db_session.bulk_insert_mappings(Result, result_mappings)
            if odds_mappings:
                db_session.bulk_insert_mappings(Odds, odds_mappings)

        db_session.commit()
        logger.info(f"Upserted chunk {i + len(chunk)}/{total_records} records...")

    return total_records


def load_and_process_csv(csv_path: str, sport: str, db_session: Optional[Session] = None) -> Tuple[pl.DataFrame, Dict[str, Any]]:
    """
    Loads CSV with polars, validates schema, generates quality report, and optional DB upsert.
    """
    logger.info(f"Loading CSV file: {csv_path}")
    df = pl.read_csv(csv_path)

    expected = EXPECTED_FIFA_COLUMNS if sport == "fifa" else EXPECTED_EBASKET_COLUMNS
    validate_schema(df, expected)

    report_path = f"data/quality_report_{sport}.md"
    metrics = generate_quality_report(df, sport, report_path)

    if db_session:
        upsert_csv_to_db(df, sport, db_session)

    return df, metrics


if __name__ == "__main__":
    from core.db import get_db

    fifa_path = "data/raw/history_pre_fifa.csv"
    ebasket_path = "data/raw/history_pre_ebasket.csv"

    if os.path.exists(fifa_path):
        with get_db() as session:
            load_and_process_csv(fifa_path, "fifa", session)

    if os.path.exists(ebasket_path):
        with get_db() as session:
            load_and_process_csv(ebasket_path, "ebasket", session)
