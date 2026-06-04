import os
from cryptography.fernet import Fernet

# Set required env vars before any project module is imported.
# Use setdefault so a real .env (if present) takes precedence.
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_bot_token_for_testing")
os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")
os.environ.setdefault("WEB_URL", "http://localhost:8080")
os.environ.setdefault("GOOGLE_CREDENTIALS_FILE", "/nonexistent/credentials.json")
os.environ.setdefault("GOOGLE_TOKEN_FILE", "/nonexistent/token.json")

import pytest
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
