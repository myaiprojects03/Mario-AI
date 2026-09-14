# eBasketball Money Line V2 Model Results & Walk-Forward Backtest Report

## Executive Summary
- **Model Version**: `v2.0.0`
- **Selected Winning Model & Strategy**: `eBasketball V2 Ensemble Strategy D (LightGBM + MLP NN)`
- **Market Odds Floor**: **1.70 Minimum Odds Floor**
- **Total Training Matches Used**: **26,035 matches** (`source = 'csv_backfill'`)
- **Total Net Units Produced**: **-315.66 Units**
- **Monthly Unit Rate**: **-78.92 Units / Month**
- **Overall ROI (%)**: **-10.25%**
- **Overall Hit Rate**: **44.16%**
- **Total Tips Evaluated**: **3,080 tips**

---

## 1. Strategy Comparison Matrix

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Winner Rationale |
|---|---|---|---|
| **Total Net Units** | -317.07 Units | **-315.66 Units** | 🏆 **Strategy D** (+1.41 Net Units higher) |
| **Overall ROI (%)** | -8.14% | **-10.25%** | 🏆 **Strategy D** |
| **Hit Rate (%)** | 50.72% | **44.16%** | 🏆 **Strategy D** |
| **Tips Evaluated** | 3,894 | **3,080** | Filtered for positive value edge |

---

## 2. Monthly Breakdown Analysis (Strategy D)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 205 | -14.24 | -6.95% | 50.24% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 1,270 | -158.77 | -12.50% | 44.09% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 1,181 | -114.28 | -9.68% | 43.78% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 424 | -28.37 | -6.69% | 42.45% | 🔴 DRAWDOWN |
