from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from core.config.settings import settings


from sqlalchemy import event


def get_engine(db_url: str | None = None):
    """Create and return a SQLAlchemy Engine using settings.DATABASE_URL or fallback."""
    url = db_url or settings.DATABASE_URL
    if not url:
        url = "sqlite:///:memory:"

    # SQLite fallback for offline/unit testing
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})
        schemas = ["core", "fifa_goals_ou", "fifa_asian_handicap", "fifa_money_line", "ebasket_ou", "ebasket_money_line"]
        
        @event.listens_for(eng, "connect")
        def _attach_sqlite_schemas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            for schema in schemas:
                cursor.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
            cursor.close()
            
        return eng

    return create_engine(url, pool_pre_ping=True)


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    """Return a new database session instance."""
    return SessionLocal()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager providing a transactional scope around database operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
