import pytest
from datetime import date, timedelta
from db.repository import UserRepo, TaskRepo, ProjectRepo
from db.models import Task, Project, TaskStatus
import config

def test_multi_user_data_isolation(engine):
    user_repo = UserRepo(engine)
    task_repo = TaskRepo(engine)
    project_repo = ProjectRepo(engine)

    # 1. Create two users
    user_a = user_repo.create_user(telegram_id=111, chat_id=111)
    user_b = user_repo.create_user(telegram_id=222, chat_id=222)

    # 2. Create projects for User A
    proj_a = Project(
        user_id=user_a.id,
        title="User A Project",
        source="manual",
        source_id="proj_a_1",
        confirmed=True
    )
    proj_a = project_repo.save(proj_a)

    # Create unconfirmed project for User A
    proj_a_unconfirmed = Project(
        user_id=user_a.id,
        title="User A Unconfirmed Project",
        source="manual",
        source_id="proj_a_2",
        confirmed=False
    )
    proj_a_unconfirmed = project_repo.save(proj_a_unconfirmed)

    # 3. Create tasks for User A
    today = config.get_today()
    
    task_a_1 = Task(
        user_id=user_a.id,
        project_id=proj_a.id,
        title="User A Task 1",
        source="manual",
        source_id="task_a_1",
        due_date=today + timedelta(days=1),
        scheduled_date=today,
        status=TaskStatus.pending
    )
    task_repo.save(task_a_1)

    task_a_2 = Task(
        user_id=user_a.id,
        project_id=proj_a_unconfirmed.id,
        title="User A Task 2",
        source="ai_plan",
        source_id="task_a_2",
        due_date=today + timedelta(days=2),
        scheduled_date=today,
        status=TaskStatus.pending
    )
    task_repo.save(task_a_2)

    # Verify User A data is accessible by User A
    assert len(project_repo.list_all(user_a.id)) == 2
    # list_active joins on tasks with pending status, both projects have pending tasks
    assert len(project_repo.list_active(user_a.id)) == 2
    assert len(project_repo.list_unconfirmed(user_a.id)) == 1
    assert project_repo.get_by_source_id(user_a.id, "proj_a_1") is not None

    assert len(task_repo.for_date(user_a.id, today)) == 2
    assert len(task_repo.upcoming(user_a.id, days=7)) == 2
    assert task_repo.get_by_id(user_a.id, task_a_1.id) is not None
    assert task_repo.exists_by_source_id(user_a.id, "task_a_1") is True

    # 4. Verify User B cannot see User A's data
    assert len(project_repo.list_all(user_b.id)) == 0
    assert len(project_repo.list_active(user_b.id)) == 0
    assert len(project_repo.list_unconfirmed(user_b.id)) == 0
    assert project_repo.get_by_source_id(user_b.id, "proj_a_1") is None

    assert len(task_repo.for_date(user_b.id, today)) == 0
    assert len(task_repo.upcoming(user_b.id, days=7)) == 0
    assert task_repo.get_by_id(user_b.id, task_a_1.id) is None
    assert task_repo.exists_by_source_id(user_b.id, "task_a_1") is False

    # 5. Verify User B cannot modify User A's data
    # Attempt to mark done by User B (should silently fail or not update User A's task because of where clause)
    task_repo.mark_done(user_b.id, task_a_1.id)
    
    # Check that User A's task is still pending
    t = task_repo.get_by_id(user_a.id, task_a_1.id)
    assert t.status == TaskStatus.pending

    # Attempt to delete AI tasks by User B
    deleted_count = task_repo.delete_ai_tasks(user_b.id, proj_a_unconfirmed.id)
    assert deleted_count == 0
    
    # Ensure User A's AI task still exists
    assert task_repo.get_by_id(user_a.id, task_a_2.id) is not None

    # Check delete_all_ai_tasks
    deleted_all_count = task_repo.delete_all_ai_tasks(user_b.id)
    assert deleted_all_count == 0
    assert len(task_repo.upcoming(user_a.id)) == 2
    
    # User B attempting to reset project confirmation
    project_repo.reset_confirmation(user_b.id, proj_a.id)
    p = project_repo.get_by_source_id(user_a.id, "proj_a_1")
    assert p.confirmed is True  # still True because reset failed

    # User B attempting to confirm project
    project_repo.confirm(user_b.id, proj_a_unconfirmed.id, 5.0)
    p_unconfirmed = project_repo.get_by_source_id(user_a.id, "proj_a_2")
    assert p_unconfirmed.confirmed is False  # still False
