import pytest
from datetime import date, datetime
from db.models import Project, Task, TaskStatus, DailyPlan
from db.repository import ProjectRepo, TaskRepo, DailyPlanRepo

def test_project_repo_save_and_get(engine):
    repo = ProjectRepo(engine)
    project = Project(user_id=1, 
        title="Test Project",
        source="test",
        source_id="sid_123",
        due_date=date(2024, 12, 31)
    )
    saved = repo.save(project)
    assert saved.id is not None
    
    fetched = repo.get_by_source_id(1, "sid_123")
    assert fetched.title == "Test Project"
    assert fetched.due_date == date(2024, 12, 31)

def test_project_repo_list_unconfirmed(engine):
    repo = ProjectRepo(engine)
    p1 = Project(user_id=1, title="P1", source="test", source_id="s1", confirmed=False)
    p2 = Project(user_id=1, title="P2", source="test", source_id="s2", confirmed=True)
    repo.save(p1)
    repo.save(p2)
    
    unconfirmed = repo.list_unconfirmed(1)
    assert len(unconfirmed) == 1
    assert unconfirmed[0].title == "P1"

def test_task_repo_save_and_exists(engine):
    repo = TaskRepo(engine)
    task = Task(user_id=1, 
        title="Test Task",
        source="test",
        source_id="tsid_1"
    )
    repo.save(task)
    
    assert repo.exists_by_source_id(1, "tsid_1") is True
    assert repo.exists_by_source_id(1, "non-existent") is False

def test_task_repo_for_date(engine):
    repo = TaskRepo(engine)
    d = date(2024, 5, 1)
    t1 = Task(user_id=1, title="T1", source="test", scheduled_date=d, status=TaskStatus.pending)
    t2 = Task(user_id=1, title="T2", source="test", scheduled_date=d, status=TaskStatus.done)
    t3 = Task(user_id=1, title="T3", source="test", scheduled_date=date(2024, 5, 2), status=TaskStatus.pending)
    repo.save_many([t1, t2, t3])
    
    tasks = repo.for_date(1, d)
    assert len(tasks) == 1
    assert tasks[0].title == "T1"

def test_daily_plan_repo_get_or_create(engine):
    repo = DailyPlanRepo(engine)
    d = date(2024, 5, 1)
    
    plan1 = repo.get_or_create(1, d)
    assert plan1.date == d
    assert plan1.task_ids == []
    
    plan2 = repo.get_or_create(1, d)
    assert plan1.id == plan2.id

def test_project_repo_is_already_planned(engine):
    repo = ProjectRepo(engine)
    p = Project(user_id=1, title="Study CS101", source="test", source_id="s1", confirmed=True)
    repo.save(p)
    
    assert repo.is_already_planned(1, "Study CS101") is True
    assert repo.is_already_planned(1, "[Study] CS101") is True
    assert repo.is_already_planned(1, "Something Else") is False
