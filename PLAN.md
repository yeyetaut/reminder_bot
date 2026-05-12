# Reminder Bot - Project Plan

## Bugs Fixed
- [x] **Timezone Inconsistency in Daily Digest**: Fixed an issue where the morning digest would use the server's local time (UTC) instead of the user's configured timezone.
- [x] **Non-functional Inline Buttons**: Fixed an issue where 'Done' buttons in Telegram digests were unresponsive because the bot was not listening for `callback_query` updates.
    - Updated `main.py` to allow `callback_query` updates.
    - Refined `handle_callback_done` with `python-pro` for idempotency, safer parsing, and robust error handling.
    - Added a comprehensive test suite with `qa-expert` covering 7 edge cases (idempotency, markdown escaping, API errors, etc.).

## Process Improvements
- [x] **Subagent Workflow**: Documented and implemented a mandatory workflow using `python-pro` for code and `qa-expert` for testing in `GEMINI.md`.

## Ongoing Tasks
- [ ] Improve test coverage for other Telegram handlers.
- [ ] Add integration tests for Google Calendar and Gmail mocks.
- [ ] Implement robust error handling for AI API failures.
