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

# Key used to store pending proposal in user context
PENDING_PROPOSAL_KEY = "pending_proposal"


async def send_proposal(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    proposal: Dict[str, Any],
) -> None:
    """Send an estimate proposal to the user and store it in context."""
    context.bot_data[PENDING_PROPOSAL_KEY] = proposal
    text = format_proposal_message(proposal)
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


async def confirm_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User accepted the AI estimate — create daily Task rows and Google Calendar events."""
    proposal = context.bot_data.get(PENDING_PROPOSAL_KEY)
    if not proposal:
        await update.message.reply_text("No pending estimate to confirm\\. Run /sync first\\.", parse_mode="Markdown")
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
    context.bot_data.pop(PENDING_PROPOSAL_KEY, None)
    return ConversationHandler.END


async def adjust_hours(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User wants to adjust the estimated hours — re-run estimator with override."""
    proposal = context.bot_data.get(PENDING_PROPOSAL_KEY)
    if not proposal:
        await update.message.reply_text("No pending estimate\\. Run /sync first\\.", parse_mode="Markdown")
        return ConversationHandler.END

    args = context.args
    if not args or not args[0].replace(".", "").isdigit():
        await update.message.reply_text("Usage: /adjust\\_hours <number>  e.g. `/adjust_hours 8`", parse_mode="Markdown")
        return AWAITING_CONFIRMATION

    new_hours = float(args[0])
    engine = context.bot_data["engine"]
    project_repo = ProjectRepo(engine)
    project = project_repo.get_by_source_id(None)  # fetch by id
    # Fetch project directly
    from sqlalchemy.orm import Session
    from db.models import Project
    from sqlalchemy import select
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
        context.bot_data[PENDING_PROPOSAL_KEY] = new_proposal
        await update.message.reply_text(
            format_proposal_message(new_proposal), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Could not regenerate estimate\\. Try /confirm\\_estimate to accept the current plan\\.", parse_mode="Markdown")

    return AWAITING_CONFIRMATION


async def skip_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User wants to skip daily breakdown — mark project confirmed with no sessions."""
    proposal = context.bot_data.get(PENDING_PROPOSAL_KEY)
    if not proposal:
        await update.message.reply_text("No pending estimate\\.", parse_mode="Markdown")
        return ConversationHandler.END

    engine = context.bot_data["engine"]
    project_repo = ProjectRepo(engine)
    project_repo.confirm(proposal["project_id"], proposal.get("estimated_hours", 0))
    context.bot_data.pop(PENDING_PROPOSAL_KEY, None)

    await update.message.reply_text(
        f"⏭️ Skipped planning for *{proposal['project_title']}*\\. "
        "It will still appear in your project list\\.",
        parse_mode="Markdown",
    )
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
