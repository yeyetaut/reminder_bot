import pytest
from datetime import date
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo
from ai.extractor import _normalize_title, _compact, _filter_new, _is_duplicate_project

def test_normalize_title():
    assert _normalize_title("[study] My Project") == "my project"
    assert _normalize_title("Another Project") == "another project"
    assert _normalize_title("  [STUDY]  Space  ") == "space"

def test_compact():
    item = {
        "source_id": "123",
        "title": "A very long title " * 10,
        "end": "2024-05-01T10:00:00Z",
        "description": "A very long description " * 20,
        "source": "google_calendar"
    }
    compacted = _compact(item)
    assert compacted["source_id"] == "123"
    assert len(compacted["title"]) <= 120
    assert len(compacted["snippet"]) <= 150
    assert compacted["date"] == "2024-05-01T10:00:00Z"

def test_filter_new(engine):
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)
    
    # Existing task
    task_repo.save(Task(title="Existing", source="test", source_id="sid_task"))
    # Existing project
    project_repo.save(Project(title="Existing Proj", source="test", source_id="sid_proj"))
    
    items = [
        {"source_id": "sid_task", "title": "Existing", "source": "test"},
        {"source_id": "sid_proj", "title": "Existing Proj", "source": "test"},
        {"source_id": "sid_new", "title": "New Task", "source": "test"},
        {"source_id": "sid_bot", "title": "[Study] My Bot Event", "source": "google_calendar"}
    ]
    
    filtered = _filter_new(items, task_repo, project_repo)
    assert len(filtered) == 1
    assert filtered[0]["source_id"] == "sid_new"

def test_is_duplicate_project(engine):
    project_repo = ProjectRepo(engine)
    project_repo.save(Project(title="CS101 Homework", source="test", source_id="s1"))
    
    assert _is_duplicate_project("CS101 Homework", project_repo) is True
    assert _is_duplicate_project("[Study] CS101 Homework", project_repo) is True
    assert _is_duplicate_project("CS101 Hmwk", project_repo) is True # Should be similar enough
    assert _is_duplicate_project("Math 101", project_repo) is False
