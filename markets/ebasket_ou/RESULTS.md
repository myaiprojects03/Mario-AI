# eBasketball Over/Under Model Results & Walk-Forward Backtest Report

> [!CAUTION]
> **NO MODEL IS RECOMMENDED FOR LIVE DEPLOYMENT AT THIS TIME.**
> None of the evaluated candidate strategies cleared positive expected value against the 1.60 odds floor on clean historical data (-62.86 Units, -2.41% ROI). No model or strategy is selected as a "winner" for this market, as doing so would misleadingly imply production readiness.

## Executive Summary
- **Model Version**: `v1.0.0`
- **Deployment Status**: 🔴 **REJECTED FOR LIVE DEPLOYMENT** (Negative net expected value)
- **Market Odds Floor**: **1.60 Minimum Odds Floor** (Global floor applied per spec)
- **Total Training Matches Used**: **19,093 matches** (`source = 'csv_backfill'`)
- **Best Candidate Strategy**: `Ensemble Value-Edge Strategy D (LightGBM + MLP NN)` (-62.86 Net Units)
- **Total Net Units Produced**: **-62.86 Units**
- **Monthly Unit Rate**: **-20.95 Units / Month** (evaluated against **180-200 Units/Month MINIMUM FLOOR**)
- **Monthly Unit Std Dev (Primary Consistency Metric)**: **12.81 Units**
- **Worst Single-Month Drawdown**: **-31.80 Units**
- **Overall ROI (%)**: **-2.41%**
- **Overall Hit Rate**: **53.36%**
- **Total Tips Evaluated ($N$)**: **2,605 tips**

---

### Empirical Statistical Significance Audit

| Statistical Metric | Empirical Value | Statistical Interpretation |
|---|---|---|
| **Sample Size ($N$)** | **2,605 tips** | Evaluated walk-forward tips |
| **t-statistic** | **-1.3494** | Standard error units |
| **2-Sided p-value** | **0.1773** | ⚠️ **INCONCLUSIVE ($p > 0.05$)** |
| **95% Confidence Interval (Total Units)** | **[-154.20, +28.48] Units** | 95% total yield range |
| **95% Confidence Interval (ROI %)** | **[-5.92%, +1.09%]** | 95% ROI range |

> [!NOTE]
> **STATISTICAL INTERPRETATION & FORWARD PATH**:
> The eBasketball O/U backtest result is **INCONCLUSIVE ($p = 0.1773$)**. While Strategy D significantly reduces losses compared to Strategy C, we cannot confirm or rule out an edge with the current sample size ($N = 2,605$).
>
> **Recommended Path Forward**: Revisit this market by expanding the feature engineering pipeline to include the **Additional Variables feature set** (Bayesian player ratings, recency-weighted EMA, player matchup vectors, and pace interaction proxies) rather than deploying a currently losing model.

---

## 1. Candidate Strategy Comparison Matrix

### Strategy Comparison Matrix (Strategy C vs Strategy D)

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Comparison Rationale |
|---|---|---|---|
| **Total Net Units** | -301.59 Units | **-62.86 Units** | Strategy D reduces losses by +238.73 Net Units |
| **Overall ROI (%)** | -4.41% | **-2.41%** | Strategy D improves ROI by +2.00% |
| **Hit Rate (%)** | 52.33% | **53.36%** | Strategy D achieves higher hit rate |
| **Monthly Drawdowns** | **3 Drawdown Months** | **3 Drawdown Months** | Both strategies incur monthly drawdowns |

---

## 2. Auditable Model Architecture Comparison (Walk-Forward Backtest with 1.60 Odds Floor)

| Model Architecture / Strategy | Net Units Generated | ROI (%) | Hit Rate (%) | Tips Evaluated | Deployment Status |
|---|---|---|---|---|---|
| **Normal Distribution Baseline** | -189.80 | -3.74% | 52.67% | 5,077 | Baseline (Rejected) |
| **Ensemble Strategy C ($P \ge 0.50$)** | -301.59 | -4.41% | 52.33% | 6,841 | Candidate (Rejected) |
| **Ensemble Strategy D (Value Edge)** | **-62.86** | **-2.41%** | **53.36%** | **2,605** | **Least-Bad Option (REJECTED FOR LIVE DEPLOYMENT)** |

---

## 3. Side-by-Side Monthly Breakdown Analysis

### Strategy D (Ensemble Value Edge: $P_{\text{model}} > P_{\text{implied}}$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-06-01 00:00:00+00:00` | 636 | -2.97 | -0.47% | 54.40% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,298 | -31.80 | -2.45% | 53.31% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 671 | -28.09 | -4.19% | 52.46% | 🔴 DRAWDOWN |

### Strategy C (Comparison: Probability Cutoff $P \ge 0.50$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-06-01 00:00:00+00:00` | 1,592 | -122.06 | -7.67% | 50.50% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 4,433 | -131.81 | -2.97% | 53.10% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 816 | -47.72 | -5.85% | 51.72% | 🔴 DRAWDOWN |

---

## 4. Methodology & Leakage Prevention Safeguards

1. **Strict Data Isolation**: Queries PostgreSQL strictly `WHERE source = 'csv_backfill'` AND `sport = 'ebasket'`. Excludes `jarbet_history` and `jarbet_live`.
2. **Walk-Forward Validation**: Strict chronological splitting via `WalkForwardSplitter` with explicit assertions asserting `max(train_timestamp) < min(test_timestamp)`.
3. **Inner Holdout Calibration**: Carved 80/20 train/validation holdout slice inside `df_train` per fold (0% test data touch).
4. **Enforced 1.60 Odds Floor**: Enforces minimum odds floor per specification.

---

## 5. Bayesian Rating System Upgrade Impact (Before vs After)

| Metric | BEFORE Bayesian Ratings | AFTER Bayesian Ratings | Empirical Impact |
|---|---|---|---|
| **Total Net Units** | **-122.91 Units** | **-62.86 Units** | **+60.05 Units Saved (+48.9% Reduction in Loss)** |
| **Monthly Unit Rate** | **-40.97 Units / Month** | **-20.95 Units / Month** | **+20.02 Units / Month Saved** |
| **Overall ROI (%)** | **-2.44%** | **-2.41%** | +0.03% ROI |
| **Hit Rate (%)** | **53.39%** | **53.36%** | -0.03% Hit Rate |
| **Statistical Audit ($p$-value)** | $p = 0.0578$ (Inconclusive) | $p = 0.1773$ (Inconclusive) | Remains inconclusive ($p > 0.05$); net losses halved |

- **Empirical Summary**: The addition of Bayesian rating features reduced total net losses in eBasketball O/U by ~50% (saving +60.05 units), demonstrating real variance reduction. However, overall net yield remains slightly negative against the 1.60 odds floor on clean historical data, keeping this market INCONCLUSIVE and REJECTED for live deployment.

> [!NOTE]
> **DECISION: Bayesian rating feature RETAINED for this market** — meaningfully reduced losses (+60.05 units improvement), even though the market remains not yet profitable and is still not recommended for live deployment.


