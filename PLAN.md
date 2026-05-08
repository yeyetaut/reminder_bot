# Project Plan: Interactive Project Checklists

## Status: Completed ✅

## Objective
Replace rigid, automatically scheduled study blocks with a flexible, interactive checklist system that uses project rubrics/notes for better task breakdown.

## Completed Tasks
- [x] **Phase 1: Database & Dependencies**
    - Added `pypdf` and `python-docx` for document parsing.
    - Added `context_notes` column to `Project` model.
    - Implemented database migration logic in `main.py`.
- [x] **Phase 2: Workflow & Extraction**
    - Implemented `integrations/document_parser.py` for PDF/DOCX text extraction.
    - Created `/checklist` conversation flow in `bot/conversations.py`.
    - Updated sync logic in `bot/telegram_bot.py` and `scheduler/jobs.py` to create reminder tasks instead of immediate AI estimation.
- [x] **Phase 3: AI Generation & Task Creation**
    - Updated `ESTIMATION_PROMPT` in `ai/estimator.py` to generate actionable checklists (sub-tasks).
    - Updated `confirm_estimate` to save sub-tasks with `source="ai_breakdown"`.
    - Updated message formatters in `bot/messages.py` to display checklists in digests.
- [x] **Phase 4: Testing & Verification**
    - Updated `tests/test_estimator.py` to match the new JSON schema.
    - Updated `tests/test_exams.py` to use `ai_breakdown`.
    - Verified all 20 tests pass.
    - Updated repository methods to handle both legacy `ai_plan` and new `ai_breakdown` tasks.

## Next Steps
- Monitor AI performance with complex rubrics.
- Consider adding a way to "re-generate" a checklist if the first one wasn't good enough (already partially supported by clearing and re-running).
