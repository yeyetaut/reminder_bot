import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from googleapiclient.discovery import build

import config
from integrations.google_auth import get_credentials

logger = logging.getLogger(__name__)


def fetch_events(days_ahead: int = 30) -> List[Dict[str, Any]]:
    """Return calendar events for the next `days_ahead` days."""
    try:
        service = build("calendar", "v3", credentials=get_credentials())
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days_ahead)

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )

        events = result.get("items", [])
        logger.info(f"Google Calendar: fetched {len(events)} events")

        parsed = []
        for e in events:
            start = e.get("start", {})
            end = e.get("end", {})
            parsed.append({
                "source": "google_calendar",
                "source_id": e.get("id"),
                "title": e.get("summary", "(no title)"),
                "description": e.get("description", ""),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "url": e.get("htmlLink", ""),
            })
        return parsed

    except Exception as e:
        logger.error(f"Google Calendar fetch failed: {e}")
        return []


def create_event(title: str, date_str: str, duration_hours: float = 1.0, description: str = "") -> str | None:
    """Create a calendar event. date_str format: 'YYYY-MM-DD'. Returns event URL or None."""
    try:
        service = build("calendar", "v3", credentials=get_credentials())
        start_dt = datetime.fromisoformat(f"{date_str}T09:00:00")
        end_dt = start_dt + timedelta(hours=duration_hours)

        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": config.TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": config.TIMEZONE},
        }

        created = service.events().insert(calendarId="primary", body=event).execute()
        logger.info(f"Created Google Calendar event: {title} on {date_str}")
        return created.get("htmlLink")

    except Exception as e:
        logger.error(f"Failed to create Google Calendar event: {e}")
        return None
