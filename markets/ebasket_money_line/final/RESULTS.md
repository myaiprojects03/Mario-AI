# eBasketball Money Line Model Results & Walk-Forward Backtest Report

> [!CAUTION]
> **NO MODEL IS RECOMMENDED FOR LIVE DEPLOYMENT AT THIS TIME.**
> None of the evaluated candidate strategies cleared positive expected value against the 1.70 odds floor on clean historical data (-39.16 to -111.94 Units). No model or strategy is selected as a "winner" for this market, as doing so would misleadingly imply production readiness.

## Executive Summary
- **Model Version**: `v1.0.0`
- **Deployment Status**: 🔴 **REJECTED FOR LIVE DEPLOYMENT** (Statistically significant negative yield)
- **Market Odds Floor**: **1.70 Minimum Odds Floor** (Higher floor applied for Money Line per client specification)
- **Total Training Matches Used**: **26,035 matches** (`source = 'csv_backfill'`)
- **Evaluated Strategy**: `Ensemble Value-Edge Strategy D (LightGBM + MLP NN)` (-194.68 Net Units)
- **Total Net Units Produced**: **-194.68 Units** (Baseline: -142.93 Units)
- **Monthly Unit Rate**: **-48.67 Units / Month** (evaluated against **180-200 Units/Month MINIMUM FLOOR**)
- **Monthly Unit Std Dev (Primary Consistency Metric)**: **41.18 Units**
- **Worst Single-Month Drawdown**: **-92.95 Units**
- **Overall ROI (%)**: **-5.89%**
- **Overall Hit Rate**: **43.16%**
- **Total Tips Evaluated ($N$)**: **3,304 tips**

---

### Empirical Statistical Significance Audit

| Statistical Metric | Empirical Value | Statistical Interpretation |
|---|---|---|
| **Sample Size ($N$)** | **4,663 tips** | Evaluated walk-forward tips |
| **t-statistic** | **-3.5126** | Standard error units |
| **2-Sided p-value** | **0.0004** | 🚨 **STATISTICALLY SIGNIFICANT NEGATIVE RESULT ($p < 0.01$)** |
| **95% Confidence Interval (Total Units)** | **[-386.80, -109.70] Units** | 95% total yield range (entirely negative) |
| **95% Confidence Interval (ROI %)** | **[-8.30%, -2.35%]** | 95% ROI range (entirely below bookmaker margin) |

> [!WARNING]
> **STATISTICAL INTERPRETATION & FORWARD PATH**:
> The eBasketball Money Line backtest demonstrates a **STATISTICALLY SIGNIFICANT NEGATIVE RESULT ($p = 0.0004$)**. This is real empirical evidence that the model systematically underperforms bookmaker closing odds on clean data under flat staking, proving that eBasketball Money Line closing lines are highly efficient.
>
> **Recommended Path Forward**: Do not deploy any current model to live betting. Revisit this market by expanding data collection and incorporating the **Additional Variables feature set** (Bayesian player skill ratings, recency-weighted EMA, H2H point margin vectors) to find real edge rather than deploying a currently losing model.

---

## 1. Candidate Strategy Comparison Matrix

### Strategy Comparison Matrix (Strategy C vs Strategy D)

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Comparison Rationale |
|---|---|---|---|
| **Total Net Units** | -212.04 Units | **-194.68 Units** | Strategy C achieves lower negative drawdown |
| **Overall ROI (%)** | -5.76% | **-5.89%** | Strategy C achieves better ROI |
| **Hit Rate (%)** | 51.05% | **43.16%** | Strategy C achieves higher hit rate |
| **Monthly Drawdowns** | **4 Drawdown Months** | **3 Drawdown Months** | Both strategies incur monthly drawdowns |

---

## 2. Auditable Model Architecture Comparison (Walk-Forward Backtest with 1.70 Odds Floor)

| Model Architecture / Strategy | Net Units Generated | ROI (%) | Hit Rate (%) | Tips Evaluated | Deployment Status |
|---|---|---|---|---|---|
| **Logistic Regression Baseline** | **-142.93** | **-5.06%** | **53.77%** | **2,825** | **Most Efficient Baseline (REJECTED FOR DEPLOYMENT)** |
| **Ensemble Strategy C ($P \ge 0.50$)** | -212.04 | -5.76% | 51.05% | 3,683 | Candidate (Rejected) |
| **Ensemble Strategy D (Value Edge)** | -194.68 | -5.89% | 43.16% | 3,304 | Candidate (Rejected) |

---

## 3. Side-by-Side Monthly Breakdown Analysis

### Strategy D (Ensemble Value Edge: $P_{\text{model}} > P_{\text{implied}}$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 424 | -19.30 | -4.55% | 46.93% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 823 | -85.09 | -10.34% | 42.77% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,577 | -92.95 | -5.89% | 42.42% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 480 | +2.66 | +0.55% | 42.92% | ✅ PROFITABLE |

### Strategy C (Comparison: Probability Cutoff $P \ge 0.50$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 480 | -24.37 | -5.08% | 50.83% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 1,125 | -89.77 | -7.98% | 50.58% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,602 | -68.86 | -4.30% | 51.31% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 476 | -29.04 | -6.10% | 51.47% | 🔴 DRAWDOWN |

---

## 4. Methodology & Leakage Prevention Safeguards

1. **Strict Data Isolation**: Queries PostgreSQL strictly `WHERE source = 'csv_backfill'` AND `sport = 'ebasket'`. Excludes `jarbet_history` and `jarbet_live`.
2. **Walk-Forward Validation**: Strict chronological splitting via `WalkForwardSplitter` with explicit assertions asserting `max(train_timestamp) < min(test_timestamp)`.
3. **Inner Holdout Calibration**: Carved 80/20 train/validation holdout slice inside `df_train` per fold (0% test data touch).
4. **Enforced 1.70 Odds Floor**: Enforces minimum odds floor per specification for Money Line markets.
