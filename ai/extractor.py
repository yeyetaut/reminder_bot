"""
Task extractor — converts raw calendar events and emails into structured tasks.

Token strategy:
- Deduplicates by source_id BEFORE hitting the API (already-seen items skipped entirely)
- Sends only minimal fields (title, date, snippet) — never full bodies
- Batches ALL new items into a single Gemini Flash call
- Returns parsed Task/Project objects ready to save to DB
"""
import json
import logging
from datetime import date
from typing import List, Dict, Any, Tuple

import google.generativeai as genai

import config
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

EXTRACTION_PROMPT = """\
You are a task extraction assistant. Given a list of calendar events and emails, identify which ones contain actionable tasks or deadlines.

For each actionable item output a JSON object. Return a JSON array — nothing else.

Rules:
- Skip newsletters, promotions, job application auto-replies, and social notifications
- Only include items with a clear action (submit, pay, attend, complete, confirm, register, etc.)
- If an item is a large project (>4 hours of work), set "is_project": true
- Dates must be ISO format (YYYY-MM-DD) or null if unknown
- Keep titles short and action-oriented (start with a verb)

Output schema (array of objects):
{
  "source_id": "<original source_id>",
  "title": "<short action title>",
  "due_date": "<YYYY-MM-DD or null>",
  "is_project": <true|false>,
  "description": "<one sentence summary, max 100 chars>"
}

Items to process:
"""


def _compact(item: Dict[str, Any]) -> Dict[str, Any]:
    """Strip item down to minimal fields before sending to AI."""
    return {
        "source_id": item.get("source_id", ""),
        "title": (item.get("title") or "")[:120],
        "date": (item.get("end") or item.get("start") or item.get("date") or "")[:30],
        "snippet": (item.get("snippet") or item.get("description") or "")[:150],
        "source": item.get("source", ""),
    }


def _filter_new(
    items: List[Dict[str, Any]],
    task_repo: TaskRepo,
    project_repo: ProjectRepo,
) -> List[Dict[str, Any]]:
    """Return only items not already stored in the DB."""
    new_items = []
    for item in items:
        sid = item.get("source_id", "")
        if not sid:
            continue
        if not task_repo.exists_by_source_id(sid) and project_repo.get_by_source_id(sid) is None:
            new_items.append(item)
    return new_items


def _fallback_save(
    items: List[Dict[str, Any]],
    task_repo: TaskRepo,
) -> Tuple[List[Task], List[Project]]:
    """
    Save events/emails directly as tasks without AI.
    Only used when the AI call fails (e.g. no credits).
    Gmail items are included since the search query already filters aggressively.
    """
    saved = []
    for item in items:
        sid = item.get("source_id", "")
        if not sid:
            continue

        end_raw = item.get("end") or item.get("start") or item.get("date")
        due = None
        if end_raw:
            try:
                due = date.fromisoformat(end_raw[:10])
            except ValueError:
                pass

        task = Task(
            title=item.get("title", "Untitled"),
            source=item.get("source", "unknown"),
            source_id=sid,
            description=(item.get("snippet") or item.get("description") or "")[:200],
            due_date=due,
            scheduled_date=None,
            status=TaskStatus.pending,
        )
        task_repo.save(task)
        saved.append(task)
        logger.info(f"  [FALLBACK TASK] {task.title} (due {due})")

    logger.info(f"Fallback: saved {len(saved)} tasks")
    return saved, []


def extract_and_save(
    calendar_events: List[Dict[str, Any]],
    emails: List[Dict[str, Any]],
    task_repo: TaskRepo,
    project_repo: ProjectRepo,
) -> Tuple[List[Task], List[Project], str | None]:
    """
    Main entry point. Filters new items, calls AI once, saves results.
    Returns (new_tasks, new_projects, ai_error_message).
    ai_error_message is None on success, a string if AI call failed.
    """
    all_items = calendar_events + emails
    new_items = _filter_new(all_items, task_repo, project_repo)

    if not new_items:
        logger.info("Extractor: no new items to process")
        return [], [], None

    logger.info(f"Extractor: {len(all_items)} total items → {len(new_items)} new, sending to AI")

    compact_items = [_compact(i) for i in new_items]
    prompt = EXTRACTION_PROMPT + json.dumps(compact_items, indent=2)

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        logger.info("Extractor: Gemini call successful")
    except Exception as e:
        logger.error(f"Extractor AI call failed: {e}")
        logger.info("Falling back to direct save (no AI filtering)")
        tasks, projects = _fallback_save(new_items, task_repo)
        return tasks, projects, str(e)

    # Parse AI response
    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        extracted = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Extractor: failed to parse AI response: {e}\nRaw: {raw[:300]}")
        return [], [], f"JSON parse error: {e}"

    source_map = {i["source_id"]: i for i in new_items}

    new_tasks: List[Task] = []
    new_projects: List[Project] = []

    for entry in extracted:
        sid = entry.get("source_id", "")
        original = source_map.get(sid, {})
        source = original.get("source", "unknown")

        due_raw = entry.get("due_date")
        due = None
        if due_raw:
            try:
                due = date.fromisoformat(due_raw[:10])
            except ValueError:
                pass

        if entry.get("is_project"):
            project = Project(
                title=entry.get("title", "Untitled project"),
                source=source,
                source_id=sid,
                description=entry.get("description", ""),
                due_date=due,
                confirmed=False,
            )
            project_repo.save(project)
            new_projects.append(project)
            logger.info(f"  [PROJECT] {project.title} (due {due})")
        else:
            task = Task(
                title=entry.get("title", "Untitled task"),
                source=source,
                source_id=sid,
                description=entry.get("description", ""),
                due_date=due,
                scheduled_date=None,
                status=TaskStatus.pending,
            )
            task_repo.save(task)
            new_tasks.append(task)
            logger.info(f"  [TASK]    {task.title} (due {due})")

    logger.info(f"Extractor: saved {len(new_tasks)} tasks, {len(new_projects)} projects")
    return new_tasks, new_projects, None
