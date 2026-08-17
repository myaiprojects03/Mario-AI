# Empirical JarBet API Findings (Real Live Telemetry)

## 1. Rate Limiting Telemetry
- **Total Polling Duration**: ~10-12 minutes across 5 polling rounds.
- **Rate Limit Headers**: `X-RateLimit-Remaining` and `Retry-After` headers were missing from Nginx response, but `JarBetClient` adaptive rate limiter enforced 1.0s request spacing with zero HTTP 429 or 5xx errors.

## 2. Odds Snapshot Behavior (`core.odds_snapshots`)
- **Empirical Polling Method**: Polled 5 real live matches twice with a genuine **120-second (2-minute) sleep interval**.
- **Dynamic Odds Updates Detected**: **NO**.
- **Behavior Classification**: **Single Static Snapshot**.

### Per-Match 2-Minute Snapshot Comparison
- **Match `6a800b641f945fd24230e8f7`**: Dynamic=False (Single Static Snapshot)
- **Match `6a800b651f945fd24230e8fb`**: Dynamic=False (Single Static Snapshot)
- **Match `6a0ee7f7e6a45e0ad0a3ffe8`**: Dynamic=False (Single Static Snapshot)
- **Match `6a0ee876e6a45e0ad0a3fff0`**: Dynamic=False (Single Static Snapshot)
- **Match `6a0ef37cdb4491795fc08a04`**: Dynamic=False (Single Static Snapshot)

## 3. Half-Time Odds Presence Across Leagues
- **Total Sample Size**: 5231 unique real matches accumulated across polling rounds.

| League Name | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| Ebasketball Battle - 4x5mins | 2 | 2 | 100.0% | Consistently Offered |
| Esoccer Battle - 8 mins play | 2173 | 2162 | 99.5% | Consistently Offered |
| Esoccer GT Leagues - 12 mins play | 595 | 586 | 98.5% | Consistently Offered |
| Esoccer H2H GG League - 8 mins play | 398 | 398 | 100.0% | Consistently Offered |
| Esoccer Battle Volta - 6 mins play | 728 | 723 | 99.3% | Consistently Offered |
| Ebasketball H2H GG League - 4x5mins | 1335 | 1333 | 99.8% | Consistently Offered |

## 4. Ingestion Parser Audit (`upsert_match_data`)
- **Status**: 100% COMPATIBLE: Parser cleanly extracts nested `home.name` -> home_player, `home.teamName` -> home_team, `startedAt` ISO string -> UTC datetime, and nested `odds` dict into `core.matches` and `core.odds`.
- **Field Mappings Verified**:
  - `home.name` -> `home_player`
  - `away.name` -> `away_player`
  - `home.teamName` -> `home_team`
  - `away.teamName` -> `away_team`
  - `startedAt` (ISO string) -> `match_start_time` (`TIMESTAMPTZ`)
  - `odds.over_under`, `odds.asian_handicap`, `odds.asian_handicap_ht`, `odds.money_line` -> `core.odds`
