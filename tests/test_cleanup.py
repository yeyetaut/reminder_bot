import pytest
from datetime import datetime, timedelta, date
from db.models import Task, TaskStatus, ProcessedSource
from db.repository import TaskRepo, ProcessedSourceRepo, ProjectRepo

from sqlalchemy.orm import Session

def test_cleanup_old_tasks(engine):
    task_repo = TaskRepo(engine)
    processed_repo = ProcessedSourceRepo(engine)
    
    # 1. Create a task that should be cleaned up (done, older than 7 days)
    old_task = Task(user_id=1, 
        title="Old Task",
        source="test",
        source_id="old_sid",
        status=TaskStatus.done,
        completed_at=datetime.utcnow() - timedelta(days=8)
    )
    # 2. Create a task that should NOT be cleaned up (done, but recent)
    recent_task = Task(user_id=1, 
        title="Recent Task",
        source="test",
        source_id="recent_sid",
        status=TaskStatus.done,
        completed_at=datetime.utcnow() - timedelta(days=2)
    )
    # 3. Create a task that should NOT be cleaned up (pending)
    pending_task = Task(user_id=1, 
        title="Pending Task",
        source="test",
        source_id="pending_sid",
        status=TaskStatus.pending
    )
    
    with Session(engine) as s:
        s.add_all([old_task, recent_task, pending_task])
        s.commit()
        old_id = old_task.id
        recent_id = recent_task.id
        pending_id = pending_task.id
    
    # Run cleanup
    deleted = task_repo.cleanup_old_tasks(1, days=7)
    
    assert deleted == 1
    
    # Verify DB state
    assert task_repo.get_by_id(1, old_id) is None
    assert task_repo.get_by_id(1, recent_id) is not None
    assert task_repo.get_by_id(1, pending_id) is not None
    
    # Verify ProcessedSource memory
    assert processed_repo.exists(1, "old_sid") is True
    assert processed_repo.exists(1, "recent_sid") is False

def test_extractor_dedup_with_processed_source(engine):
    from ai.extractor import _filter_new
    
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    processed_repo = ProcessedSourceRepo(engine)
    
    # Add an ID to processed memory
    processed_repo.save_many(1, ["already_done_sid"])
    
    items = [
        {"source_id": "already_done_sid", "title": "Old item"},
        {"source_id": "new_sid", "title": "New item"}
    ]
    
    filtered = _filter_new(items, task_repo, project_repo, processed_repo, 1)
    
    assert len(filtered) == 1
    assert filtered[0]["source_id"] == "new_sid"
