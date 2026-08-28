"""Persistence: SQLAlchemy 2.0, SQLite by default, PostgreSQL/MySQL via
DATABASE_URL env var (see docker-compose.yml for the Postgres profile).

Tables:
  feedback        — human-in-the-loop investigator verdicts (the labelled-data
                    capture for future model retraining; retraining itself is
                    out of scope for the prototype)
  dataset_upload  — metadata about bring-your-own dataset uploads
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, Column, DateTime, Float, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

os.makedirs(config.DATA_DIR, exist_ok=True)
engine = create_engine(config.DATABASE_URL, connect_args=(
    {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite")
    else {}))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=False, index=True)
    dataset_id = Column(String(64), default="demo", index=True)
    verdict = Column(String(32), nullable=False)   # confirmed | false_positive | needs_more_info
    note = Column(Text, default="")
    investigator = Column(String(128), default="")
    risk_score = Column(Float)
    band = Column(String(16))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # snapshot of the alert at feedback time (features -> retraining-ready)
    context = Column(JSON, default=dict)


class DatasetUpload(Base):
    __tablename__ = "dataset_upload"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(64), unique=True, index=True)
    filename = Column(String(256))
    kind = Column(String(16))          # projects | ledger
    n_rows = Column(Integer)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
