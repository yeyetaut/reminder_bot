"""
Project estimator — for each unconfirmed project, uses AI to:
1. Estimate total hours required
2. Propose a daily work schedule between today and the due date

AI fallback chain: Claude Haiku → Gemini 2.0 Flash → Gemini 1.5 Flash
"""
import json
import logging
from datetime import date
from typing import Optional, Dict, Any

import config
from db.models import Project

logger = logging.getLogger(__name__)

ESTIMATION_PROMPT = """\
You are a student productivity assistant. Given a project's details, estimate the work required and suggest a daily schedule.

Project:
{project_json}

Today's date: {today}

Output a single JSON object — nothing else:
{{
  "estimated_hours": <number>,
  "reasoning": "<one sentence why>",
  "daily_sessions": [
    {{"date": "YYYY-MM-DD", "hours": <number>, "focus": "<what to work on this day>"}}
  ]
}}

Rules:
- daily_sessions must start from today or tomorrow and end on or before the due date
- No session should exceed 3 hours
- Spread work evenly, avoid the last day being the heaviest
- If due_date is null or already passed, schedule 3 sessions starting from today
"""


def _call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def _call_gemini(prompt: str, model: str) -> str:
    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text.strip()


def _call_ai(prompt: str) -> tuple[str, str]:
    """Try Claude Haiku, then Gemini 2.0 Flash, then Gemini 1.5 Flash."""
    errors = []

    if config.ANTHROPIC_API_KEY:
        try:
            raw = _call_claude(prompt)
            logger.info("Estimator: Claude Haiku call successful")
            return raw, "claude-haiku"
        except Exception as e:
            logger.warning(f"Estimator: Claude Haiku failed ({e}), trying Gemini 2.0 Flash")
            errors.append(str(e))

    if config.GEMINI_API_KEY:
        try:
            raw = _call_gemini(prompt, "gemini-1.5-pro")
            logger.info("Estimator: Gemini 1.5 Pro call successful")
            return raw, "gemini-1.5-pro"
        except Exception as e:
            logger.error(f"Estimator: Gemini 1.5 Pro failed: {e}")
            errors.append(str(e))

    raise RuntimeError(f"All AI providers failed: {'; '.join(errors)}")


def estimate_project(project: Project) -> Optional[Dict[str, Any]]:
    """
    Call AI to estimate a project. Returns the parsed proposal dict or None on failure.
    Does NOT save to DB — caller handles confirmation flow.
    """
    today = date.today().isoformat()
    project_data = {
        "title": project.title,
        "description": project.description or "",
        "due_date": project.due_date.isoformat() if project.due_date else None,
    }

    prompt = ESTIMATION_PROMPT.format(
        project_json=json.dumps(project_data, indent=2),
        today=today,
    )

    try:
        raw, model_used = _call_ai(prompt)
        logger.info(f"Estimator: '{project.title}' — {model_used} call successful")
    except Exception as e:
        logger.error(f"Estimator: all AI providers failed for '{project.title}': {e}")
        return None

    try:
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        proposal = json.loads(raw)
        proposal["project_id"] = project.id
        proposal["project_title"] = project.title
        return proposal
    except json.JSONDecodeError as e:
        logger.error(f"Estimator: failed to parse AI response: {e}\nRaw: {raw[:300]}")
        return None


def format_proposal_message(proposal: Dict[str, Any]) -> str:
    """Format an estimation proposal as a Telegram message for user confirmation."""
    lines = [
        f"*New project detected:* {proposal['project_title']}",
        f"*Estimated effort:* {proposal['estimated_hours']} hours",
        f"*Why:* {proposal.get('reasoning', '')}",
        "",
        "*Proposed daily schedule:*",
    ]
    for session in proposal.get("daily_sessions", []):
        lines.append(f"  • {session['date']} — {session['hours']}h: {session['focus']}")

    lines += [
        "",
        "Reply with:",
        "✅ /confirm\\_estimate — accept this plan",
        "✏️ /adjust\\_hours <number> — change total hours",
    ]
    return "\n".join(lines)
