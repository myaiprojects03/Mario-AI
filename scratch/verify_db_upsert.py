import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from core.db import get_db

def main():
    with get_db() as session:
        match_sources = session.execute(text("SELECT source, sport, COUNT(1) FROM core.matches GROUP BY source, sport ORDER BY source, sport")).fetchall()
        print("Matches Count by Source and Sport:")
        for source, sport, count in match_sources:
            print(f"  - source = '{source}', sport = '{sport}': {count:,} matches")

if __name__ == '__main__':
    main()
