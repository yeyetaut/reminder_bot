import pytest
from datetime import date
from db.models import Project
from ai.estimator import format_proposal_message, estimate_project

def test_format_proposal_message():
    proposal = {
        "project_title": "Test Project",
        "estimated_hours": 10,
        "reasoning": "Complex task.",
        "daily_sessions": [
            {"date": "2024-05-01", "hours": 2, "focus": "Research"},
            {"date": "2024-05-02", "hours": 3, "focus": "Drafting"}
        ]
    }
    msg = format_proposal_message(proposal)
    assert "Test Project" in msg
    assert "10 hours" in msg
    assert "Research" in msg
    assert "Drafting" in msg

def test_estimate_project_success(mocker):
    # Mock _call_ai to return a fake JSON response
    mock_response = {
        "estimated_hours": 5,
        "reasoning": "Simple task",
        "daily_sessions": [{"date": "2024-05-01", "hours": 5, "focus": "Work"}]
    }
    import json
    mocker.patch("ai.estimator._call_ai", return_value=(json.dumps(mock_response), "mock-model"))
    
    project = Project(id=1, title="Test", source="test", due_date=date(2024, 5, 10))
    proposal = estimate_project(project)
    
    assert proposal is not None
    assert proposal["estimated_hours"] == 5
    assert proposal["project_id"] == 1
    assert proposal["project_title"] == "Test"

def test_estimate_project_failure(mocker):
    mocker.patch("ai.estimator._call_ai", side_effect=RuntimeError("AI Error"))
    
    project = Project(id=1, title="Test", source="test")
    proposal = estimate_project(project)
    
    assert proposal is None
