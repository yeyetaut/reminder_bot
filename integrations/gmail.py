import logging
import base64
import re
from typing import List, Dict, Any

from googleapiclient.discovery import build

import config
from integrations.google_auth import get_credentials

logger = logging.getLogger(__name__)

# Only fetch emails that are likely actionable — deadlines, payments, meetings, important alerts.
# Excludes promotions, newsletters, social updates, and automated notifications.
SEARCH_QUERY = (
    "("
    "subject:(deadline OR \"due date\" OR \"due by\" OR overdue OR payment OR invoice OR \"pay by\" OR \"action required\" OR \"response required\" OR \"your response\" OR meeting OR interview OR appointment OR reminder OR urgent OR important OR submission OR \"sign up\" OR registration OR \"confirm your\" OR \"please confirm\") "
    "OR label:important"
    ") "
    "-label:promotions "
    "-label:social "
    "-label:updates "
    "-label:forums "
    "-from:noreply "
    "-from:no-reply "
    "-from:donotreply "
    "newer_than:30d"
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


def fetch_emails(max_results: int = 50) -> List[Dict[str, Any]]:
    """Return recent emails likely related to tasks or deadlines."""
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
                "body": body[:2000],  # cap body length sent to AI
            })

        return parsed

    except Exception as e:
        logger.error(f"Gmail fetch failed: {e}")
        return []
