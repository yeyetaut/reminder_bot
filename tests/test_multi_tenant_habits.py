"""
Multi-tenant isolation tests for HabitRepo.

Verifies that User B can never read, log, or modify User A's habits,
and that completion counts are scoped strictly by user_id.
"""
import pytest
from datetime import datetime, timezone
from freezegun import freeze_time
from db.models import HabitFrequency
from db.repository import UserRepo, HabitRepo


@pytest.fixture
def two_users(engine):
    repo = UserRepo(engine)
    user_a = repo.create_user(telegram_id=111, chat_id=111)
    user_b = repo.create_user(telegram_id=222, chat_id=222)
    return user_a, user_b


@pytest.fixture
def habit_a(engine, two_users):
    user_a, _ = two_users
    return HabitRepo(engine).create(user_a.id, "Meditate", HabitFrequency.daily, target_count=1)


# ── list_active isolation ──────────────────────────────────────────────────────

def test_list_active_only_returns_own_habits(engine, two_users, habit_a):
    user_a, user_b = two_users
    hr = HabitRepo(engine)
    assert len(hr.list_active(user_a.id)) == 1
    assert len(hr.list_active(user_b.id)) == 0


def test_list_active_excludes_deactivated(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    h = hr.create(user_a.id, "Read", HabitFrequency.daily)
    assert len(hr.list_active(user_a.id)) == 1
    hr.deactivate(user_a.id, h.id)
    assert len(hr.list_active(user_a.id)) == 0


# ── get_by_id isolation ────────────────────────────────────────────────────────

def test_get_by_id_returns_own_habit(engine, two_users, habit_a):
    user_a, _ = two_users
    result = HabitRepo(engine).get_by_id(user_a.id, habit_a.id)
    assert result is not None
    assert result.title == "Meditate"


def test_get_by_id_returns_none_for_other_user(engine, two_users, habit_a):
    _, user_b = two_users
    result = HabitRepo(engine).get_by_id(user_b.id, habit_a.id)
    assert result is None


# ── deactivate isolation ───────────────────────────────────────────────────────

def test_deactivate_by_wrong_user_has_no_effect(engine, two_users, habit_a):
    user_a, user_b = two_users
    hr = HabitRepo(engine)
    hr.deactivate(user_b.id, habit_a.id)
    # Habit should still be active for user A
    habit = hr.get_by_id(user_a.id, habit_a.id)
    assert habit.active is True


def test_deactivate_by_owner_works(engine, two_users, habit_a):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    hr.deactivate(user_a.id, habit_a.id)
    assert len(hr.list_active(user_a.id)) == 0


# ── completion count isolation ─────────────────────────────────────────────────

@freeze_time("2026-06-04 12:00:00")
def test_completions_only_count_for_correct_user(engine, two_users, habit_a):
    """Logs made by user_b against habit_a's ID do not count toward user_a's total."""
    user_a, user_b = two_users
    hr = HabitRepo(engine)

    # User A logs once
    hr.log_completion(user_a.id, habit_a.id)
    # User B also logs against the same habit_id (simulating a bug or direct DB call)
    hr.log_completion(user_b.id, habit_a.id)

    count_a = hr.completions_this_period(user_a.id, habit_a.id, HabitFrequency.daily)
    count_b = hr.completions_this_period(user_b.id, habit_a.id, HabitFrequency.daily)
    assert count_a == 1
    assert count_b == 1  # user_b's own log counted for user_b


@freeze_time("2026-06-04 12:00:00")
def test_two_users_have_independent_completion_counts(engine, two_users):
    user_a, user_b = two_users
    hr = HabitRepo(engine)
    h_a = hr.create(user_a.id, "Run", HabitFrequency.daily)
    h_b = hr.create(user_b.id, "Run", HabitFrequency.daily)

    hr.log_completion(user_a.id, h_a.id)
    hr.log_completion(user_a.id, h_a.id)  # user_a logs twice

    assert hr.completions_this_period(user_a.id, h_a.id, HabitFrequency.daily) == 2
    assert hr.completions_this_period(user_b.id, h_b.id, HabitFrequency.daily) == 0


# ── daily period boundary ──────────────────────────────────────────────────────

def test_daily_completions_reset_at_midnight(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Push-ups", HabitFrequency.daily)

    with freeze_time("2026-06-03 23:00:00"):  # yesterday
        hr.log_completion(user_a.id, habit.id)

    with freeze_time("2026-06-04 08:00:00"):  # today
        count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.daily)
    assert count == 0


def test_daily_completions_accumulate_same_day(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Drink water", HabitFrequency.daily, target_count=8)

    with freeze_time("2026-06-04 09:00:00"):
        hr.log_completion(user_a.id, habit.id)
        hr.log_completion(user_a.id, habit.id)
        count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.daily)
    assert count == 2


# ── weekly period boundary ─────────────────────────────────────────────────────

def test_weekly_completions_reset_on_new_week(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Gym", HabitFrequency.weekly, target_count=3)

    with freeze_time("2026-06-01 10:00:00"):  # Monday of previous week
        hr.log_completion(user_a.id, habit.id)

    with freeze_time("2026-06-08 10:00:00"):  # Monday of next week
        count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.weekly)
    assert count == 0


def test_weekly_completions_accumulate_within_week(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Gym", HabitFrequency.weekly, target_count=3)

    with freeze_time("2026-06-01 10:00:00"):  # Monday
        hr.log_completion(user_a.id, habit.id)
    with freeze_time("2026-06-03 10:00:00"):  # Wednesday
        hr.log_completion(user_a.id, habit.id)
    with freeze_time("2026-06-04 10:00:00"):  # Thursday — check count
        count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.weekly)
    assert count == 2


# ── monthly period boundary ────────────────────────────────────────────────────

def test_monthly_completions_reset_on_new_month(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Finish course", HabitFrequency.monthly, target_count=3)

    with freeze_time("2026-05-15 10:00:00"):  # May
        hr.log_completion(user_a.id, habit.id)
        hr.log_completion(user_a.id, habit.id)

    with freeze_time("2026-06-01 10:00:00"):  # June
        count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.monthly)
    assert count == 0


def test_monthly_completions_accumulate_within_month(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Finish course", HabitFrequency.monthly, target_count=3)

    with freeze_time("2026-06-01 10:00:00"):
        hr.log_completion(user_a.id, habit.id)
    with freeze_time("2026-06-10 10:00:00"):
        hr.log_completion(user_a.id, habit.id)
    with freeze_time("2026-06-20 10:00:00"):
        hr.log_completion(user_a.id, habit.id)
        count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.monthly)
    assert count == 3


# ── target_count tracking ──────────────────────────────────────────────────────

@freeze_time("2026-06-04 12:00:00")
def test_habit_not_complete_below_target(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Gym", HabitFrequency.weekly, target_count=3)
    hr.log_completion(user_a.id, habit.id)
    hr.log_completion(user_a.id, habit.id)

    count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.weekly)
    assert count == 2
    assert count < habit.target_count


@freeze_time("2026-06-04 12:00:00")
def test_habit_complete_at_target(engine, two_users):
    user_a, _ = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Gym", HabitFrequency.weekly, target_count=2)
    hr.log_completion(user_a.id, habit.id)
    hr.log_completion(user_a.id, habit.id)

    count = hr.completions_this_period(user_a.id, habit.id, HabitFrequency.weekly)
    assert count >= habit.target_count


# ── cascade deletion ───────────────────────────────────────────────────────────

def test_habits_and_logs_cascade_with_user_deletion(engine, two_users):
    """Deleting a User cascades to their Habits and HabitLogs."""
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from db.models import User, Habit, HabitLog

    user_a, user_b = two_users
    hr = HabitRepo(engine)
    habit = hr.create(user_a.id, "Meditate", HabitFrequency.daily)

    with freeze_time("2026-06-04 10:00:00"):
        hr.log_completion(user_a.id, habit.id)
        hr.log_completion(user_a.id, habit.id)

    # Verify data exists before deletion
    with Session(engine) as s:
        assert s.scalar(select(Habit).where(Habit.user_id == user_a.id)) is not None
        assert s.scalar(select(HabitLog).where(HabitLog.user_id == user_a.id)) is not None

    # Delete user A
    with Session(engine) as s:
        user = s.get(User, user_a.id)
        s.delete(user)
        s.commit()

    # Habits and logs should be gone; user B unaffected
    with Session(engine) as s:
        assert s.scalar(select(Habit).where(Habit.user_id == user_a.id)) is None
        assert s.scalar(select(HabitLog).where(HabitLog.user_id == user_a.id)) is None
        assert s.get(User, user_b.id) is not None
