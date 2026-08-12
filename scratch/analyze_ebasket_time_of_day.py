import sys
import site
import polars as pl
from scipy import stats
from sqlalchemy import create_engine

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    engine = create_engine(settings.DATABASE_URL)
    query = """
    SELECT 
        m.match_id,
        m.match_start_time AS "startedAt",
        r.final_home_score + r.final_away_score AS total_points
    FROM core.matches m
    JOIN core.results r ON m.match_id = r.match_id
    WHERE m.sport = 'ebasket' AND m.source = 'csv_backfill'
    """
    with engine.connect() as conn:
        df = pl.read_database(query, connection=conn)

    print(f"Loaded {len(df)} eBasketball matches for ANOVA time-of-day study.")

    # Extract hour of day (UTC)
    df = df.with_columns(
        pl.col("startedAt").dt.hour().alias("hour_of_day_utc")
    )

    # Group total_points by hour
    grouped_points = []
    hours = sorted(df["hour_of_day_utc"].unique().to_list())
    for h in hours:
        pts = df.filter(pl.col("hour_of_day_utc") == h)["total_points"].to_list()
        if len(pts) > 10:
            grouped_points.append(pts)

    f_stat, p_val = stats.f_oneway(*grouped_points)
    print(f"ANOVA Results across UTC Hours:")
    print(f"  F-statistic: {f_stat:.4f}")
    print(f"  p-value: {p_val:.4e}")

    # Decision threshold: p_val < 0.05
    significant = p_val < 0.05
    print(f"Statistically significant pattern (p < 0.05)? {significant}")

    # Write findings to markets/_shared/ebasket_features_NOTES.md
    notes = [
        "# eBasketball Feature Engineering Notes - Time-of-Day Study",
        "",
        "## UTC Hour-of-Day ANOVA Statistical Study",
        f"- **Dataset Size**: {len(df)} historical eBasketball matches from PostgreSQL (`core.matches`/`core.results`).",
        f"- **Metric Evaluated**: Total points scored (`final_home_score + final_away_score`).",
        f"- **Factor**: UTC Hour of Match Start (`startedAt.dt.hour()`, hours {min(hours)} to {max(hours)}).",
        f"- **ANOVA F-statistic**: {f_stat:.4f}",
        f"- **ANOVA p-value**: {p_val:.4e}",
        f"- **Statistical Significance (p < 0.05)**: {'YES' if significant else 'NO'}",
        "",
        "## Feature Inclusion Decision",
    ]
    if significant:
        notes.append(
            f"**INCLUDED**: The ANOVA test yielded a p-value of {p_val:.4e} (< 0.05), indicating a statistically meaningful variation in scoring performance across UTC time slots. `hour_of_day_utc` is included in the eBasketball feature set."
        )
    else:
        notes.append(
            f"**DROPPED**: The ANOVA test yielded a p-value of {p_val:.4f} (>= 0.05), indicating no statistically significant variation in scoring performance across UTC time slots. `hour_of_day_utc` is dropped to prevent model overfitting."
        )

    with open("markets/_shared/ebasket_features_NOTES.md", "w", encoding="utf-8") as f:
        f.write("\n".join(notes) + "\n")

    print("Wrote analysis findings to markets/_shared/ebasket_features_NOTES.md")


if __name__ == "__main__":
    main()
