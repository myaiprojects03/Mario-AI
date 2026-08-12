"""
Walk-Forward Splitter Module with Strict Data Leakage Assertions.

GUARANTEES:
- Chronologically slides training and testing windows forward in time.
- Enforces an in-class assertion raising ValueError if max(train_timestamp) >= min(test_timestamp).
"""

from datetime import datetime, timedelta
from typing import Generator, Tuple, Union
import numpy as np
import polars as pl
import pandas as pd


class WalkForwardSplitter:
    """
    Time-series Walk-Forward Splitter for backtesting without future data leakage.
    """

    def __init__(
        self,
        train_days: int = 60,
        test_days: int = 14,
        step_days: int = 7,
        time_col: str = "startedAt",
    ):
        """
        Args:
            train_days (int): Length of training window in days.
            test_days (int): Length of testing window in days.
            step_days (int): Step size to slide forward in days.
            time_col (str): Timestamp column name in dataframe.
        """
        if train_days <= 0 or test_days <= 0 or step_days <= 0:
            raise ValueError("train_days, test_days, and step_days must be positive integers.")
        
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.time_col = time_col

    def split(
        self, df: Union[pl.DataFrame, pd.DataFrame]
    ) -> Generator[Tuple[np.ndarray, np.ndarray], None, None]:
        """
        Yields (train_index, test_index) integer array pairs for chronological walk-forward splits.

        Raises:
            ValueError: If data leakage occurs (any train timestamp >= test timestamp).
        """
        # Standardize timestamp extraction to numpy array of datetimes
        if isinstance(df, pl.DataFrame):
            times = df[self.time_col].to_numpy()
        elif isinstance(df, pd.DataFrame):
            times = df[self.time_col].to_numpy()
        else:
            raise TypeError("df must be a Polars or Pandas DataFrame.")

        if len(times) == 0:
            return

        min_time = pd.to_datetime(times.min())
        max_time = pd.to_datetime(times.max())

        train_delta = timedelta(days=self.train_days)
        test_delta = timedelta(days=self.test_days)
        step_delta = timedelta(days=self.step_days)

        current_train_start = min_time

        while True:
            current_train_end = current_train_start + train_delta
            current_test_end = current_train_end + test_delta

            if current_train_end > max_time:
                break

            train_mask = (times >= current_train_start) & (times < current_train_end)
            test_mask = (times >= current_train_end) & (times < current_test_end)

            train_indices = np.where(train_mask)[0]
            test_indices = np.where(test_mask)[0]

            # Only yield if both train and test windows have sample rows
            if len(train_indices) > 0 and len(test_indices) > 0:
                train_max_t = times[train_indices].max()
                test_min_t = times[test_indices].min()

                # STRICT IN-SPLITTER DATA LEAKAGE ASSERTION
                if train_max_t >= test_min_t:
                    raise ValueError(
                        f"Data leakage detected in WalkForwardSplitter! "
                        f"Max train timestamp ({train_max_t}) >= Min test timestamp ({test_min_t})."
                    )

                yield train_indices, test_indices

            current_train_start += step_delta
            if current_train_end >= max_time:
                break
