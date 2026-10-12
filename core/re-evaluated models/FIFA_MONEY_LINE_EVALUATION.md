# Re-evaluated Model Audit Report: Market 3 (FIFA Money Line / DNB)

**Model Version**: `v2.0.0-reevaluated`  
**Feature Version**: `v2.0.0-clean-prematch`  
**Trained At**: `2026-10-07T11:31:43.837668+00:00`  
**Total Verified Training Matches**: `128,117`  
**Artifact Location**: `core/re-evaluated models/fifa_money_line_model_v2.0.0.joblib`  

## 1. Feature Parity & Leakage Elimination Audit

- **Feature Parity Test**: `PASSED (100% Schema Parity)`
- **Closing Odds Removed**: `YES (0 closing odds fields in training)`
- **Odds Drift Eliminated**: `YES (odds_drift_abs & odds_drift_pct completely removed)`
- **Synthetic Padding Removed**: `YES (No 0.40, 0.20, 5.0, 0.0 dummy constants)`
- **Pre-match Implied Probability**: `Derived strictly from pre-match odds (1.0 / odds.money_line)`
- **Score Isolation**: `home.goals and away.goals used strictly for post-match settlement target y`

### Whitelisted Feature Names (32 Total):
1. `is_reliable_5`
2. `is_reliable_10`
3. `home_win_rate_roll_5`
4. `home_win_rate_roll_10`
5. `home_draw_rate_roll_5`
6. `home_draw_rate_roll_10`
7. `home_loss_rate_roll_5`
8. `home_loss_rate_roll_10`
9. `away_win_rate_roll_5`
10. `away_win_rate_roll_10`
11. `away_draw_rate_roll_5`
12. `away_draw_rate_roll_10`
13. `away_loss_rate_roll_5`
14. `away_loss_rate_roll_10`
15. `home_net_gd_10`
16. `away_net_gd_10`
17. `net_gd_diff_10`
18. `home_win_rate_home_games`
19. `away_win_rate_away_games`
20. `home_form_streak`
21. `away_form_streak`
22. `draw_prob_roll_10`
23. `h2h_matches_count`
24. `h2h_win_rate_a`
25. `odds_implied_prob_home`
26. `odds_implied_prob_away`
27. `implied_vs_hist_divergence`
28. `home_bayesian_rating_mean`
29. `home_bayesian_rating_std`
30. `away_bayesian_rating_mean`
31. `away_bayesian_rating_std`
32. `bayesian_rating_diff`

## 2. Walk-Forward Chronological Evaluation Results

| Fold | Train Period | Cal Period | Out-of-Sample Period | Samples | Settled Tips | Win Rate (%) | ROI (%) | Net Units | Brier Skill Score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `2026-04-09 to 2026-04-28` | `2026-04-28 to 2026-05-01` | `2026-05-01 to 2026-05-22` | 21,352 | 1,123 | 37.85% | -0.66% | -7.42 | -0.0583 |
| 2 | `2026-04-09 to 2026-05-16` | `2026-05-16 to 2026-05-22` | `2026-05-22 to 2026-06-12` | 21,352 | 873 | 33.79% | -0.17% | -1.45 | -0.0525 |
| 3 | `2026-04-09 to 2026-06-03` | `2026-06-03 to 2026-06-12` | `2026-06-12 to 2026-07-02` | 21,352 | 620 | 38.87% | -3.52% | -21.80 | -0.0585 |
| 4 | `2026-04-09 to 2026-06-20` | `2026-06-20 to 2026-07-02` | `2026-07-02 to 2026-07-24` | 21,352 | 510 | 37.06% | +9.00% | +45.91 | -0.0479 |
| 5 | `2026-04-09 to 2026-07-08` | `2026-07-08 to 2026-07-24` | `2026-07-24 to 2026-10-05` | 21,352 | 395 | 41.77% | +6.69% | +26.44 | -0.0344 |

## 3. Comprehensive Performance Metrics (All Out-of-Sample Folds)

- **Total Tips Evaluated**: `3,521`
- **Wins / Voids (Draws) / Losses**: `1315 / 811 / 1395`
- **Win Rate (Excluding Voids)**: `48.52%`
- **Total Net Units (1.0 flat stake)**: `+41.68 Units`
- **Overall ROI**: `+1.18%`
- **Maximum Drawdown**: `54.21 Units`
- **Longest Losing Streak**: `14 tips`
- **Average Odds**: `2.13`
- **Average Model Probability**: `52.83%`
- **Average Calculated Edge**: `+4.89%`
- **Brier Score**: `0.2566`
- **Brier Skill Score (vs. Bookmaker Implied)**: `-0.0528`

### Edge Monotonicity Analysis:

| Edge Tier | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 3-5% | 2,312 | +24.31 | +1.05% |
| 5-8% | 957 | +21.80 | +2.28% |
| 8-12% | 214 | -13.34 | -6.23% |
| 12%+ | 38 | +8.91 | +23.45% |

### Performance by Odds Range:

| Odds Range | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 1.60-1.80 | 648 | -24.82 | -3.83% |
| 1.80-2.00 | 502 | -37.92 | -7.55% |
| 2.00-2.20 | 814 | +28.56 | +3.51% |
| 2.20+ | 1,556 | +76.86 | +4.94% |
