import pytest
from datetime import date, timedelta
from db.models import Task, TaskStatus, Project
from db.repository import TaskRepo, ProjectRepo
from bot.messages import is_exam, exams_overview, morning_digest

def test_is_exam():
    assert is_exam("Final Exam: CS101") is True
    assert is_exam("Quiz 1") is True
    assert is_exam("Midterm Project") is True
    assert is_exam("Assessment 2") is True
    assert is_exam("Weekly Homework") is False
    assert is_exam("Study session") is False

def test_exams_overview(engine):
    task_repo = TaskRepo(engine)
    today = date.today()
    
    # Not an exam
    task_repo.save(Task(title="Homework 1", due_date=today + timedelta(days=5), source="canvas"))
    # Is an exam
    task_repo.save(Task(title="CS101 Final Exam", due_date=today + timedelta(days=10), source="canvas"))
    
    digest = exams_overview(task_repo)
    assert "CS101 Final Exam" in digest
    assert "Homework 1" not in digest
    assert "🔴 *Upcoming Exams*" in digest

def test_morning_digest_split_exams(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    today = date.today()
    
    # AI Breakdown task (linked to a project)
    project = project_repo.save(Project(title="CS101", source="test", confirmed=True))
    task_repo.save(Task(project_id=project.id, title="CS101 — Study", source="ai_breakdown", status=TaskStatus.pending))
    
    # Task
    task_repo.save(Task(title="Homework 1", due_date=today + timedelta(days=2), source="canvas"))
    # Exam
    task_repo.save(Task(title="Midterm", due_date=today + timedelta(days=3), source="canvas"))
    
    digest = morning_digest(task_repo, project_repo)
    
    assert "🟡 *Projects*" in digest
    assert "Study" in digest

    assert "🟢 *Deadlines & Tasks*" in digest
    assert "Homework 1" in digest
    
    assert "🔴 *Exams*" in digest
    assert "Midterm" in digest
    # IDs: 1 (Study), 2 (Homework), 3 (Midterm)
    assert "`ID: 2, 3, 1`" in digest or "`ID: 1, 2, 3`" in digest # order might vary but they should be there
