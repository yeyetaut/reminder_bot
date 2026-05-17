# Reminder Bot - Implementation Plan

## Recently Completed
- [x] Multi-user support with `User` model and `user_id` foreign keys in all tables.
- [x] Web-based Google OAuth flow with `aiohttp` callback server.
- [x] Per-user API keys for Anthropic and Gemini.
- [x] Redesigned `/start` menu using HTML parse mode.
- [x] Fix: Ensure Gmail tasks are written to Google Calendar with valid exclusive end dates.
- [x] AI Checklist feature with file upload support.
- [x] Fix: Retry syncing all `unsynced_tasks` during manual and background syncs (ensures Gmail tasks are correctly added to GCal).

## Immediate Tasks
- [x] **Cleanup Migration Artifacts:** Remove `patch_*.py` and `fix_*.py` files from the root directory after verifying they are fully integrated.
- [x] **Verify Multi-user Isolation:** Add a test case to ensure users cannot see or modify each other's data.
- [x] **Refine `/status` Command:** Ensure consistent formatting (currently a mix of Markdown and HTML across commands) and add user-specific info.
- [ ] **Improve Error Handling:** Better messaging when Google token refresh fails or when AI keys are missing.


## Future Enhancements
- [ ] **Canvas Webhook Integration:** Explore moving from iCal polling to webhooks for real-time updates.
- [ ] **Proactive Notifications:** Allow users to customize notification times for morning and evening digests.
- [ ] **Multiple Canvas URLs:** Support for users who have multiple Canvas accounts (e.g., teaching and learning).
- [ ] **Better Project Visualization:** Progress bars for projects in `/projects` command.
