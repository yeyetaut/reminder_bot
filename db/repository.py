from datetime import date, datetime
from typing import Optional, List
from sqlalchemy import Engine, select, update, delete
from sqlalchemy.orm import Session

import config
from db.models import Project, Task, TaskStatus, DailyPlan, ProcessedSource, User, Habit, HabitLog, HabitFrequency


class UserRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        with Session(self.engine) as s:
            return s.scalar(select(User).where(User.telegram_id == telegram_id))

    def create_user(self, telegram_id: int, chat_id: int, timezone: str = "America/New_York", **kwargs) -> User:
        with Session(self.engine) as s:
            user = User(telegram_id=telegram_id, telegram_chat_id=chat_id, timezone=timezone, **kwargs)
            s.add(user)
            s.commit()
            s.refresh(user)
            return user

    def update_user(self, user_id: int, **kwargs) -> None:
        with Session(self.engine) as s:
            s.execute(update(User).where(User.id == user_id).values(**kwargs))
            s.commit()

    def get_all_users(self) -> List[User]:
        with Session(self.engine) as s:
            return list(s.scalars(select(User)))


class ProjectRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get_by_source_id(self, user_id: int, source_id: str) -> Optional[Project]:
        with Session(self.engine) as s:
            return s.scalar(select(Project).where(Project.user_id == user_id, Project.source_id == source_id))

    def save(self, project: Project) -> Project:
        with Session(self.engine) as s:
            s.add(project)
            s.commit()
            s.refresh(project)
            return project

    def list_unconfirmed(self, user_id: int) -> List[Project]:
        from sqlalchemy.orm import joinedload
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Project)
                .join(Project.tasks)
                .where(Project.user_id == user_id, Project.confirmed == False, Task.status == TaskStatus.pending)
                .options(joinedload(Project.tasks))
                .distinct()
            ).unique())

    def list_active(self, user_id: int) -> List[Project]:
        """Projects with pending tasks (tasks eagerly loaded)."""
        from sqlalchemy.orm import joinedload
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Project)
                .join(Project.tasks)
                .where(Project.user_id == user_id, Task.status == TaskStatus.pending)
                .options(joinedload(Project.tasks))
                .distinct()
            ).unique())

    def list_all(self, user_id: int) -> List[Project]:
        with Session(self.engine) as s:
            return list(s.scalars(select(Project).where(Project.user_id == user_id)))

    def confirm(self, user_id: int, project_id: int, estimated_hours: float) -> None:
        with Session(self.engine) as s:
            s.execute(
                update(Project)
                .where(Project.user_id == user_id, Project.id == project_id)
                .values(confirmed=True, estimated_hours=estimated_hours)
            )
            s.commit()

    def is_already_planned(self, user_id: int, title: str, threshold: float = 0.55) -> bool:
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
            for p in s.scalars(select(Project).where(Project.user_id == user_id, Project.confirmed == True)):
                if SequenceMatcher(None, norm_title, norm(p.title)).ratio() >= threshold:
                    return True
        return False

    def reset_confirmation(self, user_id: int, project_id: int) -> None:
        """Reset a project to unconfirmed so it can be re-estimated."""
        with Session(self.engine) as s:
            s.execute(
                update(Project)
                .where(Project.user_id == user_id, Project.id == project_id)
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

    def get_by_id(self, user_id: int, task_id: int) -> Optional[Task]:
        with Session(self.engine) as s:
            return s.scalar(select(Task).where(Task.user_id == user_id, Task.id == task_id))

    def exists_by_source_id(self, user_id: int, source_id: str) -> bool:
        with Session(self.engine) as s:
            return s.scalar(select(Task).where(Task.user_id == user_id, Task.source_id == source_id)) is not None

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

    def for_date(self, user_id: int, d: date) -> List[Task]:
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.user_id == user_id, Task.scheduled_date == d, Task.status == TaskStatus.pending)
                .order_by(Task.due_date)
            ))

    def mark_done(self, user_id: int, task_id: int) -> None:
        self._set_status(user_id, task_id, TaskStatus.done)

    def mark_skipped(self, user_id: int, task_id: int) -> None:
        self._set_status(user_id, task_id, TaskStatus.skipped)

    def reschedule(self, user_id: int, task_id: int, new_date: date) -> None:
        with Session(self.engine) as s:
            s.execute(update(Task).where(Task.user_id == user_id, Task.id == task_id).values(scheduled_date=new_date))
            s.commit()

    def _set_status(self, user_id: int, task_id: int, status: TaskStatus) -> None:
        with Session(self.engine) as s:
            values = {"status": status}
            if status in (TaskStatus.done, TaskStatus.skipped):
                values["completed_at"] = datetime.utcnow()
            s.execute(update(Task).where(Task.user_id == user_id, Task.id == task_id).values(**values))
            s.commit()

    def cleanup_old_tasks(self, user_id: int, days: int) -> int:
        """
        Delete tasks that were completed/skipped more than `days` ago.
        Preserves their source_ids in ProcessedSource to prevent re-extraction.
        Returns count deleted.
        """
        from datetime import timedelta
        threshold = datetime.utcnow() - timedelta(days=days)
        
        with Session(self.engine) as s:
            # 1. Identify tasks to clean up
            stmt = select(Task.source_id).where(
                Task.user_id == user_id,
                Task.status.in_([TaskStatus.done, TaskStatus.skipped]),
                Task.completed_at <= threshold,
                Task.source_id != None
            )
            source_ids = list(s.scalars(stmt))
            
            if source_ids:
                # 2. Save IDs to ProcessedSource (ignore duplicates if any)
                for sid in source_ids:
                    exists = s.scalar(select(ProcessedSource).where(ProcessedSource.user_id == user_id, ProcessedSource.source_id == sid))
                    if not exists:
                        s.add(ProcessedSource(user_id=user_id, source_id=sid))
            
            # 3. Delete the tasks
            result = s.execute(
                delete(Task).where(
                    Task.user_id == user_id,
                    Task.status.in_([TaskStatus.done, TaskStatus.skipped]),
                    Task.completed_at <= threshold
                )
            )
            s.commit()
            return result.rowcount

    def unsynced_tasks(self, user_id: int) -> List[Task]:
        """Return non-calendar tasks (Gmail, Canvas, etc.) not yet written to Google Calendar."""
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(
                    Task.user_id == user_id,
                    Task.source != "google_calendar",
                    Task.gcal_synced == False,
                    Task.due_date != None
                )
            ))

    def mark_gcal_synced(self, user_id: int, task_id: int) -> None:
        with Session(self.engine) as s:
            s.execute(update(Task).where(Task.user_id == user_id, Task.id == task_id).values(gcal_synced=True))
            s.commit()

    def unsynced_canvas_tasks(self, user_id: int) -> List[Task]:
        """Return Canvas tasks not yet written to Google Calendar."""
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.user_id == user_id, Task.source == "canvas", Task.gcal_synced == False, Task.due_date != None)
            ))

    def has_ai_tasks_for_title(self, user_id: int, project_title: str) -> bool:
        """Return True if AI-generated tasks (plan or breakdown) already exist for this project title."""
        with Session(self.engine) as s:
            return s.scalar(
                select(Task.id)
                .where(Task.user_id == user_id, Task.source.in_(["ai_plan", "ai_breakdown"]), Task.title.like(project_title + " —%"))
                .limit(1)
            ) is not None

    def delete_ai_tasks(self, user_id: int, project_id: int) -> int:
        """Delete all AI-generated tasks (plan or breakdown) for a project. Returns count deleted."""
        with Session(self.engine) as s:
            result = s.execute(
                delete(Task)
                .where(Task.user_id == user_id, Task.project_id == project_id, Task.source.in_(["ai_plan", "ai_breakdown"]))
            )
            s.commit()
            return result.rowcount

    def delete_all_ai_tasks(self, user_id: int) -> int:
        """Delete all AI-generated tasks across all projects. Returns count deleted."""
        with Session(self.engine) as s:
            result = s.execute(delete(Task).where(Task.user_id == user_id, Task.source.in_(["ai_plan", "ai_breakdown"])))
            s.commit()
            return result.rowcount

    def upcoming(self, user_id: int, days: int = 7) -> List[Task]:
        from datetime import timedelta
        today = config.get_today()
        end = today + timedelta(days=days)
        with Session(self.engine) as s:
            return list(s.scalars(
                select(Task)
                .where(Task.user_id == user_id, Task.due_date <= end, Task.status == TaskStatus.pending)
                .order_by(Task.due_date)
            ))


class ProcessedSourceRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def exists(self, user_id: int, source_id: str) -> bool:
        with Session(self.engine) as s:
            return s.scalar(select(ProcessedSource).where(ProcessedSource.user_id == user_id, ProcessedSource.source_id == source_id)) is not None

    def save_many(self, user_id: int, source_ids: List[str]) -> None:
        with Session(self.engine) as s:
            s.add_all([ProcessedSource(user_id=user_id, source_id=sid) for sid in source_ids])
            s.commit()


class HabitRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, user_id: int, title: str, frequency: HabitFrequency,
               target_count: int = 1, description: Optional[str] = None) -> Habit:
        with Session(self.engine) as s:
            habit = Habit(user_id=user_id, title=title, frequency=frequency,
                          target_count=target_count, description=description)
            s.add(habit)
            s.commit()
            s.refresh(habit)
            return habit

    def list_active(self, user_id: int) -> List[Habit]:
        with Session(self.engine) as s:
            return list(s.scalars(select(Habit).where(Habit.user_id == user_id, Habit.active == True)))

    def get_by_id(self, user_id: int, habit_id: int) -> Optional[Habit]:
        with Session(self.engine) as s:
            return s.scalar(select(Habit).where(Habit.user_id == user_id, Habit.id == habit_id))

    def log_completion(self, user_id: int, habit_id: int) -> HabitLog:
        with Session(self.engine) as s:
            log = HabitLog(user_id=user_id, habit_id=habit_id)
            s.add(log)
            s.commit()
            s.refresh(log)
            return log

    def completions_this_period(self, user_id: int, habit_id: int, frequency: HabitFrequency) -> int:
        import pytz
        from datetime import timedelta
        tz = pytz.timezone(config.TIMEZONE)
        now_local = datetime.now(tz)
        if frequency == HabitFrequency.daily:
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        elif frequency == HabitFrequency.weekly:
            start_local = (now_local - timedelta(days=now_local.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
        else:  # monthly
            start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        with Session(self.engine) as s:
            from sqlalchemy import func
            return s.scalar(
                select(func.count(HabitLog.id)).where(
                    HabitLog.user_id == user_id,
                    HabitLog.habit_id == habit_id,
                    HabitLog.logged_at >= start_utc,
                )
            ) or 0

    def deactivate(self, user_id: int, habit_id: int) -> None:
        from sqlalchemy import update as sa_update
        with Session(self.engine) as s:
            s.execute(sa_update(Habit).where(Habit.user_id == user_id, Habit.id == habit_id).values(active=False))
            s.commit()


class DailyPlanRepo:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get_or_create(self, user_id: int, d: date) -> DailyPlan:
        with Session(self.engine) as s:
            plan = s.scalar(select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == d))
            if not plan:
                plan = DailyPlan(user_id=user_id, date=d, task_ids=[])
                s.add(plan)
                s.commit()
                s.refresh(plan)
            return plan

    def mark_sent(self, user_id: int, plan_id: int) -> None:
        with Session(self.engine) as s:
            s.execute(update(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.id == plan_id).values(sent_at=datetime.utcnow()))
            s.commit()
