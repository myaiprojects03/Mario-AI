# vsp-system

`vsp-system` is a Python production monorepo for eSports (FIFA / eBasketball) data ingestion, feature engineering, walk-forward backtesting, and predictive betting market modeling.

---

## Directory Layout

```text
vsp-system/
├── core/                        # Shared system infrastructure
│   ├── config/                  # Environment settings (pydantic-settings) & league definitions
│   ├── db/                      # SQLAlchemy database connections, migrations & ORM models
│   ├── features/                # Base feature engineering primitives (rolling stats, H2H, drift)
│   ├── ingestion/               # JarBet client, CSV loader & historical data backfill loaders
│   └── validation/              # Time-series walk-forward splitter, backtest engine & calibrator
├── markets/                     # Independent betting market packages
│   ├── _shared/                 # Shared feature utility builders (FIFA & eBasketball)
│   ├── fifa_goals_ou/           # FIFA Over/Under Goals market package
│   │   ├── features.py          # Market feature builder
│   │   ├── model.py             # Pipeline entry point & walk-forward backtester
│   │   ├── RESULTS.md           # Model performance & backtest report
│   │   ├── artifacts/           # Binary model artifacts (*.joblib, gitignored)
│   │   └── models/              # Sub-models folder (Poisson/Dixon-Coles, XGBoost, Blended)
│   ├── fifa_asian_handicap/     # FIFA Asian Handicap market package
│   ├── fifa_money_line/         # FIFA Money Line market package
│   ├── ebasket_ou/              # eBasketball Over/Under market package
│   ├── ebasket_money_line/      # eBasketball Money Line market package
│   └── SCHEMA.md                # Feature vector & PostgreSQL schema specification
├── docs/                        # Project documentation & empirical reports
│   ├── data_quality/            # Raw data quality audit reports (FIFA & eBasketball)
│   └── ingestion/               # Raw ingestion findings & historical loader reports
├── scratch/                     # Ad-hoc audit & verification scripts
│   ├── README.md                # Scratch directory usage guide
│   └── archive/                 # One-off completed investigation & repair scripts
├── data/                        # Local CSV storage (git-ignored)
├── alembic/                     # Database migration scripts
├── tests/                       # Automated unit & integration pytest suite
├── pyproject.toml               # Monorepo dependencies & package management
└── README.md
```

---

## Developer Navigation & Architectural Conventions

### 1. Market Independence (`markets/`)
- Each betting market in `markets/` is an independent package encapsulating its own feature engineering, predictive models, backtest reporting, and model artifacts.
- **Model Subfolder Standard**: Each market model adopts the `markets/<market>/models/` structure for sub-component models (e.g. `poisson_dixon_coles.py`, `xgb_model.py`, `blended_model.py`), with `markets/<market>/model.py` acting as the pipeline entry point.
- **Backtest Results Location**: Market backtest results and performance benchmarks are documented directly in `markets/<market>/RESULTS.md`.
- **Schema Specification**: Refer to `markets/SCHEMA.md` for feature vector column definitions and database table schemas.

### 2. Documentation Hub (`docs/`)
- **Data Quality Reports**: Found in `docs/data_quality/` (`quality_report_fifa.md`, `quality_report_ebasket.md`).
- **Ingestion Telemetry & Audits**: Found in `docs/ingestion/` (`FINDINGS.md`, `HISTORICAL_INGESTION_REPORT.md`).

### 3. Shared Infrastructure (`core/`)
- Contains database connections (`core/db/`), configuration settings (`core/config/`), ingestion clients (`core/ingestion/`), and validation/backtesting primitives (`core/validation/`).
- All settings are managed via `core/config/settings.py` (`pydantic-settings`).

---

## Getting Started

### Environment Setup
```bash
cp .env.example .env
```

### Running Tests
Execute the full test suite:
```bash
python -m pytest
```

### Running Feature Extraction & Model Backtests
```bash
python -m markets.fifa_goals_ou.model
```
