import sys
import polars as pl

df_fifa = pl.read_csv("data/raw/history_pre_fifa.csv", infer_schema_length=10000)
df_ebasket = pl.read_csv("data/raw/history_pre_ebasket.csv", infer_schema_length=10000)

print(f"data/fifa_matches.csv row count: {len(df_fifa):,}")
print(f"data/ebasket_matches.csv row count: {len(df_ebasket):,}")

# Check unique match_id count in data/fifa_matches.csv
fifa_ids = [str(r.get("_id") or r.get("idMatchBet365") or "") for r in df_fifa.to_dicts()]
ebasket_ids = [str(r.get("_id") or r.get("idMatchBet365") or "") for r in df_ebasket.to_dicts()]

print(f"Unique _id/idMatchBet365 in fifa_matches.csv: {len(set(fifa_ids)):,}")
print(f"Unique _id/idMatchBet365 in ebasket_matches.csv: {len(set(ebasket_ids)):,}")
