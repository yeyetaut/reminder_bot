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
from db.repository import TaskRepo, ProjectRepo
from bot.messages import morning_digest, evening_recap, weekly_overview, monthly_overview, get_morning_digest_buttons

logger = logging.getLogger(__name__)


# ── Job functions ──────────────────────────────────────────────────────────────

async def job_morning_digest(bot, engine):
    """Send today's task list every morning."""
    try:
        task_repo = TaskRepo(engine)
        project_repo = ProjectRepo(engine)
        text = morning_digest(task_repo, project_repo)
        buttons = get_morning_digest_buttons(task_repo, project_repo)
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
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
        text = evening_recap(TaskRepo(engine))
        if text is None:
            logger.info("Evening recap: nothing to report, skipping")
            return
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Evening recap sent")
    except Exception as e:
        logger.error(f"Evening recap failed: {e}")


async def job_weekly_overview(bot, engine):
    """Send weekly overview every Friday evening."""
    try:
        text = weekly_overview(TaskRepo(engine), ProjectRepo(engine))
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Weekly overview sent")
    except Exception as e:
        logger.error(f"Weekly overview failed: {e}")


async def job_monthly_overview(bot, engine):
    """Send monthly overview on the last day of the month."""
    # Only send if today is actually the last day of the month
    today = date.today()
    last_day = cal_module.monthrange(today.year, today.month)[1]
    if today.day != last_day:
        return

    try:
        text = monthly_overview(TaskRepo(engine), ProjectRepo(engine))
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Monthly overview sent")
    except Exception as e:
        logger.error(f"Monthly overview failed: {e}")


async def job_auto_sync(bot, engine):
    """
    Daily background sync — fetches new events/emails and saves them.
    Runs before the morning digest so the task list is always fresh.
    Sends a Telegram notification only if new tasks or projects are found.
    """
    from db.repository import TaskRepo, ProjectRepo
    from integrations.google_calendar import fetch_events as fetch_gcal
    from integrations.gmail import fetch_emails
    from integrations.ical_feeds import fetch_canvas_events
    from ai.extractor import extract_and_save
    from ai.estimator import estimate_project
    from bot.conversations import send_proposal
    from telegram.ext import ContextTypes

    try:
        gcal = fetch_gcal(days_ahead=30)
        emails, _ = fetch_emails(max_results=30, days_back=1)
        canvas = fetch_canvas_events()

        task_repo = TaskRepo(engine)
        project_repo = ProjectRepo(engine)

        new_tasks, new_projects, _ = extract_and_save(
            calendar_events=gcal + canvas,
            emails=emails,
            task_repo=task_repo,
            project_repo=project_repo,
        )

        # Add new non-calendar tasks to Google Calendar as deadline events
        from integrations.google_calendar import create_deadline_event
        for task in new_tasks:
            if task.source != "google_calendar" and task.due_date:
                create_deadline_event(
                    title=f"[Deadline] {task.title}",
                    date_str=task.due_date.isoformat(),
                    description=task.description or "",
                )

        # Create reminder tasks for new projects
        from db.models import Task, TaskStatus
        for project in new_projects:
            reminder = Task(
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
                chat_id=config.TELEGRAM_CHAT_ID,
                text=(
                    f"🆕 *New Project:* {project.title}\n"
                    f"I've added a task to upload a rubric/notes so I can break this down for you. "
                    "Use /checklist to start."
                ),
                parse_mode="Markdown"
            )

        logger.info(f"Auto-sync complete: {len(new_tasks)} tasks, {len(new_projects)} projects")

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
