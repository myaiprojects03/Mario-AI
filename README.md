# vsp-system

`vsp-system` is a Python 3.11 monorepo for sports prediction pipelines and betting market modeling.

## Directory Layout

```
vsp-system/
├── core/
│   ├── config/          # Central configuration via pydantic-settings
│   ├── db/              # Database connection and ORM models
│   ├── ingestion/       # Data fetching and ingestion utilities
│   └── validation/      # Shared data validation logic
├── markets/
│   ├── fifa_goals_ou/           # FIFA Over/Under Goals market package
│   ├── fifa_asian_handicap/     # FIFA Asian Handicap market package
│   ├── fifa_money_line/         # FIFA Money Line market package
│   ├── ebasket_ou/              # eBasketball Over/Under market package
│   └── ebasket_money_line/      # eBasketball Money Line market package
├── data/                # Local data storage (git-ignored)
├── notebooks/           # Data exploration and analysis notebooks
├── tests/               # Automated unit and integration tests
├── .env.example         # Template for environment variables
├── pyproject.toml       # Monorepo dependencies & package management
├── Makefile             # Command runner targets (install, test, lint)
└── justfile             # Just runner targets (install, test, lint)
```

## Architectural Principles

1. **Market Independence (`markets/`)**
   - Each betting market under `markets/` is designed as a **fully independent package**.
   - There is **no shared model state** between markets.
   - Each market package encapsulates its own data preparation, feature engineering, prediction model, and market-specific validation.

2. **Shared Infrastructure (`core/`)**
   - The `core/` package contains **shared infrastructure only** (database connections, raw data ingestion connectors, general data validation rules, and configuration settings).
   - Application configuration is managed exclusively via `core/config/settings.py` (`pydantic-settings`). Other modules import `settings` from `core.config` rather than accessing `os.environ` directly.

## Getting Started

### Prerequisites
- Python 3.11
- `poetry` or `uv` package manager

### Environment Configuration
Copy the sample environment configuration file and fill in your API credentials and database connection details:

```bash
cp .env.example .env
```

### Installation
Install dependencies using Make or Just:

```bash
make install
# or
just install
```

### Running Tests
Execute the test suite:

```bash
make test
# or
just test
```

### Code Formatting & Linting
Run linters and type checks:

```bash
make lint
# or
just lint
```
