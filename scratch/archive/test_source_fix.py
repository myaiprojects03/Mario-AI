import sys
import site
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    print("==========================================================================")
    print("           VERIFYING SOURCE LABEL RESTORATION IN POSTGRESQL")
    print("==========================================================================")

    engine = create_engine(settings.DATABASE_URL)

    with engine.connect() as conn:
        query_group = text("""
            SELECT sport, source, COUNT(*)
            FROM core.matches
            GROUP BY sport, source
            ORDER BY sport, source
        """)
        rows_group = conn.execute(query_group).fetchall()
        print("\n--- Verified core.matches breakdown GROUP BY source, sport ---")
        for sp, src, cnt in rows_group:
            print(f"  Sport: {sp:<10} | Source: {src:<18} | Count: {cnt:,}")

        query_totals = text("""
            SELECT sport, COUNT(*)
            FROM core.matches
            GROUP BY sport
        """)
        rows_totals = conn.execute(query_totals).fetchall()
        print("\n--- Total matches in database per sport ---")
        for sp, cnt in rows_totals:
            print(f"  Sport: {sp:<10} | Total Matches in DB: {cnt:,}")


if __name__ == "__main__":
    main()
