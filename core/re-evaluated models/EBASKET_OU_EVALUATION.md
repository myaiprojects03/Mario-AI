# Re-evaluated Model Audit Report: Market 5 (eBasketball Points Over/Under)

**Model Version**: `v2.0.0-reevaluated`  
**Feature Version**: `v2.0.0-clean-prematch`  
**Trained At**: `2026-10-07T12:00:08.700270+00:00`  
**Total Verified Training Matches**: `26,216`  
**Artifact Location**: `core/re-evaluated models/ebasket_ou_model_v2.0.0.joblib`  

## 1. Feature Parity & Leakage Elimination Audit

- **Feature Parity Test**: `PASSED (100% Schema Parity)`
- **Closing Odds Removed**: `YES (0 closing odds fields in training)`
- **Odds Drift Eliminated**: `YES (odds_drift_abs & odds_drift_pct completely removed)`
- **Synthetic Padding Removed**: `YES (No 55.6, 111.5, 0.50, 0.40, 0.20 dummy constants)`
- **Pre-match Implied Probability**: `Derived strictly from pre-match odds (1.0 / odds.over_under)`
- **Score Isolation**: `home.goals and away.goals used strictly for post-match settlement target y`

### Whitelisted Feature Names (31 Total):
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
11. `expected_total_points_5`
12. `expected_total_points_10`
13. `expected_total_conceded_10`
14. `blended_projected_points_10`
15. `ou_line_value`
16. `ou_line_diff_10`
17. `home_total_pts_std_10`
18. `away_total_pts_std_10`
19. `odds_implied_prob_over`
20. `odds_implied_prob_under`
21. `market_vig`
22. `implied_prob_ratio_over`
23. `home_bayesian_rating_mean`
24. `home_bayesian_rating_std`
25. `away_bayesian_rating_mean`
26. `away_bayesian_rating_std`
27. `bayesian_total_points`
28. `bayesian_line_diff`
29. `h2h_matches_count`
30. `h2h_mean_total_score`
31. `hour_of_day_utc`

## 2. Walk-Forward Chronological Evaluation Results

| Fold | Train Period | Cal Period | Out-of-Sample Period | Samples | Settled Tips | Win Rate (%) | ROI (%) | Net Units | Brier Skill Score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `2026-04-09 to 2026-04-28` | `2026-04-28 to 2026-05-01` | `2026-05-01 to 2026-05-22` | 4,369 | 559 | 52.95% | -3.09% | -17.28 | -0.1650 |
| 2 | `2026-04-09 to 2026-05-16` | `2026-05-16 to 2026-05-22` | `2026-05-22 to 2026-06-13` | 4,369 | 830 | 51.93% | -4.97% | -41.23 | -0.0804 |
| 3 | `2026-04-09 to 2026-06-03` | `2026-06-03 to 2026-06-13` | `2026-06-13 to 2026-07-05` | 4,369 | 1,073 | 53.96% | -1.24% | -13.34 | -0.0364 |
| 4 | `2026-04-09 to 2026-06-21` | `2026-06-21 to 2026-07-05` | `2026-07-05 to 2026-07-26` | 4,369 | 149 | 49.66% | -9.11% | -13.58 | -0.1246 |
| 5 | `2026-04-09 to 2026-07-10` | `2026-07-10 to 2026-07-26` | `2026-07-26 to 2026-10-05` | 4,369 | 789 | 57.54% | +5.30% | +41.78 | -0.0294 |

## 3. Comprehensive Performance Metrics (All Out-of-Sample Folds)

- **Total Tips Evaluated**: `3,400`
- **Wins / Voids (Pushes) / Losses**: `1834 / 0 / 1566`
- **Win Rate (Excluding Voids)**: `53.94%`
- **Total Net Units (1.0 flat stake)**: `-43.65 Units`
- **Overall ROI**: `-1.28%`
- **Maximum Drawdown**: `99.11 Units`
- **Longest Losing Streak**: `13 tips`
- **Average Odds**: `1.83`
- **Average Model Probability**: `65.11%`
- **Average Calculated Edge**: `+10.47%`
- **Brier Score**: `0.2661`
- **Brier Skill Score (vs. Bookmaker Implied)**: `-0.0707`

### Edge Monotonicity Analysis:

| Edge Tier | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 3-5% | 331 | -3.42 | -1.03% |
| 5-8% | 1,450 | -30.04 | -2.07% |
| 8-12% | 538 | +8.88 | +1.65% |
| 12%+ | 1,081 | -19.07 | -1.76% |

### Performance by Odds Range:

| Odds Range | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 1.60-1.75 | 11 | -2.39 | -21.73% |
| 1.75-1.90 | 3,379 | -41.06 | -1.22% |
| 1.90-2.05 | 10 | -0.20 | -2.00% |
