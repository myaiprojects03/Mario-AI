# Re-evaluated Model Audit Report: Market 2 (FIFA Asian Handicap)

**Model Version**: `v2.0.0-reevaluated`  
**Feature Version**: `v2.0.0-clean-prematch`  
**Trained At**: `2026-10-07T11:09:02.298652+00:00`  
**Total Verified Training Matches**: `128,019`  
**Artifact Location**: `core/re-evaluated models/fifa_asian_handicap_model_v2.0.0.joblib`  

## 1. Feature Parity & Leakage Elimination Audit

- **Feature Parity Test**: `PASSED (100% Schema Parity)`
- **Closing Odds Removed**: `YES (0 closing odds fields in training)`
- **Odds Drift Eliminated**: `YES (odds_drift_abs & odds_drift_pct completely removed)`
- **Synthetic Padding Removed**: `YES (No 0.50, 0.45, 5.0, 0.0 dummy constants)`
- **Pre-match Implied Probability**: `Derived strictly from pre-match odds (1.0 / odds.asian_handicap.home)`
- **Score Isolation**: `home.goals and away.goals used strictly for post-match settlement target y`

### Whitelisted Feature Names (18 Total):
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
11. `home_net_gd_10`
12. `away_net_gd_10`
13. `net_gd_diff_10`
14. `net_gd_margin_vs_line`
15. `handicap_line_value`
16. `ml_implied_prob_home`
17. `ml_implied_prob_away`
18. `ml_implied_diff`
19. `ah_odds_implied_prob`
20. `cross_market_divergence`
21. `h2h_matches_count`
22. `h2h_mean_combined_goals`
23. `ht_ft_goal_ratio_league`

## 2. Walk-Forward Chronological Evaluation Results

| Fold | Train Period | Cal Period | Out-of-Sample Period | Samples | Settled Tips | Win Rate (%) | ROI (%) | Net Units | Brier Skill Score |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `2026-04-09 to 2026-04-28` | `2026-04-28 to 2026-05-01` | `2026-05-01 to 2026-05-22` | 21,336 | 8,404 | 38.98% | -4.19% | -352.21 | -0.1034 |
| 2 | `2026-04-09 to 2026-05-16` | `2026-05-16 to 2026-05-22` | `2026-05-22 to 2026-06-12` | 21,336 | 7,773 | 38.42% | -3.92% | -304.44 | -0.0628 |
| 3 | `2026-04-09 to 2026-06-03` | `2026-06-03 to 2026-06-12` | `2026-06-12 to 2026-07-02` | 21,336 | 7,055 | 36.75% | -5.58% | -393.60 | -0.0811 |
| 4 | `2026-04-09 to 2026-06-20` | `2026-06-20 to 2026-07-02` | `2026-07-02 to 2026-07-24` | 21,336 | 8,270 | 37.10% | -4.62% | -381.71 | -0.0792 |
| 5 | `2026-04-09 to 2026-07-08` | `2026-07-08 to 2026-07-24` | `2026-07-24 to 2026-10-05` | 21,336 | 8,886 | 38.14% | -5.02% | -446.26 | -0.0752 |

## 3. Comprehensive Performance Metrics (All Out-of-Sample Folds)

- **Total Tips Evaluated**: `40,388`
- **Wins / Half-Wins / Voids / Half-Losses / Losses**: `15312 / 3359 / 5457 / 104 / 16156`
- **Win Rate**: `48.64%`
- **Total Net Units (1.0 flat stake)**: `-1,878.21 Units`
- **Overall ROI**: `-4.65%`
- **Maximum Drawdown**: `1880.77 Units`
- **Longest Losing Streak**: `14 tips`
- **Average Odds**: `1.85`
- **Average Model Probability**: `61.49%`
- **Average Calculated Edge**: `+7.26%`
- **Brier Score**: `0.2750`
- **Brier Skill Score (vs. Bookmaker Implied)**: `-0.0805`

### Edge Monotonicity Analysis:

| Edge Tier | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 3-5% | 10,959 | -480.47 | -4.38% |
| 5-8% | 14,198 | -675.97 | -4.76% |
| 8-12% | 13,413 | -604.95 | -4.51% |
| 12%+ | 1,818 | -116.83 | -6.43% |

### Performance by Odds Range:

| Odds Range | Tips | Net Units | ROI (%) |
|---|---|---|---|
| 1.60-1.80 | 10,160 | -390.40 | -3.84% |
| 1.80-2.00 | 30,214 | -1,484.89 | -4.91% |
| 2.00-2.20 | 8 | -0.32 | -4.06% |
| 2.20+ | 6 | -2.60 | -43.33% |
