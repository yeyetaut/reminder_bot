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
def authenticated_user(engine):
    """Pre-register a user with mock credentials for tests that require login."""
    from db.repository import UserRepo
    user_repo = UserRepo(engine)
    return user_repo.create_user(
        telegram_id=12345,
        chat_id=12345,
        google_credentials_encrypted="mock_google_creds"
    )
