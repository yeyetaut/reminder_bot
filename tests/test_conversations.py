import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, Message, User, Chat, Document, File
from telegram.ext import ContextTypes, ConversationHandler
from sqlalchemy.orm import Session
from sqlalchemy import select

from bot.conversations import (
    start_checklist_flow,
    select_project,
    handle_file_upload,
    cancel_flow,
    confirm_estimate,
    adjust_hours,
    skip_estimate,
    AWAITING_PROJECT_SELECTION,
    AWAITING_FILE_UPLOAD,
    AWAITING_CONFIRMATION,
    SELECTED_PROJECT_KEY,
    PENDING_PROPOSALS_KEY,
)
from db.models import Project, Task, TaskStatus
from db.repository import ProjectRepo, TaskRepo

def create_mock_update(text=None, document=None, args=None):
    update = MagicMock(spec=Update)
    message = AsyncMock(spec=Message)
    message.text = text
    message.document = document
    message.chat = MagicMock(spec=Chat)
    message.chat.id = 12345
    update.message = message
    update.effective_chat = message.chat
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    return update

def create_mock_context(engine, args=None, user_data=None, bot_data=None):
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = bot_data if bot_data is not None else {"engine": engine}
    context.user_data = user_data if user_data is not None else {}
    context.args = args if args is not None else []
    context.bot = AsyncMock()
    return context

@pytest.fixture
def unconfirmed_project(engine, authenticated_user):
    repo = ProjectRepo(engine)
    task_repo = TaskRepo(engine)
    project = repo.save(Project(user_id=1, title="Pending Project", source="test", confirmed=False))
    task_repo.save(Task(user_id=1, project_id=project.id, title="Upload rubric", source="reminder", status=TaskStatus.pending))
    return project

@pytest.fixture
def confirmed_project(engine, authenticated_user):
    repo = ProjectRepo(engine)
    return repo.save(Project(user_id=1, title="Confirmed Project", source="test", confirmed=True))

@pytest.mark.asyncio
async def test_start_checklist_flow_no_projects(engine, authenticated_user):
    update = create_mock_update()
    context = create_mock_context(engine)
    
    result = await start_checklist_flow(update, context)
    assert result == ConversationHandler.END
    update.message.reply_text.assert_called_once()
    assert "no pending projects" in update.message.reply_text.call_args[0][0].lower()

@pytest.mark.asyncio
async def test_start_checklist_flow_with_projects(engine, unconfirmed_project):
    update = create_mock_update()
    context = create_mock_context(engine)
    
    result = await start_checklist_flow(update, context)
    assert result == AWAITING_PROJECT_SELECTION
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "Pending Project" in call_text
    assert "1." in call_text

@pytest.mark.asyncio
async def test_select_project_invalid_input(engine, unconfirmed_project):
    update = create_mock_update(text="not a number")
    context = create_mock_context(engine)
    
    result = await select_project(update, context)
    assert result == AWAITING_PROJECT_SELECTION
    update.message.reply_text.assert_called_once()
    assert "valid project number" in update.message.reply_text.call_args[0][0].lower()

@pytest.mark.asyncio
async def test_select_project_out_of_bounds(engine, unconfirmed_project):
    update = create_mock_update(text="2")
    context = create_mock_context(engine)
    
    result = await select_project(update, context)
    assert result == AWAITING_PROJECT_SELECTION
    update.message.reply_text.assert_called_once()
    assert "invalid number" in update.message.reply_text.call_args[0][0].lower()

@pytest.mark.asyncio
async def test_select_project_valid(engine, unconfirmed_project):
    update = create_mock_update(text="1")
    context = create_mock_context(engine)
    
    result = await select_project(update, context)
    assert result == AWAITING_FILE_UPLOAD
    assert context.user_data[SELECTED_PROJECT_KEY] == unconfirmed_project.id
    update.message.reply_text.assert_called_once()
    assert "Selected: *Pending Project*" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_cancel_flow(engine, authenticated_user):
    update = create_mock_update()
    context = create_mock_context(engine)
    
    result = await cancel_flow(update, context)
    assert result == ConversationHandler.END
    update.message.reply_text.assert_called_once_with("Cancelled.")

@pytest.mark.asyncio
@patch('bot.conversations.estimate_project')
async def test_handle_file_upload_skip(mock_estimate, engine, unconfirmed_project):
    update = create_mock_update(text="skip")
    context = create_mock_context(engine, user_data={SELECTED_PROJECT_KEY: unconfirmed_project.id})
    
    mock_estimate.return_value = {
        "project_id": unconfirmed_project.id,
        "project_title": "Pending Project",
        "estimated_hours": 2.0,
        "sub_tasks": [{"title": "Task 1", "description": "Desc 1"}],
        "daily_sessions": []
    }
    
    result = await handle_file_upload(update, context)
    
    assert result == AWAITING_CONFIRMATION
    mock_estimate.assert_called_once()
    context.bot.send_message.assert_called_once()
    
    assert len(context.bot_data[PENDING_PROPOSALS_KEY]) == 1
    assert context.bot_data[PENDING_PROPOSALS_KEY][0]["project_id"] == unconfirmed_project.id

@pytest.mark.asyncio
async def test_handle_file_upload_invalid_doc(engine, unconfirmed_project):
    doc = MagicMock(spec=Document)
    doc.file_name = "image.png"
    update = create_mock_update(document=doc)
    context = create_mock_context(engine, user_data={SELECTED_PROJECT_KEY: unconfirmed_project.id})
    
    result = await handle_file_upload(update, context)
    
    assert result == AWAITING_FILE_UPLOAD
    update.message.reply_text.assert_called_once()
    assert "PDF or Word" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
@patch('bot.conversations.estimate_project')
@patch('integrations.document_parser.extract_text_from_pdf')
async def test_handle_file_upload_pdf_success(mock_extract, mock_estimate, engine, unconfirmed_project):
    doc = MagicMock(spec=Document)
    doc.file_name = "instructions.pdf"
    doc.file_id = "123"
    update = create_mock_update(document=doc)
    context = create_mock_context(engine, user_data={SELECTED_PROJECT_KEY: unconfirmed_project.id})
    
    mock_file = AsyncMock(spec=File)
    mock_file.download_as_bytearray.return_value = bytearray(b"pdf content")
    context.bot.get_file.return_value = mock_file
    
    mock_extract.return_value = "Extracted PDF text"
    mock_estimate.return_value = {
        "project_id": unconfirmed_project.id,
        "project_title": "Pending Project",
        "estimated_hours": 3.0,
        "sub_tasks": [],
        "daily_sessions": []
    }
    
    result = await handle_file_upload(update, context)
    
    assert result == AWAITING_CONFIRMATION
    mock_extract.assert_called_once()
    mock_estimate.assert_called_once()
    
    with Session(engine) as s:
        proj = s.get(Project, unconfirmed_project.id)
        assert proj.context_notes == "Extracted PDF text"

@pytest.mark.asyncio
@patch('bot.conversations.estimate_project')
@patch('integrations.document_parser.extract_text_from_pdf')
async def test_handle_file_upload_extraction_failure(mock_extract, mock_estimate, engine, unconfirmed_project):
    doc = MagicMock(spec=Document)
    doc.file_name = "instructions.pdf"
    doc.file_id = "123"
    update = create_mock_update(document=doc)
    context = create_mock_context(engine, user_data={SELECTED_PROJECT_KEY: unconfirmed_project.id})
    
    mock_file = AsyncMock(spec=File)
    mock_file.download_as_bytearray.return_value = bytearray(b"pdf content")
    context.bot.get_file.return_value = mock_file
    
    mock_extract.return_value = ""  # Failed extraction
    
    result = await handle_file_upload(update, context)
    
    assert result == AWAITING_FILE_UPLOAD
    update.message.reply_text.assert_any_call("Could not extract text. Please try copy-pasting it or type 'skip'.")
    mock_estimate.assert_not_called()

@pytest.mark.asyncio
@patch('bot.conversations.estimate_project')
async def test_handle_file_upload_estimate_failure(mock_estimate, engine, unconfirmed_project):
    update = create_mock_update(text="skip")
    context = create_mock_context(engine, user_data={SELECTED_PROJECT_KEY: unconfirmed_project.id})
    
    mock_estimate.return_value = None
    
    result = await handle_file_upload(update, context)
    
    assert result == AWAITING_CONFIRMATION
    update.message.reply_text.assert_any_call("Failed to generate checklist. Please try again later.")

@pytest.fixture
def pending_proposal(unconfirmed_project):
    return {
        "project_id": unconfirmed_project.id,
        "project_title": unconfirmed_project.title,
        "estimated_hours": 5.0,
        "sub_tasks": [{"title": "Sub 1", "description": "Desc 1"}, {"title": "Sub 2", "description": "Desc 2"}],
        "daily_sessions": [{"date": "2023-10-01", "hours": 2.5, "focus": "Part 1"}, {"date": "2023-10-02", "hours": 2.5, "focus": "Part 2"}]
    }

@pytest.mark.asyncio
async def test_confirm_estimate_no_proposals(engine, authenticated_user):
    update = create_mock_update()
    context = create_mock_context(engine, bot_data={"engine": engine, PENDING_PROPOSALS_KEY: []})
    
    result = await confirm_estimate(update, context)
    
    assert result == ConversationHandler.END
    update.message.reply_text.assert_called_once()
    assert "No pending estimate" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_confirm_estimate_success(engine, pending_proposal):
    update = create_mock_update()
    context = create_mock_context(engine, bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal]})
    
    result = await confirm_estimate(update, context)
    
    assert result == ConversationHandler.END
    update.message.reply_text.assert_called_once()
    assert "Checklist confirmed" in update.message.reply_text.call_args[0][0]
    
    with Session(engine) as s:
        project = s.get(Project, pending_proposal["project_id"])
        assert project.confirmed is True
    
    task_repo = TaskRepo(engine)
    tasks = task_repo.list_active() if hasattr(task_repo, 'list_active') else [] # actually let's query tasks manually
    with Session(engine) as s:
        tasks = list(s.scalars(select(Task).where(Task.project_id == pending_proposal["project_id"])))
        assert len(tasks) == 3
    
    assert len(context.bot_data[PENDING_PROPOSALS_KEY]) == 0

@pytest.mark.asyncio
async def test_confirm_estimate_with_index(engine, pending_proposal, unconfirmed_project):
    prop2 = dict(pending_proposal)
    prop2["project_id"] = 999
    
    update = create_mock_update()
    context = create_mock_context(engine, args=["2"], bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal, prop2]})
    
    result = await confirm_estimate(update, context)
    
    assert result == ConversationHandler.END
    assert len(context.bot_data[PENDING_PROPOSALS_KEY]) == 1
    assert context.bot_data[PENDING_PROPOSALS_KEY][0]["project_id"] == unconfirmed_project.id

@pytest.mark.asyncio
async def test_adjust_hours_invalid_usage(engine, pending_proposal):
    update = create_mock_update()
    context = create_mock_context(engine, args=["not_a_number"], bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal]})
    
    result = await adjust_hours(update, context)
    
    assert result == AWAITING_CONFIRMATION
    update.message.reply_text.assert_called_once()
    assert "Usage: /adjust\\_hours" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
@patch('ai.estimator.estimate_project')
async def test_adjust_hours_success(mock_estimate, engine, pending_proposal, unconfirmed_project):
    update = create_mock_update()
    context = create_mock_context(engine, args=["10"], bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal]})
    
    new_proposal = dict(pending_proposal)
    new_proposal["estimated_hours"] = 10.0
    new_proposal["daily_sessions"] = [
        {"date": "2023-10-01", "hours": 5.0, "focus": "Part 1"}, 
        {"date": "2023-10-02", "hours": 5.0, "focus": "Part 2"}
    ]
    mock_estimate.return_value = new_proposal
    
    result = await adjust_hours(update, context)
    
    assert result == AWAITING_CONFIRMATION
    mock_estimate.assert_called_once()
    
    assert context.bot_data[PENDING_PROPOSALS_KEY][0]["estimated_hours"] == 10.0
    assert context.bot_data[PENDING_PROPOSALS_KEY][0]["daily_sessions"][0]["hours"] == 5.0

@pytest.mark.asyncio
async def test_skip_estimate_success(engine, pending_proposal):
    update = create_mock_update()
    context = create_mock_context(engine, bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal]})
    
    result = await skip_estimate(update, context)
    
    assert result == ConversationHandler.END
    update.message.reply_text.assert_called_once()
    assert "Skipped planning" in update.message.reply_text.call_args[0][0]
    
    with Session(engine) as s:
        project = s.get(Project, pending_proposal["project_id"])
        assert project.confirmed is True
    
    assert len(context.bot_data[PENDING_PROPOSALS_KEY]) == 0

@pytest.mark.asyncio
async def test_skip_estimate_with_index(engine, pending_proposal):
    prop2 = dict(pending_proposal)
    prop2["project_id"] = 999
    
    update = create_mock_update()
    context = create_mock_context(engine, args=["1"], bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal, prop2]})
    
    result = await skip_estimate(update, context)
    
    assert result == ConversationHandler.END
    assert len(context.bot_data[PENDING_PROPOSALS_KEY]) == 1
    assert context.bot_data[PENDING_PROPOSALS_KEY][0]["project_id"] == 999

@pytest.mark.asyncio
async def test_resolve_proposal_invalid_index(engine, pending_proposal):
    update = create_mock_update()
    context = create_mock_context(engine, args=["5"], bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal]})
    
    result = await skip_estimate(update, context)
    
    assert result == ConversationHandler.END
    update.message.reply_text.assert_called_once()
    assert "Invalid project index" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
@patch('ai.estimator.estimate_project')
async def test_adjust_hours_with_index(mock_estimate, engine, pending_proposal):
    prop2 = dict(pending_proposal)
    prop2["project_id"] = 999
    prop2["project_title"] = "Project 2"
    
    update = create_mock_update()
    context = create_mock_context(engine, args=["2", "8"], bot_data={"engine": engine, PENDING_PROPOSALS_KEY: [pending_proposal, prop2]})
    
    mock_estimate.return_value = {
        "project_id": 999,
        "project_title": "Project 2",
        "estimated_hours": 8.0,
        "sub_tasks": [],
        "daily_sessions": [{"date": "2023-10-01", "hours": 8.0, "focus": "Part 1"}]
    }
    
    repo = ProjectRepo(engine)
    repo.save(Project(user_id=1, id=999, title="Project 2", source="test", confirmed=False))

    result = await adjust_hours(update, context)
    
    assert result == AWAITING_CONFIRMATION
    mock_estimate.assert_called_once()
    
    assert len(context.bot_data[PENDING_PROPOSALS_KEY]) == 2
    assert context.bot_data[PENDING_PROPOSALS_KEY][0]["estimated_hours"] == 5.0
    assert context.bot_data[PENDING_PROPOSALS_KEY][1]["estimated_hours"] == 8.0


@pytest.mark.asyncio
@patch('bot.conversations.estimate_project')
@patch('integrations.document_parser.extract_text_with_ai')
@patch('integrations.document_parser.extract_text_from_pdf')
async def test_handle_file_upload_pdf_ai_fallback(mock_extract_pdf, mock_extract_ai, mock_estimate, engine, unconfirmed_project):
    doc = MagicMock(spec=Document)
    doc.file_name = "scanned.pdf"
    doc.file_id = "123"
    update = create_mock_update(document=doc)
    context = create_mock_context(engine, user_data={SELECTED_PROJECT_KEY: unconfirmed_project.id})
    
    file_bytes = bytearray(b"pdf content")
    mock_file = AsyncMock(spec=File)
    mock_file.download_as_bytearray.return_value = file_bytes
    context.bot.get_file.return_value = mock_file
    
    mock_extract_pdf.return_value = ""  # Simulate empty text from standard PDF extraction
    mock_extract_ai.return_value = "Extracted text via AI Vision"
    mock_estimate.return_value = {
        "project_id": unconfirmed_project.id,
        "project_title": "Pending Project",
        "estimated_hours": 3.0,
        "sub_tasks": [],
        "daily_sessions": []
    }
    
    result = await handle_file_upload(update, context)
    
    assert result == AWAITING_CONFIRMATION
    mock_extract_pdf.assert_called_once_with(file_bytes)
    mock_extract_ai.assert_called_once_with(file_bytes)
    mock_estimate.assert_called_once()
    
    # Verify the "Using AI Vision" message was sent
    update.message.reply_text.assert_any_call("This looks like a scanned document. Using AI Vision to read it... ⏳")
    
    from sqlalchemy.orm import Session
    from db.models import Project
    with Session(engine) as s:
        proj = s.get(Project, unconfirmed_project.id)
        assert proj.context_notes == "Extracted text via AI Vision"
