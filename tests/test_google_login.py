"""
Tests for the Google OAuth login flow.

Covers:
  - oauth2callback handler (success, error cases)
  - Credential encryption round-trip (encrypt_json / decrypt_json)
  - UserRepo credential storage and retrieval
  - get_credentials() path for per-user credentials
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_fake_creds(token="tok", refresh_token="ref", valid=True, expired=False):
    """Build a MagicMock that looks like google.oauth2.credentials.Credentials."""
    creds = MagicMock()
    creds.token = token
    creds.refresh_token = refresh_token
    creds.token_uri = "https://oauth2.googleapis.com/token"
    creds.client_id = "client_id"
    creds.client_secret = "client_secret"
    creds.scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    creds.valid = valid
    creds.expired = expired
    return creds


def _make_request(query: dict, engine, bot):
    """Minimal aiohttp Request-lookalike for testing oauth2callback."""
    req = MagicMock()
    req.query = query
    req.app = {"engine": engine, "bot": bot}
    return req


# ── credential encryption round-trip ──────────────────────────────────────────

def test_encrypt_decrypt_credentials_roundtrip():
    """encrypt_json / decrypt_json must survive a full credential dict unchanged."""
    from utils.security import encrypt_json, decrypt_json

    creds = {
        "token": "access_token_abc",
        "refresh_token": "refresh_xyz",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client_id_123",
        "client_secret": "secret_456",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }
    encrypted = encrypt_json(creds)
    assert encrypted != str(creds)           # must be ciphertext
    assert isinstance(encrypted, str)
    decrypted = decrypt_json(encrypted)
    assert decrypted == creds


def test_encrypt_json_empty_returns_empty():
    from utils.security import encrypt_json
    assert encrypt_json(None) == ""
    assert encrypt_json({}) == ""


def test_decrypt_json_empty_returns_none():
    from utils.security import decrypt_json
    assert decrypt_json(None) is None
    assert decrypt_json("") is None


def test_two_encryptions_of_same_data_differ():
    """Fernet produces different ciphertext each call (random IV)."""
    from utils.security import encrypt_json
    data = {"key": "value"}
    assert encrypt_json(data) != encrypt_json(data)


# ── UserRepo: credential persistence ──────────────────────────────────────────

def test_user_google_credentials_stored_and_retrieved(engine):
    """Encrypted credentials saved via UserRepo can be read back."""
    from db.repository import UserRepo
    from utils.security import encrypt_json, decrypt_json

    repo = UserRepo(engine)
    user = repo.create_user(telegram_id=1001, chat_id=1001)
    assert user.google_credentials_encrypted is None

    creds_dict = {"token": "t", "refresh_token": "r", "scopes": []}
    encrypted = encrypt_json(creds_dict)
    repo.update_user(user.id, google_credentials_encrypted=encrypted)

    fetched = repo.get_by_telegram_id(1001)
    assert fetched.google_credentials_encrypted == encrypted
    assert decrypt_json(fetched.google_credentials_encrypted) == creds_dict


def test_different_users_have_independent_credentials(engine):
    """User A's credentials update must not affect User B."""
    from db.repository import UserRepo
    from utils.security import encrypt_json

    repo = UserRepo(engine)
    user_a = repo.create_user(telegram_id=1001, chat_id=1001)
    user_b = repo.create_user(telegram_id=1002, chat_id=1002)

    enc_a = encrypt_json({"token": "token_a"})
    repo.update_user(user_a.id, google_credentials_encrypted=enc_a)

    assert repo.get_by_telegram_id(1002).google_credentials_encrypted is None


def test_credentials_can_be_overwritten(engine):
    """A second OAuth flow (re-login) replaces the old credentials."""
    from db.repository import UserRepo
    from utils.security import encrypt_json, decrypt_json

    repo = UserRepo(engine)
    user = repo.create_user(telegram_id=1001, chat_id=1001)

    old_enc = encrypt_json({"token": "old_token"})
    repo.update_user(user.id, google_credentials_encrypted=old_enc)

    new_enc = encrypt_json({"token": "new_token"})
    repo.update_user(user.id, google_credentials_encrypted=new_enc)

    assert decrypt_json(repo.get_by_telegram_id(1001).google_credentials_encrypted)["token"] == "new_token"


# ── oauth2callback handler ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oauth_callback_success(engine):
    """Valid code + state saves encrypted credentials and returns 200."""
    from main import oauth2callback
    from db.repository import UserRepo
    from utils.security import decrypt_json

    user_repo = UserRepo(engine)
    user = user_repo.create_user(telegram_id=5001, chat_id=5001)

    fake_creds = _make_fake_creds()
    bot = AsyncMock()

    with patch("main.Flow") as MockFlow:
        flow_instance = MagicMock()
        flow_instance.credentials = fake_creds
        MockFlow.from_client_secrets_file.return_value = flow_instance

        request = _make_request({"code": "auth_code_123", "state": str(user.telegram_id)}, engine, bot)
        response = await oauth2callback(request)

    assert response.status == 200
    assert "Success" in response.text

    updated = user_repo.get_by_telegram_id(user.telegram_id)
    assert updated.google_credentials_encrypted is not None
    saved = decrypt_json(updated.google_credentials_encrypted)
    assert saved["token"] == fake_creds.token
    assert saved["refresh_token"] == fake_creds.refresh_token


@pytest.mark.asyncio
async def test_oauth_callback_missing_code_returns_400(engine):
    from main import oauth2callback
    bot = AsyncMock()
    request = _make_request({"state": "12345"}, engine, bot)   # no code
    response = await oauth2callback(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_oauth_callback_missing_state_returns_400(engine):
    from main import oauth2callback
    bot = AsyncMock()
    request = _make_request({"code": "xyz"}, engine, bot)      # no state
    response = await oauth2callback(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_oauth_callback_non_integer_state_returns_400(engine):
    from main import oauth2callback
    bot = AsyncMock()
    request = _make_request({"code": "xyz", "state": "not_a_number"}, engine, bot)
    response = await oauth2callback(request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_oauth_callback_unknown_telegram_id_returns_404(engine):
    """State contains a valid integer but no matching user exists."""
    from main import oauth2callback
    bot = AsyncMock()

    with patch("main.Flow") as MockFlow:
        flow_instance = MagicMock()
        flow_instance.credentials = _make_fake_creds()
        MockFlow.from_client_secrets_file.return_value = flow_instance

        request = _make_request({"code": "xyz", "state": "99999"}, engine, bot)
        response = await oauth2callback(request)

    assert response.status == 404


@pytest.mark.asyncio
async def test_oauth_callback_flow_exception_returns_500(engine):
    """If the Google Flow raises, the handler returns 500 gracefully."""
    from main import oauth2callback
    from db.repository import UserRepo

    UserRepo(engine).create_user(telegram_id=5001, chat_id=5001)
    bot = AsyncMock()

    with patch("main.Flow") as MockFlow:
        MockFlow.from_client_secrets_file.side_effect = Exception("network error")

        request = _make_request({"code": "xyz", "state": "5001"}, engine, bot)
        response = await oauth2callback(request)

    assert response.status == 500


@pytest.mark.asyncio
async def test_oauth_callback_does_not_overwrite_another_users_creds(engine):
    """Only the user matching the state telegram_id gets credentials updated."""
    from main import oauth2callback
    from db.repository import UserRepo

    user_repo = UserRepo(engine)
    user_a = user_repo.create_user(telegram_id=5001, chat_id=5001)
    user_b = user_repo.create_user(telegram_id=5002, chat_id=5002)

    bot = AsyncMock()
    with patch("main.Flow") as MockFlow:
        flow_instance = MagicMock()
        flow_instance.credentials = _make_fake_creds()
        MockFlow.from_client_secrets_file.return_value = flow_instance

        # OAuth completes for user_a only
        request = _make_request({"code": "code", "state": str(user_a.telegram_id)}, engine, bot)
        await oauth2callback(request)

    assert user_repo.get_by_telegram_id(user_a.telegram_id).google_credentials_encrypted is not None
    assert user_repo.get_by_telegram_id(user_b.telegram_id).google_credentials_encrypted is None


@pytest.mark.asyncio
async def test_oauth_callback_second_login_replaces_credentials(engine):
    """A repeat OAuth flow (token refresh / re-auth) replaces old credentials."""
    from main import oauth2callback
    from db.repository import UserRepo
    from utils.security import decrypt_json

    user_repo = UserRepo(engine)
    user = user_repo.create_user(telegram_id=5001, chat_id=5001)
    bot = AsyncMock()

    async def _do_oauth(token: str):
        with patch("main.Flow") as MockFlow:
            flow_instance = MagicMock()
            flow_instance.credentials = _make_fake_creds(token=token)
            MockFlow.from_client_secrets_file.return_value = flow_instance
            req = _make_request({"code": "code", "state": str(user.telegram_id)}, engine, bot)
            await oauth2callback(req)

    await _do_oauth("first_token")
    await _do_oauth("second_token")

    saved = decrypt_json(user_repo.get_by_telegram_id(user.telegram_id).google_credentials_encrypted)
    assert saved["token"] == "second_token"


# ── get_credentials() ─────────────────────────────────────────────────────────

def test_get_credentials_with_valid_user_dict():
    """get_credentials returns immediately when passed a valid credential dict."""
    from integrations.google_auth import get_credentials

    creds_dict = {
        "token": "valid_token",
        "refresh_token": "refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid",
        "client_secret": "csecret",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }

    with patch("integrations.google_auth.Credentials") as MockCreds:
        mock_creds = MagicMock()
        mock_creds.valid = True
        MockCreds.return_value = mock_creds

        result = get_credentials(user_credentials=creds_dict)

    assert result is mock_creds
    MockCreds.assert_called_once_with(
        token=creds_dict["token"],
        refresh_token=creds_dict["refresh_token"],
        token_uri=creds_dict["token_uri"],
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=creds_dict["scopes"],
    )


def test_get_credentials_refreshes_expired_token():
    """Expired user credentials with a refresh_token are refreshed automatically."""
    from integrations.google_auth import get_credentials

    creds_dict = {"token": "old", "refresh_token": "ref", "token_uri": "u",
                  "client_id": "c", "client_secret": "s", "scopes": []}

    with patch("integrations.google_auth.Credentials") as MockCreds, \
         patch("integrations.google_auth.Request") as MockRequest:
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "ref"
        MockCreds.return_value = mock_creds

        result = get_credentials(user_credentials=creds_dict)

    mock_creds.refresh.assert_called_once()
    assert result is mock_creds


def test_get_credentials_raises_when_no_refresh_token():
    """Expired user credentials without a refresh_token raise ValueError."""
    from integrations.google_auth import get_credentials

    creds_dict = {"token": "old", "refresh_token": None, "token_uri": "u",
                  "client_id": "c", "client_secret": "s", "scopes": []}

    with patch("integrations.google_auth.Credentials") as MockCreds:
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None
        MockCreds.return_value = mock_creds

        with pytest.raises(ValueError, match="invalid or expired"):
            get_credentials(user_credentials=creds_dict)
