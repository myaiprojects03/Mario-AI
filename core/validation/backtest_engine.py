"""
Backtest Engine Module for Flat-Staking Betting Strategy Evaluation.

SPECIFICATION RULES:
- Flat 1-unit staking per evaluated tip.
- Win: +(odds - 1.0) units.
- Loss: -1.0 unit.
- Void: 0.0 unit.
- Odds Floor Filters:
  - Global floor: 1.60
  - Money Line market floor: 1.70
"""

from typing import Dict, Any, List, Optional, Union
import numpy as np
import polars as pl
import pandas as pd


class BacktestEngine:
    """
    Backtest Engine evaluating model recommendations against actual odds and outcomes.
    """

    def __init__(
        self,
        global_odds_floor: float = 1.60,
        money_line_floor: float = 1.70,
        min_confidence: float = 0.50,
    ):
        """
        Args:
            global_odds_floor (float): Minimum odds filter for general markets (1.60).
            money_line_floor (float): Minimum odds filter for money line markets (1.70).
            min_confidence (float): Minimum confidence score threshold to publish a tip.
        """
        self.global_odds_floor = global_odds_floor
        self.money_line_floor = money_line_floor
        self.min_confidence = min_confidence

    def evaluate_tips(
        self,
        df: Union[pl.DataFrame, pd.DataFrame],
        is_money_line: bool = False,
        confidence_col: str = "confidence",
        odds_col: str = "odds_close",
        outcome_col: str = "is_win",
        time_col: str = "startedAt",
    ) -> Dict[str, Any]:
        """
        Evaluates tips using flat 1-unit staking with odds and confidence filtering.

        Args:
            df: Dataframe containing recommendations, odds, and actual outcomes.
            is_money_line: If True, applies money line floor (1.70) instead of global floor (1.60).
            confidence_col: Model confidence probability column name.
            odds_col: Closing odds column name.
            outcome_col: Outcome column (1.0 for Win, 0.0 for Loss, None/-1 for Void).
            time_col: Timestamp column name for window breakdowns.

        Returns:
            Dict containing total_units, roi_pct, hit_rate, tips_evaluated, and per_window_breakdown.
        """
        min_odds_floor = self.money_line_floor if is_money_line else self.global_odds_floor

        # Standardize input to Polars
        if isinstance(df, pd.DataFrame):
            work_df = pl.from_pandas(df)
        else:
            work_df = df

        if work_df.is_empty():
            return {
                "total_units": 0.0,
                "roi_pct": 0.0,
                "hit_rate": 0.0,
                "tips_evaluated": 0,
                "wins": 0,
                "losses": 0,
                "voids": 0,
                "per_window_breakdown": [],
            }

        # Filter tips meeting minimum odds floor AND confidence threshold
        filtered_df = work_df.filter(
            (pl.col(odds_col) >= min_odds_floor) &
            (pl.col(confidence_col) >= self.min_confidence)
        )

        if filtered_df.is_empty():
            return {
                "total_units": 0.0,
                "roi_pct": 0.0,
                "hit_rate": 0.0,
                "tips_evaluated": 0,
                "wins": 0,
                "losses": 0,
                "voids": 0,
                "per_window_breakdown": [],
            }

        # Calculate unit profit per tip
        # Win (1.0): +(odds - 1.0)
        # Loss (0.0): -1.0
        # Void (-1.0 or null): 0.0
        filtered_df = filtered_df.with_columns(
            pl.when(pl.col(outcome_col) == 1.0)
            .then(pl.col(odds_col) - 1.0)
            .when(pl.col(outcome_col) == 0.0)
            .then(-1.0)
            .otherwise(0.0)
            .alias("pnl_units")
        )

        total_units = float(filtered_df["pnl_units"].sum())
        tips_evaluated = len(filtered_df)

        wins = filtered_df.filter(pl.col(outcome_col) == 1.0).height
        losses = filtered_df.filter(pl.col(outcome_col) == 0.0).height
        voids = tips_evaluated - (wins + losses)

        roi_pct = (total_units / tips_evaluated) * 100.0 if tips_evaluated > 0 else 0.0
        hit_rate = (wins / (wins + losses)) if (wins + losses) > 0 else 0.0

        # Per time-window breakdown (monthly grouping)
        per_window_breakdown = []
        if time_col in filtered_df.columns:
            df_with_month = filtered_df.with_columns(
                pl.col(time_col).dt.truncate("1mo").alias("month_window")
            )
            grouped = df_with_month.group_by("month_window").agg([
                pl.len().alias("tips"),
                pl.col("pnl_units").sum().alias("units"),
                (pl.col(outcome_col) == 1.0).sum().alias("wins"),
                (pl.col(outcome_col) == 0.0).sum().alias("losses"),
            ]).sort("month_window")

            for row in grouped.to_dicts():
                w_tips = row["tips"]
                w_units = row["units"]
                w_wins = row["wins"]
                w_losses = row["losses"]
                per_window_breakdown.append({
                    "window": str(row["month_window"]),
                    "tips": w_tips,
                    "units": round(float(w_units), 4),
                    "roi_pct": round(float((w_units / w_tips) * 100.0), 2) if w_tips > 0 else 0.0,
                    "hit_rate": round(float(w_wins / (w_wins + w_losses)), 4) if (w_wins + w_losses) > 0 else 0.0,
                })

        return {
            "total_units": round(total_units, 4),
            "roi_pct": round(roi_pct, 2),
            "hit_rate": round(hit_rate, 4),
            "tips_evaluated": tips_evaluated,
            "wins": wins,
            "losses": losses,
            "voids": voids,
            "per_window_breakdown": per_window_breakdown,
        }
