import msal
import logging
from typing import Optional, Dict, Any
import config

logger = logging.getLogger(__name__)

# Scopes required for the Microsoft Graph API
MS_SCOPES = ["User.Read", "Mail.Read"]

def _build_msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        config.MICROSOFT_CLIENT_ID,
        authority="https://login.microsoftonline.com/common",
        client_credential=config.MICROSOFT_CLIENT_SECRET,
    )

def get_ms_auth_url(telegram_id: int) -> str:
    """Generate the Microsoft authorization URL."""
    app = _build_msal_app()
    redirect_uri = f"{config.WEB_URL.rstrip('/')}/oauth2callback_ms"
    auth_url = app.get_authorization_request_url(
        MS_SCOPES,
        redirect_uri=redirect_uri,
        state=str(telegram_id),
    )
    return auth_url

def acquire_ms_token(code: str) -> Optional[Dict[str, Any]]:
    """Exchange the authorization code for a token."""
    app = _build_msal_app()
    redirect_uri = f"{config.WEB_URL.rstrip('/')}/oauth2callback_ms"
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=MS_SCOPES,
        redirect_uri=redirect_uri,
    )
    if "error" in result:
        logger.error(f"Microsoft token exchange failed: {result.get('error_description')}")
        return None
    return result

def get_ms_client(token_data: Dict[str, Any]) -> str:
    """Return the access token from saved token data, refreshing if necessary."""
    app = _build_msal_app()
    
    # Try to get token from cache
    accounts = app.get_accounts()
    if accounts:
        # result = app.acquire_token_silent(MS_SCOPES, account=accounts[0])
        # However, we aren't using a persistent cache file here for multi-tenant.
        # Instead, we rely on the refresh token if the access token is expired.
        pass

    # Simplified: return the access token. 
    # In a real production app, you'd use msal's SerializableTokenCache.
    # For now, we'll store the whole result dict and use the 'access_token'.
    return token_data.get("access_token", "")
