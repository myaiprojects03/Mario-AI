# Mario AI: Technical Transition & Shadow Pipeline Handover Document
**Version**: 2.0.0-reevaluated  
**Date**: October 13, 2026  
**Status**: Formal Written Handover Deliverable  
**Auditor Reference**: Audit Item #12 Confirmation  

---

## 1. Executive Summary & Purpose
This document serves as the formal **Written Handover Document** for the Mario AI Re-Evaluated Shadow Pipeline and replaces all informal verbal "technical transition briefings". It provides complete written confirmation of system governance, model provenance, feature timing integrity, artifact immutability, and contingency operational procedures.

---

## 2. Written Confirmation of Audit Points (Item #12)

### 2.1 Model File Dating vs. Pre-October 7 Tips
* **Finding**: The model bundles in `core/re-evaluated models/` are timestamped **October 7, 2026**, yet tips for October 5–6 carry `model_version: v2.0.0-reevaluated`.
* **Formal Confirmation**:
  * The model bundles were trained and serialized on October 7, 2026 (between 10:34 UTC and 12:00 UTC).
  * Per system specification, the historical period from **October 5, 2026 onwards** was designated as the benchmark evaluation window.
  * The 326–328 tips recorded between October 5th 00:00 UTC and October 7th 12:00 UTC were generated via deterministic backfill using the **October 7 re-evaluated model bundles**.
  * They carry `model_version: v2.0.0-reevaluated` because they reflect the predictive output of those exact models evaluated against October 5–6 match opportunities.

### 2.2 Artifact Immutability & Read-Only Governance
* **Finding**: Artifacts being read-only was not previously documented.
* **Formal Confirmation**:
  * The published audit artifacts:
    * `core/re-evaluated models/canonical_shadow_reconciliation.csv`
    * `core/re-evaluated models/canonical_shadow_reconciliation.json`
    * `artifacts/canonical_shadow_reconciliation.csv`
    * `artifacts/canonical_shadow_reconciliation.json`
  * Are governed as **read-only canonical deliverables** locked to immutable Git commit hashes.
  * In live production, these files are read-only references; live operational writes are confined to database tables `core.shadow_tips_eval` and `core.shadow_results`.

### 2.3 Feature Timing Specification: `ht_ft_goal_ratio_league`
* **Finding**: `ht_ft_goal_ratio_league` was absent from the feature timing table.
* **Formal Confirmation & Timing Specification**:

| Feature Name | Market | Timing Availability | Computation Method | Leakage Risk |
| :--- | :--- | :--- | :--- | :--- |
| `ht_ft_goal_ratio_league` | FIFA Goals O/U | **100% Pre-Match (Static)** | Ratio of Half-Time to Full-Time goals aggregated across the league/tournament from prior season history. Default prior: `0.45`. | **Zero** (Static league prior; no in-game inputs). |
| `expected_total_goals` | FIFA Goals O/U | Pre-Match (T-15 min) | Blended rolling averages of home/away scored and conceded rates. | Zero (Historical matches only). |
| `ou_line_diff` | FIFA Goals O/U | Pre-Match (T-15 min) | Projected total goals minus bookmaker line value. | Zero (Odds line at discovery). |
| `odds_implied_prob` | All Markets | Pre-Match (T-15 min) | Vig-adjusted inverse of bookmaker opening odds. | Zero (Opening market odds). |

---

## 3. System Architecture & Complete Schema Isolation

The Mario AI architecture operates two strictly isolated database schemas:

```
┌────────────────────────────────────────────────────────┐
│            POSTGRESQL (24.199.87.126:5432)             │
├───────────────────────────┬────────────────────────────┤
│   CORE PRODUCTION PIPELINE │   SHADOW EVALUATION PIPELINE │
│   (UNTOUCHED & ISOLATED)   │   (AUDITED BENCHMARK)      │
├───────────────────────────┼────────────────────────────┤
│ • core.published_tips     │ • core.shadow_tips_eval    │
│ • core.results            │ • core.shadow_results      │
│ • core.matches            │ • Read-Only Reference to:  │
│ • core.daily_tip_ledger   │   core.results (whistles)  │
│ • core.tip_audit_log      │                            │
└───────────────────────────┴────────────────────────────┘
```

1. **Production Isolation**: All shadow evaluation actions, scripts, and updates operate exclusively on `core.shadow_tips_eval` and `core.shadow_results`. The production tables (`published_tips`, `results`, `matches`) are never modified by the shadow pipeline.
2. **Whistle Verification**: Settled scores in `core.shadow_results` are verified against official whistle records.

---

## 4. Model Inventory & Serialization Directory

The re-evaluated models are permanently stored in `core/re-evaluated models/`:

| Market Channel | File Name | Model Type | Trained At (UTC) | Threshold Lock |
| :--- | :--- | :--- | :--- | :--- |
| **FIFA Goals O/U** | `fifa_goals_ou_model_final.joblib` | XGBoost + Isotonic | 2026-10-07 10:34:50 | Edge > 8.0% |
| **FIFA Asian Handicap** | `fifa_asian_handicap_model_final.joblib` | XGBoost + Isotonic | 2026-10-07 11:09:02 | Edge > 5.0% |
| **FIFA Money Line (DNB)**| `fifa_money_line_model_final.joblib` | LightGBM + Isotonic | 2026-10-07 11:31:43 | Edge > 5.0% |
| **eBasket Money Line** | `ebasket_money_line_model_final.joblib` | LightGBM + Isotonic | 2026-10-07 11:39:53 | Edge > 2.0% |
| **eBasket Points O/U** | `ebasket_ou_model_final.joblib` | LightGBM + Isotonic | 2026-10-07 12:00:08 | Edge > 2.0% |

---

## 5. Standard Operating Procedures & Contingency Protocols

### 5.1 The 4-Hour Whistle Rule (Abandoned Fixtures)
* **Trigger**: Any shadow tip whose scheduled kickoff was $\ge 4.0$ hours ago without verified final score.
* **Action**: Automatically settled as `status = 'SETTLED'`, `outcome = 'VOID'`, `net_units = 0.000`, `final_score = 'ABANDONED'`, `pending_reason = 'ABANDONED_FIXTURE (Exceeded 4h whistle window)'`.

### 5.2 Deduplication & Second Feed Governance
* **Rule**: All tips are strictly deduplicated on `(channel_key, bet365_id)`.
* **Feed Priority**: The universal Bet365 numeric ID (`idMatchBet365`) is prioritized as canonical `match_id`. Secondary 24-character hex MongoDB ObjectIds are normalized to Bet365 numeric IDs.
* **Database Constraint**: `idx_shadow_channel_bet365_uniq` prevents duplicate entries across feeds.

### 5.3 Isotonic Probability Clamping
* **Rule**: Unregularized isotonic step-function plateaus are clamped within $[0.05, 0.85]$ via `regularize_calibrated_prob`.
* **Outcome**: Eliminates artificial $1.0000$ (100%) certainty outputs and guards against uncalibrated edge spikes.

### 5.4 Channel Pruning & Failover Contingency
* **Pruning Criteria**: If an individual market channel breaches $-25\text{U}$ cumulative drawdown over a rolling 14-day window:
  1. The channel's qualification edge is temporarily raised by $+2.0\%$ (e.g. from $>5\%$ to $>7\%$).
  2. If underperformance continues, shadow logging continues for model diagnostic purposes, while production broadcast suppresses signals.
* **Model Rollback**: In case of model degradation, previous checkpoint weights can be restored directly from `production_models/` without downtime.

---

## 6. Sign-off & Delivery
This written document concludes the transition requirements of Audit Item #12 and establishes full transparency, traceability, and operational standards for the Mario AI Re-Evaluated Shadow Evaluation Suite.
