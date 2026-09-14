# eBasketball Over/Under V2 Model Results & Walk-Forward Backtest Report

## Executive Summary
- **Model Version**: `v2.0.0`
- **Selected Winning Model & Strategy**: `eBasketball V2 Ensemble Strategy D (LightGBM + MLP NN)`
- **Market Odds Floor**: **1.60 Minimum Odds Floor**
- **Total Training Matches Used**: **26,035 matches** (`source = 'csv_backfill'`)
- **Total Net Units Produced**: **-268.88 Units**
- **Monthly Unit Rate**: **-67.22 Units / Month**
- **Overall ROI (%)**: **-6.98%**
- **Overall Hit Rate**: **50.92%**
- **Total Tips Evaluated**: **3,853 tips**

---

## 1. Strategy Comparison Matrix

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Winner Rationale |
|---|---|---|---|
| **Total Net Units** | -897.19 Units | **-268.88 Units** | 🏆 **Strategy D** (+628.31 Net Units higher) |
| **Overall ROI (%)** | -5.94% | **-6.98%** | 🏆 **Strategy D** |
| **Hit Rate (%)** | 51.31% | **50.92%** | 🏆 **Strategy D** |
| **Tips Evaluated** | 15,101 | **3,853** | Filtered for positive value edge |

---

## 2. Monthly Breakdown Analysis (Strategy D)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 369 | -3.72 | -1.01% | 54.20% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 2,828 | -235.00 | -8.31% | 50.18% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 545 | -42.04 | -7.71% | 50.46% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 111 | +11.88 | +10.70% | 61.26% | ✅ PROFITABLE |
