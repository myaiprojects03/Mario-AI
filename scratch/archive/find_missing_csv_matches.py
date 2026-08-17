import sys
import site
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        print("--- Inspecting settlement_source in core.results ---")
        res_sources = conn.execute(text("SELECT settlement_source, COUNT(DISTINCT match_id) FROM core.results GROUP BY settlement_source")).fetchall()
        for src, cnt in res_sources:
            print(f"  Result settlement_source: {src:<18} | Distinct match_id count: {cnt:,}")

        # Check total match count originally loaded from CSV files
        # Notice that in Task 3, csv_loader.py created matches with source='csv_backfill' and results with settlement_source='csv_backfill'
        # Let's check if there are matches in core.matches that have raw_payload containing CSV fields or created during Task 3!
        query_csv_candidates = text("""
            SELECT sport, count(*)
            FROM core.matches
            WHERE match_id IN (
                SELECT DISTINCT match_id FROM core.results WHERE settlement_source = 'csv_backfill'
            )
            GROUP BY sport
        """)
        print("\n--- Matches linked to settlement_source='csv_backfill' ---")
        for sp, cnt in conn.execute(query_csv_candidates).fetchall():
            print(f"  Sport: {sp:<10} | Linked matches: {cnt:,}")

        # Check why 669 FIFA matches in core.results had settlement_source='jarbet_history' or missing settlement_source
        query_unlinked_csv = text("""
            SELECT sport, count(*)
            FROM core.matches
            WHERE source != 'csv_backfill' AND (raw_payload IS NULL OR source = 'jarbet_history')
            GROUP BY sport
        """)

if __name__ == "__main__":
    main()
