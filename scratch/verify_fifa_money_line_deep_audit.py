import numpy as np
import pandas as pd
import polars as pl
from scipy import stats
from sqlalchemy import create_engine
from core.config.settings import settings
from core.validation.walk_forward import WalkForwardSplitter
from core.validation.confidence import ConfidenceCalibrator
from core.validation.backtest_engine import BacktestEngine
from markets.fifa_money_line.model import load_training_dataset
from markets.fifa_money_line.models import LightGBMMoneyLineModel

engine = create_engine(settings.DATABASE_URL)
df_train = load_training_dataset(engine)

splitter = WalkForwardSplitter(train_days=45, test_days=7, step_days=7, time_col="match_start_time")
lgbm_model = LightGBMMoneyLineModel()

test_records = []
lgb_preds = []

print("Running walk-forward splits for deep empirical audit...")
for train_idx, test_idx in splitter.split(df_train):
    df_tr = df_train[train_idx]
    df_te = df_train[test_idx]

    n_tr = len(df_tr)
    split_pt = int(n_tr * 0.80)
    df_tr_sub = df_tr[:split_pt]
    df_val_sub = df_tr[split_pt:]

    lgb_sub = LightGBMMoneyLineModel()
    lgb_sub.fit(df_tr_sub)
    p_val_sub = lgb_sub.predict_probs(df_val_sub)

    df_val_pd = df_val_sub.to_pandas()
    y_val_sub = (df_val_pd["home.goals"].values > df_val_pd["away.goals"].values).astype(float)

    calibrator = ConfidenceCalibrator(method="isotonic")
    calibrator.fit(p_val_sub, y_val_sub)

    lgbm_model.fit(df_tr)
    p_lgb_raw = lgbm_model.predict_probs(df_te)
    p_lgb = calibrator.predict_confidence(p_lgb_raw)

    df_te_pd = df_te.to_pandas()
    is_win = (df_te_pd["home.goals"].values > df_te_pd["away.goals"].values).astype(float)
    is_draw = (df_te_pd["home.goals"].values == df_te_pd["away.goals"].values).astype(float)
    is_loss = (df_te_pd["home.goals"].values < df_te_pd["away.goals"].values).astype(float)

    for idx in range(len(df_te_pd)):
        odds_val = df_te_pd["closingOdds.money_line.home"].iloc[idx] if "closingOdds.money_line.home" in df_te_pd.columns else 1.90
        if pd.isna(odds_val) or float(odds_val) <= 1.0:
            odds_val = 1.90
        test_records.append({
            "match_id": df_te_pd["match_id"].iloc[idx],
            "startedAt": df_te_pd["startedAt"].iloc[idx],
            "odds_close": float(odds_val),
            "home_goals": df_te_pd["home.goals"].iloc[idx],
            "away_goals": df_te_pd["away.goals"].iloc[idx],
            "is_win": is_win[idx],
            "is_draw": is_draw[idx],
            "is_loss": is_loss[idx],
        })
        lgb_preds.append(p_lgb[idx])

df_eval = pl.DataFrame(test_records).with_columns(
    pl.Series("confidence", lgb_preds),
    (pl.Series("confidence", lgb_preds) - (1.0 / pl.col("odds_close"))).alias("edge")
)

# Apply Strategy D filter: edge >= 0.02, odds_close >= 1.70
tips_df = df_eval.filter((pl.col("edge") >= 0.02) & (pl.col("odds_close") >= 1.70))

# PnL calculation: + (odds_close - 1.0) if is_win == 1.0 else -1.0
tips_df = tips_df.with_columns(
    pl.when(pl.col("is_win") == 1.0)
    .then(pl.col("odds_close") - 1.0)
    .otherwise(-1.0)
    .alias("pnl_units")
)

tips_pd = tips_df.to_pandas()

print("\n==========================================================================")
print(" 1. ODDS & PNL MATH AUDIT (SAMPLE OF 20 WINNING TIPS)")
print("==========================================================================")
winning_tips = tips_pd[tips_pd["is_win"] == 1.0]
sample_wins = winning_tips.head(20)

for idx, r in sample_wins.reset_index().iterrows():
    expected_pnl = r["odds_close"] - 1.0
    print(f"Tip #{idx+1:02d} | Match: {r['match_id']} | Score: {int(r['home_goals'])}-{int(r['away_goals'])} | Odds: {r['odds_close']:.2f} | Model Conf: {r['confidence']:.4f} | Implied Prob: {1/r['odds_close']:.4f} | PnL: +{r['pnl_units']:.2f} (Check: {expected_pnl:.2f})")

print("\n--- ODDS DISTRIBUTION SUMMARY FOR ALL 677 TIPS ---")
print(f"Min Odds: {tips_pd['odds_close'].min():.2f}")
print(f"Mean Odds: {tips_pd['odds_close'].mean():.2f}")
print(f"Median Odds: {tips_pd['odds_close'].median():.2f}")
print(f"Max Odds: {tips_pd['odds_close'].max():.2f}")
print(f"Count of Odds > 5.0: {(tips_pd['odds_close'] > 5.0).sum()}")
print(f"Count of Odds > 10.0: {(tips_pd['odds_close'] > 10.0).sum()}")

print("\n==========================================================================")
print(" 2. OUTCOME BREAKDOWN (HOME WIN vs DRAW vs AWAY WIN)")
print("==========================================================================")
n_tips = len(tips_pd)
n_wins = (tips_pd["is_win"] == 1.0).sum()
n_draws = (tips_pd["is_draw"] == 1.0).sum()
n_losses = (tips_pd["is_loss"] == 1.0).sum()

print(f"Total Tips Evaluated: {n_tips}")
print(f"Home Wins (Winning Tips): {n_wins} ({n_wins/n_tips*100:.2f}%) -> Total PnL: +{winning_tips['pnl_units'].sum():.2f} units")
print(f"Draws (Lost Tips):        {n_draws} ({n_draws/n_tips*100:.2f}%) -> Total PnL: -{n_draws:.2f} units")
print(f"Away Wins (Lost Tips):    {n_losses} ({n_losses/n_tips*100:.2f}%) -> Total PnL: -{n_losses:.2f} units")

print("\n==========================================================================")
print(" 3. STATISTICAL SIGNIFICANCE & 95% CONFIDENCE INTERVAL CHECK")
print("==========================================================================")
pnl_series = tips_pd["pnl_units"].values
mean_pnl = np.mean(pnl_series)
std_pnl = np.std(pnl_series, ddof=1)
sem_pnl = stats.sem(pnl_series)
t_stat, p_val = stats.ttest_1samp(pnl_series, 0.0)

ci_lower_pnl, ci_upper_pnl = stats.t.interval(0.95, df=len(pnl_series)-1, loc=mean_pnl, scale=sem_pnl)

total_units_est = mean_pnl * n_tips
total_units_ci_lower = ci_lower_pnl * n_tips
total_units_ci_upper = ci_upper_pnl * n_tips

roi_est = mean_pnl * 100.0
roi_ci_lower = ci_lower_pnl * 100.0
roi_ci_upper = ci_upper_pnl * 100.0

print(f"Sample Size (N): {n_tips} tips")
print(f"Mean PnL per Tip: {mean_pnl:+.4f} units")
print(f"Std Dev of PnL:   {std_pnl:.4f} units")
print(f"Standard Error:   {sem_pnl:.4f} units")
print(f"t-statistic:      {t_stat:+.4f}")
print(f"p-value (1-sided): {p_val / 2.0:.4f}")
print(f"p-value (2-sided): {p_val:.4f}")
print(f"95% CI (Mean PnL/Tip): [{ci_lower_pnl:+.4f}, {ci_upper_pnl:+.4f}] units")
print(f"95% CI (Total Net Units): [{total_units_ci_lower:+.2f}, {total_units_ci_upper:+.2f}] units")
print(f"95% CI (ROI %): [{roi_ci_lower:+.2f}%, {roi_ci_upper:+.2f}%]")
