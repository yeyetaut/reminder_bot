"""
Message formatters for all Telegram digests.
All functions return plain Telegram markdown strings.
"""
from datetime import date, timedelta
from typing import List

import config
from db.models import Task, Project, TaskStatus
from db.repository import TaskRepo, ProjectRepo


def _due_label(task: Task) -> str:
    """Return a human-readable due label like 'today', 'tomorrow', 'in 3 days', or 'overdue'."""
    if not task.due_date:
        return ""
    today = config.get_today()
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


def is_exam(title: str) -> bool:
    """Return True if the title contains exam-related keywords."""
    keywords = ["exam", "quiz", "midterm", "final", "test", "assessment"]
    t = title.lower()
    return any(kw in t for kw in keywords)


def morning_digest(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = config.get_today()

    # Upcoming deadlines in the next 4 days (includes today)
    upcoming = task_repo.upcoming(days=4)
    # Active projects
    active_projects = project_repo.list_active()

    # Filter upcoming to exclude AI-generated tasks (they are shown in the Projects section)
    deadlines = [t for t in upcoming if t.source not in ("ai_plan", "ai_breakdown")]
    
    # Split deadlines into exams and regular tasks
    exams = [t for t in deadlines if is_exam(t.title)]
    tasks = [t for t in deadlines if not is_exam(t.title)]

    lines = [f"● *Plan for {today.strftime('%A, %b %d')}*\n"]

    if not deadlines and not active_projects:
        lines.append("_No tasks scheduled for the next few days._")
        return "\n".join(lines)

    if active_projects:
        lines.append("🟡 *Projects*")
        project_displayed = False
        for p in active_projects:
            pending = [t for t in p.tasks if t.status == TaskStatus.pending and t.source == "ai_breakdown"]
            if not pending:
                continue
            
            project_displayed = True
            lines.append(f"· *{p.title}*")
            # Show top 3 tasks that remain
            for st in pending[:3]:
                # Strip project prefix from sub-task title for cleaner display
                display_title = st.title.split(" — ")[-1] if " — " in st.title else st.title
                lines.append(f"  ▫️ {display_title}")
            
            if len(pending) > 3:
                lines.append(f"  _...and {len(pending)-3} more_")
            lines.append("") # Extra space between projects
        
        if not project_displayed:
            # If no projects had pending ai_breakdown tasks, remove the header we added
            lines.pop()

    if tasks:
        lines.append("🟢 *Deadlines & Tasks*")
        for task in tasks:
            label = _due_label(task)
            lines.append(f"· {task.title}{label}")
            if task.description:
                lines.append(f"  _{task.description}_")
            lines.append("") # Extra space between deadlines

    if exams:
        lines.append("🔴 *Exams*")
        for exam in exams:
            label = _due_label(exam)
            lines.append(f"· {exam.title}{label}")
            if exam.description:
                lines.append(f"  _{exam.description}_")
            lines.append("") # Extra space between exams

    # Footer with IDs for reference (only tasks with deadlines/exams)
    all_ids = [str(t.id) for t in deadlines]
    
    # Add project sub-task IDs to the footer as well so they can be marked done
    for p in active_projects:
        pending = [str(t.id) for t in p.tasks if t.status == TaskStatus.pending and t.source == "ai_breakdown"]
        all_ids.extend(pending[:3]) # Only include IDs for the 3 shown

    lines += [
        "---",
        f"_Actions: /done or /snooze_ · `ID: {', '.join(all_ids)}`",
    ]
    return "\n".join(lines)


def evening_recap(task_repo: TaskRepo) -> str:
    """Returns None if there's nothing worth reporting (skip the message)."""
    today = config.get_today()
    tomorrow = today + timedelta(days=1)

    today_tasks = task_repo.for_date(today)
    done = [t for t in today_tasks if t.status == TaskStatus.done]
    tomorrow_tasks = task_repo.upcoming(days=2)  # tasks due today or tomorrow

    # Only send if something was completed or there's something due tomorrow
    if not done and not tomorrow_tasks:
        return None

    lines = [f"● *Evening Recap · {today.strftime('%b %d')}*\n"]

    if done:
        lines.append("🟢 *Completed*")
        for t in done:
            lines.append(f"· {t.title}")
            lines.append("")

    if tomorrow_tasks:
        lines.append("🟢 *Coming up next*")
        for t in tomorrow_tasks:
            lines.append(f"· {t.title}{_due_label(t)}")
            lines.append("")

    return "\n".join(lines)


def weekly_overview(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = config.get_today()
    upcoming = task_repo.upcoming(days=7)
    active_projects = project_repo.list_active()

    # Filter out AI breakdowns from the regular deadlines list
    deadlines = [t for t in upcoming if t.source not in ("ai_plan", "ai_breakdown")]
    exams = [t for t in deadlines if is_exam(t.title)]
    tasks = [t for t in deadlines if not is_exam(t.title)]

    lines = [f"● *Weekly Overview · week of {today.strftime('%b %d')}*\n"]

    if tasks:
        lines.append(f"🟢 *Tasks ({len(tasks)})*")
        for t in tasks:
            lines.append(f"· {t.title}{_due_label(t)}")
            lines.append("")

    if exams:
        lines.append(f"🔴 *Exams ({len(exams)})*")
        for t in exams:
            lines.append(f"· {t.title}{_due_label(t)}")
            lines.append("")

    if active_projects:
        lines.append(f"🟡 *Projects ({len(active_projects)})*")
        for p in active_projects:
            pending = [t for t in p.tasks if t.status == TaskStatus.pending and t.source == "ai_breakdown"]
            due_str = p.due_date.strftime('%b %d') if p.due_date else "no date"
            lines.append(f"· {p.title} · _{len(pending)} tasks left · due {due_str}_")
            lines.append("")

    if not deadlines and not active_projects:
        lines.append("_No active tasks or projects this week._")

    return "\n".join(lines)


def monthly_overview(task_repo: TaskRepo, project_repo: ProjectRepo) -> str:
    today = config.get_today()
    upcoming = task_repo.upcoming(days=30)
    active_projects = project_repo.list_active()

    # Filter out AI breakdowns from the regular deadlines list
    deadlines = [t for t in upcoming if t.source not in ("ai_plan", "ai_breakdown")]
    exams = [t for t in deadlines if is_exam(t.title)]
    tasks = [t for t in deadlines if not is_exam(t.title)]

    lines = [f"● *Monthly Overview · {today.strftime('%B %Y')}*\n"]

    if tasks:
        lines.append(f"🟢 *Deadlines ({len(tasks)})*")
        for t in tasks:
            due = t.due_date.strftime('%b %d') if t.due_date else "?"
            lines.append(f"· {due} · {t.title}")
            lines.append("")

    if exams:
        lines.append(f"🔴 *Exams ({len(exams)})*")
        for t in exams:
            due = t.due_date.strftime('%b %d') if t.due_date else "?"
            lines.append(f"· {due} · {t.title}")
            lines.append("")

    if active_projects:
        lines.append(f"🟡 *Active Projects*")
        for p in active_projects:
            due_str = p.due_date.strftime('%b %d') if p.due_date else "no date"
            pending = [t for t in p.tasks if t.status == TaskStatus.pending and t.source == "ai_breakdown"]
            lines.append(f"· {p.title} · _{len(pending)} tasks left · due {due_str}_")
            lines.append("")

    if not deadlines and not active_projects:
        lines.append("_Your calendar is clear for the month._")

    return "\n".join(lines)


def project_list(project_repo: ProjectRepo) -> str:
    active = project_repo.list_active()
    if not active:
        return "_No active projects right now._"

    lines = ["● 🟡 *Active Projects*\n"]
    for p in active:
        pending = [t for t in p.tasks if t.status == TaskStatus.pending and t.source == "ai_breakdown"]
        due_str = p.due_date.strftime('%b %d') if p.due_date else "no date"
        lines.append(f"· *{p.title}*")
        lines.append(f"  _{len(pending)} tasks left · due {due_str}_")
        lines.append("")
    return "\n".join(lines)


def exams_overview(task_repo: TaskRepo) -> str:
    """Returns a 180-day outlook for exams."""
    # Look further ahead for exams (6 months)
    upcoming = task_repo.upcoming(days=180)
    
    exams = [t for t in upcoming if is_exam(t.title)]
    
    if not exams:
        return "● 🔴 *Exams*\n\n_No upcoming exams found in the next 6 months._"

    lines = ["● 🔴 *Upcoming Exams*\n"]
    for e in exams:
        label = _due_label(e)
        lines.append(f"· {e.title}{label}")
        if e.description:
            lines.append(f"  _{e.description}_")
        lines.append("")
        
    return "\n".join(lines)


def get_morning_digest_buttons(task_repo: TaskRepo, project_repo: ProjectRepo):
    """Generate an InlineKeyboardMarkup with 'Done' buttons for visible tasks."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    today = config.get_today()

    # 1. Deadlines (next 4 days)
    upcoming = task_repo.upcoming(days=4)
    
    deadlines = []
    for t in upcoming:
        if t.source == "ai_breakdown":
            continue
        if is_exam(t.title):
            # Include exams only if overdue or due today
            if t.due_date and (t.due_date - today).days <= 0:
                deadlines.append(t)
        else:
            deadlines.append(t)
    
    # 2. Project Sub-tasks (top 3 for each)
    active_projects = project_repo.list_active()
    
    buttons = []
    
    # Add project sub-tasks first (matches digest order)
    for p in active_projects:
        pending = [t for t in p.tasks if t.status == TaskStatus.pending and t.source == "ai_breakdown"]
        for st in pending[:3]:
            label = st.title.split(" — ")[-1] if " — " in st.title else st.title
            buttons.append([InlineKeyboardButton(f"✅ {label}", callback_data=f"done_{st.id}")])

    # Add regular deadlines
    for t in deadlines:
        buttons.append([InlineKeyboardButton(f"✅ {t.title}", callback_data=f"done_{t.id}")])

    if not buttons:
        return None
        
    return InlineKeyboardMarkup(buttons)
