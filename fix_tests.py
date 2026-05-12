import re

with open("tests/test_conversations.py", "r") as f:
    content = f.read()

# Fix get_by_id
content = content.replace("repo.get_by_id(unconfirmed_project.id)", "context.bot_data['engine'].connect() # wait, we should just use Session")
content = content.replace(
    "proj = repo.get_by_id(unconfirmed_project.id)",
    "from sqlalchemy.orm import Session\n    with Session(engine) as s:\n        proj = s.get(Project, unconfirmed_project.id)"
)
content = content.replace(
    "project = project_repo.get_by_id(pending_proposal[\"project_id\"])",
    "from sqlalchemy.orm import Session\n    with Session(engine) as s:\n        project = s.get(Project, pending_proposal[\"project_id\"])"
)

# Fix adjust_hours patch
content = content.replace("@patch('bot.conversations.estimate_project')", "@patch('bot.conversations.estimate_project')\n@patch('ai.estimator.estimate_project')")

# Wait, if I add two patches, I need to update the function signature. Let's do it manually with regex.
