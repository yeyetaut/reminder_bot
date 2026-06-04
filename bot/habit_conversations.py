"""
Conversation handler for the /add_habit flow.

Flow:
  /add_habit
  → Bot: "What habit do you want to track?"
  → User types title
  → Bot: inline buttons [Daily] [Weekly] [Monthly]
  → User picks frequency
  → Bot: "How many times per <period>?" + [Once] button
  → User types number or clicks [Once]
  → Bot: "✅ Added: <title> — Nx <frequency>"
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters,
)

from db.models import HabitFrequency
from db.repository import HabitRepo
from utils.format import escape_md

logger = logging.getLogger(__name__)

ASKING_TITLE = 0
ASKING_FREQUENCY = 1
ASKING_COUNT = 2

DRAFT_KEY = "habit_draft"

_FREQ_LABELS = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
}


def _get_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from db.repository import UserRepo
    import config
    engine = context.bot_data["engine"]
    user_repo = UserRepo(engine)
    telegram_id = update.effective_user.id
    user = user_repo.get_by_telegram_id(telegram_id)
    if not user:
        user = user_repo.create_user(
            telegram_id=telegram_id,
            chat_id=update.effective_chat.id,
            timezone=config.TIMEZONE,
        )
    return user


async def start_add_habit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(DRAFT_KEY, None)
    msg = "What habit do you want to track? (e.g. 'Meditate 10 minutes')"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg)
    else:
        await update.message.reply_text(msg)
    return ASKING_TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Please enter a habit title.")
        return ASKING_TITLE
    context.user_data[DRAFT_KEY] = {"title": title}
    buttons = [[
        InlineKeyboardButton("Daily", callback_data="hfreq_daily"),
        InlineKeyboardButton("Weekly", callback_data="hfreq_weekly"),
        InlineKeyboardButton("Monthly", callback_data="hfreq_monthly"),
    ]]
    await update.message.reply_text(
        f"Got it: *{escape_md(title)}*\n\nHow often?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ASKING_FREQUENCY


async def receive_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    freq_str = query.data.split("_", 1)[1]  # "daily" / "weekly" / "monthly"
    draft = context.user_data.get(DRAFT_KEY, {})
    draft["frequency"] = freq_str
    context.user_data[DRAFT_KEY] = draft
    period = _FREQ_LABELS[freq_str]
    buttons = [[InlineKeyboardButton("Once", callback_data="hcount_1")]]
    await query.edit_message_text(
        f"*{escape_md(draft['title'])}* — {freq_str}\n\n"
        f"How many times per {period}? (type a number or press Once)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ASKING_COUNT


async def receive_count_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text("Please enter a positive number (e.g. 2).")
        return ASKING_COUNT
    return await _save_habit(update, context, int(text))


async def receive_count_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    count = int(query.data.split("_")[1])
    return await _save_habit(update, context, count, query=query)


async def _save_habit(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      count: int, query=None) -> int:
    user = _get_user(update, context)
    draft = context.user_data.pop(DRAFT_KEY, {})
    title = draft.get("title", "Habit")
    freq_str = draft.get("frequency", "daily")
    frequency = HabitFrequency(freq_str)

    engine = context.bot_data["engine"]
    habit_repo = HabitRepo(engine)
    habit = habit_repo.create(user.id, title, frequency, target_count=count)

    period = _FREQ_LABELS[freq_str]
    times = "once" if count == 1 else f"{count}×"
    confirm = f"✅ Habit added: *{escape_md(title)}* — {times} per {period}"
    if query:
        await query.edit_message_text(confirm, parse_mode="Markdown")
    else:
        await update.message.reply_text(confirm, parse_mode="Markdown")
    return ConversationHandler.END


async def cancel_habit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(DRAFT_KEY, None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


def build_add_habit_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("add_habit", start_add_habit),
            CallbackQueryHandler(start_add_habit, pattern="^quick_add_habit$"),
        ],
        states={
            ASKING_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title),
            ],
            ASKING_FREQUENCY: [
                CallbackQueryHandler(receive_frequency, pattern="^hfreq_"),
            ],
            ASKING_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_count_text),
                CallbackQueryHandler(receive_count_button, pattern="^hcount_"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_habit)],
        persistent=False,
        name="add_habit_flow",
    )
