# Documentation Hub

Central repository documentation, empirical findings, and data quality audits.

## Directory Layout

- **`docs/ingestion/`**:
  - `FINDINGS.md`: Empirical telemetry study output covering odds snapshot behavior and half-time odds availability.
  - `HISTORICAL_INGESTION_REPORT.md`: Comprehensive audit report for JarBet historical endpoint ingestion (`/history/pre` and `/history/ebasket/pre`).

- **`docs/data_quality/`**:
  - `quality_report_fifa.md`: Data quality audit report for raw FIFA CSV historical datasets.
  - `quality_report_ebasket.md`: Data quality audit report for raw eBasketball CSV historical datasets.

- **`markets/`**:
  - `SCHEMA.md`: Canonical database and feature vector schema specification for all betting markets (retained in `markets/` for direct co-location with feature engineering modules).
  - `<market>/RESULTS.md`: Walk-forward backtest results and model performance reports (retained inside each market folder).
