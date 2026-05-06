import pytest
from sqlalchemy import create_engine
from db.models import Base, init_db

@pytest.fixture
def engine():
    """Create a fresh in-memory SQLite database for each test."""
    # Use a unique name for each test or just memory
    engine = init_db("sqlite:///:memory:")
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def session(engine):
    """Provide a SQLAlchemy session (optional if using repository pattern directly)."""
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        yield s
