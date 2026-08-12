# Database Infrastructure (`core/db`)

This module provides the PostgreSQL database schema definitions, SQLAlchemy models, database connection management, and Alembic migrations for `vsp-system`.

## Multi-Schema Architecture

The database is partitioned into **6 PostgreSQL schemas (namespaces)**:

1. **`core`**: Contains shared infrastructure entities common to all sports prediction markets:
   - `core.matches`: Central match catalog storing teams, players, sports, schedule, game version (`game_version`), and raw payload data.
   - `core.odds`: Derived summary table capturing high-level opening (`odds_open`) and closing (`odds_close`) line bounds for fast querying.
   - `core.odds_snapshots`: Granular time-series snapshot table capturing every individual odds poll for a match. `odds_snapshots` exists separately from `odds` to support complex market microstructure and odds trajectory features (e.g., path volatility, time-weighted average odds, drift velocity), which require the complete temporal sequence of market polls rather than just boundary values.
   - `core.results`: Settled match scores and outcome details.

2. **Per-Market Schemas**:
   - `fifa_goals_ou`
   - `fifa_asian_handicap`
   - `fifa_money_line`
   - `ebasket_ou`
   - `ebasket_money_line`

Each market schema contains independent instances of:
- `features`: Feature vectors computed specifically for that market model pipeline.
- `model_scores`: Inference score logs, probability estimates, and confidence scores.
- `tip_log`: Published tips, entry odds, threshold bounds, and settlement PnL tracking.

### Rationale for Per-Market Schema Partitioning

- **Query Isolation**: High-frequency feature generation, batch retraining, or heavy scoring queries on one market (e.g., `ebasket_ou`) will never lock or slow down table access or indexing for another market (e.g., `fifa_money_line`).
- **Independent Schema & Feature Evolution**: Market feature sets and model score representations can evolve independently per market without requiring migration locks across unrelated prediction pipelines.
- **Strict Architectural Alignment**: Directly reflects the project specification where all 5 prediction pipelines operate as **fully independent models** with isolated data preparation, feature engineering, model state, and validation.

## Key Schema Indexing

- `core.matches.match_start_time`: B-tree index for fast date-range filtering.
- `core.matches.league`: B-tree index for filtering by competition/league.
- `core.odds`: Composite index on `(match_id, market_type)` for ultra-fast odds lookup by match and market.

## Usage & Session Factory

```python
from core.db import get_db, Match, FifaGoalsOUFeature

# Transactional Context Manager
with get_db() as session:
    match = session.query(Match).filter_by(match_id="12345").first()
```

## Running Database Migrations

Apply Alembic migrations to upgrade the database schema:

```bash
alembic upgrade head
```

To rollback:

```bash
alembic downgrade -1
```
