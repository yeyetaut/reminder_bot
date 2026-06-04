from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    create_engine, String, Integer, Boolean, DateTime, Date,
    Float, ForeignKey, JSON, Enum as SAEnum, BigInteger
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class TaskStatus(enum.Enum):
    pending = "pending"
    done = "done"
    skipped = "skipped"


class HabitFrequency(enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class Base(DeclarativeBase):
    pass


class User(Base):
    """Represents a multi-tenant user."""
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canvas_ical_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, default="America/New_York")
    
    # Encrypted fields
    google_credentials_encrypted: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    anthropic_api_key_encrypted: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    gemini_api_key_encrypted: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    projects: Mapped[List["Project"]] = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="user", cascade="all, delete-orphan")
    processed_sources: Mapped[List["ProcessedSource"]] = relationship("ProcessedSource", back_populates="user", cascade="all, delete-orphan")
    daily_plans: Mapped[List["DailyPlan"]] = relationship("DailyPlan", back_populates="user", cascade="all, delete-orphan")
    habits: Mapped[List["Habit"]] = relationship("Habit", back_populates="user", cascade="all, delete-orphan")


class Project(Base):
    """A large assignment or project that spans multiple days."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)          # google_calendar | gmail | outlook | canvas | blackboard
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    context_notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="projects")
    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    """A single actionable work unit, either standalone or part of a project."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    scheduled_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus, native_enum=False, length=50), default=TaskStatus.pending)
    gcal_synced: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="tasks")
    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="tasks")


class ProcessedSource(Base):
    """Memory of source IDs that have already been handled, even if the task was deleted."""
    __tablename__ = "processed_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    source_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    user: Mapped[Optional["User"]] = relationship("User", back_populates="processed_sources")


class DailyPlan(Base):
    """Record of a daily digest that was generated and sent."""
    __tablename__ = "daily_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    task_ids: Mapped[list] = mapped_column(JSON, default=list)   # ordered list of Task.id
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    user: Mapped[Optional["User"]] = relationship("User", back_populates="daily_plans")


class Habit(Base):
    """A recurring habit with a frequency and a target completion count per period."""
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    frequency: Mapped[HabitFrequency] = mapped_column(SAEnum(HabitFrequency, native_enum=False, length=20), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="habits")
    logs: Mapped[List["HabitLog"]] = relationship("HabitLog", back_populates="habit", cascade="all, delete-orphan")


class HabitLog(Base):
    """A single logged completion of a habit."""
    __tablename__ = "habit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    habit_id: Mapped[int] = mapped_column(Integer, ForeignKey("habits.id"), nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.utcnow())

    user: Mapped[Optional["User"]] = relationship("User")
    habit: Mapped["Habit"] = relationship("Habit", back_populates="logs")


def init_db(database_url: str):
    """Create all tables and return the engine."""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return engine
