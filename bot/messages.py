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
        return " ⚠️ overdue"
    if delta == 0:
        return " — due TODAY"
    if delta == 1:
        return " — due tomorrow"
    if delta <= 7:
        return f" — due in {delta}d"
    return f" — due {task.due_date.strftime('%b %d')}"


def morning_digest(task_repo: TaskRepo) -> str:
    today = date.today()

    # AI-planned sessions scheduled for today
    planned = task_repo.for_date(today)
    # Upcoming deadlines in the next 4 days (includes today)
    upcoming = task_repo.upcoming(days=4)

    # Merge: planned first, then upcoming not already in planned
    planned_ids = {t.id for t in planned}
    combined = planned + [t for t in upcoming if t.id not in planned_ids]

    lines = [f"☀️ *Good morning\\! Here's your plan for {today.strftime('%A, %b %d')}*\n"]

    if not combined:
        lines.append("No tasks in the next 4 days\\. Enjoy your day\\! 🎉")
        return "\n".join(lines)

    for task in combined:
        label = _due_label(task)
        lines.append(f"\\[{task.id}\\] {task.title}{label}")
        if task.description:
            lines.append(f"   _{task.description}_")

    lines += [
        "",
        f"📋 {len(combined)} task(s) — use /done <id> or /snooze <id>",
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

    lines = [f"🌙 *Evening Recap — {today.strftime('%A, %b %d')}*\n"]

    if done:
        lines.append(f"✅ *Done today ({len(done)}):*")
        for t in done:
            lines.append(f"  • {t.title}")
        lines.append("")

    if tomorrow_tasks:
        lines.append(f"📅 *Coming up:*")
        for t in tomorrow_tasks:
            lines.append(f"  • {t.title}{_due_label(t)}")

    return "\n".join(lines)


def weekly_overview(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = date.today()
    week_end = today + timedelta(days=7)

    upcoming = task_repo.upcoming(days=7)
    active_projects = project_repo.list_active()

    lines = [f"📊 *Weekly Overview — week of {today.strftime('%b %d')}*\n"]

    if upcoming:
        lines.append(f"*Upcoming tasks ({len(upcoming)}):*")
        for t in upcoming:
            lines.append(f"  • {t.title}{_due_label(t)}")
        lines.append("")

    if active_projects:
        lines.append(f"*Active projects ({len(active_projects)}):*")
        for p in active_projects:
            pending = [t for t in p.tasks if t.status == TaskStatus.pending]
            due_str = p.due_date.strftime('%b %d') if p.due_date else "no due date"
            lines.append(f"  • {p.title} — {len(pending)} sessions left, due {due_str}")
        lines.append("")

    if not upcoming and not active_projects:
        lines.append("Nothing on the radar this week\\. 🎉")

    return "\n".join(lines)


def monthly_overview(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = date.today()
    upcoming = task_repo.upcoming(days=30)
    active_projects = project_repo.list_active()

    lines = [f"📆 *Monthly Overview — {today.strftime('%B %Y')}*\n"]

    if upcoming:
        lines.append(f"*All upcoming deadlines ({len(upcoming)}):*")
        for t in upcoming:
            due = t.due_date.strftime('%b %d') if t.due_date else "?"
            lines.append(f"  • {due} — {t.title}")
        lines.append("")

    if active_projects:
        lines.append(f"*Active projects ({len(active_projects)}):*")
        for p in active_projects:
            due_str = p.due_date.strftime('%b %d') if p.due_date else "no due date"
            hours = f"{p.estimated_hours}h" if p.estimated_hours else "unestimated"
            lines.append(f"  • {p.title} — {hours}, due {due_str}")

    if not upcoming and not active_projects:
        lines.append("Clear calendar ahead\\! 🎉")

    return "\n".join(lines)


def project_list(project_repo: ProjectRepo) -> str:
    active = project_repo.list_active()
    if not active:
        return "No active projects right now\\. 🎉"

    lines = ["*Active Projects:*\n"]
    for i, p in enumerate(active, 1):
        pending = [t for t in p.tasks if t.status == TaskStatus.pending]
        due_str = p.due_date.strftime('%b %d') if p.due_date else "no due date"
        hours = f"{p.estimated_hours}h estimated" if p.estimated_hours else "unestimated"
        lines.append(f"{i}\\. *{p.title}*")
        lines.append(f"   {len(pending)} sessions left • {hours} • due {due_str}")
    return "\n".join(lines)
