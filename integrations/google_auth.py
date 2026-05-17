"""Shared Google OAuth helper — single token covers Calendar + Gmail."""
import os
import json
import logging
from typing import Optional, Dict, Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_credentials(user_credentials: Optional[Dict[str, Any]] = None) -> Credentials:
    """Return valid Google credentials, refreshing or re-authorizing as needed.
    If user_credentials is provided, use those. Otherwise, fall back to global token.json."""
    creds = None

    if user_credentials:
        creds = Credentials(
            token=user_credentials.get('token'),
            refresh_token=user_credentials.get('refresh_token'),
            token_uri=user_credentials.get('token_uri'),
            client_id=user_credentials.get('client_id'),
            client_secret=user_credentials.get('client_secret'),
            scopes=user_credentials.get('scopes')
        )
    else:
        token_path = config.GOOGLE_TOKEN_FILE
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if not user_credentials:
            # Save global token if it was refreshed
            token_path = config.GOOGLE_TOKEN_FILE
            with open(token_path, "w") as f:
                f.write(creds.to_json())
    elif not user_credentials:
        # Only do local flow for global fallback
        flow = InstalledAppFlow.from_client_secrets_file(
            config.GOOGLE_CREDENTIALS_FILE, SCOPES
        )
        creds = flow.run_local_server(port=0)
        token_path = config.GOOGLE_TOKEN_FILE
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    else:
        raise ValueError("User credentials are invalid or expired without a refresh token.")

    return creds
