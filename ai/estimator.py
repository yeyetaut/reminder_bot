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
    import time
    errors = []

    if config.ANTHROPIC_API_KEY:
        for attempt in range(3):
            try:
                raw = _call_claude(prompt)
                logger.info(f"Estimator: Claude Haiku call successful (attempt {attempt+1})")
                return raw, "claude-haiku"
            except Exception as e:
                err_str = str(e)
                if "credit" in err_str.lower() or "api_key" in err_str.lower():
                    errors.append(f"Claude: {err_str}")
                    break
                logger.warning(f"Estimator: Claude attempt {attempt+1} failed: {e}")
                errors.append(f"Claude: {err_str}")
                if attempt < 2:
                    time.sleep(2 ** attempt)

    if config.GEMINI_API_KEY:
        for attempt in range(2):
            try:
                raw = _call_gemini(prompt, "gemini-1.5-pro")
                logger.info(f"Estimator: Gemini 1.5 Pro call successful (attempt {attempt+1})")
                return raw, "gemini-1.5-pro"
            except Exception as e:
                err_str = str(e)
                if "credit" in err_str.lower() or "api_key" in err_str.lower():
                    errors.append(f"Gemini: {err_str}")
                    break
                logger.warning(f"Estimator: Gemini attempt {attempt+1} failed: {e}")
                errors.append(f"Gemini: {err_str}")
                if attempt < 1:
                    time.sleep(1)

    raise RuntimeError(f"All AI providers failed: {'; '.join(errors)}")


def _extract_json_object(text: str) -> Dict[str, Any]:
    """More robustly extract a JSON object from AI response text."""
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    import re
    match = re.search(r'\{\s*".*\}\s*', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") and part.endswith("}"):
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue

    raise ValueError("Could not find a valid JSON object in AI response")


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
        proposal = _extract_json_object(raw)
        proposal["project_id"] = project.id
        proposal["project_title"] = project.title
        return proposal
    except Exception as e:
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
