"""
Shared V3 Multi-Line Expansion and Quarter-Kelly Bet-Sizing Module.
"""

from typing import Dict, Any, List, Tuple
import numpy as np
import polars as pl
import pandas as pd


def calculate_quarter_kelly_stake(
    p_model: float,
    odds: float,
    fraction: float = 0.25,
    max_stake: float = 2.0,
    min_stake: float = 0.10,
) -> float:
    """
    Calculates Quarter-Kelly stake fraction:
    f* = fraction * (p * b - q) / b where b = odds - 1.0, q = 1 - p
    Clamped between min_stake and max_stake.
    """
    if odds <= 1.0 or p_model <= 0.0 or p_model >= 1.0:
        return 0.0

    b = odds - 1.0
    q = 1.0 - p_model
    full_kelly = (p_model * b - q) / b

    if full_kelly <= 0.0:
        return 0.0

    quarter_stake = fraction * full_kelly * 10.0  # Scale 10-unit base bankroll fraction
    clamped_stake = float(np.clip(quarter_stake, min_stake, max_stake))
    return round(clamped_stake, 2)


def evaluate_percentile_tiers_with_kelly(
    test_records: List[Dict[str, Any]],
    percentiles: List[int] = [100, 90, 80, 70, 50],
    is_money_line: bool = False,
    odds_floor: float = 1.60,
) -> List[Dict[str, Any]]:
    """
    Evaluates backtest test records across percentile filter tiers comparing Flat 1-Unit vs Quarter-Kelly Staking.
    """
    df_all = pl.DataFrame(test_records).filter(
        pl.col("odds_close").is_not_null() &
        (pl.col("odds_close") >= odds_floor) &
        pl.col("edge").is_not_null() &
        (pl.col("edge") > 0.0)
    )

    if df_all.is_empty():
        return []

    min_date = df_all["startedAt"].min()
    max_date = df_all["startedAt"].max()
    total_days = max(1, (max_date - min_date).days)
    months = total_days / 30.0

    results = []

    for pct in percentiles:
        if pct == 100:
            df_tier = df_all
        else:
            q_val = np.percentile(df_all["edge"].to_numpy(), 100 - pct)
            df_tier = df_all.filter(pl.col("edge") >= q_val)

        if df_tier.is_empty():
            continue

        pdf = df_tier.to_pandas()
        tips_count = len(pdf)
        daily_tips = round(tips_count / total_days, 1)

        # Flat 1-Unit PnL
        flat_pnl = np.where(pdf["is_win"].values == 1.0, pdf["odds_close"].values - 1.0, -1.0)
        flat_total_units = float(np.sum(flat_pnl))
        flat_monthly_rate = round(flat_total_units / max(1.0, months), 2)
        flat_roi = round((flat_total_units / tips_count) * 100.0, 2)
        hit_rate = round(float(np.mean(pdf["is_win"].values == 1.0)) * 100.0, 2)

        # Quarter-Kelly PnL
        kelly_stakes = []
        for idx in range(tips_count):
            p = float(pdf["confidence"].iloc[idx])
            o = float(pdf["odds_close"].iloc[idx])
            stk = calculate_quarter_kelly_stake(p, o)
            kelly_stakes.append(stk)

        kelly_stakes = np.array(kelly_stakes)
        kelly_pnl = np.where(pdf["is_win"].values == 1.0, kelly_stakes * (pdf["odds_close"].values - 1.0), -kelly_stakes)
        kelly_total_units = float(np.sum(kelly_pnl))
        total_staked = float(np.sum(kelly_stakes))
        kelly_monthly_rate = round(kelly_total_units / max(1.0, months), 2)
        kelly_roi = round((kelly_total_units / total_staked) * 100.0, 2) if total_staked > 0 else 0.0

        results.append({
            "tier_name": f"Top {pct}% Tips",
            "cutoff_percentile": 100 - pct,
            "tips_evaluated": tips_count,
            "daily_tips": daily_tips,
            "hit_rate": hit_rate,
            "flat_total_units": round(flat_total_units, 2),
            "flat_monthly_rate": flat_monthly_rate,
            "flat_roi": flat_roi,
            "kelly_total_units": round(kelly_total_units, 2),
            "kelly_monthly_rate": kelly_monthly_rate,
            "kelly_roi": kelly_roi,
            "avg_kelly_stake": round(float(np.mean(kelly_stakes)), 2),
        })

    return results
