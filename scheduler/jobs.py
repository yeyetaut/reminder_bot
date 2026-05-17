"""
Scheduled digest jobs — wired to APScheduler at bot startup.

All times are in the user's local timezone (config.TIMEZONE).
Jobs use the Telegram bot to send messages to config.TELEGRAM_CHAT_ID.
"""
import logging
import calendar as cal_module
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import config
from db.repository import TaskRepo, ProjectRepo, UserRepo
from bot.messages import morning_digest, evening_recap, weekly_overview, monthly_overview, get_morning_digest_buttons

logger = logging.getLogger(__name__)


# ── Job functions ──────────────────────────────────────────────────────────────

async def job_morning_digest(bot, engine):
    """Send today's task list every morning."""
    try:
        user_repo = UserRepo(engine)
        task_repo = TaskRepo(engine)
        project_repo = ProjectRepo(engine)
        for user in user_repo.get_all_users():
            text = morning_digest(task_repo, project_repo, user.id)
            buttons = get_morning_digest_buttons(task_repo, project_repo, user.id)
            await bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=buttons,
            )
        logger.info("Morning digest sent")
    except Exception as e:
        logger.error(f"Morning digest failed: {e}")


async def job_evening_recap(bot, engine):
    """Send done/skipped recap + tomorrow preview every evening (skips if nothing to report)."""
    try:
        user_repo = UserRepo(engine)
        task_repo = TaskRepo(engine)
        for user in user_repo.get_all_users():
            text = evening_recap(task_repo, user.id)
            if text is None:
                continue
            await bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
                parse_mode="Markdown",
            )
        logger.info("Evening recap sent")
    except Exception as e:
        logger.error(f"Evening recap failed: {e}")


async def job_weekly_overview(bot, engine):
    """Send weekly overview every Friday evening."""
    try:
        user_repo = UserRepo(engine)
        task_repo = TaskRepo(engine)
        project_repo = ProjectRepo(engine)
        for user in user_repo.get_all_users():
            text = weekly_overview(task_repo, project_repo, user.id)
            await bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
                parse_mode="Markdown",
            )
        logger.info("Weekly overview sent")
    except Exception as e:
        logger.error(f"Weekly overview failed: {e}")


async def job_monthly_overview(bot, engine):
    """Send monthly overview on the last day of the month."""
    today = config.get_today()
    last_day = cal_module.monthrange(today.year, today.month)[1]
    if today.day != last_day:
        return

    try:
        user_repo = UserRepo(engine)
        task_repo = TaskRepo(engine)
        project_repo = ProjectRepo(engine)
        for user in user_repo.get_all_users():
            text = monthly_overview(task_repo, project_repo, user.id)
            await bot.send_message(
                chat_id=user.telegram_chat_id,
                text=text,
                parse_mode="Markdown",
            )
        logger.info("Monthly overview sent")
    except Exception as e:
        logger.error(f"Monthly overview failed: {e}")


async def job_cleanup_tasks(bot, engine):
    """Delete old completed/skipped tasks and preserve their IDs for dedup."""
    try:
        from db.repository import TaskRepo
        user_repo = UserRepo(engine)
        task_repo = TaskRepo(engine)
        for user in user_repo.get_all_users():
            deleted_count = task_repo.cleanup_old_tasks(user.id, config.RETENTION_DAYS)
            if deleted_count > 0:
                logger.info(f"Cleanup for user {user.id}: removed {deleted_count} old tasks")
    except Exception as e:
        logger.error(f"Cleanup job failed: {e}")


async def job_auto_sync(bot, engine):
    """
    Daily background sync — fetches new events/emails and saves them.
    Runs before the morning digest so the task list is always fresh.
    Sends a Telegram notification only if new tasks or projects are found.
    """
    from db.repository import TaskRepo, ProjectRepo, ProcessedSourceRepo, UserRepo
    from integrations.google_calendar import fetch_events as fetch_gcal, create_deadline_event, find_event_by_title
    from integrations.gmail import fetch_emails
    from integrations.ical_feeds import fetch_canvas_events
    from ai.extractor import extract_and_save
    from telegram.ext import ContextTypes
    from utils.security import decrypt_json, decrypt_string

    try:
        user_repo = UserRepo(engine)
        for user in user_repo.get_all_users():
            google_creds = decrypt_json(user.google_credentials_encrypted) if user.google_credentials_encrypted else None
            anthropic_key = decrypt_string(user.anthropic_api_key_encrypted) if user.anthropic_api_key_encrypted else None
            gemini_key = decrypt_string(user.gemini_api_key_encrypted) if user.gemini_api_key_encrypted else None

            gcal = fetch_gcal(days_ahead=30, user_credentials=google_creds)
            emails, _ = fetch_emails(max_results=30, days_back=1, user_credentials=google_creds)
            canvas = fetch_canvas_events(canvas_url=user.canvas_ical_url)

            task_repo = TaskRepo(engine)
            project_repo = ProjectRepo(engine)
            processed_repo = ProcessedSourceRepo(engine)

            new_tasks, new_projects, _ = extract_and_save(
                calendar_events=gcal + canvas,
                emails=emails,
                task_repo=task_repo,
                project_repo=project_repo,
                processed_repo=processed_repo,
                user_id=user.id,
                anthropic_api_key=anthropic_key,
                gemini_api_key=gemini_key,
            )

            # Sync all pending non-calendar tasks to Google Calendar
            unsynced = task_repo.unsynced_tasks(user.id)
            if unsynced:
                for task in unsynced:
                    title = f"[Deadline] {task.title}"
                    if find_event_by_title(title, task.due_date.isoformat(), user_credentials=google_creds):
                        logger.info(f"Skipping deadline event creation for '{task.title}' — already exists on GCal")
                        task_repo.mark_gcal_synced(user.id, task.id)
                        continue

                    event_id = create_deadline_event(
                        title=title,
                        date_str=task.due_date.isoformat(),
                        description=task.description or "",
                        user_credentials=google_creds,
                    )
                    if event_id:
                        task_repo.mark_gcal_synced(user.id, task.id)

            # Create reminder tasks for new projects
            from db.models import Task, TaskStatus
            for project in new_projects:
                reminder = Task(
                    user_id=user.id,
                    project_id=project.id,
                    title=f"Upload context/rubric for {project.title}",
                    description=f"Send a PDF or notes to the bot to generate a checklist for this project.",
                    due_date=project.due_date,
                    source="reminder",
                    status=TaskStatus.pending,
                )
                task_repo.save(reminder)
                # Notify user about new project and the need for rubric
                await bot.send_message(
                    chat_id=user.telegram_chat_id,
                    text=(
                        f"🆕 *New Project:* {project.title}\n"
                        f"I've added a task to upload a rubric/notes so I can break this down for you. "
                        "Use /checklist to start."
                    ),
                    parse_mode="Markdown"
                )

            logger.info(f"Auto-sync complete for user {user.id}: {len(new_tasks)} tasks, {len(new_projects)} projects")

    except Exception as e:
        logger.error(f"Auto-sync failed: {e}")


# ── Scheduler builder ──────────────────────────────────────────────────────────

def build_scheduler(bot, engine) -> AsyncIOScheduler:
    """Create and configure the APScheduler with all jobs."""
    tz = pytz.timezone(config.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    # Auto-sync at 7:00 AM daily (runs before morning digest)
    scheduler.add_job(
        job_auto_sync,
        CronTrigger(hour=7, minute=0, timezone=tz),
        args=[bot, engine],
        id="auto_sync",
        name="Daily auto-sync",
        replace_existing=True,
    )

    # Cleanup job at 3:00 AM daily
    scheduler.add_job(
        job_cleanup_tasks,
        CronTrigger(hour=3, minute=0, timezone=tz),
        args=[bot, engine],
        id="cleanup_tasks",
        name="Daily task cleanup",
        replace_existing=True,
    )

    # Morning digest at 7:30 AM daily
    scheduler.add_job(
        job_morning_digest,
        CronTrigger(hour=7, minute=30, timezone=tz),
        args=[bot, engine],
        id="morning_digest",
        name="Morning digest",
        replace_existing=True,
    )

    # Evening recap at 9:00 PM daily
    scheduler.add_job(
        job_evening_recap,
        CronTrigger(hour=21, minute=0, timezone=tz),
        args=[bot, engine],
        id="evening_recap",
        name="Evening recap",
        replace_existing=True,
    )

    # Weekly overview every Friday at 9:00 PM
    scheduler.add_job(
        job_weekly_overview,
        CronTrigger(day_of_week="fri", hour=21, minute=0, timezone=tz),
        args=[bot, engine],
        id="weekly_overview",
        name="Weekly overview",
        replace_existing=True,
    )

    # Monthly overview check daily at 9:30 PM (the job itself checks if it's the last day)
    scheduler.add_job(
        job_monthly_overview,
        CronTrigger(hour=21, minute=30, timezone=tz),
        args=[bot, engine],
        id="monthly_overview",
        name="Monthly overview",
        replace_existing=True,
    )

    logger.info(
        f"Scheduler configured (timezone: {config.TIMEZONE}) — "
        "sync@7:00, morning@7:30, evening@21:00, weekly@Fri 21:00, monthly@last-day 21:30"
    )
    return scheduler
