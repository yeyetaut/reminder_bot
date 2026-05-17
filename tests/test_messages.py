from telegram import InlineKeyboardMarkup
import config
import pytest
from datetime import date, timedelta
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo
from bot.messages import _due_label, morning_digest, get_morning_digest_buttons

def test_due_label():
    today = date.today()
    
    t_today = Task(user_id=1, due_date=today)
    assert "_today_" in _due_label(t_today)
    
    t_tomorrow = Task(user_id=1, due_date=today + timedelta(days=1))
    assert "_tomorrow_" in _due_label(t_tomorrow)
    
    t_overdue = Task(user_id=1, due_date=today - timedelta(days=1))
    assert "_overdue_" in _due_label(t_overdue)
    
    t_future = Task(user_id=1, due_date=today + timedelta(days=5))
    assert "_5d_" in _due_label(t_future)

def test_morning_digest_empty(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    digest = morning_digest(task_repo, project_repo, 1)
    assert "No tasks scheduled" in digest

def test_morning_digest_with_tasks(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    today = date.today()
    
    # Only tasks with due_date in next 4 days are shown in Deadlines
    task_repo.save(Task(user_id=1, title="Today's Task", due_date=today, source="test", status=TaskStatus.pending))
    task_repo.save(Task(user_id=1, title="Upcoming Deadline", due_date=today + timedelta(days=2), source="test", status=TaskStatus.pending))
    
    digest = morning_digest(task_repo, project_repo, 1)
    assert "Today's Task" in digest
    assert "Upcoming Deadline" in digest
    assert "_2d_" in digest


def test_get_morning_digest_buttons(engine, monkeypatch):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    today = date(2024, 5, 15)
    
    # Mock config.get_today() to return a fixed date
    monkeypatch.setattr(config, "get_today", lambda: today)
    
    # Let us add a project with some sub-tasks
    p = Project(user_id=1, title="Test Project", source="test")
    
    t1 = Task(user_id=1, title="Test Project — AI Task 1", due_date=today + timedelta(days=10), source="ai_breakdown", status=TaskStatus.pending)
    t2 = Task(user_id=1, title="Test Project — AI Task 2", due_date=today + timedelta(days=10), source="ai_breakdown", status=TaskStatus.pending)
    t3 = Task(user_id=1, title="Test Project — AI Task 3", due_date=today + timedelta(days=10), source="ai_breakdown", status=TaskStatus.pending)
    t4 = Task(user_id=1, title="Test Project — AI Task 4", due_date=today + timedelta(days=10), source="ai_breakdown", status=TaskStatus.pending)
    
    p.tasks = [t1, t2, t3, t4]
    project_repo.save(p)
    
    # Now adding non-project tasks (regular ones in next 4 days)
    # Regular Task (due in 2 days) -> gets Done button
    task_repo.save(Task(user_id=1, title="Regular Task", due_date=today + timedelta(days=2), source="test", status=TaskStatus.pending))
    
    # Exam in 2 days (FUTURE) -> NO Done button
    task_repo.save(Task(user_id=1, title="Math Exam", due_date=today + timedelta(days=2), source="test", status=TaskStatus.pending))
    
    # Exam due TODAY -> gets Done button
    task_repo.save(Task(user_id=1, title="Physics Exam", due_date=today, source="test", status=TaskStatus.pending))
    
    # Exam OVERDUE -> gets Done button
    task_repo.save(Task(user_id=1, title="History Exam", due_date=today - timedelta(days=1), source="test", status=TaskStatus.pending))

    markup = get_morning_digest_buttons(task_repo, project_repo, 1)
    
    assert markup is not None
    assert isinstance(markup, InlineKeyboardMarkup)
    
    buttons_text = []
    for row in markup.inline_keyboard:
        for btn in row:
            buttons_text.append(btn.text)
            
    buttons_joined = " ".join(buttons_text)
    
    # Verify AI sub-tasks
    assert "AI Task 1" in buttons_joined
    assert "AI Task 2" in buttons_joined
    assert "AI Task 3" in buttons_joined
    assert "AI Task 4" not in buttons_joined # Only top 3 are included
    
    # Verify Regular task
    assert "Regular Task" in buttons_joined
    
    # Verify Future Exam (Not present)
    assert "Math Exam" not in buttons_joined
    
    # Verify Today Exam
    assert "Physics Exam" in buttons_joined
    
    # Verify Overdue Exam
    assert "History Exam" in buttons_joined
