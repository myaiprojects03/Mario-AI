# Scratch Directory

This directory contains ad-hoc diagnostic, feature extraction, and empirical audit scripts created during development.

> [!NOTE]
> Scripts in this folder are **not** part of the automated production pipeline. They are retained for manual audit, verification, and debugging purposes.

## Folder Structure

- **`scratch/` (Root)**: Reusable verification and feature extraction utility scripts.
  - `count_csv_files.py`: Utility to count raw CSV data rows.
  - `run_real_fifa_feature_extraction.py`: Runs real FIFA Goals O/U feature extraction against DB.
  - `run_real_fifa_ah_extraction.py`: Runs real FIFA Asian Handicap feature extraction against DB.
  - `run_real_fifa_money_line_extraction.py`: Runs real FIFA Money Line feature extraction against DB.
  - `run_real_ebasket_feature_extraction.py`: Runs real eBasketball market feature extraction against DB.
  - `verify_all_market_feature_row_counts_correct.py`: Audits output row counts across all 5 market feature builders against database `source='csv_backfill'`.

- **`scratch/archive/`**: Completed one-off investigation, data repair, and telemetry study scripts.
