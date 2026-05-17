import pytest
from datetime import date, timedelta
from db.models import Task, TaskStatus, Project
from db.repository import TaskRepo, ProjectRepo
from bot.messages import morning_digest

def test_morning_digest_with_projects(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    today = date.today()
    
    # Create an active project
    project = project_repo.save(Project(user_id=1, title="Big Research Paper", source="canvas", due_date=today + timedelta(days=10), confirmed=True))
    
    # Add some sub-tasks (source="ai_breakdown")
    task_repo.save(Task(user_id=1, project_id=project.id, title="Big Research Paper — Step 1", source="ai_breakdown", status=TaskStatus.pending))
    task_repo.save(Task(user_id=1, project_id=project.id, title="Big Research Paper — Step 2", source="ai_breakdown", status=TaskStatus.pending))
    task_repo.save(Task(user_id=1, project_id=project.id, title="Big Research Paper — Step 3", source="ai_breakdown", status=TaskStatus.pending))
    task_repo.save(Task(user_id=1, project_id=project.id, title="Big Research Paper — Step 4", source="ai_breakdown", status=TaskStatus.pending))
    
    digest = morning_digest(task_repo, project_repo, 1)
    
    assert "🟡 *Projects*" in digest
    assert "Big Research Paper" in digest
    assert "Step 1" in digest
    assert "Step 2" in digest
    assert "Step 3" in digest
    assert "Step 4" not in digest  # Only top 3
    assert "...and 1 more" in digest
