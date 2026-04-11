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
| 5 | Scheduler (automated digests) | 🔲 Next |
| 6 | Deployment setup (VPS) | 🔲 Pending |

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

## Phase 5 — Scheduler (Next) 🔲

### Goals
- Send automated digests without user triggering them

### File to create
- `scheduler/jobs.py` — APScheduler cron jobs

### Schedule
| Job | Trigger | Content |
|-----|---------|---------|
| Morning digest | Daily 7:30 AM | Today's tasks ordered by deadline |
| Evening recap | Daily 9:00 PM | Done/skipped recap + tomorrow preview |
| Weekly overview | Friday 9:00 PM | Week summary + next week big items |
| Monthly overview | Last calendar day 9:00 PM | Month recap + upcoming deadlines |

### Deliverable
All 4 jobs registered at startup; manually invoking each sends correct Telegram message.

---

## Phase 6 — Deployment (VPS) 🔲

### Goals
- Run bot persistently on a Linux VPS

### Steps
1. Copy project to VPS, create `venv`, install deps
2. Copy `.env`, `credentials.json`, `token.json` to VPS
3. Install systemd service:
```ini
[Unit]
Description=Reminder Bot
[Service]
WorkingDirectory=/opt/reminder_bot
ExecStart=/opt/reminder_bot/venv/bin/python main.py
Restart=always
[Install]
WantedBy=multi-user.target
```

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
