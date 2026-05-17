import pytest
from datetime import date
from db.models import Project
from ai.estimator import format_proposal_message, estimate_project

def test_format_proposal_message():
    proposal = {
        "project_title": "Test Project",
        "reasoning": "Complex task.",
        "sub_tasks": [
            {"title": "Research", "description": "Look for sources"},
            {"title": "Drafting", "description": "Write first draft"}
        ]
    }
    msg = format_proposal_message(proposal)
    assert "Test Project" in msg
    assert "Research" in msg
    assert "Drafting" in msg
    assert "Look for sources" in msg

def test_estimate_project_success(mocker):
    # Mock _call_ai to return a fake JSON response
    mock_response = {
        "reasoning": "Simple task",
        "sub_tasks": [{"title": "Work", "description": "Just do it"}]
    }
    import json
    mocker.patch("ai.estimator._call_ai", return_value=(json.dumps(mock_response), "mock-model"))
    
    project = Project(user_id=1, id=1, title="Test", source="test", due_date=date(2024, 5, 10))
    proposal = estimate_project(project)
    
    assert proposal is not None
    assert proposal.get("reasoning") == "Simple task"
    assert proposal["project_id"] == 1
    assert proposal["project_title"] == "Test"
    assert len(proposal["sub_tasks"]) == 1

def test_estimate_project_failure(mocker):
    mocker.patch("ai.estimator._call_ai", side_effect=RuntimeError("AI Error"))
    
    project = Project(user_id=1, id=1, title="Test", source="test")
    proposal = estimate_project(project)
    
    assert proposal is None
