"""
Telegram bot — command handlers and bot startup.
"""
import logging
from datetime import date, timedelta
from functools import wraps

from sqlalchemy.orm import Session
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from db.repository import TaskRepo, ProjectRepo, DailyPlanRepo, HabitRepo
from db.models import TaskStatus
from bot.messages import (
    morning_digest, evening_recap, weekly_overview, monthly_overview,
    project_list, exams_overview, get_morning_digest_buttons,
    habits_section, get_habit_log_buttons,
)
from bot.conversations import send_proposal, confirm_estimate, adjust_hours, skip_estimate
from ai.extractor import extract_and_save
from ai.estimator import estimate_project
from integrations.google_calendar import fetch_events as fetch_gcal, delete_study_events, create_deadline_event
from integrations.gmail import fetch_emails
from integrations.ical_feeds import fetch_canvas_events
from utils.format import escape_md

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from db.repository import UserRepo
    engine = context.bot_data["engine"]
    user_repo = UserRepo(engine)
    telegram_id = update.effective_user.id
    user = user_repo.get_by_telegram_id(telegram_id)
    if not user:
        chat_id = update.effective_chat.id
        user = user_repo.create_user(
            telegram_id=telegram_id,
            chat_id=chat_id,
            timezone=config.TIMEZONE,
            canvas_ical_url=config.CANVAS_ICAL_URL,
        )
    return user


def require_login(func):
    """Decorator to require a user to have Google credentials set up before using a command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = _get_user(update, context)
        if not user.google_credentials_encrypted:
            msg = "⚠️ You need to connect your Google account first.\n\n👉 Please run /login to continue."
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            else:
                await update.message.reply_text(msg)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def _repos(context: ContextTypes.DEFAULT_TYPE):
    engine = context.bot_data["engine"]
    return TaskRepo(engine), ProjectRepo(engine), DailyPlanRepo(engine)


def _habit_repo(context: ContextTypes.DEFAULT_TYPE) -> HabitRepo:
    return HabitRepo(context.bot_data["engine"])


def _parse_task_ref(args, task_repo: TaskRepo, user_id: int):
    """Resolve a task by its stable DB id or partial title.

    /today now shows [id] instead of positional numbers so ids are stable
    even after marking other tasks done.
    """
    if not args:
        return None
    ref = " ".join(args)
    # Try as direct task ID first
    if ref.isdigit():
        task = task_repo.get_by_id(user_id, int(ref))
        if task and task.status.value == "pending":
            return task
    # Fall back to partial title match across today's visible tasks
    today = config.get_today()
    planned = task_repo.for_date(user_id, today)
    upcoming = task_repo.upcoming(user_id, days=7)
    planned_ids = {t.id for t in planned}
    tasks = planned + [t for t in upcoming if t.id not in planned_ids]
    ref_lower = ref.lower()
    for t in tasks:
        if ref_lower in t.title.lower():
            return t
    return None


# ── Command handlers ───────────────────────────────────────────────────────────



async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    from google_auth_oauthlib.flow import Flow
    import config

    # We must use InstalledAppFlow or Web Flow. Since we have a redirect URI, we use Flow.
    try:
        flow = Flow.from_client_secrets_file(
            config.GOOGLE_CREDENTIALS_FILE,
            scopes=[
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
            redirect_uri=f"{config.WEB_URL.rstrip('/')}/oauth2callback"
        )

        # We pass telegram_id as state
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=str(user.telegram_id)
        )

        await update.message.reply_text(
            f"🔗 <b>Connect your Google Account</b>\n\n"
            f"<a href='{authorization_url}'>Click here to authorize</a>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.exception(f"Error generating login URL: {e}")
        await update.message.reply_text(f"⚠️ Error starting login process: {e}")


async def cmd_set_anthropic_key(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = _get_user(update, context)
    if not context.args:
        await update.message.reply_text("Usage: /set_anthropic_key <your_api_key>")
        return
    key = context.args[0]
    from utils.security import encrypt_string
    encrypted = encrypt_string(key)

    engine = context.bot_data["engine"]
    from sqlalchemy.orm import Session
    from db.models import User
    with Session(engine) as s:
        db_user = s.get(User, user.id)
        db_user.anthropic_api_key_encrypted = encrypted
        s.commit()

    await update.message.reply_text("✅ Anthropic API key saved securely.")

async def cmd_set_gemini_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    if not context.args:
        await update.message.reply_text("Usage: /set_gemini_key <your_api_key>")
        return
    key = context.args[0]
    from utils.security import encrypt_string
    encrypted = encrypt_string(key)

    engine = context.bot_data["engine"]
    from sqlalchemy.orm import Session
    from db.models import User
    with Session(engine) as s:
        db_user = s.get(User, user.id)
        db_user.gemini_api_key_encrypted = encrypted
        s.commit()

    await update.message.reply_text("✅ Gemini API key saved securely.")


async def cmd_set_canvas_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    if not context.args:
        await update.message.reply_text("Usage: /set_canvas_url <your_canvas_ical_url>")
        return
    url = context.args[0]

    engine = context.bot_data["engine"]
    from sqlalchemy.orm import Session
    from db.models import User
    with Session(engine) as s:
        db_user = s.get(User, user.id)
        db_user.canvas_ical_url = url
        s.commit()

    await update.message.reply_text("✅ Canvas iCal URL saved.")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = _get_user(update, context)
    if not user.google_credentials_encrypted:
        await update.message.reply_text(
            "👋 <b>Welcome to Reminder Bot!</b>\n\n"
            "To get started, you need to connect your Google account so I can sync your calendar and emails.\n\n"
            "👉 Please run /login to continue.",
            parse_mode="HTML"
        )
        return

    hr = _habit_repo(context)
    has_habits = bool(hr.list_active(user.id))

    habit_hint = (
        "\n💡 <b>No habits set up yet.</b> Tap <b>Add a Habit</b> below to get started!"
        if not has_habits else ""
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add a Habit", callback_data="quick_add_habit"),
            InlineKeyboardButton("📋 My Habits", callback_data="quick_habits"),
        ],
        [InlineKeyboardButton("📅 Today's Plan", callback_data="quick_today")],
    ])

    await update.message.reply_text(
        "👋 <b>Reminder Bot is running!</b>\n\n"
        "<b>Core Commands:</b>\n"
        "/today — Today's digest &amp; deadlines\n"
        "/projects — Active projects overview\n"
        "/checklist — Generate an AI checklist for a project\n"
        "/exams — Upcoming exams\n\n"
        "<b>Habits:</b>\n"
        "/habits — View all habits &amp; progress\n"
        "/add_habit — Add a daily, weekly, or monthly habit\n"
        "/log_habit &lt;id&gt; — Log one completion\n"
        "/delete_habit &lt;id&gt; — Remove a habit\n\n"
        "<b>Overviews:</b>\n"
        "/weekly — Weekly summary\n"
        "/monthly — Monthly calendar\n\n"
        "<b>Settings:</b>\n"
        "/login — Connect your Google account\n"
        "/help — Setup instructions &amp; FAQ\n"
        "/set_canvas_url &lt;url&gt; — Link your Canvas iCal feed\n"
        "/set_anthropic_key &lt;key&gt; — Set your Claude API key\n"
        "/set_gemini_key &lt;key&gt; — Set your Gemini API key"
        + habit_hint,
        parse_mode="HTML",
        reply_markup=buttons,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🛠️ <b>Reminder Bot Setup Guide</b>\n\n"
        "<b>1. Gmail &amp; Google Calendar</b>\n"
        "Run /login to connect your Google account. This allows the bot to read your emails for deadlines and sync them to your calendar.\n\n"
        "<b>2. Outlook (School/Work Email)</b>\n"
        "Since university security blocks direct access, the easiest way to sync Outlook is via forwarding:\n"
        "• Open Outlook Web > Settings > Mail > Forwarding.\n"
        "• Forward to your connected Gmail address.\n"
        "• The bot will now read your Outlook deadlines through Gmail!\n\n"
        "<b>3. Canvas / Blackboard / Moodle (iCal)</b>\n"
        "You can sync your classes directly by providing a calendar feed URL:\n"
        "• <b>Canvas:</b> Calendar > Calendar Feed (bottom right).\n"
        "• <b>Blackboard:</b> Calendar > Get External Calendar Link.\n"
        "• Once you have the link (ends in .ics), run:\n"
        "  <code>/set_canvas_url &lt;your_url&gt;</code>"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands."""
    await update.message.reply_text(
        "🤔 <b>I don't recognize that command.</b>\n"
        "Please type /start to see the list of available commands.",
        parse_mode="HTML"
    )


@require_login
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, project_repo, _ = _repos(context)
    with Session(task_repo.engine) as s:
        from sqlalchemy import func, select
        from db.models import Task, Project
        task_count = s.scalar(select(func.count(Task.id)).where(Task.user_id == user.id))
        pending_count = s.scalar(select(func.count(Task.id)).where(Task.user_id == user.id, Task.status == TaskStatus.pending))
        proj_count = s.scalar(select(func.count(Project.id)).where(Project.user_id == user.id))

    google_status = "✅ Linked" if user.google_credentials_encrypted else "❌ Not Linked"
    canvas_status = f"✅ Linked (<code>{user.canvas_ical_url[:15]}...</code>)" if user.canvas_ical_url else "❌ Not Linked"
    anthropic_status = "✅ Set" if user.anthropic_api_key_encrypted else "❌ Not Set"
    gemini_status = "✅ Set" if user.gemini_api_key_encrypted else "❌ Not Set"

    await update.message.reply_text(
        f"📊 <b>User Status</b>\n\n"
        f"<b>Data Overview:</b>\n"
        f"• Total Tasks: {task_count}\n"
        f"• Pending Tasks: {pending_count}\n"
        f"• Total Projects: {proj_count}\n\n"
        f"<b>Integrations:</b>\n"
        f"• Google Account: {google_status}\n"
        f"• Canvas Feed: {canvas_status}\n"
        f"• Anthropic Key: {anthropic_status}\n"
        f"• Gemini Key: {gemini_status}\n\n"
        f"<b>Environment:</b>\n"
        f"• Timezone: <code>{user.timezone}</code>\n"
        f"• DB Host: <code>{config.DATABASE_URL.split('@')[-1].split('/')[0]}</code>",
        parse_mode="HTML"
    )


@require_login
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, project_repo, _ = _repos(context)
    hr = _habit_repo(context)
    text = morning_digest(task_repo, project_repo, user.id, habit_repo=hr)
    buttons = get_morning_digest_buttons(task_repo, project_repo, user.id, habit_repo=hr)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=buttons)


@require_login
async def handle_callback_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle clicking the 'Done' button in the digest."""
    user = _get_user(update, context)
    query = update.callback_query
    await query.answer()

    data = query.data
    logger.info(f"Callback received: {data}")
    if not data.startswith("done_"):
        return

    try:
        task_id = int(data.split("_")[1])
        task_repo, project_repo, _ = _repos(context)

        task = task_repo.get_by_id(user.id, task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for callback")
            hr = _habit_repo(context)
            new_text = morning_digest(task_repo, project_repo, user.id, habit_repo=hr)
            new_buttons = get_morning_digest_buttons(task_repo, project_repo, user.id, habit_repo=hr)
            try:
                await query.edit_message_text(new_text, parse_mode="Markdown", reply_markup=new_buttons)
            except Exception as e:
                logger.error(f"Failed to edit message for missing task: {e}")
            return

        if task.status == TaskStatus.done:
            return

        task_repo.mark_done(user.id, task_id)
        logger.info(f"Task {task_id} ('{task.title}') marked as done via callback")

        hr = _habit_repo(context)
        new_text = morning_digest(task_repo, project_repo, user.id, habit_repo=hr)
        new_buttons = get_morning_digest_buttons(task_repo, project_repo, user.id, habit_repo=hr)

        try:
            await query.edit_message_text(
                new_text,
                parse_mode="Markdown",
                reply_markup=new_buttons
            )
        except Exception as e:
            # If text is identical, Telegram raises BadRequest. We can ignore or log it.
            if "Message is not modified" in str(e):
                logger.info("Message not modified, skipping edit")
            else:
                logger.error(f"Failed to edit digest message: {e}")

        # Notify the user (escape title for Markdown)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"✅ Marked as done: *{escape_md(task.title)}*",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception(f"Error in handle_callback_done: {e}")


@require_login
async def handle_callback_snooze_opt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show snooze options for a task."""
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split("_")[-1])
    from bot.messages import get_snooze_options_buttons
    await query.edit_message_reply_markup(reply_markup=get_snooze_options_buttons(task_id))


@require_login
async def handle_callback_snooze_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply the selected snooze duration."""
    user = _get_user(update, context)
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    task_id = int(parts[2])
    days = int(parts[3])

    task_repo, project_repo, _ = _repos(context)
    task = task_repo.get_by_id(user.id, task_id)
    if not task:
        return

    new_date = config.get_today() + timedelta(days=days)
    task_repo.reschedule(user.id, task.id, new_date)

    hr = _habit_repo(context)
    new_text = morning_digest(task_repo, project_repo, user.id, habit_repo=hr)
    new_buttons = get_morning_digest_buttons(task_repo, project_repo, user.id, habit_repo=hr)

    try:
        await query.edit_message_text(new_text, parse_mode="Markdown", reply_markup=new_buttons)
    except Exception as e:
        logger.error(f"Failed to edit digest message after snooze: {e}")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"⏭️ Snoozed {days} day{'s' if days > 1 else ''}: *{escape_md(task.title)}*",
        parse_mode="Markdown"
    )


@require_login
async def handle_callback_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to the main digest buttons."""
    user = _get_user(update, context)
    query = update.callback_query
    await query.answer()

    task_repo, project_repo, _ = _repos(context)
    hr = _habit_repo(context)
    new_buttons = get_morning_digest_buttons(task_repo, project_repo, user.id, habit_repo=hr)
    await query.edit_message_reply_markup(reply_markup=new_buttons)


@require_login
async def cmd_projects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    _, project_repo, _ = _repos(context)
    await update.message.reply_text(project_list(project_repo, user.id), parse_mode="Markdown")


@require_login
async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, project_repo, _ = _repos(context)
    await update.message.reply_text(weekly_overview(task_repo, project_repo, user.id), parse_mode="Markdown")


@require_login
async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, project_repo, _ = _repos(context)
    await update.message.reply_text(monthly_overview(task_repo, project_repo, user.id), parse_mode="Markdown")


@require_login
async def cmd_exams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, _, _ = _repos(context)
    await update.message.reply_text(exams_overview(task_repo, user.id), parse_mode="Markdown")


@require_login
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, _, _ = _repos(context)
    task = _parse_task_ref(context.args, task_repo, user.id)
    if not task:
        await update.message.reply_text("Task not found\\. Use /today to see task numbers\\.", parse_mode="Markdown")
        return
    task_repo.mark_done(user.id, task.id)
    await update.message.reply_text(f"✅ Done: *{escape_md(task.title)}*", parse_mode="Markdown")


@require_login
async def cmd_snooze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    task_repo, _, _ = _repos(context)
    task = _parse_task_ref(context.args, task_repo, user.id)
    if not task:
        await update.message.reply_text("Task not found\\. Use /today to see task numbers\\.", parse_mode="Markdown")
        return
    tomorrow = config.get_today() + timedelta(days=1)
    task_repo.reschedule(user.id, task.id, tomorrow)
    await update.message.reply_text(f"⏭️ Snoozed to tomorrow: *{escape_md(task.title)}*", parse_mode="Markdown")


async def _run_sync(update, context, days_back: int, label: str, user):

    """Shared sync logic. days_back controls Gmail lookback window."""
    from db.repository import ProcessedSourceRepo
    engine = context.bot_data["engine"]
    task_repo, project_repo, _ = _repos(context)
    processed_repo = ProcessedSourceRepo(engine)
    await update.message.reply_text(f"🔄 {label}", parse_mode="Markdown")

    from utils.security import decrypt_json, decrypt_string
    google_creds = decrypt_json(user.google_credentials_encrypted) if user.google_credentials_encrypted else None

    gcal = fetch_gcal(days_ahead=30, user_credentials=google_creds)
    emails, gmail_error = fetch_emails(max_results=30, days_back=days_back, user_credentials=google_creds)
    canvas = fetch_canvas_events(canvas_url=user.canvas_ical_url)

    anthropic_key = decrypt_string(user.anthropic_api_key_encrypted) if user.anthropic_api_key_encrypted else None
    gemini_key = decrypt_string(user.gemini_api_key_encrypted) if user.gemini_api_key_encrypted else None

    new_tasks, new_projects, ai_error = extract_and_save(
        calendar_events=gcal + canvas,
        emails=emails,
        task_repo=task_repo,
        project_repo=project_repo,
        processed_repo=processed_repo,
        user_id=user.id,
        anthropic_api_key=anthropic_key,
        gemini_api_key=gemini_key,
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

    # Sync all pending non-calendar tasks to Google Calendar
    unsynced = task_repo.unsynced_tasks(user.id)
    if unsynced:
        from integrations.google_calendar import find_event_by_title
        synced_count = 0
        for task in unsynced:
            title = f"[Deadline] {task.title}"
            if find_event_by_title(title, task.due_date.isoformat(), user_credentials=google_creds):
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
                synced_count += 1
        
        if synced_count > 0:
            await update.message.reply_text(f"📅 Added {synced_count} new deadline event(s) to your Google Calendar.")

    for project in new_projects:
        # Instead of immediate AI estimation, create a reminder task to upload context
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
        await update.message.reply_text(
            f"🆕 *New Project:* {project.title}\n"
            f"I've added a task to upload a rubric/notes so I can break this down for you.",
            parse_mode="Markdown"
        )


@require_login
async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Light daily sync — only today's emails \\+ calendar."""
    user = _get_user(update, context)
    await _run_sync(update, context, days_back=1, label="Syncing today's emails\\.\\.\\.", user=user)


@require_login
async def cmd_total_sync(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Full sync — 14 days of emails \\+ 30 days calendar, plus backfill all Canvas tasks to Google Calendar."""
    task_repo, _, _ = _repos(context)
    user = _get_user(update, context)
    await _run_sync(update, context, days_back=14, label="Syncing all sources\\.\\.\\.", user=user)
    # Backfill any existing non-calendar tasks not yet written to Google Calendar
    unsynced = task_repo.unsynced_tasks(user.id)
    if unsynced:
        from utils.security import decrypt_json
        google_creds = decrypt_json(user.google_credentials_encrypted) if user.google_credentials_encrypted else None
        for task in unsynced:
            # Re-use the existing logic to check for duplicates before creating
            title = f"[Deadline] {task.title}"
            from integrations.google_calendar import find_event_by_title
            if find_event_by_title(title, task.due_date.isoformat(), user_credentials=google_creds):
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
        await update.message.reply_text(
            f"📅 Synced {len(unsynced)} existing deadline{'s' if len(unsynced) != 1 else ''} to Google Calendar\\.",
            parse_mode="Markdown",
        )


@require_login
async def cmd_clear_study_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    """Delete study sessions for a specific project by its list index (/projects numbering)."""
    task_repo, project_repo, _ = _repos(context)
    active = project_repo.list_active(user.id)

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
    
    from utils.security import decrypt_json
    google_creds = decrypt_json(user.google_credentials_encrypted) if user.google_credentials_encrypted else None
    
    deleted = task_repo.delete_ai_tasks(user.id, project.id)
    cal_deleted = delete_study_events(project.title, user_credentials=google_creds)
    project_repo.reset_confirmation(user.id, project.id)
    await update.message.reply_text(
        f"🗑️ Cleared {deleted} AI task{'s' if deleted != 1 else ''} for *{escape_md(project.title)}*"
        f" and {cal_deleted} Google Calendar event{'s' if cal_deleted != 1 else ''}\\.\n"
        "Project reset to unconfirmed — run /checklist to re\\-generate breakdown\\.",
        parse_mode="Markdown",
    )


@require_login
async def cmd_clear_all_study_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update, context)
    """Delete all AI-generated tasks across every project."""
    task_repo, project_repo, _ = _repos(context)
    from utils.security import decrypt_json
    google_creds = decrypt_json(user.google_credentials_encrypted) if user.google_credentials_encrypted else None
    
    deleted = task_repo.delete_all_ai_tasks(user.id)
    cal_deleted = delete_study_events(user_credentials=google_creds)  # deletes all [Study] events
    for project in project_repo.list_all(user.id):
        project_repo.reset_confirmation(user.id, project.id)
    await update.message.reply_text(
        f"🗑️ Cleared {deleted} AI task{'s' if deleted != 1 else ''} across all projects"
        f" and {cal_deleted} Google Calendar event{'s' if cal_deleted != 1 else ''}\\.\n"
        "All projects reset to unconfirmed\\.",
        parse_mode="Markdown",
    )


@require_login
async def cmd_confirm_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await confirm_estimate(update, context)


@require_login
async def cmd_adjust_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await adjust_hours(update, context)


@require_login
async def cmd_skip_estimate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await skip_estimate(update, context)


@require_login
async def handle_callback_quick_add_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Add a Habit' button on /start — launches the add_habit conversation."""
    from bot.habit_conversations import start_add_habit
    query = update.callback_query
    await query.answer()
    await start_add_habit(update, context)


@require_login
async def handle_callback_quick_habits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'My Habits' button on /start — shows the habits overview."""
    from telegram import InlineKeyboardMarkup
    user = _get_user(update, context)
    query = update.callback_query
    await query.answer()
    hr = _habit_repo(context)
    from bot.messages import habits_section, get_habit_log_buttons
    section = habits_section(hr, user.id)
    if not section:
        await query.message.reply_text("No habits yet\\. Use /add\\_habit to add one\\.", parse_mode="Markdown")
        return
    rows = get_habit_log_buttons(hr, user.id)
    markup = InlineKeyboardMarkup(rows) if rows else None
    await query.message.reply_text(section, parse_mode="Markdown", reply_markup=markup)


@require_login
async def handle_callback_quick_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Today's Plan' button on /start — shows the morning digest."""
    user = _get_user(update, context)
    query = update.callback_query
    await query.answer()
    task_repo, project_repo, _ = _repos(context)
    hr = _habit_repo(context)
    text = morning_digest(task_repo, project_repo, user.id, habit_repo=hr)
    buttons = get_morning_digest_buttons(task_repo, project_repo, user.id, habit_repo=hr)
    await query.message.reply_text(text, parse_mode="Markdown", reply_markup=buttons)


@require_login
async def cmd_habits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all active habits with their current period progress and Log buttons."""
    from telegram import InlineKeyboardMarkup
    user = _get_user(update, context)
    hr = _habit_repo(context)
    section = habits_section(hr, user.id)
    if not section:
        await update.message.reply_text("You have no active habits yet\\. Use /add\\_habit to add one\\.", parse_mode="Markdown")
        return
    rows = get_habit_log_buttons(hr, user.id)
    markup = InlineKeyboardMarkup(rows) if rows else None
    await update.message.reply_text(section, parse_mode="Markdown", reply_markup=markup)


@require_login
async def cmd_log_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/log_habit <id> — log one completion for the given habit."""
    user = _get_user(update, context)
    hr = _habit_repo(context)
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /log\\_habit <id>  \\(use /habits to see IDs\\)", parse_mode="Markdown")
        return
    habit_id = int(context.args[0])
    habit = hr.get_by_id(user.id, habit_id)
    if not habit:
        await update.message.reply_text("Habit not found\\.", parse_mode="Markdown")
        return
    hr.log_completion(user.id, habit_id)
    count = hr.completions_this_period(user.id, habit_id, habit.frequency)
    from bot.messages import _period_label
    period = _period_label(habit.frequency)
    if count >= habit.target_count:
        status = "✅ done"
    else:
        status = f"{count}/{habit.target_count} {period}"
    await update.message.reply_text(
        f"📝 Logged: *{escape_md(habit.title)}* — {status}", parse_mode="Markdown"
    )


@require_login
async def cmd_delete_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delete_habit <id> — deactivate a habit."""
    user = _get_user(update, context)
    hr = _habit_repo(context)
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /delete\\_habit <id>  \\(use /habits to see IDs\\)", parse_mode="Markdown")
        return
    habit_id = int(context.args[0])
    habit = hr.get_by_id(user.id, habit_id)
    if not habit:
        await update.message.reply_text("Habit not found\\.", parse_mode="Markdown")
        return
    hr.deactivate(user.id, habit_id)
    await update.message.reply_text(f"🗑️ Deleted habit: *{escape_md(habit.title)}*", parse_mode="Markdown")


@require_login
async def handle_callback_log_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log a habit completion from an inline button."""
    from telegram import InlineKeyboardMarkup
    user = _get_user(update, context)
    query = update.callback_query
    await query.answer()
    habit_id = int(query.data.split("_")[2])
    hr = _habit_repo(context)
    habit = hr.get_by_id(user.id, habit_id)
    if not habit:
        return
    hr.log_completion(user.id, habit_id)
    # Re-render the habits message in-place
    from bot.messages import _period_label, habits_section, get_habit_log_buttons
    section = habits_section(hr, user.id)
    rows = get_habit_log_buttons(hr, user.id)
    markup = InlineKeyboardMarkup(rows) if rows else None
    try:
        await query.edit_message_text(section, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Failed to edit habits message: {e}")


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
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("projects", cmd_projects))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("exams", cmd_exams))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("set_anthropic_key", cmd_set_anthropic_key))
    app.add_handler(CommandHandler("set_gemini_key", cmd_set_gemini_key))
    app.add_handler(CommandHandler("set_canvas_url", cmd_set_canvas_url))

    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("snooze", cmd_snooze))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("totalsync", cmd_total_sync))
    
    app.add_handler(CommandHandler("confirm_estimate", cmd_confirm_estimate))
    app.add_handler(CommandHandler("adjust_hours", cmd_adjust_hours))
    app.add_handler(CommandHandler("skip_estimate", cmd_skip_estimate))

    app.add_handler(CommandHandler("habits", cmd_habits))
    app.add_handler(CommandHandler("log_habit", cmd_log_habit))
    app.add_handler(CommandHandler("delete_habit", cmd_delete_habit))
    
    # Handle 'Done' buttons
    from telegram.ext import CallbackQueryHandler
    from bot.conversations import handle_callback_confirm_est, handle_callback_skip_est
    app.add_handler(CallbackQueryHandler(handle_callback_quick_habits, pattern="^quick_habits$"))
    app.add_handler(CallbackQueryHandler(handle_callback_quick_today, pattern="^quick_today$"))
    app.add_handler(CallbackQueryHandler(handle_callback_log_habit, pattern="^log_habit_"))
    app.add_handler(CallbackQueryHandler(handle_callback_done, pattern="^done_"))
    app.add_handler(CallbackQueryHandler(handle_callback_snooze_opt, pattern="^snooze_opt_"))
    app.add_handler(CallbackQueryHandler(handle_callback_snooze_apply, pattern="^snooze_apply_"))
    app.add_handler(CallbackQueryHandler(handle_callback_back, pattern="^back_to_digest$"))
    app.add_handler(CallbackQueryHandler(handle_callback_confirm_est, pattern="^confirm_est_"))
    app.add_handler(CallbackQueryHandler(handle_callback_skip_est, pattern="^skip_est_"))
    
    # Register conversation handlers AFTER explicit commands to ensure / commands have priority.
    from bot.conversations import build_estimate_conversation
    from bot.habit_conversations import build_add_habit_conversation
    app.add_handler(build_estimate_conversation())
    app.add_handler(build_add_habit_conversation())

    # Catch-all for unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    logger.info("Telegram bot handlers registered")
    return app
