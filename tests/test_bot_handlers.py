import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, CallbackQuery, User, Chat, Message
from telegram.ext import ContextTypes
from bot.telegram_bot import handle_callback_done
from db.models import Task, TaskStatus
from db.repository import TaskRepo

def create_mock_update(task_id: int):
    query = AsyncMock(spec=CallbackQuery)
    query.data = f"done_{task_id}"
    query.from_user = MagicMock(spec=User)
    query.message = AsyncMock(spec=Message)
    query.message.chat = MagicMock(spec=Chat)
    query.message.chat.id = 12345
    
    update = MagicMock(spec=Update)
    update.callback_query = query
    update.effective_chat = query.message.chat
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    return update, query

def create_mock_context(engine):
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {"engine": engine}
    context.bot = AsyncMock()
    return context

@pytest.mark.asyncio
async def test_handle_callback_done_success(engine, mocker):
    repo = TaskRepo(engine)
    task = repo.save(Task(user_id=1, title="Test Task", source="test", status=TaskStatus.pending))
    
    update, query = create_mock_update(task.id)
    context = create_mock_context(engine)

    await handle_callback_done(update, context)

    query.answer.assert_called_once()
    assert repo.get_by_id(1, task.id).status == TaskStatus.done
    query.edit_message_text.assert_called_once()
    context.bot.send_message.assert_called_once()
    args, kwargs = context.bot.send_message.call_args
    assert "Marked as done" in kwargs["text"]
    assert "Test Task" in kwargs["text"]

@pytest.mark.asyncio
async def test_handle_callback_done_idempotency(engine, mocker):
    repo = TaskRepo(engine)
    task = repo.save(Task(user_id=1, title="Already Done", source="test", status=TaskStatus.done))
    
    update, query = create_mock_update(task.id)
    context = create_mock_context(engine)

    await handle_callback_done(update, context)

    query.answer.assert_called_once()
    assert repo.get_by_id(1, task.id).status == TaskStatus.done
    # Because it returns early, edit_message_text and send_message shouldn't be called
    query.edit_message_text.assert_not_called()
    context.bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_handle_callback_done_task_not_found(engine, mocker):
    update, query = create_mock_update(9999)
    context = create_mock_context(engine)
    
    await handle_callback_done(update, context)
    
    query.answer.assert_called_once()
    query.edit_message_text.assert_called_once()
    context.bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_handle_callback_done_markdown_escaping(engine, mocker):
    repo = TaskRepo(engine)
    # Title with markdown special characters
    task = repo.save(Task(user_id=1, title="Test_Task *with* `special` [chars]", source="test", status=TaskStatus.pending))
    
    update, query = create_mock_update(task.id)
    context = create_mock_context(engine)

    await handle_callback_done(update, context)

    query.answer.assert_called_once()
    context.bot.send_message.assert_called_once()
    args, kwargs = context.bot.send_message.call_args
    # Verify escaping
    expected_title = "Test\\_Task \\*with\\* \\`special\\` \\[chars\\]"
    assert expected_title in kwargs["text"]

@pytest.mark.asyncio
async def test_handle_callback_done_message_not_modified(engine, mocker):
    from telegram.error import BadRequest
    repo = TaskRepo(engine)
    task = repo.save(Task(user_id=1, title="Test Task", source="test", status=TaskStatus.pending))
    
    update, query = create_mock_update(task.id)
    # Mock edit_message_text to raise BadRequest "Message is not modified"
    query.edit_message_text.side_effect = BadRequest("Message is not modified")
    context = create_mock_context(engine)

    # Should not raise an exception
    await handle_callback_done(update, context)

    query.answer.assert_called_once()
    assert repo.get_by_id(1, task.id).status == TaskStatus.done
    # send_message should STILL be called even if edit_message_text raises that specific error
    context.bot.send_message.assert_called_once()

@pytest.mark.asyncio
async def test_handle_callback_done_other_edit_error(engine, mocker):
    from telegram.error import BadRequest
    repo = TaskRepo(engine)
    task = repo.save(Task(user_id=1, title="Test Task", source="test", status=TaskStatus.pending))
    
    update, query = create_mock_update(task.id)
    # Mock edit_message_text to raise a different BadRequest
    query.edit_message_text.side_effect = BadRequest("Some other error")
    context = create_mock_context(engine)

    # Should handle it gracefully and log it, then still send_message
    await handle_callback_done(update, context)

    query.answer.assert_called_once()
    assert repo.get_by_id(1, task.id).status == TaskStatus.done
    context.bot.send_message.assert_called_once()

@pytest.mark.asyncio
async def test_handle_callback_done_integration_with_projects(engine, mocker):
    # Test integration with both TaskRepo and ProjectRepo
    from db.repository import TaskRepo, ProjectRepo
    from db.models import Project
    task_repo = TaskRepo(engine)
    proj_repo = ProjectRepo(engine)
    
    project = proj_repo.save(Project(user_id=1, title="Test Project", source="test"))
    task = task_repo.save(Task(user_id=1, title="Proj Task", source="test", project_id=project.id, status=TaskStatus.pending))
    
    update, query = create_mock_update(task.id)
    context = create_mock_context(engine)
    
    # Run
    await handle_callback_done(update, context)
    
    # Verify integration worked seamlessly
    query.answer.assert_called_once()
    assert task_repo.get_by_id(1, task.id).status == TaskStatus.done
    query.edit_message_text.assert_called_once()
    
    args, kwargs = query.edit_message_text.call_args
    # Ensure edit_message_text uses reply_markup
    assert "reply_markup" in kwargs
    
    context.bot.send_message.assert_called_once()
