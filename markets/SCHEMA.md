# FIFA & eBasketball Market Features Schema Documentation

This document defines the schema, column names, data types, technical definitions, and imputation strategies for feature sets generated across all prediction markets:
- `markets/fifa_goals_ou`
- `markets/fifa_asian_handicap`
- `markets/fifa_money_line`
- `markets/ebasket_ou`
- `markets/ebasket_money_line`

---

## 1. Rolling Feature Imputation & Reliability Strategy

> [!IMPORTANT]
> **Cold-Start Imputation Strategy**:
> When a player or team has fewer than 3 prior historical matches in the dataset (cold-start / early-season matches), sample rolling window statistics cannot be calculated from past data.
> - **FIFA Goals Fallback**: Imputes **`2.28` goals per match per team** (global historical population average across 93,663 FIFA matches).
> - **FIFA Win/Loss/Draw Fallback**: Imputes **`0.40` (40.0%) Win Rate**, **`0.20` (20.0%) Draw Rate**, and **`0.40` (40.0%) Loss Rate**.
> - **eBasketball Points Fallback**: Imputes **`55.6` points per match per team** (global historical population average: 111.27 total points / 2 teams across 19,246 eBasketball matches).
> - **eBasketball Win Rate Fallback**: Imputes **`0.50` (50.0%) Win Rate** (eBasketball games cannot end in a draw).
>
> **Mandatory Model Training Requirement**:
> All downstream model training code (e.g. LightGBM, XGBoost, sample weighting algorithms) **MUST** consume the `is_reliable_5` and `is_reliable_10` boolean flag columns.
> - `is_reliable_5 / 10 = True`: Indicates $\ge 3$ prior matches exist, so rolling feature values represent true historical player/team form.
> - `is_reliable_5 / 10 = False`: Indicates $< 3$ prior matches exist and feature values contain imputed fallback priors.

---

## 2. FIFA Goals Over/Under Schema (`fifa_goals_ou`)

Primary feature builder: `build_fifa_goals_ou_features()` in `markets/fifa_goals_ou/features.py`.

| Column Name | Data Type | Description |
|---|---|---|
| `match_id` | `String` | Natural unique match identifier (Primary Key). |
| `is_reliable_5` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 5-match rolling window. |
| `is_reliable_10` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 10-match rolling window. |
| `home_scored_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals scored by home player (fallback: 2.28). |
| `home_scored_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals scored by home player (fallback: 2.28). |
| `home_conceded_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals conceded by home player (fallback: 2.28). |
| `home_conceded_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals conceded by home player (fallback: 2.28). |
| `away_scored_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals scored by away player (fallback: 2.28). |
| `away_scored_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals scored by away player (fallback: 2.28). |
| `away_conceded_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals conceded by away player (fallback: 2.28). |
| `away_conceded_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals conceded by away player (fallback: 2.28). |
| `expected_total_goals` | `Float64` | Sum of home and away 10-match expected goals (`home_scored_10 + away_scored_10`). |
| `h2h_matches_count` | `Int64` | Total count of prior head-to-head encounters between players. |
| `h2h_mean_combined_goals` | `Float64` | Average combined goals scored in prior head-to-head encounters. |
| `ou_line_value` | `Float64` | Over/Under target line offered (e.g. 2.5, 3.5, 4.5). |
| `ou_line_diff` | `Float64` | Expected total goals minus target line (`expected_total_goals - ou_line_value`). |
| `ou_line_hit_rate_roll` | `Float64` | Rolling historical over-hit rate for the target line value. |
| `ht_ft_goal_ratio_league` | `Float64` | League-segmented ratio of first-half goals to full-time goals. |
| `odds_implied_prob` | `Float64` | Implied probability derived from closing odds ($1 / \text{odds\_close}$). |
| `implied_vs_hist_divergence` | `Float64` | Implied probability minus historical hit rate ($P_{implied} - \text{ou\_line\_hit\_rate\_roll}$). |
| `odds_drift_abs` | `Float64` | Absolute closing odds minus opening odds drift ($\text{odds\_close} - \text{odds\_open}$). |
| `odds_drift_pct` | `Float64` | Percentage closing odds minus opening odds drift ($\frac{\text{close} - \text{open}}{\text{open}} \times 100$). |

---

## 3. FIFA Asian Handicap Schema (`fifa_asian_handicap`)

Primary feature builder: `build_fifa_asian_handicap_features()` in `markets/fifa_asian_handicap/features.py`.

| Column Name | Data Type | Description |
|---|---|---|
| `match_id` | `String` | Natural unique match identifier (Primary Key). |
| `is_reliable_5` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 5-match rolling window. |
| `is_reliable_10` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 10-match rolling window. |
| `home_scored_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals scored by home player (fallback: 2.28). |
| `home_scored_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals scored by home player (fallback: 2.28). |
| `home_conceded_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals conceded by home player (fallback: 2.28). |
| `home_conceded_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals conceded by home player (fallback: 2.28). |
| `away_scored_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals scored by away player (fallback: 2.28). |
| `away_scored_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals scored by away player (fallback: 2.28). |
| `away_conceded_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean goals conceded by away player (fallback: 2.28). |
| `away_conceded_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean goals conceded by away player (fallback: 2.28). |
| `expected_home_margin` | `Float64` | Rolling expected home goal difference (`home_scored_10 - away_scored_10`). |
| `handicap_line_value` | `Float64` | Asian handicap line offered (e.g. -0.5, -1.0, +0.5). |
| `normalized_adjusted_margin` | `Float64` | Handicap-adjusted expected margin (`expected_home_margin + handicap_line_value`). |
| `h2h_matches_count` | `Int64` | Total count of prior head-to-head encounters between players. |
| `h2h_mean_combined_goals` | `Float64` | Average combined goals scored in prior head-to-head encounters. |
| `ht_ft_goal_ratio_league` | `Float64` | League-segmented ratio of first-half goals to full-time goals. |
| `odds_implied_prob` | `Float64` | Implied probability derived from closing odds ($1 / \text{odds\_close}$). |
| `implied_vs_hist_divergence` | `Float64` | Implied probability minus historical hit rate. |
| `odds_drift_abs` | `Float64` | Absolute closing odds minus opening odds drift. |
| `odds_drift_pct` | `Float64` | Percentage closing odds minus opening odds drift. |

---

## 4. FIFA 1X2 Money Line Schema (`fifa_money_line`)

Primary feature builder: `build_fifa_money_line_features()` in `markets/fifa_money_line/features.py`.

| Column Name | Data Type | Description |
|---|---|---|
| `match_id` | `String` | Natural unique match identifier (Primary Key). |
| `is_reliable_5` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 5-match rolling window. |
| `is_reliable_10` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 10-match rolling window. |
| `home_win_rate_roll_5` | `Float64` | Past 5-match rolling win rate for home player (fallback: 0.40). |
| `home_win_rate_roll_10` | `Float64` | Past 10-match rolling win rate for home player (fallback: 0.40). |
| `home_draw_rate_roll_5` | `Float64` | Past 5-match rolling draw rate for home player (fallback: 0.20). |
| `home_draw_rate_roll_10` | `Float64` | Past 10-match rolling draw rate for home player (fallback: 0.20). |
| `home_loss_rate_roll_5` | `Float64` | Past 5-match rolling loss rate for home player (fallback: 0.40). |
| `home_loss_rate_roll_10` | `Float64` | Past 10-match rolling loss rate for home player (fallback: 0.40). |
| `away_win_rate_roll_5` | `Float64` | Past 5-match rolling win rate for away player (fallback: 0.40). |
| `away_win_rate_roll_10` | `Float64` | Past 10-match rolling win rate for away player (fallback: 0.40). |
| `away_draw_rate_roll_5` | `Float64` | Past 5-match rolling draw rate for away player (fallback: 0.20). |
| `away_draw_rate_roll_10` | `Float64` | Past 10-match rolling draw rate for away player (fallback: 0.20). |
| `away_loss_rate_roll_5` | `Float64` | Past 5-match rolling loss rate for away player (fallback: 0.40). |
| `away_loss_rate_roll_10` | `Float64` | Past 10-match rolling loss rate for away player (fallback: 0.40). |
| `home_win_rate_home_games` | `Float64` | Rolling home win rate specifically in home matches. |
| `away_win_rate_away_games` | `Float64` | Rolling away win rate specifically in away matches. |
| `home_form_streak` | `Int64` | Current signed win/loss streak for home player (+N for wins, -N for losses, 0 for draw/start). |
| `away_form_streak` | `Int64` | Current signed win/loss streak for away player (+N for wins, -N for losses, 0 for draw/start). |
| `draw_prob_roll_10` | `Float64` | Explicit draw probability feature based on 10-match rolling draw rate (FIFA-specific, not shared with eBasketball). |
| `h2h_matches_count` | `Int64` | Total count of prior head-to-head encounters between players. |
| `h2h_win_rate_a` | `Float64` | Home player's win rate in prior head-to-head encounters. |
| `odds_implied_prob` | `Float64` | Implied win probability derived from closing odds ($1 / \text{odds\_close}$). |
| `implied_vs_hist_divergence` | `Float64` | Implied probability minus historical win rate ($P_{implied} - \text{home\_win\_rate\_roll\_10}$). |
| `odds_drift_abs` | `Float64` | Absolute closing odds minus opening odds drift ($\text{odds\_close} - \text{odds\_open}$). |
| `odds_drift_pct` | `Float64` | Percentage closing odds minus opening odds drift ($\frac{\text{close} - \text{open}}{\text{open}} \times 100$). |

---

## 5. eBasketball Over/Under Schema (`ebasket_ou`)

Primary feature builder: `build_ebasket_ou_features()` in `markets/ebasket_ou/features.py`.

| Column Name | Data Type | Description |
|---|---|---|
| `match_id` | `String` | Natural unique match identifier (Primary Key). |
| `is_reliable_5` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 5-match rolling window. |
| `is_reliable_10` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 10-match rolling window. |
| `home_scored_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean points scored by home player (fallback: 55.6). |
| `home_scored_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean points scored by home player (fallback: 55.6). |
| `home_conceded_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean points conceded by home player (fallback: 55.6). |
| `home_conceded_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean points conceded by home player (fallback: 55.6). |
| `away_scored_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean points scored by away player (fallback: 55.6). |
| `away_scored_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean points scored by away player (fallback: 55.6). |
| `away_conceded_roll_mean_5` | `Float64` | Past 5-match past-only rolling mean points conceded by away player (fallback: 55.6). |
| `away_conceded_roll_mean_10` | `Float64` | Past 10-match past-only rolling mean points conceded by away player (fallback: 55.6). |
| `expected_total_points` | `Float64` | Sum of home and away 10-match expected points (`home_scored_10 + away_scored_10`). |
| `ht_ft_points_ratio_roll` | `Float64` | Rolling ratio of first-half points to full-time total points (pace proxy). |
| `ou_line_value` | `Float64` | Over/Under target line offered (e.g. 110.5, 112.5). |
| `ou_line_diff` | `Float64` | Expected total points minus target line (`expected_total_points - ou_line_value`). |
| `ou_line_over_hit_rate_roll` | `Float64` | Rolling historical over-hit rate for target line value. |
| `hour_of_day_utc` | `Int64` | Hour of match start in UTC (statistically validated via ANOVA). |
| `odds_drift_abs` | `Float64` | Absolute closing odds minus opening odds drift. |
| `odds_drift_pct` | `Float64` | Percentage closing odds minus opening odds drift. |

---

## 6. eBasketball Money Line Schema (`ebasket_money_line`)

Primary feature builder: `build_ebasket_money_line_features()` in `markets/ebasket_money_line/features.py`.

| Column Name | Data Type | Description |
|---|---|---|
| `match_id` | `String` | Natural unique match identifier (Primary Key). |
| `is_reliable_5` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 5-match rolling window. |
| `is_reliable_10` | `Boolean` | `True` if player has $\ge 3$ prior historical matches for 10-match rolling window. |
| `home_win_rate_roll_5` | `Float64` | Past 5-match rolling win rate for home player (fallback: 0.50). |
| `home_win_rate_roll_10` | `Float64` | Past 10-match rolling win rate for home player (fallback: 0.50). |
| `away_win_rate_roll_5` | `Float64` | Past 5-match rolling win rate for away player (fallback: 0.50). |
| `away_win_rate_roll_10` | `Float64` | Past 10-match rolling win rate for away player (fallback: 0.50). |
| `margin_of_victory_roll_10` | `Float64` | Rolling average point differential (`home_scored_10 - away_scored_10`). |
| `hour_of_day_utc` | `Int64` | Hour of match start in UTC (statistically validated via ANOVA). |
| `h2h_matches_count` | `Int64` | Total count of prior head-to-head encounters between players. |
| `h2h_win_rate_a` | `Float64` | Home player's win rate in prior head-to-head encounters. |
| `h2h_mean_point_diff` | `Float64` | Average point margin in prior head-to-head encounters. |
| `odds_implied_prob` | `Float64` | Implied win probability derived from closing odds ($1 / \text{odds\_close}$). |
| `implied_vs_hist_divergence` | `Float64` | Implied probability minus historical win rate ($P_{implied} - \text{home\_win\_rate\_roll\_10}$). |
| `odds_drift_abs` | `Float64` | Absolute closing odds minus opening odds drift. |
| `odds_drift_pct` | `Float64` | Percentage closing odds minus opening odds drift. |
