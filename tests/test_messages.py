import pytest
from datetime import date, timedelta
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo
from bot.messages import _due_label, morning_digest

def test_due_label():
    today = date.today()
    
    t_today = Task(due_date=today)
    assert "_today_" in _due_label(t_today)
    
    t_tomorrow = Task(due_date=today + timedelta(days=1))
    assert "_tomorrow_" in _due_label(t_tomorrow)
    
    t_overdue = Task(due_date=today - timedelta(days=1))
    assert "_overdue_" in _due_label(t_overdue)
    
    t_future = Task(due_date=today + timedelta(days=5))
    assert "_5d_" in _due_label(t_future)

def test_morning_digest_empty(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    digest = morning_digest(task_repo, project_repo)
    assert "No tasks scheduled" in digest

def test_morning_digest_with_tasks(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    today = date.today()
    
    # Only tasks with due_date in next 4 days are shown in Deadlines
    task_repo.save(Task(title="Today's Task", due_date=today, source="test", status=TaskStatus.pending))
    task_repo.save(Task(title="Upcoming Deadline", due_date=today + timedelta(days=2), source="test", status=TaskStatus.pending))
    
    digest = morning_digest(task_repo, project_repo)
    assert "Today's Task" in digest
    assert "Upcoming Deadline" in digest
    assert "_2d_" in digest
