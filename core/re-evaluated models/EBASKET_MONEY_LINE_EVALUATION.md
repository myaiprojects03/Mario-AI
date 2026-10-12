# Re-evaluated Model Audit Report: Market 4 (eBasketball Money Line)

**Model Version**: `v2.0.0-reevaluated`  
**Feature Version**: `v2.0.0-clean-prematch`  
**Trained At**: `2026-10-07T11:39:53.947908+00:00`  
**Total Verified Training Matches**: `26,023`  
**Artifact Location**: `core/re-evaluated models/ebasket_money_line_model_v2.0.0.joblib`  

## 1. Feature Parity & Leakage Elimination Audit

- **Feature Parity Test**: `PASSED (100% Schema Parity)`
- **Closing Odds Removed**: `YES (0 closing odds fields in training)`
- **Odds Drift Eliminated**: `YES (odds_drift_abs & odds_drift_pct completely removed)`
- **Synthetic Padding Removed**: `YES (No 0.50, 0.40, 0.20, 55.6 dummy constants)`
- **Pre-match Implied Probability**: `Derived strictly from pre-match odds (1.0 / odds.money_line)`
- **Score Isolation**: `home.goals and away.goals used strictly for post-match settlement target y`

### Whitelisted Feature Names (30 Total):
1. `is_reliable_5`
2. `is_reliable_10`
3. `home_win_rate_roll_5`
4. `home_win_rate_roll_10`
5. `away_win_rate_roll_5`
6. `away_win_rate_roll_10`
7. `win_rate_diff_10`
8. `home_points_scored_roll_10`
9. `home_points_conceded_roll_10`
10. `away_points_scored_roll_10`
11. `away_points_conceded_roll_10`
12. `home_net_point_diff_10`
13. `away_net_point_diff_10`
14. `net_point_diff_delta_10`
15. `home_form_streak`
16. `away_form_streak`
17. `h2h_matches_count`
18. `h2h_win_rate_a`
19. `h2h_mean_point_diff`
20. `odds_implied_prob_home`
21. `odds_implied_prob_away`
22. `market_vig`
23. `implied_prob_ratio`
24. `implied_vs_hist_divergence`
25. `home_bayesian_rating_mean`
26. `home_bayesian_rating_std`
27. `away_bayesian_rating_mean`
28. `away_bayesian_rating_std`
29. `bayesian_rating_diff`
30. `hour_of_day_utc`

## 2. Walk-Forward Chronological Evaluation Results

| Fold | Train Period | Cal Period | Out-of-Sample Period | Samples | Settled Tips | Win Rate (%) | ROI (%) | Net Units | Brier Skill Score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `2026-04-09 to 2026-04-28` | `2026-04-28 to 2026-05-01` | `2026-05-01 to 2026-05-22` | 4,337 | 1,951 | 40.24% | -12.54% | -244.61 | -0.1045 |
| 2 | `2026-04-09 to 2026-05-16` | `2026-05-16 to 2026-05-22` | `2026-05-22 to 2026-06-12` | 4,337 | 988 | 50.30% | -0.21% | -2.10 | -0.0295 |
| 3 | `2026-04-09 to 2026-06-03` | `2026-06-03 to 2026-06-12` | `2026-06-12 to 2026-07-05` | 4,337 | 1,320 | 47.35% | -9.10% | -120.12 | -0.0480 |
| 4 | `2026-04-09 to 2026-06-21` | `2026-06-21 to 2026-07-05` | `2026-07-05 to 2026-07-26` | 4,337 | 601 | 47.25% | -6.71% | -40.31 | -0.0284 |
| 5 | `2026-04-09 to 2026-07-10` | `2026-07-10 to 2026-07-26` | `2026-07-26 to 2026-10-05` | 4,337 | 774 | 46.25% | -6.83% | -52.83 | -0.0241 |

## 3. Comprehensive Performance Metrics (All Out-of-Sample Folds)

- **Total Tips Evaluated**: `5,634`
- **Wins / Voids (Ties) / Losses**: `2549 / 4 / 3081`
- **Win Rate (Excluding Voids)**: `45.28%`
- **Total Net Units (1.0 flat stake)**: `-459.97 Units`
- **Overall ROI**: `-8.16%`
- **Maximum Drawdown**: `466.17 Units`
- **Longest Losing Streak**: `12 tips`
- **Average Odds**: `2.15`
- **Average Model Probability**: `56.54%`
- **Average Calculated Edge**: `+7.63%`
- **Brier Score**: `0.2502`
- **Brier Skill Score (vs. Bookmaker Implied)**: `-0.0584`

### Edge Monotonicity Analysis:

| Edge Tier | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 3-5% | 2,311 | -223.68 | -9.68% |
| 5-8% | 1,388 | -108.21 | -7.80% |
| 8-12% | 1,075 | -22.24 | -2.07% |
| 12%+ | 860 | -105.84 | -12.31% |

### Performance by Odds Range:

| Odds Range | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 1.40-1.60 | 625 | -18.79 | -3.01% |
| 1.60-1.80 | 1,067 | -68.17 | -6.39% |
| 1.80-2.00 | 971 | -77.69 | -8.00% |
| 2.00-2.30 | 978 | -26.80 | -2.74% |
| 2.30+ | 1,993 | -268.52 | -13.47% |
