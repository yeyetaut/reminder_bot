# Reminder Bot — Implementation Plan

## Context
Build a personal productivity bot that aggregates tasks and deadlines from multiple calendar/email sources, uses Claude AI to analyze and break down large projects into daily tasks, and delivers structured digests via Telegram. The user is a student using Google Calendar, Canvas, and Gmail as their primary sources.

---

## Phases Overview
| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project scaffold + database + config | ✅ Complete |
| 2 | Calendar/email integrations | ✅ Complete |
| 3 | AI layer (extraction + estimation) | ✅ Complete |
| 4 | Telegram bot (commands + confirmation flow) | ✅ Complete |
| 5 | Scheduler (automated digests) | ✅ Complete |
| 6 | Deployment (Railway) | ✅ Complete |

---

## Phase 1 — Scaffold, Config & Database ✅

### Files
- `main.py` — entry point, initializes DB, starts bot
- `config.py` — loads all env vars via `python-dotenv`
- `.env.example` — credential template
- `.claudeignore` / `.gitignore` — protects `.env`, `token.json`, `credentials.json`
- `requirements.txt`
- `db/models.py` — `Project`, `Task`, `DailyPlan` SQLAlchemy models
- `db/repository.py` — CRUD helpers for all 3 models

---

## Phase 2 — Integrations ✅

> **Scope:** Google Calendar, Gmail, Canvas iCal only.
> Outlook skipped (no app registration access). Blackboard deferred.

### Files
- `integrations/google_auth.py` — shared OAuth2 token covering Calendar + Gmail (single browser flow)
- `integrations/google_calendar.py` — reads events 30 days forward; `create_event()` for write-back
- `integrations/gmail.py` — searches Gmail with targeted query (deadlines, payments, meetings); excludes promotions/newsletters/noreply senders
- `integrations/ical_feeds.py` — fetches Canvas iCal URL, parses VEVENT; resolves dates from DTEND, DUE, or DTSTART

### Notes
- Gmail filter: `label:important` OR subject keywords, minus `label:promotions`, `label:social`, `label:updates`, `-from:noreply`
- Canvas dates resolved via `DUE` field fallback (many Canvas events omit DTEND)

---

## Phase 3 — AI Layer ✅

### Files
- `ai/extractor.py` — deduplicates by `source_id` before AI call; sends compact fields only (title, date, snippet ≤150 chars); single batched Haiku call; falls back to direct calendar save if AI credits unavailable
- `ai/estimator.py` — one Sonnet call per new project; returns estimated hours + daily session schedule; `format_proposal_message()` formats for Telegram

### Token strategy
| Operation | Model | When |
|-----------|-------|------|
| Task extraction | `claude-haiku-4-5` | Once per sync, batched |
| Project estimation | `claude-sonnet-4-6` | Once per new project |
| Fallback (no credits) | None | Calendar events saved directly, emails skipped |

---

## Phase 4 — Telegram Bot ✅

### Files
- `bot/telegram_bot.py` — all command handlers, `/sync` triggers AI extraction + estimate proposals
- `bot/messages.py` — formatters: morning digest, evening recap, weekly/monthly overviews, project list
- `bot/conversations.py` — estimate confirmation flow: confirm / adjust hours / skip

### Commands
| Command | Action |
|---------|--------|
| `/start` | Onboarding + command list |
| `/today` | Today's tasks (falls back to upcoming 3 days if none scheduled) |
| `/projects` | Active projects + sessions remaining |
| `/done <number\|title>` | Mark task complete |
| `/snooze <number\|title>` | Push task to tomorrow |
| `/sync` | Re-fetch all sources, extract tasks, propose estimates |
| `/weekly` | Week overview |
| `/monthly` | Month overview |
| `/confirm_estimate` | Accept AI project plan → saves tasks + Google Calendar events |
| `/adjust_hours <n>` | Re-scale daily sessions to new hour total |
| `/skip_estimate` | Mark project confirmed with no daily breakdown |

### Running the bot
```bash
cd "/Users/yeyetaut/Desktop/Dev Projects/Reminder_bot"
venv/bin/python main.py > /tmp/reminder_bot.log 2>&1 &
tail -f /tmp/reminder_bot.log
```

---

## Phase 5 — Scheduler ✅

### File
- `scheduler/jobs.py` — APScheduler cron jobs wired to `TIMEZONE` env var

### Schedule
| Job | Trigger | Content |
|-----|---------|---------|
| Auto-sync | Daily 7:00 AM | Re-fetch all sources |
| Morning digest | Daily 7:30 AM | Today's tasks ordered by deadline |
| Evening recap | Daily 9:00 PM | Done/skipped recap + tomorrow preview |
| Weekly overview | Friday 9:00 PM | Week summary + next week big items |
| Monthly overview | Last calendar day 9:30 PM | Month recap + upcoming deadlines |

---

## Recent Fixes (2026-04-12)

### Duplicate project detection
- `ai/extractor.py`: Before saving a new project, checks if any existing project has ≥72% title similarity (`difflib.SequenceMatcher`). Duplicates from study-segment emails are silently dropped.
- `db/repository.py`: Added `ProjectRepo.list_all()` to support the title comparison.

### Multi-project pending proposals
- `bot/conversations.py`: Pending proposals stored as a list. When multiple projects are detected at once, all are queued and labeled `[Project N]`.
- `/confirm_estimate [index]`, `/adjust_hours [index] <hours>`, `/skip_estimate [index]` now accept an optional 1-based index to target any pending project. Default is project 1 (oldest).
- After confirming/skipping, the bot notifies the user if more proposals remain.

### Split /sync into daily vs. full
- `/sync` → today's emails only (`newer_than:1d`) + calendar. Fast daily check.
- `/totalsync` → full sync: 14 days of emails + 30 days calendar (old `/sync` behavior).
- 7 AM auto-sync job also uses the 1-day email filter.

---

## Phase 6 — Deployment (Railway) ✅

### Platform
Deployed on [Railway](https://railway.com) as a persistent worker service.

### Key files
- `railway.json` — `startCommand: python main.py`, restart on failure
- `Procfile` — `worker: python main.py`
- `.railwayignore` — excludes `venv/`, `*.db`, `token.json`, `credentials.json`, `.env`
- `startup.py` — decodes `GOOGLE_CREDENTIALS_B64` → `credentials.json` and `GOOGLE_TOKEN_B64` → `token.json` at startup

### Railway environment variables required
| Variable | Notes |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `ANTHROPIC_API_KEY` | Anthropic console |
| `GOOGLE_CREDENTIALS_B64` | `base64 -i credentials.json \| tr -d '\n'` |
| `GOOGLE_TOKEN_B64` | `base64 -i token.json \| tr -d '\n'` (run OAuth locally first) |
| `CANVAS_ICAL_URL` | Canvas calendar feed URL |
| `TIMEZONE` | e.g. `Asia/Singapore` |

---

## Tech Stack
- **Language**: Python 3.10 (on Mac) / 3.11+ recommended for VPS
- **Telegram**: `python-telegram-bot` v20+
- **Google APIs**: `google-api-python-client` + `google-auth-oauthlib`
- **LMS**: `icalendar` + `requests` (Canvas iCal feed)
- **AI**: `anthropic` SDK — Haiku for extraction, Sonnet for estimation
- **Database**: `SQLAlchemy` + SQLite (`reminder_bot.db`)
- **Scheduler**: `APScheduler`
- **Config**: `python-dotenv`

---

## Project Structure
```
Reminder_bot/
├── main.py                    # Entry point
├── config.py                  # Env var loader
├── .env                       # Credentials (git-ignored, claude-ignored)
├── .env.example               # Credential template
├── .claudeignore              # Blocks Claude from reading secrets
├── .gitignore
├── requirements.txt
├── reminder_bot.db            # SQLite database
├── credentials.json           # Google OAuth app creds (git-ignored)
├── token.json                 # Google OAuth token (git-ignored)
│
├── integrations/
│   ├── google_auth.py         # Shared OAuth2 credentials
│   ├── google_calendar.py     # Read + write Google Calendar
│   ├── gmail.py               # Read Gmail (filtered)
│   └── ical_feeds.py          # Canvas iCal parser
│
├── ai/
│   ├── extractor.py           # Haiku extraction + fallback
│   └── estimator.py           # Sonnet project estimation
│
├── db/
│   ├── models.py              # Task, Project, DailyPlan models
│   └── repository.py          # CRUD helpers
│
├── bot/
│   ├── telegram_bot.py        # Command handlers + bot builder
│   ├── messages.py            # Digest formatters
│   └── conversations.py       # Estimate confirmation flow
│
└── scheduler/
    └── jobs.py                # (Phase 5) APScheduler cron jobs
```

---

## Credentials
| Service | Status | How to get |
|---------|--------|------------|
| Telegram Bot Token | ✅ | @BotFather |
| Telegram Chat ID | ✅ | getUpdates API |
| Google OAuth (`credentials.json`) | ✅ | Cloud Console → OAuth 2.0 Desktop app |
| Canvas iCal URL | ✅ | Canvas → Account → Calendar Feed |
| Anthropic API Key | ⚠️ needs credits | console.anthropic.com → Plans & Billing |
