from typing import Tuple, Optional
import polars as pl


def compute_odds_drift_pair(odds_open: Optional[float], odds_close: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute absolute drift (odds_close - odds_open) and percentage drift for a single odds pair.
    Returns (abs_drift, pct_drift). Returns (None, None) if open or close is missing.
    """
    if odds_open is None or odds_close is None:
        return None, None

    abs_drift = float(odds_close - odds_open)
    if odds_open != 0:
        pct_drift = float((abs_drift / odds_open) * 100.0)
    else:
        pct_drift = 0.0

    return abs_drift, pct_drift


def add_odds_drift_columns(
    df: pl.DataFrame,
    open_col: str,
    close_col: str,
    prefix: str = "odds",
) -> pl.DataFrame:
    """
    Appends absolute drift (close - open) and percentage drift ((close - open) / open * 100)
    columns to a Polars DataFrame.
    """
    if open_col not in df.columns or close_col not in df.columns:
        return df

    abs_expr = (pl.col(close_col) - pl.col(open_col)).alias(f"{prefix}_drift_abs")
    pct_expr = (
        pl.when(pl.col(open_col) != 0)
        .then(((pl.col(close_col) - pl.col(open_col)) / pl.col(open_col)) * 100.0)
        .otherwise(0.0)
        .alias(f"{prefix}_drift_pct")
    )

    return df.with_columns([abs_expr, pct_expr])
