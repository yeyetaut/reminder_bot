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
AWAITING_PROJECT_SELECTION = 2

# Keys used to store state in user context
PENDING_PROPOSALS_KEY = "pending_proposals"
PENDING_CONTEXT_KEY = "pending_context"


def _get_proposals(context: ContextTypes.DEFAULT_TYPE) -> list:
    return context.bot_data.setdefault(PENDING_PROPOSALS_KEY, [])


async def handle_context_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Triggered when a document or long text is received. Extracts text and asks for project."""
    text = ""
    if update.message.document:
        doc = update.message.document
        if not doc.file_name.lower().endswith(('.pdf', '.docx')):
            await update.message.reply_text("Please upload a PDF or Word (.docx) file.")
            return ConversationHandler.END
        
        await update.message.reply_text("Parsing document... ⏳")
        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        
        from integrations.document_parser import extract_text_from_pdf, extract_text_from_docx
        if doc.file_name.lower().endswith('.pdf'):
            text = extract_text_from_pdf(file_bytes)
        else:
            text = extract_text_from_docx(file_bytes)
    else:
        # Long text message
        text = update.message.text
        if len(text) < 100:
            # Too short to be a rubric, probably just chatting. Skip.
            return ConversationHandler.END

    if not text:
        await update.message.reply_text("Could not extract any text from that. Try copy-pasting it?")
        return ConversationHandler.END

    # Store text temporarily
    context.user_data[PENDING_CONTEXT_KEY] = text

    # List unconfirmed projects
    _, project_repo, _ = _repos(context)
    unconfirmed = project_repo.list_unconfirmed()
    
    if not unconfirmed:
        await update.message.reply_text(
            "I found some project context, but there are no pending projects to attach it to. "
            "Run /sync first to detect new projects."
        )
        return ConversationHandler.END

    lines = ["📝 *Which project is this context for?*"]
    for i, p in enumerate(unconfirmed):
        lines.append(f"{i+1}. {p.title}")
    
    lines.append("\nReply with the project number.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    return AWAITING_PROJECT_SELECTION


async def select_project_for_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """User replied with a project number. Link the context and offer to generate checklist."""
    if not update.message.text or not update.message.text.isdigit():
        await update.message.reply_text("Please enter a valid project number.")
        return AWAITING_PROJECT_SELECTION

    idx = int(update.message.text) - 1
    _, project_repo, _ = _repos(context)
    unconfirmed = project_repo.list_unconfirmed()

    if idx < 0 or idx >= len(unconfirmed):
        await update.message.reply_text(f"Invalid number. Choose 1 to {len(unconfirmed)}.")
        return AWAITING_PROJECT_SELECTION

    project = unconfirmed[idx]
    context_text = context.user_data.pop(PENDING_CONTEXT_KEY, "")
    
    # Save to DB
    from sqlalchemy import update as sa_update
    from db.models import Project
    engine = context.bot_data["engine"]
    from sqlalchemy.orm import Session
    with Session(engine) as s:
        s.execute(
            sa_update(Project)
            .where(Project.id == project.id)
            .values(context_notes=context_text)
        )
        s.commit()
    
    await update.message.reply_text(
        f"✅ Context attached to *{project.title}*!\n\n"
        "I'll use this to generate a more comprehensive checklist. "
        "Generating now... 🤖",
        parse_mode="Markdown"
    )

    # Trigger AI breakdown (Phase 3 will refine this)
    # For now, just a placeholder or call existing estimator
    proposal = estimate_project(project) # This will be updated to use context_notes in Phase 3
    if proposal:
        await send_proposal(context, update.effective_chat.id, proposal)
    
    return ConversationHandler.END


def _repos(context: ContextTypes.DEFAULT_TYPE):
    # Helper to get repos from bot_data engine
    from db.repository import TaskRepo, ProjectRepo, DailyPlanRepo
    engine = context.bot_data["engine"]
    return TaskRepo(engine), ProjectRepo(engine), DailyPlanRepo(engine)


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
    """User accepted the AI checklist — create Task rows."""
    proposal, idx, err = _resolve_proposal(context, context.args)
    if err:
        await update.message.reply_text(err, parse_mode="Markdown")
        return ConversationHandler.END

    engine = context.bot_data["engine"]
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)

    project_id = proposal["project_id"]
    sub_tasks = proposal.get("sub_tasks", [])

    # Save sub-tasks
    tasks = []
    for st in sub_tasks:
        task = Task(
            project_id=project_id,
            title=f"{proposal['project_title']} — {st['title']}",
            description=st['description'],
            scheduled_date=None,  # No rigid schedule
            due_date=None,
            source="ai_breakdown",
            status=TaskStatus.pending,
        )
        tasks.append(task)

    if tasks:
        task_repo.save_many(tasks)
    
    # Mark project as confirmed (estimated_hours is now optional/0)
    project_repo.confirm(project_id, 0)

    reply = (
        f"✅ Checklist confirmed for *{proposal['project_title']}*\\!\n"
        f"{len(tasks)} tasks added to your project breakdown\\."
    )

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
        entry_points=[
            MessageHandler(filters.Document.ALL | (filters.TEXT & ~filters.COMMAND & filters.Regex(r'^.{100,}$')), handle_context_upload)
        ],
        states={
            AWAITING_CONFIRMATION: [
                CommandHandler("confirm_estimate", confirm_estimate),
                CommandHandler("adjust_hours", adjust_hours),
                CommandHandler("skip_estimate", skip_estimate),
            ],
            AWAITING_PROJECT_SELECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_project_for_context)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END)
        ],
        persistent=False,
        name="estimate_flow",
    )
