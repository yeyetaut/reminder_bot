import asyncio
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, CallbackQuery, Chat, Message
from telegram.ext import ContextTypes
import config
from bot.telegram_bot import handle_callback_done
from db.repository import TaskRepo, ProjectRepo
from db.models import init_db, Task, TaskStatus

async def main():
    engine = init_db("sqlite:///:memory:")
    task_repo = TaskRepo(engine)
    task_repo.run_migrations()
    project_repo = ProjectRepo(engine)
    
    # Add a task
    task = Task(title="Homework", due_date=config.get_today(), status=TaskStatus.pending, source="google_calendar")
    task_repo.save(task)
    
    update = MagicMock(spec=Update)
    query = AsyncMock(spec=CallbackQuery)
    query.data = f"done_{task.id}"
    update.callback_query = query
    
    chat = MagicMock(spec=Chat)
    chat.id = 12345
    update.effective_chat = chat
    
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {"engine": engine}
    context.bot.send_message = AsyncMock()
    
    await handle_callback_done(update, context)
    
    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once()
    context.bot.send_message.assert_called_once()
    print("Success")

if __name__ == "__main__":
    asyncio.run(main())
