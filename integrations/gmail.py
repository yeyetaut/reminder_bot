import logging
import base64
from typing import List, Dict, Any, Tuple

from googleapiclient.discovery import build

import config
from integrations.google_auth import get_credentials

logger = logging.getLogger(__name__)

# Search body + subject — no "subject:" prefix so Gmail searches everywhere.
# Catches deadlines/payments buried in email bodies, not just headers.
SEARCH_QUERY = (
    "("
    "assignment OR deadline OR \"due date\" OR \"due by\" OR submission OR "
    "\"action required\" OR \"response required\" OR payment OR invoice OR \"pay by\" OR "
    "appointment OR registration OR \"please confirm\" OR "
    "overdue OR \"balance due\""
    ") "
    "-label:promotions "
    "-label:social "
    "-label:updates "
    "-subject:\"thank you for applying\" "
    "-subject:\"application received\" "
    "-subject:\"build failed\" "
    "-subject:\"deployment\" "
    "-subject:\"order confirmation\" "
    "newer_than:14d"
)


def _decode_body(payload: Dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    body = ""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    elif "parts" in payload:
        for part in payload["parts"]:
            body += _decode_body(part)
    return body


def fetch_emails(max_results: int = 30) -> Tuple[List[Dict[str, Any]], str | None]:
    """
    Return (emails, error_message).
    error_message is None on success, a string describing the failure otherwise.
    """
    try:
        service = build("gmail", "v1", credentials=get_credentials())

        results = service.users().messages().list(
            userId="me",
            q=SEARCH_QUERY,
            maxResults=max_results,
        ).execute()

        messages = results.get("messages", [])
        logger.info(f"Gmail: found {len(messages)} matching messages")

        parsed = []
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full",
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "")
            date_str = headers.get("Date", "")
            snippet = msg.get("snippet", "")
            body = _decode_body(msg.get("payload", {}))

            parsed.append({
                "source": "gmail",
                "source_id": msg["id"],
                "title": subject,
                "sender": sender,
                "date": date_str,
                "snippet": snippet,
                "body": body[:1500],
            })

        return parsed, None

    except Exception as e:
        logger.error(f"Gmail fetch failed: {e}")
        return [], str(e)
