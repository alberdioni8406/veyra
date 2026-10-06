from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import StaticPool
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/veyra.db")

# Neon / Vercel often provide postgres:// or postgresql://
# Force a concrete driver so SQLAlchemy does not look for missing packages.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

if DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    # Prefer psycopg2 (psycopg2-binary) which is reliable on Vercel
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

is_sqlite = DATABASE_URL.startswith("sqlite")

engine_kwargs = {}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine_kwargs["poolclass"] = StaticPool
else:
    # Serverless-friendly pooling
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import (
        User,
        Room,
        RoomParticipant,
        Payment,
        Connection,
        RoomMessage,
        PlatformConfig,
    )

    Base.metadata.create_all(bind=engine)
