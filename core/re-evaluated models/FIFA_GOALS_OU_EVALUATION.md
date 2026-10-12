# Re-evaluated Model Audit Report: Market 1 (FIFA Goals Over/Under)

**Model Version**: `v2.0.0-reevaluated`  
**Feature Version**: `v2.0.0-clean-prematch`  
**Trained At**: `2026-10-07T10:34:50.158603+00:00`  
**Total Verified Training Matches**: `127,984`  
**Artifact Location**: `core/re-evaluated models/fifa_goals_ou_model_v2.0.0.joblib`  

## 1. Feature Parity & Leakage Elimination Audit

- **Feature Parity Test**: `PASSED (100% Schema Parity)`
- **Closing Odds Removed**: `YES (0 closing odds fields in training)`
- **Odds Drift Eliminated**: `YES (odds_drift_abs & odds_drift_pct completely removed)`
- **Synthetic Padding Removed**: `YES (No 0.50, 0.45, 5.0, 0.0 dummy constants)`
- **Pre-match Implied Probability**: `Derived strictly from pre-match odds (1.0 / odds.over_under.over)`
- **Score Isolation**: `home.goals and away.goals used strictly for post-match settlement target y`

### Whitelisted Feature Names (19 Total):
1. `is_reliable_5`
2. `is_reliable_10`
3. `home_scored_roll_mean_5`
4. `home_scored_roll_mean_10`
5. `home_conceded_roll_mean_5`
6. `home_conceded_roll_mean_10`
7. `away_scored_roll_mean_5`
8. `away_scored_roll_mean_10`
9. `away_conceded_roll_mean_5`
10. `away_conceded_roll_mean_10`
11. `expected_total_goals`
12. `h2h_matches_count`
13. `h2h_mean_combined_goals`
14. `ou_line_value`
15. `ou_line_diff`
16. `ou_line_hit_rate_roll`
17. `ht_ft_goal_ratio_league`
18. `odds_implied_prob`
19. `implied_vs_hist_divergence`

## 2. Walk-Forward Chronological Evaluation Results

| Fold | Train Period | Cal Period | Out-of-Sample Period | Samples | Settled Tips | Win Rate (%) | ROI (%) | Net Units | Brier Skill Score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `2026-04-09 to 2026-04-28` | `2026-04-28 to 2026-05-01` | `2026-05-01 to 2026-05-22` | 21,330 | 894 | 41.83% | -5.51% | -49.27 | -0.0313 |
| 2 | `2026-04-09 to 2026-05-16` | `2026-05-16 to 2026-05-22` | `2026-05-22 to 2026-06-12` | 21,330 | 133 | 49.62% | +13.98% | +18.60 | +0.0357 |
| 3 | `2026-04-09 to 2026-06-03` | `2026-06-03 to 2026-06-12` | `2026-06-12 to 2026-07-02` | 21,330 | 1,247 | 41.06% | -0.74% | -9.28 | +0.0010 |
| 4 | `2026-04-09 to 2026-06-20` | `2026-06-20 to 2026-07-02` | `2026-07-02 to 2026-07-24` | 21,330 | 919 | 43.85% | +0.17% | +1.60 | -0.0083 |
| 5 | `2026-04-09 to 2026-07-08` | `2026-07-08 to 2026-07-24` | `2026-07-24 to 2026-10-05` | 21,330 | 374 | 38.77% | +1.32% | +4.93 | +0.0225 |

## 3. Comprehensive Performance Metrics (All Out-of-Sample Folds)

- **Total Tips Evaluated**: `3,567`
- **Wins / Half-Wins / Voids / Half-Losses / Losses**: `1500 / 485 / 25 / 43 / 1514`
- **Win Rate**: `49.20%`
- **Total Net Units (1.0 flat stake)**: `-33.43 Units`
- **Overall ROI**: `-0.94%`
- **Maximum Drawdown**: `70.55 Units`
- **Longest Losing Streak**: `8 tips`
- **Average Odds**: `1.86`
- **Average Model Probability**: `59.22%`
- **Average Calculated Edge**: `+5.52%`
- **Brier Score**: `0.2486`
- **Brier Skill Score (vs. Bookmaker Implied)**: `-0.0061`

### Edge Monotonicity Analysis:

| Edge Tier | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 3-5% | 2,076 | -20.69 | -1.00% |
| 5-8% | 897 | -39.87 | -4.44% |
| 8-12% | 541 | +13.07 | +2.42% |
| 12%+ | 53 | +14.04 | +26.50% |

### Performance by Odds Range:

| Odds Range | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 1.60-1.80 | 574 | -12.33 | -2.15% |
| 1.80-2.00 | 2,992 | -22.16 | -0.74% |
| 2.00-2.20 | 1 | +1.05 | +105.00% |
| 2.20+ | 0 | +0.00 | +0.00% |
