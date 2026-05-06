"""
Task extractor — converts raw calendar events and emails into structured tasks.

Token strategy:
- Deduplicates by source_id BEFORE hitting the API (already-seen items skipped entirely)
- Sends only minimal fields (title, date, snippet) — never full bodies
- Batches ALL new items into a single AI call
- Returns parsed Task/Project objects ready to save to DB

AI fallback chain: Claude Haiku → Gemini 2.0 Flash → Gemini 1.5 Flash → direct save
"""
import json
import logging
import re
from datetime import date
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple

import config
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo

logger = logging.getLogger(__name__)

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


_STUDY_PREFIX = re.compile(r'^\[study\]\s*', re.IGNORECASE)
_BOT_PREFIX = re.compile(r'^\[(Study|Deadline)\]\s*', re.IGNORECASE)


def _normalize_title(title: str) -> str:
    """Strip [study] prefix and lowercase for comparison."""
    return _STUDY_PREFIX.sub("", title.strip()).lower().strip()


def _is_duplicate_project(title: str, project_repo: ProjectRepo) -> bool:
    """Return True if an existing project has a similar title (>=72% similarity).
    Strips [study] prefixes before comparing so calendar study sessions
    don't re-trigger proposals for already-known projects.
    """
    normalized = _normalize_title(title)
    for existing in project_repo.list_all():
        ratio = SequenceMatcher(None, normalized, _normalize_title(existing.title)).ratio()
        if ratio >= 0.72:
            logger.info(f"  [DUP SKIP] '{title}' matches existing '{existing.title}' ({ratio:.2f})")
            return True
    return False


def _filter_new(
    items: List[Dict[str, Any]],
    task_repo: TaskRepo,
    project_repo: ProjectRepo,
) -> List[Dict[str, Any]]:
    """Return only items not already stored in the DB.

    Also drops any items whose title starts with '[Study]' — these are
    Google Calendar events we wrote back ourselves and must never be
    re-classified as new projects or tasks.
    """
    new_items = []
    for item in items:
        sid = item.get("source_id", "")
        if not sid:
            continue
        title = item.get("title") or ""
        if item.get("source") == "google_calendar" and _BOT_PREFIX.match(title):
            logger.debug(f"  [BOT SKIP] Ignoring own bot event: {title!r}")
            continue
        if not task_repo.exists_by_source_id(sid) and project_repo.get_by_source_id(sid) is None:
            new_items.append(item)
    return new_items


def _call_claude(prompt: str) -> str:
    """Call Claude. Raises on any error."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _call_gemini(prompt: str, model: str) -> str:
    """Call a Gemini model. Raises on any error."""
    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text.strip()


def _call_ai(prompt: str) -> Tuple[str, str]:
    """
    Try AI providers in order. Returns (raw_text, model_used).
    Includes retry logic for transient errors.
    """
    import time
    errors = []

    # 1. Claude Haiku (primary)
    if config.ANTHROPIC_API_KEY:
        for attempt in range(3):
            try:
                raw = _call_claude(prompt)
                logger.info(f"Extractor: Claude Haiku call successful (attempt {attempt+1})")
                return raw, "claude-haiku"
            except Exception as e:
                err_str = str(e)
                # If it's a credit/auth error, don't retry
                if "credit" in err_str.lower() or "api_key" in err_str.lower() or "permission" in err_str.lower():
                    errors.append(f"Claude: {err_str}")
                    break
                
                logger.warning(f"Extractor: Claude attempt {attempt+1} failed: {e}")
                errors.append(f"Claude: {err_str}")
                if attempt < 2:
                    time.sleep(2 ** attempt)  # 1s, 2s backoff
        
    # 2. Gemini (fallback)
    if config.GEMINI_API_KEY:
        for attempt in range(2):
            try:
                raw = _call_gemini(prompt, "gemini-1.5-pro")
                logger.info(f"Extractor: Gemini 1.5 Pro call successful (attempt {attempt+1})")
                return raw, "gemini-1.5-pro"
            except Exception as e:
                err_str = str(e)
                if "credit" in err_str.lower() or "api_key" in err_str.lower():
                    errors.append(f"Gemini: {err_str}")
                    break
                logger.warning(f"Extractor: Gemini attempt {attempt+1} failed: {e}")
                errors.append(f"Gemini: {err_str}")
                if attempt < 1:
                    time.sleep(1)

    raise RuntimeError(f"All AI providers failed: {'; '.join(errors)}")


def _fallback_save(
    items: List[Dict[str, Any]],
    task_repo: TaskRepo,
) -> Tuple[List[Task], List[Project]]:
    """
    Save calendar events directly as tasks without AI filtering.
    Only calendar/Canvas items (which have dates) are saved — Gmail items without
    dates are skipped to avoid noise.
    """
    saved = []
    for item in items:
        sid = item.get("source_id", "")
        if not sid:
            continue

        # Skip Gmail items with no date — they're likely noise without AI filtering
        source = item.get("source", "")
        end_raw = item.get("end") or item.get("start") or item.get("date")
        if source == "gmail" and not end_raw:
            continue

        due = None
        if end_raw:
            try:
                due = date.fromisoformat(end_raw[:10])
            except ValueError:
                pass

        task = Task(
            title=item.get("title", "Untitled"),
            source=source or "unknown",
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


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    """More robustly extract a JSON array from AI response text."""
    # First try direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try to find something that looks like [ ... ]
    import re
    match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    # Try the old markdown block splitting as a last resort
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("[") and part.endswith("]"):
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue
    
    raise ValueError("Could not find a valid JSON array in AI response")


def extract_and_save(
    calendar_events: List[Dict[str, Any]],
    emails: List[Dict[str, Any]],
    task_repo: TaskRepo,
    project_repo: ProjectRepo,
) -> Tuple[List[Task], List[Project], str | None]:
    """
    Main entry point. Filters new items, calls AI in batches, saves results.
    Returns (new_tasks, new_projects, ai_error_message).
    """
    all_items = calendar_events + emails
    new_items = _filter_new(all_items, task_repo, project_repo)

    if not new_items:
        logger.info("Extractor: no new items to process")
        return [], [], None

    logger.info(f"Extractor: {len(all_items)} total items → {len(new_items)} new, processing in batches")

    # Process in batches of 20 to avoid token limits and truncation
    BATCH_SIZE = 20
    new_tasks: List[Task] = []
    new_projects: List[Project] = []
    all_errors = []

    for i in range(0, len(new_items), BATCH_SIZE):
        batch = new_items[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(new_items) + BATCH_SIZE - 1) // BATCH_SIZE
        
        logger.info(f"Extractor: processing batch {batch_num}/{total_batches} ({len(batch)} items)")
        
        compact_items = [_compact(item) for item in batch]
        prompt = EXTRACTION_PROMPT + json.dumps(compact_items, indent=2)

        try:
            raw, model_used = _call_ai(prompt)
        except Exception as e:
            logger.error(f"Extractor: batch {batch_num} failed: {e}")
            all_errors.append(f"Batch {batch_num}: {e}")
            # Fallback for calendar/canvas items in this batch
            b_tasks, b_projects = _fallback_save(batch, task_repo)
            new_tasks.extend(b_tasks)
            new_projects.extend(b_projects)
            continue

        # Parse AI response for this batch
        try:
            extracted = _extract_json_array(raw)
        except Exception as e:
            logger.error(f"Extractor: failed to parse batch {batch_num}: {e}\nRaw: {raw[:300]}")
            all_errors.append(f"Batch {batch_num} JSON error: {e}")
            continue

        source_map = {item["source_id"]: item for item in batch}

        for entry in extracted:
            sid = entry.get("source_id", "")
            original = source_map.get(sid, {})
            if not original and sid:
                # AI might have hallucinated/truncated a source_id, try fuzzy or skip
                continue
            
            source = original.get("source", "unknown")

            due_raw = entry.get("due_date")
            due = None
            if due_raw:
                try:
                    due = date.fromisoformat(due_raw[:10])
                except ValueError:
                    pass

            if entry.get("is_project"):
                proj_title = entry.get("title", "Untitled project")
                if _is_duplicate_project(proj_title, project_repo):
                    logger.info(f"  [DUP DROP] Skipping project '{proj_title}' — already exists")
                    continue
                project = Project(
                    title=proj_title,
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

    ai_error = "; ".join(all_errors) if all_errors else None
    logger.info(f"Extractor: total saved {len(new_tasks)} tasks, {len(new_projects)} projects")
    return new_tasks, new_projects, ai_error
