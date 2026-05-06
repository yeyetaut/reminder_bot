# Codebase Improvement Plan

This plan outlines the steps to address the logical and architectural issues identified in the codebase audit.

## Phase 0: Testing & Stability

- [x] **Implement Formal Testing Suite:**
    - Set up `pytest` environment and `conftest.py`.
    - Add unit tests for `db/repository.py`, `ai/extractor.py`, `ai/estimator.py`, and `bot/messages.py`.
    - **Bug Fixes identified during testing:**
        - Fixed `InvalidRequestError` in `ProjectRepo.list_unconfirmed` and `list_active` (missing `.unique()` call for joined eager loads).
        - Fixed whitespace handling in `ai/extractor._normalize_title`.

## Phase 1: Efficiency & Reliability (Immediate Fixes)

- [x] **Fix Inefficient Migrations:** 
    - Move `_migrate_scheduled_dates` from `TaskRepo.__init__` to a one-time startup sequence in `main.py`.
    - Ensure all schema changes are handled centrally at startup.
- [ ] **Improve Error Transparency:**
    - Refactor `integrations/` to avoid broad `try-except Exception` blocks that return empty results silently.
    - Implement specific exception handling (e.g., `googleapiclient.errors.HttpError`) and bubble up meaningful errors to the UI/Telegram logs.

## Phase 2: Data Integrity & AI Robustness

- [ ] **Atomic Sync Transactions:**
    - Wrap the sync process in a more robust transaction management system.
    - Ensure that database writes and external API "write-backs" (like GCal event creation) are synchronized or idempotent.
- [ ] **Strict AI Validation:**
    - Implement a validation layer (e.g., using Pydantic or a dedicated schema validator) for AI-generated JSON.
    - Add retry logic for malformed AI responses.
- [ ] **Robust Deduplication:**
    - Move away from simple fuzzy matching for projects.
    - Use a combination of `source_id`, date ranges, and more sophisticated similarity checks (possibly AI-assisted or stricter thresholding).

## Phase 3: Scalability

- [ ] **Database Optimization:**
    - Evaluate moving from SQLite to PostgreSQL if the user base or task volume grows.
    - Optimize long-running sync operations to prevent "Database is locked" errors.
