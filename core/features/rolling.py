from typing import List, Optional
import polars as pl


def compute_rolling_features(
    df: pl.DataFrame,
    entity_col: str,
    value_col: str,
    time_col: str,
    window_sizes: List[int],
    prefix: Optional[str] = None,
) -> pl.DataFrame:
    """
    Computes past-only rolling window mean and standard deviation over N matches for a player/team.
    
    STRICT DATA LEAKAGE GUARANTEE:
    Applies `.shift(1)` BEFORE calculating rolling aggregations per entity group.
    This guarantees that match N's own outcome is NEVER included in match N's rolling features.
    """
    if df.is_empty():
        return df

    pfx = prefix or f"{entity_col}_{value_col}"
    
    # Sort chronologically by entity and time
    sorted_df = df.sort([entity_col, time_col])

    exprs = []
    for w in window_sizes:
        # 1. Shift by 1 to exclude current match
        # 2. Compute rolling mean and std over past window
        shifted_col = pl.col(value_col).shift(1).over(entity_col)
        
        exprs.append(
            shifted_col.rolling_mean(window_size=w, min_samples=1)
            .over(entity_col)
            .alias(f"{pfx}_roll_mean_{w}")
        )
        exprs.append(
            shifted_col.rolling_std(window_size=w, min_samples=2)
            .over(entity_col)
            .alias(f"{pfx}_roll_std_{w}")
        )

    return sorted_df.with_columns(exprs)
