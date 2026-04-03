"""
Shared pytest fixtures for backend tests.

Tests run against the Docker PostgreSQL container on localhost:5432.
Each test function gets a transaction that is rolled back on teardown,
so tests are fully isolated and leave no data behind.

Prerequisites: docker-compose up (postgres service must be running)
"""
import os

# Provide defaults so Settings() doesn't fail when running tests locally
# without a .env file. Tests that actually hit the DB/Redis will still
# need the services running, but schema/unit tests work without them.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://databishop:databishop@localhost:5432/chess_puzzles_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Database setup

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://databishop:databishop@localhost:5432/chess_puzzles_test",
)

_ADMIN_DB_URL = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"


def _ensure_test_db_exists() -> None:
    """Create the test database if it doesn't already exist."""
    engine = create_engine(_ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'chess_puzzles_test'")
        ).fetchone()
        if not exists:
            conn.execute(text("CREATE DATABASE chess_puzzles_test"))
    engine.dispose()


@pytest.fixture(scope="session")
def test_database():
    """Create schema in the test database once per test session."""
    _ensure_test_db_exists()

    from database import Base
    engine = create_engine(TEST_DB_URL)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db(test_database):
    """
    Provide a database session that is rolled back after each test.
    Keeps tests isolated without needing to truncate tables.
    """
    connection = test_database.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# FastAPI test client

@pytest.fixture()
def client(db):
    """TestClient with the database dependency overridden to use the test session."""
    from database import get_db
    from main import app

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# Redis

@pytest.fixture()
def fake_redis():
    """In-memory Redis replacement — no running Redis required."""
    import fakeredis
    return fakeredis.FakeRedis(decode_responses=False)
