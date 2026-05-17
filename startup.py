"""
Railway startup helper.
Decodes base64 Google credential env vars back into files before the bot starts.
On local dev these env vars are absent and the files already exist, so this is a no-op.
"""
import os
import base64
import logging

import config

logger = logging.getLogger(__name__)


def prepare_google_credentials():
    """Write credentials.json and token.json from env vars if present."""
    creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
    token_b64 = os.getenv("GOOGLE_TOKEN_B64")

    if creds_b64:
        creds_b64 = creds_b64.strip()
        if creds_b64.startswith("{"):
            with open(config.GOOGLE_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
                f.write(creds_b64)
            logger.info("Wrote credentials.json from raw JSON in GOOGLE_CREDENTIALS_B64")
        else:
            with open(config.GOOGLE_CREDENTIALS_FILE, "wb") as f:
                f.write(base64.b64decode(creds_b64))
            logger.info("Wrote credentials.json from base64 in GOOGLE_CREDENTIALS_B64")

    if token_b64:
        token_b64 = token_b64.strip()
        if token_b64.startswith("{"):
            with open(config.GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(token_b64)
            logger.info("Wrote token.json from raw JSON in GOOGLE_TOKEN_B64")
        else:
            with open(config.GOOGLE_TOKEN_FILE, "wb") as f:
                f.write(base64.b64decode(token_b64))
            logger.info("Wrote token.json from base64 in GOOGLE_TOKEN_B64")
