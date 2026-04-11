from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    create_engine, String, Integer, Boolean, DateTime, Date,
    Float, ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class TaskStatus(enum.Enum):
    pending = "pending"
    done = "done"
    skipped = "skipped"


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A large assignment or project that spans multiple days."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)          # google_calendar | gmail | outlook | canvas | blackboard
    source_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    """A single actionable work unit, either standalone or part of a project."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    scheduled_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), default=TaskStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="tasks")


class DailyPlan(Base):
    """Record of a daily digest that was generated and sent."""
    __tablename__ = "daily_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    task_ids: Mapped[list] = mapped_column(JSON, default=list)   # ordered list of Task.id
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


def init_db(database_url: str):
    """Create all tables and return the engine."""
    import os
    # Ensure the directory exists (important for Railway volume mount at /data)
    if database_url.startswith("sqlite:////"):
        db_path = database_url[len("sqlite:///"):]
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return engine
