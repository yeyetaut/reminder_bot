from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

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
        with Session(self.engine) as s:
            return list(s.scalars(select(Project).where(Project.confirmed == False)))

    def list_active(self) -> List[Project]:
        """Projects with pending tasks."""
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Project)
                .join(Project.tasks)
                .where(Task.status == TaskStatus.pending)
                .distinct()
            ))

    def confirm(self, project_id: int, estimated_hours: float) -> None:
        with Session(self.engine) as s:
            s.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(confirmed=True, estimated_hours=estimated_hours)
            )
            s.commit()


class TaskRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

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

    def upcoming(self, days: int = 7) -> List[Task]:
        from datetime import timedelta
        today = date.today()
        end = today + timedelta(days=days)
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.due_date >= today, Task.due_date <= end, Task.status == TaskStatus.pending)
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
