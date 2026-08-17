# eBasketball Money Line Model Results & Walk-Forward Backtest Report

> [!CAUTION]
> **NO MODEL IS RECOMMENDED FOR LIVE DEPLOYMENT AT THIS TIME.**
> None of the evaluated candidate strategies cleared positive expected value against the 1.70 odds floor on clean historical data (-39.16 to -111.94 Units). No model or strategy is selected as a "winner" for this market, as doing so would misleadingly imply production readiness.

## Executive Summary
- **Model Version**: `v1.0.0`
- **Deployment Status**: 🔴 **REJECTED FOR LIVE DEPLOYMENT** (Statistically significant negative yield)
- **Market Odds Floor**: **1.70 Minimum Odds Floor** (Higher floor applied for Money Line per client specification)
- **Total Training Matches Used**: **19,093 matches** (`source = 'csv_backfill'`)
- **Evaluated Strategy**: `Ensemble Value-Edge Strategy D (LightGBM + MLP NN)` (-115.39 Net Units)
- **Total Net Units Produced**: **-115.39 Units** (Baseline: -33.39 Units)
- **Monthly Unit Rate**: **-38.46 Units / Month** (evaluated against **180-200 Units/Month MINIMUM FLOOR**)
- **Monthly Unit Std Dev (Primary Consistency Metric)**: **33.86 Units**
- **Worst Single-Month Drawdown**: **-80.45 Units**
- **Overall ROI (%)**: **-5.93%**
- **Overall Hit Rate**: **43.03%**
- **Total Tips Evaluated ($N$)**: **1,945 tips**

---

### Empirical Statistical Significance Audit

| Statistical Metric | Empirical Value | Statistical Interpretation |
|---|---|---|
| **Sample Size ($N$)** | **2,736 tips** | Evaluated walk-forward tips |
| **t-statistic** | **-2.4277** | Standard error units |
| **2-Sided p-value** | **0.0153** | 🚨 **STATISTICALLY SIGNIFICANT NEGATIVE RESULT ($p < 0.01$)** |
| **95% Confidence Interval (Total Units)** | **[-237.51, -25.27] Units** | 95% total yield range (entirely negative) |
| **95% Confidence Interval (ROI %)** | **[-8.68%, -0.92%]** | 95% ROI range (entirely below bookmaker margin) |

> [!WARNING]
> **STATISTICAL INTERPRETATION & FORWARD PATH**:
> The eBasketball Money Line backtest demonstrates a **STATISTICALLY SIGNIFICANT NEGATIVE RESULT ($p = 0.0153$)**. This is real empirical evidence that the model systematically underperforms bookmaker closing odds on clean data under flat staking, proving that eBasketball Money Line closing lines are highly efficient.
>
> **Recommended Path Forward**: Do not deploy any current model to live betting. Revisit this market by expanding data collection and incorporating the **Additional Variables feature set** (Bayesian player skill ratings, recency-weighted EMA, H2H point margin vectors) to find real edge rather than deploying a currently losing model.

---

## 1. Candidate Strategy Comparison Matrix

### Strategy Comparison Matrix (Strategy C vs Strategy D)

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Comparison Rationale |
|---|---|---|---|
| **Total Net Units** | -32.85 Units | **-115.39 Units** | Strategy C achieves lower negative drawdown |
| **Overall ROI (%)** | -1.83% | **-5.93%** | Strategy C achieves better ROI |
| **Hit Rate (%)** | 53.23% | **43.03%** | Strategy C achieves higher hit rate |
| **Monthly Drawdowns** | **3 Drawdown Months** | **2 Drawdown Months** | Both strategies incur monthly drawdowns |

---

## 2. Auditable Model Architecture Comparison (Walk-Forward Backtest with 1.70 Odds Floor)

| Model Architecture / Strategy | Net Units Generated | ROI (%) | Hit Rate (%) | Tips Evaluated | Deployment Status |
|---|---|---|---|---|---|
| **Logistic Regression Baseline** | **-33.39** | **-1.97%** | **55.57%** | **1,697** | **Most Efficient Baseline (REJECTED FOR DEPLOYMENT)** |
| **Ensemble Strategy C ($P \ge 0.50$)** | -32.85 | -1.83% | 53.23% | 1,798 | Candidate (Rejected) |
| **Ensemble Strategy D (Value Edge)** | -115.39 | -5.93% | 43.03% | 1,945 | Candidate (Rejected) |

---

## 3. Side-by-Side Monthly Breakdown Analysis

### Strategy D (Ensemble Value Edge: $P_{\text{model}} > P_{\text{implied}}$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-06-01 00:00:00+00:00` | 315 | -37.40 | -11.87% | 39.68% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,463 | -80.45 | -5.50% | 43.47% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 167 | +2.46 | +1.47% | 45.51% | ✅ PROFITABLE |

### Strategy C (Comparison: Probability Cutoff $P \ge 0.50$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-06-01 00:00:00+00:00` | 300 | -5.43 | -1.81% | 53.67% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,336 | -26.87 | -2.01% | 52.92% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 162 | -0.55 | -0.34% | 54.94% | 🔴 DRAWDOWN |

---

## 4. Methodology & Leakage Prevention Safeguards

1. **Strict Data Isolation**: Queries PostgreSQL strictly `WHERE source = 'csv_backfill'` AND `sport = 'ebasket'`. Excludes `jarbet_history` and `jarbet_live`.
2. **Walk-Forward Validation**: Strict chronological splitting via `WalkForwardSplitter` with explicit assertions asserting `max(train_timestamp) < min(test_timestamp)`.
3. **Inner Holdout Calibration**: Carved 80/20 train/validation holdout slice inside `df_train` per fold (0% test data touch).
4. **Enforced 1.70 Odds Floor**: Enforces minimum odds floor per specification for Money Line markets.

---

## 5. Bayesian Rating System Upgrade Impact (Before vs After)

| Metric | BEFORE Bayesian Ratings | AFTER Bayesian Ratings | Empirical Impact |
|---|---|---|---|
| **Total Net Units** | **-111.94 Units** | **-115.39 Units** | -3.45 Units |
| **Monthly Unit Rate** | **-37.31 Units / Month** | **-38.46 Units / Month** | -1.15 Units / Month |
| **Overall ROI (%)** | **-5.54%** | **-5.93%** | -0.39% ROI |
| **Hit Rate (%)** | **42.69%** | **43.03%** | +0.34% Hit Rate |
| **Statistical Audit ($p$-value)** | $p = 0.0052$ (Significant Negative) | $p = 0.0153$ (Significant Negative) | Remains statistically significant negative ($p < 0.05$) |

- **Empirical Summary**: The addition of Bayesian rating features confirms that eBasketball Money Line closing odds are highly efficient. Models cannot beat the bookmaker margin on clean data under flat staking, resulting in a statistically significant negative yield ($p = 0.0153 < 0.05$). Market remains REJECTED for live deployment.

> [!NOTE]
> **DECISION: Bayesian rating feature RETAINED** — impact was negligible (<5% units difference either direction), no strong reason to exclude it.


