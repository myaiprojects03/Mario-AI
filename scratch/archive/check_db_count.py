import sys
from sqlalchemy import create_engine, text
sys.path.insert(0, ".")
from core.config.settings import settings

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as conn:
    cnt = conn.execute(text("SELECT count(*) FROM core.matches WHERE source='jarbet_history'")).scalar()
    res_cnt = conn.execute(text("SELECT count(*) FROM core.results WHERE settlement_source='jarbet_history'")).scalar()

print(f"PostgreSQL jarbet_history matches count: {cnt}")
print(f"PostgreSQL jarbet_history results count: {res_cnt}")
