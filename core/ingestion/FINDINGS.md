# Ingestion & API Behavior Empirical Findings Log

This file documents empirical observations and live telemetry collected from the JarBet API endpoints (`/matches/pre`, `/matches/ebasket/pre`, `/history/pre`, `/history/ebasket/pre`).

---

## Rate Limit & Header Observations

- **Initial Spacing**: Conservative start at 1 request/second (`min_interval = 1.0s`).
- **Telemetry Headers Tracked**:
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Limit`
  - `X-RateLimit-Reset`
  - `Retry-After`
- **429 Handling**: Exponential backoff triggered on `429 Too Many Requests` responses with dynamic interval scaling (`self.min_interval` doubled).

---

## Odds Snapshot Behavior Empirical Test

- **Hypothesis**: Determine whether JarBet pre-match odds are a single static snapshot or dynamically change across consecutive polls for the same match.
- **Methodology**: `detect_odds_snapshot_behavior()` polls match odds twice separated by 120 seconds and records opening/closing line delta.

---

## FIFA Half-Time (HT) Odds Field Presence Analysis

- **Hypothesis**: Determine whether missing half-time odds (`over_under_ht`, `asian_handicap_ht`) are a "market not offered" pattern (concentrated in specific leagues) or a "random collection gap" pattern (spread across all leagues).

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |

## Odds Snapshot Behavior Empirical Test
- **Match ID**: `m_test`
- **Poll 1 Odds**: open=1.8, close=1.85
- **Poll 2 Odds**: open=1.8, close=1.95
- **Empirical Behavior Detected**: **Dynamic Updates Across Polls**

## FIFA Half-Time (HT) Odds Field Presence Analysis
| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |
|---|---|---|---|---|
| League A | 2 | 2 | 100.0% | Consistently Offered |
| League B | 1 | 0 | 0.0% | Market Not Offered (Concentrated) |
