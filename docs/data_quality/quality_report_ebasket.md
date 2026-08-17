# Data Quality & Distribution Sanity Report - EBASKET
- **Total Input Rows**: 19246
- **Generated At (UTC)**: 2026-08-11T12:59:20.127072+00:00

## 1. Distribution Sanity Check
- **Metric Analyzed**: Total Points
- **Actual Mean / Std**: 111.27 / 24.31
- **Spec Benchmark Mean / Std**: 111.80 / 23.10
- **Status**: ✅ PASSED SANITY CHECK

## 2. Per-Market Exclusion Counts (Odds Coverage Filter)
| Market Type | Retained Rows | Excluded Rows | Exclusion Rate (%) |
|---|---|---|---|
| ebasket_ou | 19246 | 0 | 0.00% |
| ebasket_money_line | 19078 | 168 | 0.87% |

## 3. Missing Odds Coverage by League
| League | Total Matches | Missing Odds Rows | Missing Rate (%) |
|---|---|---|---|
| Ebasketball H2H GG League - 4x5mins | 15114 | 0 | 0.00% |
| Ebasketball Battle - 4x5mins | 4132 | 0 | 0.00% |

## 4. Column Null Rates
| Column Name | Null Count | Null Rate (%) |
|---|---|---|
| `_id` | 0 | 0.00% |
| `away.goals` | 153 | 0.79% |
| `away.goalsHT` | 161 | 0.84% |
| `away.name` | 0 | 0.00% |
| `away.nameLower` | 0 | 0.00% |
| `away.teamName` | 0 | 0.00% |
| `away.teamNameLower` | 0 | 0.00% |
| `closingOdds.asian_handicap.away` | 99 | 0.51% |
| `closingOdds.asian_handicap.home` | 99 | 0.51% |
| `closingOdds.asian_handicap.line` | 99 | 0.51% |
| `closingOdds.asian_handicap_ht.away` | 40 | 0.21% |
| `closingOdds.asian_handicap_ht.home` | 40 | 0.21% |
| `closingOdds.asian_handicap_ht.line` | 40 | 0.21% |
| `closingOdds.money_line.away` | 181 | 0.94% |
| `closingOdds.money_line.draw` | 19246 | 100.00% |
| `closingOdds.money_line.home` | 181 | 0.94% |
| `closingOdds.over_under.line` | 1 | 0.01% |
| `closingOdds.over_under.over` | 1 | 0.01% |
| `closingOdds.over_under.under` | 1 | 0.01% |
| `closingOdds.over_under_ht.line` | 39 | 0.20% |
| `closingOdds.over_under_ht.over` | 39 | 0.20% |
| `closingOdds.over_under_ht.under` | 39 | 0.20% |
| `createdAt` | 0 | 0.00% |
| `home.goals` | 153 | 0.79% |
| `home.goalsHT` | 161 | 0.84% |
| `home.name` | 0 | 0.00% |
| `home.nameLower` | 0 | 0.00% |
| `home.teamName` | 0 | 0.00% |
| `home.teamNameLower` | 0 | 0.00% |
| `idMatchBet365` | 0 | 0.00% |
| `league` | 0 | 0.00% |
| `odds.asian_handicap.away` | 65 | 0.34% |
| `odds.asian_handicap.home` | 65 | 0.34% |
| `odds.asian_handicap.line` | 65 | 0.34% |
| `odds.asian_handicap_ht.away` | 59 | 0.31% |
| `odds.asian_handicap_ht.home` | 59 | 0.31% |
| `odds.asian_handicap_ht.line` | 59 | 0.31% |
| `odds.money_line.away` | 172 | 0.89% |
| `odds.money_line.draw` | 19246 | 100.00% |
| `odds.money_line.home` | 172 | 0.89% |
| `odds.over_under.line` | 0 | 0.00% |
| `odds.over_under.over` | 0 | 0.00% |
| `odds.over_under.under` | 0 | 0.00% |
| `odds.over_under_ht.line` | 59 | 0.31% |
| `odds.over_under_ht.over` | 59 | 0.31% |
| `odds.over_under_ht.under` | 59 | 0.31% |
| `startedAt` | 0 | 0.00% |
| `updatedAt` | 31 | 0.16% |
