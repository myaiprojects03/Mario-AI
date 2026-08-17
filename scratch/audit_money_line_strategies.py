import numpy as np
import pandas as pd
import polars as pl
from sqlalchemy import create_engine
from core.config.settings import settings
from markets.fifa_money_line.model import load_training_dataset, run_walk_forward_backtest

engine = create_engine(settings.DATABASE_URL)
df_train = load_training_dataset(engine)
res = run_walk_forward_backtest(df_train)
