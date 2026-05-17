import logging
from datetime import datetime, date, timezone
from typing import List, Dict, Any

import requests
from icalendar import Calendar

import config

logger = logging.getLogger(__name__)


def _parse_dt(value) -> str | None:
    """Normalize icalendar date/datetime values to ISO string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fetch_ical(url: str, source_name: str) -> List[Dict[str, Any]]:
    """Fetch and parse an iCal URL into a list of event dicts."""
    if not url:
        logger.info(f"{source_name}: no URL configured, skipping")
        return []

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        cal = Calendar.from_ical(resp.content)

        events = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            uid = str(component.get("UID", ""))
            summary = str(component.get("SUMMARY", "(no title)"))
            description = str(component.get("DESCRIPTION", ""))
            def _get_dt(field):
                val = component.get(field)
                return _parse_dt(val.dt) if val else None

            dtstart = _get_dt("DTSTART")
            dtend = _get_dt("DTEND")
            due = _get_dt("DUE")
            url_field = str(component.get("URL", ""))

            # Use the most specific date available as the deadline
            end = dtend or due or dtstart

            # Optimization: skip events that are already overdue
            if end:
                try:
                    end_date = date.fromisoformat(end[:10])
                    if end_date < config.get_today():
                        continue
                except (ValueError, TypeError):
                    pass

            events.append({
                "source": source_name,
                "source_id": f"{source_name}::{uid}",
                "title": summary,
                "description": description,
                "start": dtstart,
                "end": end,
                "url": url_field,
            })

        logger.info(f"{source_name}: fetched {len(events)} events")
        return events

    except requests.RequestException as e:
        logger.error(f"{source_name}: HTTP error — {e}")
        return []
    except Exception as e:
        logger.error(f"{source_name}: parse error — {e}")
        return []


def fetch_canvas_events(canvas_url: str | None = None) -> List[Dict[str, Any]]:
    if not canvas_url:
        return []
    return _fetch_ical(canvas_url, "canvas")
