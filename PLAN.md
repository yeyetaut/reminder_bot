# Reminder Bot Project Plan

## Completed
- [x] Initial setup and bot structure.
- [x] Google Calendar, Gmail, and Canvas integrations.
- [x] AI task extraction (Claude Haiku).
- [x] Project estimation and breakdown (Claude Sonnet).
- [x] Database persistence (SQLAlchemy).
- [x] Automated digests and recaps (APScheduler).
- [x] **Auto-delete strategy**:
    - [x] Added `ProcessedSource` for deduplication memory.
    - [x] Added `completed_at` to tasks.
    - [x] Implemented daily cleanup job.
    - [x] Optimized iCal sync to skip past events.

## To Do
- [ ] Multi-user support (Verify full deployment and isolation).
- [x] Improved snooze options (Interactive buttons in digest).
- [x] Interactive checklist management (Interactive buttons for confirmation).
