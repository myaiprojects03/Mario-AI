import sys
import site
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from core.ingestion.jarbet_history_loader import JarBetHistoryLoader

logger = logging.getLogger("run_live_historical_ingestion")
logging.basicConfig(level=logging.INFO)


def main():
    print("==========================================================================")
    print("   STARTING LIVE JARBET HISTORICAL INGESTION (POSTGRESQL & JARBET API)")
    print("==========================================================================")
    print(f"Target Database URL: {settings.DATABASE_URL}")

    engine = create_engine(settings.DATABASE_URL)
    db_session = Session(bind=engine)
    loader = JarBetHistoryLoader()

    # 1. Ingest eSoccer FIFA History
    print("\n--- INGESTING FIFA HISTORICAL DATA (GET /history/pre) ---")
    fifa_report = loader.ingest_sport_history(sport="fifa", db_session=db_session)
    print(f"FIFA Ingestion Report:\n{json.dumps(fifa_report, indent=2)}")

    # 2. Ingest eBasketball History
    print("\n--- INGESTING EBASKETBALL HISTORICAL DATA (GET /history/ebasket/pre) ---")
    ebasket_report = loader.ingest_sport_history(sport="ebasket", db_session=db_session)
    print(f"eBasketball Ingestion Report:\n{json.dumps(ebasket_report, indent=2)}")

    db_session.close()

    print("\n==========================================================================")
    print("                      HISTORICAL INGESTION SUMMARY REPORT")
    print("==========================================================================")
    print(f"- **FIFA Total Records Pulled**: {fifa_report['total_records_pulled']}")
    print(f"- **FIFA Confirmed Results**: {fifa_report['confirmed_result_records']} (Skipped {fifa_report['skipped_incomplete_records']} incomplete)")
    print(f"- **FIFA Overlap with CSV Backfill**: {fifa_report['overlap_with_csv_backfill_by_id']} by ID / {fifa_report['overlap_with_csv_backfill_by_triplet']} by match triplet")
    print(f"- **FIFA Genuinely New Training Records**: {fifa_report['genuinely_new_training_records']}")
    print(f"- **FIFA Date Range Covered**: {fifa_report['date_range_start']} to {fifa_report['date_range_end']}")
    print("")
    print(f"- **eBasketball Total Records Pulled**: {ebasket_report['total_records_pulled']}")
    print(f"- **eBasketball Confirmed Results**: {ebasket_report['confirmed_result_records']} (Skipped {ebasket_report['skipped_incomplete_records']} incomplete)")
    print(f"- **eBasketball Overlap with CSV Backfill**: {ebasket_report['overlap_with_csv_backfill_by_id']} by ID / {ebasket_report['overlap_with_csv_backfill_by_triplet']} by match triplet")
    print(f"- **eBasketball Genuinely New Training Records**: {ebasket_report['genuinely_new_training_records']}")
    print(f"- **eBasketball Date Range Covered**: {ebasket_report['date_range_start']} to {ebasket_report['date_range_end']}")

    # Save summary report artifact to core/ingestion/HISTORICAL_INGESTION_REPORT.md
    summary_md = [
        "# JarBet Historical Live Ingestion Report",
        "",
        "## 1. Executive Summary",
        f"- **FIFA Historical Matches Ingested**: {fifa_report['total_ingested']}",
        f"- **FIFA Genuinely New Training Matches**: {fifa_report['genuinely_new_training_records']}",
        f"- **eBasketball Matches Ingested**: {ebasket_report['total_ingested']}",
        f"- **eBasketball Genuinely New Training Matches**: {ebasket_report['genuinely_new_training_records']}",
        "",
        "## 2. eSoccer FIFA History Breakdown",
        f"- **Total Records Pulled from API**: {fifa_report['total_records_pulled']}",
        f"- **Confirmed Final Result Count**: {fifa_report['confirmed_result_records']}",
        f"- **Skipped Incomplete Records**: {fifa_report['skipped_incomplete_records']}",
        f"- **Overlap with `csv_backfill` (Match ID)**: {fifa_report['overlap_with_csv_backfill_by_id']}",
        f"- **Overlap with `csv_backfill` (Match Triplet)**: {fifa_report['overlap_with_csv_backfill_by_triplet']}",
        f"- **Genuinely New Training Records**: **{fifa_report['genuinely_new_training_records']}**",
        f"- **Date Range Covered**: `{fifa_report['date_range_start']}` to `{fifa_report['date_range_end']}`",
        "",
        "## 3. eBasketball History Breakdown",
        f"- **Total Records Pulled from API**: {ebasket_report['total_records_pulled']}",
        f"- **Confirmed Final Result Count**: {ebasket_report['confirmed_result_records']}",
        f"- **Skipped Incomplete Records**: {ebasket_report['skipped_incomplete_records']}",
        f"- **Overlap with `csv_backfill` (Match ID)**: {ebasket_report['overlap_with_csv_backfill_by_id']}",
        f"- **Overlap with `csv_backfill` (Match Triplet)**: {ebasket_report['overlap_with_csv_backfill_by_triplet']}",
        f"- **Genuinely New Training Records**: **{ebasket_report['genuinely_new_training_records']}**",
        f"- **Date Range Covered**: `{ebasket_report['date_range_start']}` to `{ebasket_report['date_range_end']}`",
    ]

    with open("core/ingestion/HISTORICAL_INGESTION_REPORT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(summary_md) + "\n")

    print("\nReport written to core/ingestion/HISTORICAL_INGESTION_REPORT.md!")


if __name__ == "__main__":
    main()
