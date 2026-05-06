"""
Message formatters for all Telegram digests.
All functions return plain Telegram markdown strings.
"""
from datetime import date, timedelta
from typing import List

from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo


def _due_label(task: Task) -> str:
    """Return a human-readable due label like 'today', 'tomorrow', 'in 3 days', or 'overdue'."""
    if not task.due_date:
        return ""
    today = date.today()
    delta = (task.due_date - today).days
    if delta < 0:
        return " ! _overdue_"
    if delta == 0:
        return " · _today_"
    if delta == 1:
        return " · _tomorrow_"
    if delta <= 7:
        return f" · _{delta}d_"
    return f" · _{task.due_date.strftime('%b %d')}_"


def morning_digest(task_repo: TaskRepo) -> str:
    today = date.today()

    # AI-planned sessions scheduled for today
    planned = task_repo.for_date(today)
    # Upcoming deadlines in the next 4 days (includes today)
    upcoming = task_repo.upcoming(days=4)

    # Filter upcoming to exclude AI sessions (which are in 'planned')
    deadlines = [t for t in upcoming if t.source != "ai_plan"]

    lines = [f"● *Plan for {today.strftime('%A, %b %d')}*\n"]

    if not planned and not deadlines:
        lines.append("_No tasks scheduled for the next few days._")
        return "\n".join(lines)

    if planned:
        lines.append("*Focus Sessions*")
        for task in planned:
            lines.append(f"· {task.title}")
            if task.description:
                lines.append(f"  _{task.description}_")
        lines.append("")

    if deadlines:
        lines.append("*Deadlines & Tasks*")
        for task in deadlines:
            label = _due_label(task)
            lines.append(f"· {task.title}{label}")
            if task.description:
                lines.append(f"  _{task.description}_")
        lines.append("")

    # Footer with IDs for reference
    all_ids = [str(t.id) for t in planned + deadlines]
    lines += [
        "---",
        f"_Actions: /done or /snooze_ · `ID: {', '.join(all_ids)}`",
    ]
    return "\n".join(lines)


def evening_recap(task_repo: TaskRepo) -> str:
    """Returns None if there's nothing worth reporting (skip the message)."""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    today_tasks = task_repo.for_date(today)
    done = [t for t in today_tasks if t.status == TaskStatus.done]
    tomorrow_tasks = task_repo.upcoming(days=2)  # tasks due today or tomorrow

    # Only send if something was completed or there's something due tomorrow
    if not done and not tomorrow_tasks:
        return None

    lines = [f"● *Evening Recap · {today.strftime('%b %d')}*\n"]

    if done:
        lines.append("*Completed*")
        for t in done:
            lines.append(f"· {t.title}")
        lines.append("")

    if tomorrow_tasks:
        lines.append("*Coming up next*")
        for t in tomorrow_tasks:
            lines.append(f"· {t.title}{_due_label(t)}")

    return "\n".join(lines)


def weekly_overview(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = date.today()
    upcoming = task_repo.upcoming(days=7)
    active_projects = project_repo.list_active()

    lines = [f"● *Weekly Overview · week of {today.strftime('%b %d')}*\n"]

    if upcoming:
        lines.append(f"*Tasks ({len(upcoming)})*")
        for t in upcoming:
            lines.append(f"· {t.title}{_due_label(t)}")
        lines.append("")

    if active_projects:
        lines.append(f"*Projects ({len(active_projects)})*")
        for p in active_projects:
            pending = [t for t in p.tasks if t.status == TaskStatus.pending]
            due_str = p.due_date.strftime('%b %d') if p.due_date else "no date"
            lines.append(f"· {p.title} · _{len(pending)} sessions left · due {due_str}_")
        lines.append("")

    if not upcoming and not active_projects:
        lines.append("_No active tasks or projects this week._")

    return "\n".join(lines)


def monthly_overview(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = date.today()
    upcoming = task_repo.upcoming(days=30)
    active_projects = project_repo.list_active()

    lines = [f"● *Monthly Overview · {today.strftime('%B %Y')}*\n"]

    if upcoming:
        lines.append(f"*Deadlines ({len(upcoming)})*")
        for t in upcoming:
            due = t.due_date.strftime('%b %d') if t.due_date else "?"
            lines.append(f"· {due} · {t.title}")
        lines.append("")

    if active_projects:
        lines.append(f"*Active Projects*")
        for p in active_projects:
            due_str = p.due_date.strftime('%b %d') if p.due_date else "no date"
            hours = f"{p.estimated_hours}h" if p.estimated_hours else "unestimated"
            lines.append(f"· {p.title} · _{hours} · due {due_str}_")

    if not upcoming and not active_projects:
        lines.append("_Your calendar is clear for the month._")

    return "\n".join(lines)


def project_list(project_repo: ProjectRepo) -> str:
    active = project_repo.list_active()
    if not active:
        return "_No active projects right now._"

    lines = ["● *Active Projects*\n"]
    for p in active:
        pending = [t for t in p.tasks if t.status == TaskStatus.pending]
        due_str = p.due_date.strftime('%b %d') if p.due_date else "no date"
        hours = f"{p.estimated_hours}h" if p.estimated_hours else "unestimated"
        lines.append(f"· *{p.title}*")
        lines.append(f"  _{len(pending)} sessions left · {hours} · due {due_str}_")
        lines.append("")
    return "\n".join(lines)
