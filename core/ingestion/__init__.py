"""Data ingestion module for external virtual sports API connectors and historical CSV loaders."""

from core.ingestion.jarbet_client import (
    JarBetClient,
    JarBetServerError,
    detect_odds_snapshot_behavior,
    analyze_half_time_odds_presence,
)
from core.ingestion.csv_loader import (
    validate_schema,
    filter_for_market,
    parse_utc_timestamp,
    generate_quality_report,
    upsert_csv_to_db,
    load_and_process_csv,
    EXPECTED_FIFA_COLUMNS,
    EXPECTED_EBASKET_COLUMNS,
)

__all__ = [
    "JarBetClient",
    "JarBetServerError",
    "detect_odds_snapshot_behavior",
    "analyze_half_time_odds_presence",
    "validate_schema",
    "filter_for_market",
    "parse_utc_timestamp",
    "generate_quality_report",
    "upsert_csv_to_db",
    "load_and_process_csv",
    "EXPECTED_FIFA_COLUMNS",
    "EXPECTED_EBASKET_COLUMNS",
]
