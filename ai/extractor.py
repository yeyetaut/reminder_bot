"""
Task extractor — converts raw calendar events and emails into structured tasks.

Token strategy:
- Deduplicates by source_id BEFORE hitting the API (already-seen items skipped entirely)
- Sends only minimal fields (title, date, snippet) — never full bodies
- Batches ALL new items into a single Haiku call
- Returns parsed Task/Project objects ready to save to DB
"""
import json
import logging
from datetime import date
from typing import List, Dict, Any, Tuple

import anthropic

import config
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

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
    Save calendar events directly as tasks without AI.
    Only used when the AI call fails (e.g. no credits).
    Skips email items — too noisy without AI filtering.
    """
    saved = []
    for item in items:
        if item.get("source") == "gmail":
            continue  # skip emails without AI — too noisy
        sid = item.get("source_id", "")
        if not sid:
            continue

        end_raw = item.get("end") or item.get("start")
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
            description=(item.get("description") or "")[:200],
            due_date=due,
            scheduled_date=None,
            status=TaskStatus.pending,
        )
        task_repo.save(task)
        saved.append(task)
        logger.info(f"  [FALLBACK TASK] {task.title} (due {due})")

    logger.info(f"Fallback: saved {len(saved)} tasks from calendar events")
    return saved, []


def extract_and_save(
    calendar_events: List[Dict[str, Any]],
    emails: List[Dict[str, Any]],
    task_repo: TaskRepo,
    project_repo: ProjectRepo,
) -> Tuple[List[Task], List[Project]]:
    """
    Main entry point. Filters new items, calls AI once, saves results.
    Returns (new_tasks, new_projects).
    """
    all_items = calendar_events + emails
    new_items = _filter_new(all_items, task_repo, project_repo)

    if not new_items:
        logger.info("Extractor: no new items to process")
        return [], []

    logger.info(f"Extractor: {len(all_items)} total items → {len(new_items)} new, sending to AI")

    compact_items = [_compact(i) for i in new_items]
    prompt = EXTRACTION_PROMPT + json.dumps(compact_items, indent=2)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        logger.info(f"Extractor: used {response.usage.input_tokens} in / {response.usage.output_tokens} out tokens")
    except Exception as e:
        logger.error(f"Extractor AI call failed: {e}")
        logger.info("Falling back to direct calendar save (no AI filtering)")
        return _fallback_save(new_items, task_repo)

    # Parse AI response
    try:
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        extracted = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Extractor: failed to parse AI response: {e}\nRaw: {raw[:300]}")
        return [], []

    # Build a source_id → original item map to recover source field
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
    return new_tasks, new_projects
