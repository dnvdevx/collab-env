"""
Database engine + session setup.
For local dev we use SQLite; swap DATABASE_URL for Postgres in production
(e.g. Railway/Render connection string) - SQLModel/SQLAlchemy code doesn't change.
"""

import os
from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./mission_control.db")

# check_same_thread=False is only needed for SQLite (FastAPI runs multi-threaded)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
