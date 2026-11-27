# ============================================================
# FILE: shared/database.py
# PURPOSE: SQLAlchemy engine + session factory + Base class
#          shared by all 3 use cases and the FastAPI server.
# USE CASE: All (Shared)
#
# HOW IT WORKS:
#   - Creates the SQLAlchemy engine from DATABASE_URL in .env.
#   - SessionLocal is used by FastAPI routes via Depends(get_db).
#   - Base is imported by shared/models.py for table definitions.
#   - Tables are created on startup via Base.metadata.create_all().
#
# DEBUG TIPS:
#   - Database not found / OperationalError?
#       → Check DATABASE_URL in .env (default: sqlite:///./perimeter_monitor.db)
#       → SQLite DB file is created in the PROJECT ROOT directory.
#       → Run: python -c "from shared.database import Base, engine; Base.metadata.create_all(engine)"
#   - "check_same_thread" error?
#       → Only applies to SQLite. connect_args already handles this.
#   - Session not closing properly?
#       → Always use get_db() as a FastAPI dependency — it closes session in finally.
#   - Migration needed (new column)?
#       → main.py runs PRAGMA / ALTER TABLE on startup for known migrations.
#       → For new columns: add to shared/models.py and run ALTER TABLE manually or restart.
#
# DEPENDENCIES:
#   - shared/config.py  → settings.database_url
# ============================================================

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from shared.config import settings

# SQLite requires check_same_thread=False for multi-threaded use
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

# Session factory: autoflush=False so explicit flush/commit is required
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""
    pass


def get_db():
    """
    FastAPI dependency that provides a DB session per request.
    Always closes the session after the request finishes.

    Usage:
        @app.get("/api/example")
        def example(db: Session = Depends(get_db)):
            ...

    DEBUG: Session errors / DetachedInstanceError?
           → expire_on_commit=False keeps objects accessible after commit.
           → Do not cache db objects across requests.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
