import sys
import site
import polars as pl
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings


def main():
    print("==========================================================================")
    print("         MATCHING CSV FILE MATCH_IDS AGAINST CORE.MATCHES IN DB")
    print("==========================================================================")

    df_fifa = pl.read_csv("data/raw/history_pre_fifa.csv", infer_schema_length=10000)
    df_ebasket = pl.read_csv("data/raw/history_pre_ebasket.csv", infer_schema_length=10000)

    fifa_csv_ids = set([str(r.get("_id") or r.get("idMatchBet365") or "") for r in df_fifa.to_dicts()])
    ebasket_csv_ids = set([str(r.get("_id") or r.get("idMatchBet365") or "") for r in df_ebasket.to_dicts()])

    engine = create_engine(settings.DATABASE_URL)

    with engine.begin() as conn:
        # Check current sources for FIFA CSV IDs
        fifa_sources_query = text("""
            SELECT source, COUNT(*)
            FROM core.matches
            WHERE match_id = ANY(:ids)
            GROUP BY source
        """)
        fifa_sources = conn.execute(fifa_sources_query, {"ids": list(fifa_csv_ids)}).fetchall()
        print("\n--- Current source breakdown in DB for all 93,663 FIFA CSV match_ids ---")
        for src, cnt in fifa_sources:
            print(f"  Source: {src:<18} | Count: {cnt:,}")

        # Check current sources for eBasketball CSV IDs
        ebasket_sources_query = text("""
            SELECT source, COUNT(*)
            FROM core.matches
            WHERE match_id = ANY(:ids)
            GROUP BY source
        """)
        ebasket_sources = conn.execute(ebasket_sources_query, {"ids": list(ebasket_csv_ids)}).fetchall()
        print("\n--- Current source breakdown in DB for all 19,246 eBasketball CSV match_ids ---")
        for src, cnt in ebasket_sources:
            print(f"  Source: {src:<18} | Count: {cnt:,}")

        # RESTORE source='csv_backfill' for ALL match_ids in fifa_csv_ids or ebasket_csv_ids
        print("\n--- Restoring source='csv_backfill' for all match_ids in CSV files ---")
        restore_fifa = text("""
            UPDATE core.matches
            SET source = 'csv_backfill'
            WHERE match_id = ANY(:ids)
        """)
        res_fifa = conn.execute(restore_fifa, {"ids": list(fifa_csv_ids)})
        print(f"Restored FIFA source='csv_backfill' for {res_fifa.rowcount:,} rows.")

        restore_ebasket = text("""
            UPDATE core.matches
            SET source = 'csv_backfill'
            WHERE match_id = ANY(:ids)
        """)
        res_ebasket = conn.execute(restore_ebasket, {"ids": list(ebasket_csv_ids)})
        print(f"Restored eBasketball source='csv_backfill' for {res_ebasket.rowcount:,} rows.")

    with engine.connect() as conn:
        print("\n==========================================================================")
        print("          VERIFIED FINAL core.matches BREAKDOWN AFTER RESTORATION")
        print("==========================================================================")
        query_group = text("""
            SELECT sport, source, COUNT(*)
            FROM core.matches
            GROUP BY sport, source
            ORDER BY sport, source
        """)
        rows_group = conn.execute(query_group).fetchall()
        for sp, src, cnt in rows_group:
            print(f"  Sport: {sp:<10} | Source: {src:<18} | Count: {cnt:,}")


if __name__ == "__main__":
    main()
