# eBasketball Feature Engineering Notes - Time-of-Day Study

## UTC Hour-of-Day ANOVA Statistical Study
- **Dataset Size**: 38186 historical eBasketball matches from PostgreSQL (`core.matches`/`core.results`).
- **Metric Evaluated**: Total points scored (`final_home_score + final_away_score`).
- **Factor**: UTC Hour of Match Start (`startedAt.dt.hour()`, hours 0 to 23).
- **ANOVA F-statistic**: 60.5179
- **ANOVA p-value**: 5.5969e-275
- **Statistical Significance (p < 0.05)**: YES

## Feature Inclusion Decision
**INCLUDED**: The ANOVA test yielded a p-value of 5.5969e-275 (< 0.05), indicating a statistically meaningful variation in scoring performance across UTC time slots. `hour_of_day_utc` is included in the eBasketball feature set.
