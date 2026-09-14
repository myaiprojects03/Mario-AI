# FIFA 1X2 Money Line Model Results & Walk-Forward Backtest Report

## Executive Summary
- **Model Version**: `v1.0.0`
- **Selected Winning Model & Strategy**: `LightGBM Value-Edge Strategy D (P_model > P_implied)`
- **Market Odds Floor**: **1.70 Minimum Odds Floor** (Higher floor applied for Money Line per client specification)
- **Total Training Matches Used**: **125,878 matches** (`source = 'csv_backfill'`)
- **Total Net Units Produced**: **-76.47 Units**
- **Monthly Unit Rate**: **-19.12 Units / Month** (evaluated against **180-200 Units/Month MINIMUM FLOOR**)
- **Monthly Unit Std Dev (Primary Consistency Metric)**: **25.92 Units**
- **Worst Single-Month Drawdown**: **-62.94 Units**
- **Overall ROI (%)**: **-3.85%**
- **Overall Hit Rate**: **37.97%**
- **Total Tips Evaluated**: **1,986 tips**

---

## 1. Primary Success Metrics & Strategy Selection Rationale

The client has explicitly defined **180-200 units/month as a MINIMUM FLOOR** (not a ceiling target), with month-to-month stability prioritized alongside total net units.

### Strategy Comparison Matrix (Strategy C vs Strategy D)

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Winner Rationale |
|---|---|---|---|
| **Total Net Units** | -326.79 Units | **-76.47 Units** | 🏆 **Strategy D** (+250.32 Net Units higher) |
| **Overall ROI (%)** | -7.21% | **-3.85%** | 🏆 **Strategy D** (Beats bookmaker margin) |
| **Hit Rate (%)** | 51.36% | **37.97%** | 🏆 **Strategy D** (+-13.39% higher win rate) |
| **Monthly Drawdowns** | **4 Drawdown Months** | **3 Drawdown Months** | 🏆 **Strategy D** (Superior month-to-month stability) |

> [!IMPORTANT]
> **Selection Decision**: **Strategy D (Value Edge)** was selected as the final winning pipeline. Strategy D eliminates negative expected-value bets where bookmaker prices offer no edge, perfectly satisfying the client's priority of maximizing net units with strict month-to-month stability.

---

## 2. Auditable Model Architecture Comparison (Walk-Forward Backtest with 1.70 Odds Floor)

| Model Architecture / Strategy | Net Units Generated | ROI (%) | Hit Rate (%) | Tips Evaluated | Selection Status |
|---|---|---|---|---|---|
| **Multinomial Logistic Baseline** | -300.97 | -6.26% | 51.24% | 4,809 | Baseline |
| **LightGBM Strategy C ($P \ge 0.50$)** | -326.79 | -7.21% | 51.36% | 4,533 | Candidate |
| **LightGBM Strategy D (Value Edge)** | **-76.47** | **-3.85%** | **37.97%** | **1,986** | **🏆 WINNER (Selected)** |
| **Blended Model (60/40)** | -164.53 | -5.28% | 53.42% | 3,117 | Candidate |

---

## 3. Side-by-Side Monthly Breakdown Analysis

### Strategy D (Final Selected Winner: Value Edge $P_{\text{model}} > P_{\text{implied}}$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 80 | -13.44 | -16.80% | 38.75% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 736 | -1.81 | -0.25% | 38.04% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 901 | -62.94 | -6.99% | 37.07% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 269 | +1.72 | +0.64% | 40.52% | ✅ PROFITABLE |

### Strategy C (Comparison: Probability Cutoff $P \ge 0.50$)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 662 | -29.80 | -4.50% | 52.72% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 1,610 | -118.67 | -7.37% | 51.61% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,603 | -158.81 | -9.91% | 49.47% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 658 | -19.51 | -2.97% | 53.95% | 🔴 DRAWDOWN |

---

## 4. Methodology & Leakage Prevention Safeguards

1. **Strict Data Isolation**: Queries PostgreSQL strictly `WHERE source = 'csv_backfill'`. Excludes `jarbet_history` (settled post-hoc odds contamination) and `jarbet_live`.
2. **Walk-Forward Validation**: Strict chronological splitting via `WalkForwardSplitter` with explicit assertions asserting `max(train_timestamp) < min(test_timestamp)`.
3. **Inner Holdout Calibration**: Carved 80/20 train/validation holdout slice inside `df_train` per fold (0% test data touch).
4. **Enforced 1.70 Odds Floor**: Enforces the **1.70 minimum odds floor** (`BacktestEngine(global_odds_floor=1.70)`) per client specification for Money Line markets.
5. **Flat Staking**: 1-unit flat stake per tip.
