from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool
from .config import DATABASE_URL, DATA_DIR

class Base(DeclarativeBase):
    pass

def build_engine(url=DATABASE_URL):
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine

DATA_DIR.mkdir(parents=True, exist_ok=True)
engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def initialize(engine_override=None):
    from . import models  # register mappings
    Base.metadata.create_all(engine_override or engine)
