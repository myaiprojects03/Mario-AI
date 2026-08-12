import sys
import site
import pytest
from datetime import datetime, timezone
import polars as pl

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.leagues import get_duration_minutes
from core.ingestion.csv_loader import (
    validate_schema,
    filter_for_market,
    parse_utc_timestamp,
    EXPECTED_FIFA_COLUMNS,
    EXPECTED_EBASKET_COLUMNS,
)


def test_schema_validation_success():
    df = pl.DataFrame({col: ["sample"] for col in EXPECTED_FIFA_COLUMNS})
    assert validate_schema(df, EXPECTED_FIFA_COLUMNS) is True


def test_schema_validation_failure_path():
    # Synthetic DataFrame missing required columns
    bad_df = pl.DataFrame({"_id": ["1"], "league": ["FIFA League"], "unexpected_col": ["test"]})
    
    with pytest.raises(ValueError) as exc_info:
        validate_schema(bad_df, EXPECTED_FIFA_COLUMNS)
    
    err_msg = str(exc_info.value)
    assert "Schema Validation Failed!" in err_msg
    assert "Missing columns" in err_msg


def test_per_market_exclusion_logic():
    # 15-row synthetic dataset with varying odds coverage
    data = {
        "_id": [f"m_{i}" for i in range(15)],
        "odds.over_under.over": [1.85, None, 1.90, None, 1.80, 1.85, None, 1.90, None, 1.80, 1.85, None, 1.90, None, 1.80],
        "closingOdds.over_under.over": [None, None, 1.90, None, None, None, None, 1.90, None, None, None, None, 1.90, None, None],
        "odds.money_line.home": [1.90, 2.10, 1.85, 2.00, 1.95, 1.90, 2.10, 1.85, 2.00, 1.95, 1.90, 2.10, 1.85, 2.00, 1.95],
        "closingOdds.money_line.home": [1.90, 2.10, 1.85, 2.00, 1.95, 1.90, 2.10, 1.85, 2.00, 1.95, 1.90, 2.10, 1.85, 2.00, 1.95],
    }
    df = pl.DataFrame(data)

    ou_filtered = filter_for_market(df, "fifa_goals_ou")
    ml_filtered = filter_for_market(df, "fifa_money_line")

    # O/U filter should exclude rows missing both opening and closing O/U odds
    assert len(ou_filtered) < 15
    assert len(ml_filtered) == 15  # MoneyLine odds are 100% present, preserved for ML market


def test_timezone_conversion_correctness():
    iso_utc_z = "2026-08-11T12:00:00.000Z"
    iso_offset = "2026-05-07T00:55:00.000+00:00"
    naive_dt = datetime(2026, 8, 11, 12, 0, 0)

    dt1 = parse_utc_timestamp(iso_utc_z)
    dt2 = parse_utc_timestamp(iso_offset)
    dt3 = parse_utc_timestamp(naive_dt)

    assert dt1.tzinfo == timezone.utc
    assert dt2.tzinfo == timezone.utc
    assert dt3.tzinfo == timezone.utc

    assert dt1.year == 2026 and dt1.month == 8 and dt1.day == 11 and dt1.hour == 12


def test_match_duration_lookup():
    assert get_duration_minutes("Esoccer Battle - 8 mins play", "fifa") == 8
    assert get_duration_minutes("Esoccer Battle Volta - 6 mins", "fifa") == 6
    assert get_duration_minutes("Esoccer GT Leagues - 12 mins", "fifa") == 12
    assert get_duration_minutes("eBasketball H2H GG League - 4x5mins", "ebasket") == 20
