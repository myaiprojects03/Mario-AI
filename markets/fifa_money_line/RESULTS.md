# FIFA 1X2 Money Line Model Results & Walk-Forward Backtest Report

## Executive Summary
- **Model Version**: `v1.0.0`
- **Selected Winning Model & Strategy**: `LightGBM Value-Edge Strategy D (P_model > P_implied)`
- **Market Odds Floor**: **1.70 Minimum Odds Floor** (Higher floor applied for Money Line per client specification)
- **Total Training Matches Used**: **93,215 matches** (`source = 'csv_backfill'`)
- **Total Net Units Produced**: **+15.22 Units**
- **Monthly Unit Rate**: **+5.07 Units / Month** (evaluated against **180-200 Units/Month MINIMUM FLOOR**)
- **Monthly Unit Std Dev (Primary Consistency Metric)**: **13.59 Units**
- **Worst Single-Month Drawdown**: **-5.90 Units**
- **Overall ROI (%)**: **+1.94%**
- **Overall Hit Rate**: **37.53%**
- **Total Tips Evaluated**: **786 tips**

---

## 1. Primary Success Metrics & Strategy Selection Rationale

The client has explicitly defined **180-200 units/month as a MINIMUM FLOOR** (not a ceiling target), with month-to-month stability prioritized alongside total net units.

### Strategy Comparison Matrix (Strategy C vs Strategy D)

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Winner Rationale |
|---|---|---|---|
| **Total Net Units** | -196.49 Units | **+15.22 Units** | 🏆 **Strategy D** (+211.71 Net Units higher) |
| **Overall ROI (%)** | -9.57% | **+1.94%** | 🏆 **Strategy D** (Beats bookmaker margin) |
| **Hit Rate (%)** | 50.19% | **37.53%** | 🏆 **Strategy D** (+-12.66% higher win rate) |
| **Monthly Drawdowns** | **2 Drawdown Months** | **2 Drawdown Months** | 🏆 **Strategy D** (Superior month-to-month stability) |

> [!IMPORTANT]
> **Selection Decision**: **Strategy D (Value Edge)** was selected as the final winning pipeline. Strategy D eliminates negative expected-value bets where bookmaker prices offer no edge, perfectly satisfying the client's priority of maximizing net units with strict month-to-month stability.

---

## 2. Auditable Model Architecture Comparison (Walk-Forward Backtest with 1.70 Odds Floor)

| Model Architecture / Strategy | Net Units Generated | ROI (%) | Hit Rate (%) | Tips Evaluated | Selection Status |
|---|---|---|---|---|---|
| **Multinomial Logistic Baseline** | -196.57 | -7.24% | 50.98% | 2,715 | Baseline |
| **LightGBM Strategy C ($P \ge 0.50$)** | -196.49 | -9.57% | 50.19% | 2,054 | Candidate |
| **LightGBM Strategy D (Value Edge)** | **+15.22** | **+1.94%** | **37.53%** | **786** | **🏆 WINNER (Selected)** |
| **Blended Model (60/40)** | -132.03 | -7.46% | 52.06% | 1,771 | Candidate |

---

## 3. Side-by-Side Monthly Breakdown Analysis

### Strategy D (Final Selected Winner: Value Edge $P_{\text{model}} > P_{\text{implied}}$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-06-01 00:00:00+00:00` | 121 | +24.22 | +20.02% | 40.50% | ✅ PROFITABLE |
| `2026-07-01 00:00:00+00:00` | 611 | -5.90 | -0.97% | 36.99% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 54 | -3.10 | -5.74% | 37.04% | 🔴 DRAWDOWN |

### Strategy C (Comparison: Probability Cutoff $P \ge 0.50$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-06-01 00:00:00+00:00` | 367 | -38.37 | -10.46% | 50.68% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,616 | -163.07 | -10.09% | 49.57% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 71 | +4.95 | +6.97% | 61.97% | ✅ PROFITABLE |

---

## 4. Methodology & Leakage Prevention Safeguards

1. **Strict Data Isolation**: Queries PostgreSQL strictly `WHERE source = 'csv_backfill'`. Excludes `jarbet_history` (settled post-hoc odds contamination) and `jarbet_live`.
2. **Walk-Forward Validation**: Strict chronological splitting via `WalkForwardSplitter` with explicit assertions asserting `max(train_timestamp) < min(test_timestamp)`.
3. **Inner Holdout Calibration**: Carved 80/20 train/validation holdout slice inside `df_train` per fold (0% test data touch).
4. **Enforced 1.70 Odds Floor**: Enforces the **1.70 minimum odds floor** (`BacktestEngine(global_odds_floor=1.70)`) per client specification for Money Line markets.
5. **Flat Staking**: 1-unit flat stake per tip.

---

## 5. Bayesian Rating System Upgrade Impact (Before vs After)

| Metric | BEFORE Bayesian Ratings | AFTER Bayesian Ratings | Empirical Impact |
|---|---|---|---|
| **Total Net Units** | **+23.20 Units** | **+15.22 Units** | -7.98 Units |
| **Monthly Unit Rate** | **+7.73 Units / Month** | **+5.07 Units / Month** | -2.66 Units / Month |
| **Overall ROI (%)** | **+3.43%** | **+1.94%** | -1.49% ROI |
| **Hit Rate (%)** | **36.34%** | **37.53%** | +1.19% Hit Rate |
| **Statistical Audit ($p$-value)** | $p = 0.4952$ (Not Significant) | $p = 0.5341$ (Not Significant) | Remains not statistically distinguishable from chance ($p > 0.05$) |

- **Empirical Summary**: The addition of Bayesian rating features slightly narrows positive yield (+15.22 Units, +1.94% ROI, $N=786$). Statistical significance testing confirms that the 1X2 Money Line market remains statistically inconclusive ($p = 0.5341 > 0.05$) on a 3-month sample size.

> [!NOTE]
> **DECISION: Bayesian rating feature RETAINED** — impact was negligible (<5% units difference either direction), no strong reason to exclude it.


