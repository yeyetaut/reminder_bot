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


def delete_study_events(project_title: str | None = None) -> int:
    """Delete Google Calendar events whose title starts with '[Study] <project_title>'.

    If project_title is None, deletes ALL events starting with '[Study] '.
    Returns the number of events deleted.
    """
    try:
        service = build("calendar", "v3", credentials=get_credentials())
        now = datetime.now(timezone.utc)
        # Look back 90 days and forward 365 days to catch all study sessions
        time_min = (now - timedelta(days=90)).isoformat()
        time_max = (now + timedelta(days=365)).isoformat()

        prefix = f"[Study] {project_title}" if project_title else "[Study] "

        deleted = 0
        page_token = None
        while True:
            kwargs = dict(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                maxResults=250,
            )
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.events().list(**kwargs).execute()

            for event in result.get("items", []):
                summary = event.get("summary", "")
                if summary.startswith(prefix):
                    service.events().delete(calendarId="primary", eventId=event["id"]).execute()
                    logger.info(f"Deleted calendar event: {summary}")
                    deleted += 1

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"delete_study_events: removed {deleted} events (prefix={prefix!r})")
        return deleted

    except Exception as e:
        logger.error(f"Failed to delete study calendar events: {e}")
        return 0


def create_deadline_event(title: str, date_str: str, description: str = "") -> str | None:
    """Create an all-day calendar event for a task deadline. date_str: 'YYYY-MM-DD'."""
    try:
        service = build("calendar", "v3", credentials=get_credentials())
        event = {
            "summary": title,
            "description": description,
            "start": {"date": date_str},
            "end": {"date": date_str},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        logger.info(f"Created deadline event: {title} on {date_str}")
        return created.get("htmlLink")
    except Exception as e:
        logger.error(f"Failed to create deadline event: {e}")
        return None


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
