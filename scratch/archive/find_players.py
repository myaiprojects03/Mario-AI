import sys
sys.path.insert(0, ".")
from sqlalchemy import create_engine, text
from core.config.settings import settings

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as conn:
    fifa_players = [r[0] for r in conn.execute(text("SELECT DISTINCT home_player FROM core.matches WHERE sport='fifa' LIMIT 10")).fetchall()]
    ebasket_players = [r[0] for r in conn.execute(text("SELECT DISTINCT home_player FROM core.matches WHERE sport='ebasket' LIMIT 10")).fetchall()]

print("FIFA sample players:", fifa_players)
print("eBasketball sample players:", ebasket_players)
