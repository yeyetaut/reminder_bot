from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import Engine, select, update, delete
from sqlalchemy.orm import Session

import config
from db.models import Project, Task, TaskStatus, DailyPlan


class ProjectRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get_by_source_id(self, source_id: str) -> Optional[Project]:
        with Session(self.engine) as s:
            return s.scalar(select(Project).where(Project.source_id == source_id))

    def save(self, project: Project) -> Project:
        with Session(self.engine) as s:
            s.add(project)
            s.commit()
            s.refresh(project)
            return project

    def list_unconfirmed(self) -> List[Project]:
        from sqlalchemy.orm import joinedload
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Project)
                .where(Project.confirmed == False)
                .options(joinedload(Project.tasks))
            ).unique())

    def list_active(self) -> List[Project]:
        """Projects with pending tasks (tasks eagerly loaded)."""
        from sqlalchemy.orm import joinedload
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Project)
                .join(Project.tasks)
                .where(Task.status == TaskStatus.pending)
                .options(joinedload(Project.tasks))
                .distinct()
            ).unique())

    def list_all(self) -> List[Project]:
        with Session(self.engine) as s:
            return list(s.scalars(select(Project)))

    def confirm(self, project_id: int, estimated_hours: float) -> None:
        with Session(self.engine) as s:
            s.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(confirmed=True, estimated_hours=estimated_hours)
            )
            s.commit()

    def is_already_planned(self, title: str, threshold: float = 0.55) -> bool:
        """Return True if a confirmed project with a similar title already exists.
        Lower threshold (0.55) than _is_duplicate_project (0.72) — this is the
        final safety net before sending a proposal.
        """
        from difflib import SequenceMatcher
        import re
        _study = re.compile(r'^\[study\]\s*', re.IGNORECASE)
        def norm(t: str) -> str:
            return _study.sub("", t).lower().strip()
        norm_title = norm(title)
        with Session(self.engine) as s:
            for p in s.scalars(select(Project).where(Project.confirmed == True)):
                if SequenceMatcher(None, norm_title, norm(p.title)).ratio() >= threshold:
                    return True
        return False

    def reset_confirmation(self, project_id: int) -> None:
        """Reset a project to unconfirmed so it can be re-estimated."""
        with Session(self.engine) as s:
            s.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(confirmed=False, estimated_hours=None)
            )
            s.commit()


class TaskRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def run_migrations(self) -> None:
        """One-time fix: clear scheduled_date for non-AI tasks so they
        appear via due_date-based upcoming() queries instead of for_date()."""
        with Session(self.engine) as s:
            s.execute(
                update(Task)
                .where(Task.source.not_in(["ai_plan", "ai_breakdown"]), Task.scheduled_date != None)
                .values(scheduled_date=None)
            )
            s.commit()

    def get_by_id(self, task_id: int) -> Optional[Task]:
        with Session(self.engine) as s:
            return s.get(Task, task_id)

    def exists_by_source_id(self, source_id: str) -> bool:
        with Session(self.engine) as s:
            return s.scalar(select(Task).where(Task.source_id == source_id)) is not None

    def save(self, task: Task) -> Task:
        with Session(self.engine) as s:
            s.add(task)
            s.commit()
            s.refresh(task)
            return task

    def save_many(self, tasks: List[Task]) -> None:
        with Session(self.engine) as s:
            s.add_all(tasks)
            s.commit()

    def for_date(self, d: date) -> List[Task]:
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.scheduled_date == d, Task.status == TaskStatus.pending)
                .order_by(Task.due_date)
            ))

    def mark_done(self, task_id: int) -> None:
        self._set_status(task_id, TaskStatus.done)

    def mark_skipped(self, task_id: int) -> None:
        self._set_status(task_id, TaskStatus.skipped)

    def reschedule(self, task_id: int, new_date: date) -> None:
        with Session(self.engine) as s:
            s.execute(update(Task).where(Task.id == task_id).values(scheduled_date=new_date))
            s.commit()

    def _set_status(self, task_id: int, status: TaskStatus) -> None:
        with Session(self.engine) as s:
            s.execute(update(Task).where(Task.id == task_id).values(status=status))
            s.commit()

    def mark_gcal_synced(self, task_id: int) -> None:
        with Session(self.engine) as s:
            s.execute(update(Task).where(Task.id == task_id).values(gcal_synced=True))
            s.commit()

    def unsynced_canvas_tasks(self) -> List[Task]:
        """Return Canvas tasks not yet written to Google Calendar."""
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.source == "canvas", Task.gcal_synced == False, Task.due_date != None)
            ))

    def has_ai_tasks_for_title(self, project_title: str) -> bool:
        """Return True if AI-generated tasks (plan or breakdown) already exist for this project title."""
        with Session(self.engine) as s:
            return s.scalar(
                select(Task.id)
                .where(Task.source.in_(["ai_plan", "ai_breakdown"]), Task.title.like(project_title + " —%"))
                .limit(1)
            ) is not None

    def delete_ai_tasks(self, project_id: int) -> int:
        """Delete all AI-generated tasks (plan or breakdown) for a project. Returns count deleted."""
        with Session(self.engine) as s:
            result = s.execute(
                delete(Task)
                .where(Task.project_id == project_id, Task.source.in_(["ai_plan", "ai_breakdown"]))
            )
            s.commit()
            return result.rowcount

    def delete_all_ai_tasks(self) -> int:
        """Delete all AI-generated tasks across all projects. Returns count deleted."""
        with Session(self.engine) as s:
            result = s.execute(delete(Task).where(Task.source.in_(["ai_plan", "ai_breakdown"])))
            s.commit()
            return result.rowcount

    def upcoming(self, days: int = 7) -> List[Task]:
        from datetime import timedelta
        today = config.get_today()
        end = today + timedelta(days=days)
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.due_date <= end, Task.status == TaskStatus.pending)
                .order_by(Task.due_date)
            ))


class DailyPlanRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get_or_create(self, d: date) -> DailyPlan:
        with Session(self.engine) as s:
            plan = s.scalar(select(DailyPlan).where(DailyPlan.date == d))
            if not plan:
                plan = DailyPlan(date=d, task_ids=[])
                s.add(plan)
                s.commit()
                s.refresh(plan)
            return plan

    def mark_sent(self, plan_id: int) -> None:
        with Session(self.engine) as s:
            s.execute(update(DailyPlan).where(DailyPlan.id == plan_id).values(sent_at=datetime.utcnow()))
            s.commit()
