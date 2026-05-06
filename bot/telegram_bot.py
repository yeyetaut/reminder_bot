"""
Telegram bot — command handlers and bot startup.
"""
import logging
from datetime import date, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import config
from db.repository import TaskRepo, ProjectRepo, DailyPlanRepo
from db.models import TaskStatus
from bot.messages import morning_digest, evening_recap, weekly_overview, monthly_overview, project_list
from bot.conversations import send_proposal, confirm_estimate, adjust_hours, skip_estimate
from ai.extractor import extract_and_save
from ai.estimator import estimate_project
from integrations.google_calendar import fetch_events as fetch_gcal, delete_study_events, create_deadline_event
from integrations.gmail import fetch_emails
from integrations.ical_feeds import fetch_canvas_events

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _repos(context: ContextTypes.DEFAULT_TYPE):
    engine = context.bot_data["engine"]
    return TaskRepo(engine), ProjectRepo(engine), DailyPlanRepo(engine)


def _parse_task_ref(args, task_repo: TaskRepo):
    """Resolve a task by its stable DB id or partial title.

    /today now shows [id] instead of positional numbers so ids are stable
    even after marking other tasks done.
    """
    if not args:
        return None
    ref = " ".join(args)
    # Try as direct task ID first
    if ref.isdigit():
        task = task_repo.get_by_id(int(ref))
        if task and task.status.value == "pending":
            return task
    # Fall back to partial title match across today's visible tasks
    today = date.today()
    planned = task_repo.for_date(today)
    upcoming = task_repo.upcoming(days=7)
    planned_ids = {t.id for t in planned}
    tasks = planned + [t for t in upcoming if t.id not in planned_ids]
    ref_lower = ref.lower()
    for t in tasks:
        if ref_lower in t.title.lower():
            return t
    return None


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Reminder Bot is running\\!*\n\n"
        "Commands:\n"
        "/today — today's task list\n"
        "/projects — active projects\n"
        "/sync — fetch today's new emails\n"
        "/totalsync — full sync \\(last 14 days of emails \\+ 30 days calendar\\)\n"
        "/done <number\\|title> — mark a task complete\n"
        "/snooze <number\\|title> — push task to tomorrow\n"
        "/clear\\_study\\_session <number> — remove study sessions for a project\n"
        "/clear\\_all\\_study\\_sessions — remove all study sessions\n"
        "/weekly — weekly overview\n"
        "/monthly — monthly overview",
        parse_mode="Markdown",
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_repo, _, _ = _repos(context)
    await update.message.reply_text(morning_digest(task_repo), parse_mode="Markdown")


async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, project_repo, _ = _repos(context)
    await update.message.reply_text(project_list(project_repo), parse_mode="Markdown")


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_repo, project_repo, _ = _repos(context)
    await update.message.reply_text(weekly_overview(task_repo, project_repo), parse_mode="Markdown")


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_repo, project_repo, _ = _repos(context)
    await update.message.reply_text(monthly_overview(task_repo, project_repo), parse_mode="Markdown")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_repo, _, _ = _repos(context)
    task = _parse_task_ref(context.args, task_repo)
    if not task:
        await update.message.reply_text("Task not found\\. Use /today to see task numbers\\.", parse_mode="Markdown")
        return
    task_repo.mark_done(task.id)
    await update.message.reply_text(f"✅ Done: *{task.title}*", parse_mode="Markdown")


async def cmd_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_repo, _, _ = _repos(context)
    task = _parse_task_ref(context.args, task_repo)
    if not task:
        await update.message.reply_text("Task not found\\. Use /today to see task numbers\\.", parse_mode="Markdown")
        return
    tomorrow = date.today() + timedelta(days=1)
    task_repo.reschedule(task.id, tomorrow)
    await update.message.reply_text(f"⏭️ Snoozed to tomorrow: *{task.title}*", parse_mode="Markdown")


async def _run_sync(update, context, days_back: int, label: str):
    """Shared sync logic. days_back controls Gmail lookback window."""
    task_repo, project_repo, _ = _repos(context)
    await update.message.reply_text(f"🔄 {label}", parse_mode="Markdown")

    gcal = fetch_gcal(days_ahead=30)
    emails, gmail_error = fetch_emails(max_results=30, days_back=days_back)
    canvas = fetch_canvas_events()

    new_tasks, new_projects, ai_error = extract_and_save(
        calendar_events=gcal + canvas,
        emails=emails,
        task_repo=task_repo,
        project_repo=project_repo,
    )

    lines = [
        "✅ *Sync complete\\!*" if not ai_error else "⚠️ *Sync finished with AI issues*",
        f"• Google Calendar: {len(gcal)} events",
        f"• Canvas: {len(canvas)} events",
        f"• Gmail: {len(emails)} emails" + (" ⚠️ _error_" if gmail_error else ""),
        f"• New tasks saved: {len(new_tasks)}",
        f"• New projects: {len(new_projects)}",
    ]
    if ai_error:
        # Clean up and escape error for Telegram Markdown
        clean_err = ai_error.replace("_", "\\_").replace("*", "\\*").replace(".", "\\.").replace("[", "\\[").replace("]", "\\]")
        if "credit" in ai_error.lower() or "balance" in ai_error.lower():
            lines.append(f"\n💳 *AI Credit Issue:* Your AI provider (Anthropic/Google) reported a credit/balance issue. Error: `{clean_err}`")
        else:
            lines.append(f"\n⚠️ *AI Error:* `{clean_err}`")
    
    if gmail_error:
        short_err = gmail_error[:150].replace("_", "\\_").replace("*", "\\*").replace(".", "\\.")
        lines.append(f"⚠️ *Gmail error:* `{short_err}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # Add new non-calendar tasks to Google Calendar as deadline events
    from integrations.google_calendar import find_event_by_title
    for task in new_tasks:
        if task.source != "google_calendar" and task.due_date:
            title = f"[Deadline] {task.title}"
            if find_event_by_title(title, task.due_date.isoformat()):
                logger.info(f"Skipping deadline event creation for '{task.title}' — already exists on GCal")
                task_repo.mark_gcal_synced(task.id)
                continue

            event_id = create_deadline_event(
                title=title,
                date_str=task.due_date.isoformat(),
                description=task.description or "",
            )
            if event_id:
                task_repo.mark_gcal_synced(task.id)

    for project in new_projects:
        if task_repo.has_ai_sessions_for_title(project.title) or project_repo.is_already_planned(project.title):
            logger.info(f"Skipping proposal for '{project.title}' — already planned")
            continue
        proposal = estimate_project(project)
        if proposal:
            await send_proposal(context, update.effective_chat.id, proposal)


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Light daily sync — only today's emails \\+ calendar."""
    await _run_sync(update, context, days_back=1, label="Syncing today's emails\\.\\.\\.")


async def cmd_total_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Full sync — 14 days of emails \\+ 30 days calendar, plus backfill all Canvas tasks to Google Calendar."""
    task_repo, _, _ = _repos(context)
    await _run_sync(update, context, days_back=14, label="Syncing all sources\\.\\.\\.")
    # Backfill any existing Canvas tasks not yet written to Google Calendar
    unsynced = task_repo.unsynced_canvas_tasks()
    if unsynced:
        for task in unsynced:
            event_id = create_deadline_event(
                title=f"[Deadline] {task.title}",
                date_str=task.due_date.isoformat(),
                description=task.description or "",
            )
            if event_id:
                task_repo.mark_gcal_synced(task.id)
        await update.message.reply_text(
            f"📅 Synced {len(unsynced)} existing Canvas task{'s' if len(unsynced) != 1 else ''} to Google Calendar\\.",
            parse_mode="Markdown",
        )


async def cmd_clear_study_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete study sessions for a specific project by its list index (/projects numbering)."""
    task_repo, project_repo, _ = _repos(context)
    active = project_repo.list_active()

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /clear\\_study\\_session <number>  \\(use /projects to see numbers\\)",
            parse_mode="Markdown",
        )
        return

    idx = int(context.args[0]) - 1
    if idx < 0 or idx >= len(active):
        await update.message.reply_text(
            f"Invalid number\\. There are {len(active)} active projects\\. Use /projects to see them\\.",
            parse_mode="Markdown",
        )
        return

    project = active[idx]
    deleted = task_repo.delete_ai_sessions(project.id)
    cal_deleted = delete_study_events(project.title)
    project_repo.reset_confirmation(project.id)
    await update.message.reply_text(
        f"🗑️ Cleared {deleted} study session{'s' if deleted != 1 else ''} for *{project.title}*"
        f" and {cal_deleted} Google Calendar event{'s' if cal_deleted != 1 else ''}\\.\n"
        "Project reset to unconfirmed — run /sync or /totalsync to re\\-estimate\\.",
        parse_mode="Markdown",
    )


async def cmd_clear_all_study_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete all AI-planned study sessions across every project."""
    task_repo, project_repo, _ = _repos(context)
    deleted = task_repo.delete_all_ai_sessions()
    cal_deleted = delete_study_events()  # deletes all [Study] events
    for project in project_repo.list_all():
        project_repo.reset_confirmation(project.id)
    await update.message.reply_text(
        f"🗑️ Cleared {deleted} study session{'s' if deleted != 1 else ''} across all projects"
        f" and {cal_deleted} Google Calendar event{'s' if cal_deleted != 1 else ''}\\.\n"
        "All projects reset to unconfirmed\\.",
        parse_mode="Markdown",
    )


async def cmd_confirm_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await confirm_estimate(update, context)


async def cmd_adjust_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await adjust_hours(update, context)


async def cmd_skip_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await skip_estimate(update, context)


# ── Bot builder ───────────────────────────────────────────────────────────────

def build_bot(engine, post_init=None, post_shutdown=None) -> Application:
    builder = Application.builder().token(config.TELEGRAM_BOT_TOKEN)
    if post_init:
        builder = builder.post_init(post_init)
    if post_shutdown:
        builder = builder.post_shutdown(post_shutdown)
    app = builder.build()
    app.bot_data["engine"] = engine

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("snooze", cmd_snooze))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("totalsync", cmd_total_sync))
    app.add_handler(CommandHandler("clear_study_session", cmd_clear_study_session))
    app.add_handler(CommandHandler("clear_all_study_sessions", cmd_clear_all_study_sessions))
    app.add_handler(CommandHandler("confirm_estimate", cmd_confirm_estimate))
    app.add_handler(CommandHandler("adjust_hours", cmd_adjust_hours))
    app.add_handler(CommandHandler("skip_estimate", cmd_skip_estimate))

    logger.info("Telegram bot handlers registered")
    return app
