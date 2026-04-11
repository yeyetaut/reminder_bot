"""
Conversation handler for the AI estimate confirmation flow.

Flow:
  Bot: "New project detected: X — estimated 6h. Here's the daily plan..."
  User: /confirm_estimate  → saves tasks, writes to Google Calendar
       /adjust_hours 8     → re-runs estimator with new hours, shows updated plan
       /skip_estimate      → marks project confirmed with no daily breakdown
"""
import logging
from typing import Dict, Any

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from db.repository import TaskRepo, ProjectRepo
from db.models import Task, TaskStatus
from ai.estimator import estimate_project, format_proposal_message
from integrations.google_calendar import create_event

logger = logging.getLogger(__name__)

# ConversationHandler states
AWAITING_CONFIRMATION = 1

# Key used to store list of pending proposals in user context
PENDING_PROPOSALS_KEY = "pending_proposals"


def _get_proposals(context: ContextTypes.DEFAULT_TYPE) -> list:
    return context.bot_data.setdefault(PENDING_PROPOSALS_KEY, [])


async def send_proposal(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    proposal: Dict[str, Any],
) -> None:
    """Append a proposal to the pending list and send it to the user."""
    proposals = _get_proposals(context)
    proposals.append(proposal)
    idx = len(proposals)
    text = format_proposal_message(proposal)
    if idx > 1:
        text = f"*\\[Project {idx}\\]* " + text
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def _notify_remaining(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    proposals = _get_proposals(context)
    if not proposals:
        return
    n = len(proposals)
    names = ", ".join(f"*{p['project_title']}*" for p in proposals)
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📋 {n} more pending project{'s' if n > 1 else ''}: {names}\\.\n"
            f"Use /confirm\\_estimate, /adjust\\_hours, or /skip\\_estimate\\. "
            f"Add an index \\(1–{n}\\) to target a specific project\\."
        ),
        parse_mode="Markdown",
    )


def _resolve_proposal(context: ContextTypes.DEFAULT_TYPE, args) -> tuple:
    """Return (proposal, index, error_message). index is 0-based into the list."""
    proposals = _get_proposals(context)
    if not proposals:
        return None, -1, "No pending estimate\\. Run /sync first\\."

    # Determine which index the user wants (1-based arg, default 1)
    idx = 0
    remaining_args = list(args or [])
    if remaining_args and remaining_args[0].isdigit():
        requested = int(remaining_args.pop(0)) - 1
        if requested < 0 or requested >= len(proposals):
            return None, -1, f"Invalid project index\\. There are {len(proposals)} pending projects\\."
        idx = requested

    return proposals[idx], idx, None


async def confirm_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User accepted the AI estimate — create daily Task rows and Google Calendar events."""
    proposal, idx, err = _resolve_proposal(context, context.args)
    if err:
        await update.message.reply_text(err, parse_mode="Markdown")
        return ConversationHandler.END

    engine = context.bot_data["engine"]
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)

    project_id = proposal["project_id"]
    estimated_hours = proposal["estimated_hours"]
    sessions = proposal.get("daily_sessions", [])

    # Save daily task sessions
    from datetime import date as date_type
    tasks = []
    for session in sessions:
        session_date = date_type.fromisoformat(session["date"]) if isinstance(session["date"], str) else session["date"]
        task = Task(
            project_id=project_id,
            title=f"{proposal['project_title']} — {session['focus']}",
            description=session["focus"],
            scheduled_date=session_date,
            due_date=session_date,
            source="ai_plan",
            status=TaskStatus.pending,
        )
        tasks.append(task)

    task_repo.save_many(tasks)
    project_repo.confirm(project_id, estimated_hours)

    # Write sessions to Google Calendar
    cal_links = []
    for session in sessions:
        link = create_event(
            title=f"[Study] {proposal['project_title']}",
            date_str=session["date"],
            duration_hours=session["hours"],
            description=session["focus"],
        )
        if link:
            cal_links.append(link)

    reply = (
        f"✅ Plan confirmed for *{proposal['project_title']}*\\!\n"
        f"{len(tasks)} work sessions added to your schedule"
    )
    if cal_links:
        reply += f" and Google Calendar\\."
    else:
        reply += "\\."

    await update.message.reply_text(reply, parse_mode="Markdown")
    _get_proposals(context).pop(idx)
    await _notify_remaining(context, update.effective_chat.id)
    return ConversationHandler.END


async def adjust_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User wants to adjust the estimated hours — re-run estimator with override.

    Usage:
      /adjust_hours 8          → adjusts project #1 (oldest pending) to 8 hours
      /adjust_hours 2 8        → adjusts project #2 to 8 hours
    """
    proposals = _get_proposals(context)
    if not proposals:
        await update.message.reply_text("No pending estimate\\. Run /sync first\\.", parse_mode="Markdown")
        return ConversationHandler.END

    args = list(context.args or [])

    # If two numeric args, first is 1-based project index, second is hours
    idx = 0
    if len(args) >= 2 and args[0].isdigit() and args[1].replace(".", "").isdigit():
        idx = int(args.pop(0)) - 1
        if idx < 0 or idx >= len(proposals):
            await update.message.reply_text(f"Invalid project index\\. There are {len(proposals)} pending projects\\.", parse_mode="Markdown")
            return ConversationHandler.END

    proposal = proposals[idx]

    if not args or not args[0].replace(".", "").isdigit():
        await update.message.reply_text(
            "Usage: /adjust\\_hours <hours>  or  /adjust\\_hours <index> <hours>\n"
            "e\\.g\\. `/adjust_hours 8` or `/adjust_hours 2 8`",
            parse_mode="Markdown",
        )
        return AWAITING_CONFIRMATION

    new_hours = float(args[0])
    engine = context.bot_data["engine"]
    from sqlalchemy.orm import Session
    from db.models import Project
    with Session(engine) as s:
        project = s.get(Project, proposal["project_id"])

    if not project:
        await update.message.reply_text("Project not found\\.", parse_mode="Markdown")
        return ConversationHandler.END

    # Re-estimate with hint about desired hours
    proposal["estimated_hours"] = new_hours
    # Rebuild daily sessions to match new hour total
    from ai.estimator import estimate_project as _estimate
    new_proposal = _estimate(project)
    if new_proposal:
        # Scale sessions to match user's requested hours
        total = sum(s["hours"] for s in new_proposal.get("daily_sessions", []))
        if total > 0:
            scale = new_hours / total
            for sess in new_proposal["daily_sessions"]:
                sess["hours"] = round(sess["hours"] * scale, 1)
        new_proposal["estimated_hours"] = new_hours
        _get_proposals(context)[idx] = new_proposal
        n = len(proposals)
        prefix = f"*\\[Project {idx + 1}/{n}\\]* " if n > 1 else ""
        await update.message.reply_text(
            prefix + format_proposal_message(new_proposal), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Could not regenerate estimate\\. Try /confirm\\_estimate to accept the current plan\\.", parse_mode="Markdown")

    return AWAITING_CONFIRMATION


async def skip_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User wants to skip daily breakdown — mark project confirmed with no sessions."""
    proposal, idx, err = _resolve_proposal(context, context.args)
    if err:
        await update.message.reply_text(err, parse_mode="Markdown")
        return ConversationHandler.END

    engine = context.bot_data["engine"]
    project_repo = ProjectRepo(engine)
    project_repo.confirm(proposal["project_id"], proposal.get("estimated_hours", 0))
    _get_proposals(context).pop(idx)

    await update.message.reply_text(
        f"⏭️ Skipped planning for *{proposal['project_title']}*\\. "
        "It will still appear in your project list\\.",
        parse_mode="Markdown",
    )
    await _notify_remaining(context, update.effective_chat.id)
    return ConversationHandler.END


def build_estimate_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[],  # triggered programmatically via send_proposal
        states={
            AWAITING_CONFIRMATION: [
                CommandHandler("confirm_estimate", confirm_estimate),
                CommandHandler("adjust_hours", adjust_hours),
                CommandHandler("skip_estimate", skip_estimate),
            ]
        },
        fallbacks=[],
        persistent=False,
        name="estimate_flow",
    )
