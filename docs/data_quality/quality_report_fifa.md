# Data Quality & Distribution Sanity Report - FIFA
- **Total Input Rows**: 93663
- **Generated At (UTC)**: 2026-08-11T12:58:05.130650+00:00

## 1. Distribution Sanity Check
- **Metric Analyzed**: Total Goals
- **Actual Mean / Std**: 4.59 / 2.65
- **Spec Benchmark Mean / Std**: 4.56 / 2.65
- **Status**: ✅ PASSED SANITY CHECK

## 2. Per-Market Exclusion Counts (Odds Coverage Filter)
| Market Type | Retained Rows | Excluded Rows | Exclusion Rate (%) |
|---|---|---|---|
| fifa_goals_ou | 93633 | 30 | 0.03% |
| fifa_asian_handicap | 93639 | 24 | 0.03% |
| fifa_money_line | 93652 | 11 | 0.01% |

## 3. Missing Odds Coverage by League
| League | Total Matches | Missing Odds Rows | Missing Rate (%) |
|---|---|---|---|
| Esoccer Battle - 8 mins play | 28180 | 86 | 0.31% |
| Esoccer H2H GG League - 8 mins play | 25191 | 99 | 0.39% |
| Esoccer GT Leagues - 12 mins play | 16490 | 81 | 0.49% |
| Esoccer Battle Volta - 6 mins play | 23802 | 72 | 0.30% |

## 4. Column Null Rates
| Column Name | Null Count | Null Rate (%) |
|---|---|---|
| `_id` | 0 | 0.00% |
| `away.goals` | 448 | 0.48% |
| `away.goalsHT` | 481 | 0.51% |
| `away.name` | 0 | 0.00% |
| `away.nameLower` | 0 | 0.00% |
| `away.teamName` | 0 | 0.00% |
| `away.teamNameLower` | 0 | 0.00% |
| `closingOdds.asian_handicap.away` | 109 | 0.12% |
| `closingOdds.asian_handicap.home` | 109 | 0.12% |
| `closingOdds.asian_handicap.line` | 109 | 0.12% |
| `closingOdds.asian_handicap_ht.away` | 1285 | 1.37% |
| `closingOdds.asian_handicap_ht.home` | 1285 | 1.37% |
| `closingOdds.asian_handicap_ht.line` | 1285 | 1.37% |
| `closingOdds.draw_no_bet.away` | 98 | 0.10% |
| `closingOdds.draw_no_bet.home` | 98 | 0.10% |
| `closingOdds.money_line.away` | 97 | 0.10% |
| `closingOdds.money_line.draw` | 97 | 0.10% |
| `closingOdds.money_line.home` | 97 | 0.10% |
| `closingOdds.over_under.line` | 114 | 0.12% |
| `closingOdds.over_under.over` | 114 | 0.12% |
| `closingOdds.over_under.under` | 114 | 0.12% |
| `closingOdds.over_under_ht.line` | 1319 | 1.41% |
| `closingOdds.over_under_ht.over` | 1319 | 1.41% |
| `closingOdds.over_under_ht.under` | 1319 | 1.41% |
| `createdAt` | 0 | 0.00% |
| `home.goals` | 448 | 0.48% |
| `home.goalsHT` | 481 | 0.51% |
| `home.name` | 0 | 0.00% |
| `home.nameLower` | 0 | 0.00% |
| `home.teamName` | 0 | 0.00% |
| `home.teamNameLower` | 0 | 0.00% |
| `idMatchBet365` | 0 | 0.00% |
| `league` | 0 | 0.00% |
| `odds.asian_handicap.away` | 311 | 0.33% |
| `odds.asian_handicap.home` | 311 | 0.33% |
| `odds.asian_handicap.line` | 311 | 0.33% |
| `odds.asian_handicap_ht.away` | 1598 | 1.71% |
| `odds.asian_handicap_ht.home` | 1598 | 1.71% |
| `odds.asian_handicap_ht.line` | 1598 | 1.71% |
| `odds.draw_no_bet.away` | 251 | 0.27% |
| `odds.draw_no_bet.home` | 251 | 0.27% |
| `odds.money_line.away` | 251 | 0.27% |
| `odds.money_line.draw` | 251 | 0.27% |
| `odds.money_line.home` | 251 | 0.27% |
| `odds.over_under.line` | 338 | 0.36% |
| `odds.over_under.over` | 338 | 0.36% |
| `odds.over_under.under` | 338 | 0.36% |
| `odds.over_under_ht.line` | 1628 | 1.74% |
| `odds.over_under_ht.over` | 1628 | 1.74% |
| `odds.over_under_ht.under` | 1628 | 1.74% |
| `startedAt` | 0 | 0.00% |
| `updatedAt` | 940 | 1.00% |
