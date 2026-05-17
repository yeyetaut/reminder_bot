import logging
import requests
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

# Standard search query for academic/actionable emails
# Graph API $search syntax uses KQL (Keyword Query Language)
_MS_SEARCH_QUERY = (
    'assignment OR deadline OR "due date" OR "due by" OR submission OR '
    '"action required" OR "response required" OR payment OR invoice OR "pay by" OR '
    'appointment OR registration OR "please confirm" OR overdue OR "balance due"'
)

def fetch_outlook_emails(
    max_results: int = 30, 
    days_back: int = 14, 
    token_data: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], str | None]:
    """
    Fetch relevant emails from Outlook using Microsoft Graph API.
    Returns (emails, error_message).
    """
    if not token_data:
        return [], None

    access_token = token_data.get("access_token")
    if not access_token:
        return [], "No Microsoft access token provided"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Graph API URL with search and top parameters
    # Note: $search doesn't support combined $filter easily in some configurations, 
    # but we can filter by date range locally if needed or use receivedDateTime.
    url = "https://graph.microsoft.com/v1.0/me/messages"
    params = {
        "$search": f'"{_MS_SEARCH_QUERY}"',
        "$top": max_results,
        "$select": "id,subject,from,bodyPreview,receivedDateTime,body"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        # Handle token expiration (simplified refresh check)
        if response.status_code == 401:
            return [], "Microsoft access token expired"
            
        response.raise_for_status()
        data = response.json()
        messages = data.get("value", [])
        
        logger.info(f"Outlook: found {len(messages)} matching messages")

        parsed = []
        threshold = datetime.now() - timedelta(days=days_back)

        for msg in messages:
            # Local date filtering (Graph $search doesn't always play nice with $filter)
            received_str = msg.get("receivedDateTime", "")
            if received_str:
                received_dt = datetime.fromisoformat(received_str.replace("Z", "+00:00")).replace(tzinfo=None)
                if received_dt < threshold:
                    continue

            body_content = msg.get("body", {}).get("content", "")
            # Graph API returns HTML by default. We'll strip tags if needed, 
            # but AI can handle it. We'll truncate to save tokens.
            
            parsed.append({
                "source": "outlook",
                "source_id": msg["id"],
                "title": msg.get("subject", "(no subject)"),
                "sender": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "date": received_str,
                "snippet": msg.get("bodyPreview", ""),
                "body": body_content[:2000], # Outlook bodies can be large HTML
            })

        return parsed, None

    except Exception as e:
        logger.error(f"Outlook fetch failed: {e}")
        return [], str(e)
