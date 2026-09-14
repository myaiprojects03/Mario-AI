# eBasketball Over/Under Model Results & Walk-Forward Backtest Report

> [!CAUTION]
> **NO MODEL IS RECOMMENDED FOR LIVE DEPLOYMENT AT THIS TIME.**
> None of the evaluated candidate strategies cleared positive expected value against the 1.60 odds floor on clean historical data (-252.97 Units, -2.67% ROI). No model or strategy is selected as a "winner" for this market, as doing so would misleadingly imply production readiness.

## Executive Summary
- **Model Version**: `v1.0.0`
- **Deployment Status**: 🔴 **REJECTED FOR LIVE DEPLOYMENT** (Negative net expected value)
- **Market Odds Floor**: **1.60 Minimum Odds Floor** (Global floor applied per spec)
- **Total Training Matches Used**: **26,035 matches** (`source = 'csv_backfill'`)
- **Best Candidate Strategy**: `Ensemble Value-Edge Strategy D (LightGBM + MLP NN)` (-252.97 Net Units)
- **Total Net Units Produced**: **-252.97 Units**
- **Monthly Unit Rate**: **-63.24 Units / Month** (evaluated against **180-200 Units/Month MINIMUM FLOOR**)
- **Monthly Unit Std Dev (Primary Consistency Metric)**: **79.73 Units**
- **Worst Single-Month Drawdown**: **-184.29 Units**
- **Overall ROI (%)**: **-2.67%**
- **Overall Hit Rate**: **52.98%**
- **Total Tips Evaluated ($N$)**: **9,473 tips**

---

### Empirical Statistical Significance Audit

| Statistical Metric | Empirical Value | Statistical Interpretation |
|---|---|---|
| **Sample Size ($N$)** | **9,473 tips** | Evaluated walk-forward tips |
| **t-statistic** | **-2.8338** | Standard error units |
| **2-Sided p-value** | **0.0046** | ⚠️ **INCONCLUSIVE ($p > 0.05$)** |
| **95% Confidence Interval (Total Units)** | **[-427.96, -77.98] Units** | 95% total yield range |
| **95% Confidence Interval (ROI %)** | **[-4.52%, -0.82%]** | 95% ROI range |

> [!NOTE]
> **STATISTICAL INTERPRETATION & FORWARD PATH**:
> The eBasketball O/U backtest result is **INCONCLUSIVE ($p = 0.0046$)**. While Strategy D significantly reduces losses compared to Strategy C, we cannot confirm or rule out an edge with the current sample size ($N = 9,473$).
>
> **Recommended Path Forward**: Revisit this market by expanding the feature engineering pipeline to include the **Additional Variables feature set** (Bayesian player ratings, recency-weighted EMA, player matchup vectors, and pace interaction proxies) rather than deploying a currently losing model.

---

## 1. Candidate Strategy Comparison Matrix

### Strategy Comparison Matrix (Strategy C vs Strategy D)

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Comparison Rationale |
|---|---|---|---|
| **Total Net Units** | -560.84 Units | **-252.97 Units** | Strategy D reduces losses by +307.87 Net Units |
| **Overall ROI (%)** | -4.09% | **-2.67%** | Strategy D improves ROI by +1.42% |
| **Hit Rate (%)** | 52.29% | **52.98%** | Strategy D achieves higher hit rate |
| **Monthly Drawdowns** | **4 Drawdown Months** | **2 Drawdown Months** | Both strategies incur monthly drawdowns |

---

## 2. Auditable Model Architecture Comparison (Walk-Forward Backtest with 1.60 Odds Floor)

| Model Architecture / Strategy | Net Units Generated | ROI (%) | Hit Rate (%) | Tips Evaluated | Deployment Status |
|---|---|---|---|---|---|
| **Normal Distribution Baseline** | -314.02 | -3.77% | 52.61% | 8,337 | Baseline (Rejected) |
| **Ensemble Strategy C ($P \ge 0.50$)** | -560.84 | -4.09% | 52.29% | 13,706 | Candidate (Rejected) |
| **Ensemble Strategy D (Value Edge)** | **-252.97** | **-2.67%** | **52.98%** | **9,473** | **Least-Bad Option (REJECTED FOR LIVE DEPLOYMENT)** |

---

## 3. Side-by-Side Monthly Breakdown Analysis

### Strategy D (Ensemble Value Edge: $P_{\text{model}} > P_{\text{implied}}$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 156 | +6.39 | +4.10% | 57.05% | ✅ PROFITABLE |
| `2026-06-01 00:00:00+00:00` | 3,938 | -184.29 | -4.68% | 52.13% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 3,440 | -85.51 | -2.49% | 53.31% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 1,939 | +10.44 | +0.54% | 53.79% | ✅ PROFITABLE |

### Strategy C (Comparison: Probability Cutoff $P \ge 0.50$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 636 | -9.58 | -1.51% | 53.93% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 5,354 | -293.90 | -5.49% | 51.68% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 5,513 | -205.41 | -3.73% | 52.68% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 2,203 | -51.95 | -2.36% | 52.34% | 🔴 DRAWDOWN |

---

## 4. Methodology & Leakage Prevention Safeguards

1. **Strict Data Isolation**: Queries PostgreSQL strictly `WHERE source = 'csv_backfill'` AND `sport = 'ebasket'`. Excludes `jarbet_history` and `jarbet_live`.
2. **Walk-Forward Validation**: Strict chronological splitting via `WalkForwardSplitter` with explicit assertions asserting `max(train_timestamp) < min(test_timestamp)`.
3. **Inner Holdout Calibration**: Carved 80/20 train/validation holdout slice inside `df_train` per fold (0% test data touch).
4. **Enforced 1.60 Odds Floor**: Enforces minimum odds floor per specification.
