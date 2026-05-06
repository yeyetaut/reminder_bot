# Reminder Bot

A personal productivity bot that aggregates deadlines from Google Calendar, Gmail, and Canvas, uses Claude AI to extract and break down tasks, and delivers structured digests via Telegram.

## Features

- **Multi-source sync** — Google Calendar, Gmail (deadline-related emails), and Canvas iCal feed
- **AI task extraction** — Claude Haiku reads raw events/emails and extracts structured tasks, deduplicating by source ID
- **Project estimation** — Claude Sonnet estimates total hours for large projects and proposes a daily work schedule
- **Telegram commands** — `/today`, `/projects`, `/sync`, `/done`, `/snooze`, `/weekly`, `/monthly`
- **Scheduled digests** — morning task list (7:30 AM), evening recap (9:00 PM), weekly overview (Friday 9:00 PM), monthly overview (last day of month 9:30 PM)
- **Google Calendar write-back** — confirmed daily work sessions are created as calendar events

## Project Structure

```
main.py                    # Entry point
config.py                  # Env var loading
startup.py                 # Decodes base64 Google credentials at startup (Railway)
integrations/
  google_auth.py           # Shared OAuth2 token (Calendar + Gmail)
  google_calendar.py       # Read events + create_event()
  gmail.py                 # Read deadline-related emails
  ical_feeds.py            # Canvas iCal feed parser
ai/
  extractor.py             # Haiku: raw events → structured tasks → DB
  estimator.py             # Sonnet: project → estimated hours + daily sessions
db/
  models.py                # SQLAlchemy models: Project, Task, DailyPlan
  repository.py            # CRUD helpers
bot/
  telegram_bot.py          # Command handlers
  messages.py              # Digest formatters
  conversations.py         # Estimate confirmation flow
scheduler/
  jobs.py                  # APScheduler cron jobs
```

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd reminder_bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Credentials

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | How to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Create a bot via [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_CHAT_ID` | Send a message to your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `GOOGLE_CREDENTIALS_FILE` | Google Cloud Console → enable Gmail + Calendar APIs → OAuth 2.0 → download `credentials.json` |
| `CANVAS_ICAL_URL` | Canvas → Account → Calendar → "Calendar Feed" → copy URL |
| `TIMEZONE` | e.g. `Asia/Singapore`, `America/New_York` |

#### Google OAuth setup

On first run, a browser window will open to authorize Google access. This generates `token.json` which covers both Gmail and Google Calendar.

```bash
python main.py
```

### 3. Run locally

```bash
python main.py
```

## Railway Deployment

The bot is designed for [Railway](https://railway.com) deployment.

### Environment variables (Railway)

Set all variables from `.env` in Railway → your service → **Variables**. Additionally:

| Variable | Value |
|---|---|
| `GOOGLE_CREDENTIALS_B64` | `base64 -i credentials.json` |
| `GOOGLE_TOKEN_B64` | `base64 -i token.json` (generate locally first) |

**Encoding the files:**

```bash
# macOS
base64 -i credentials.json | tr -d '\n'
base64 -i token.json | tr -d '\n'
```

Paste each output (starting with `eyJ...`) as the corresponding Railway variable. At startup, `startup.py` decodes these back into files before the bot initializes.

### Re-deploying after token refresh

If the Google token expires and auto-refresh fails, re-run the OAuth flow locally and re-encode `token.json`:

```bash
python main.py   # triggers re-auth if token is invalid
base64 -i token.json | tr -d '\n'
# paste output into GOOGLE_TOKEN_B64 in Railway
```

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Show command list |
| `/today` | Today's tasks ordered by deadline |
| `/projects` | Active projects with completion status |
| `/sync` | Manually re-fetch from all sources |
| `/done <number or title>` | Mark a task complete |
| `/snooze <number or title>` | Push a task to tomorrow |
| `/weekly` | This week's overview |
| `/monthly` | This month's recap |

## Scheduled Jobs

| Job | Time |
|---|---|
| Auto-sync | Daily 7:00 AM |
| Morning digest | Daily 7:30 AM |
| Evening recap | Daily 9:00 PM |
| Weekly overview | Friday 9:00 PM |
| Monthly overview | Last day of month, 9:30 PM |

All times use the `TIMEZONE` environment variable.
