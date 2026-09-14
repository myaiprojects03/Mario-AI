# FIFA 1X2 Money Line V2 Model Results & Walk-Forward Backtest Report

## Executive Summary
- **Model Version**: `v2.0.0`
- **Selected Winning Model & Strategy**: `LightGBM V2 Value-Edge Strategy D (P_model > P_implied)`
- **Market Odds Floor**: **1.70 Minimum Odds Floor**
- **Total Training Matches Used**: **125,878 matches** (`source = 'csv_backfill'`)
- **Total Net Units Produced**: **-336.72 Units**
- **Monthly Unit Rate**: **-84.18 Units / Month**
- **Overall ROI (%)**: **-6.28%**
- **Overall Hit Rate**: **37.31%**
- **Total Tips Evaluated**: **5,361 tips**

---

## 1. Strategy Comparison Matrix

| Metric | Strategy C ($P \ge 0.50$) | Strategy D ($P > P_{\text{implied}}$) | Winner Rationale |
|---|---|---|---|
| **Total Net Units** | -406.09 Units | **-336.72 Units** | 🏆 **Strategy D** (+69.37 Net Units higher) |
| **Overall ROI (%)** | -8.68% | **-6.28%** | 🏆 **Strategy D** |
| **Hit Rate (%)** | 50.58% | **37.31%** | 🏆 **Strategy D** |
| **Tips Evaluated** | 4,678 | **5,361** | Filtered for positive value edge |

---

## 2. Monthly Breakdown Analysis (Strategy D)

| Month Window | Tips Evaluated | Net Units Generated | Monthly ROI (%) | Hit Rate (%) | Status |
|---|---|---|---|---|---|
| `2026-05-01 00:00:00+00:00` | 247 | -14.36 | -5.81% | 40.89% | 🔴 DRAWDOWN |
| `2026-06-01 00:00:00+00:00` | 2,054 | -132.57 | -6.45% | 38.56% | 🔴 DRAWDOWN |
| `2026-07-01 00:00:00+00:00` | 2,433 | -159.08 | -6.54% | 36.05% | 🔴 DRAWDOWN |
| `2026-08-01 00:00:00+00:00` | 627 | -30.71 | -4.90% | 36.68% | 🔴 DRAWDOWN |
