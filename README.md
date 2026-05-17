# Reminder Bot

A multi-user personal productivity bot that aggregates deadlines from Google Calendar, Gmail, and Canvas, uses Claude AI to extract and break down tasks, and delivers structured digests via Telegram.

## 🚀 Features

- **Multi-Source Sync** — Automatically pulls deadlines from Google Calendar, Gmail (AI-extracted from emails), and Canvas iCal feeds.
- **AI Task Extraction** — Uses Claude Haiku to parse complex emails into actionable tasks, avoiding duplicates and filtering out overdue items.
- **Interactive UI** — Manage your day directly from Telegram with "Done" and "Snooze" buttons. No more typing manual command numbers.
- **AI Project Checklists** — Generate deep breakdowns for major projects by uploading rubrics or notes. Confirm or skip tasks with interactive buttons.
- **Privacy & Security** — Supports multiple users with isolated data. All personal API keys and Google tokens are stored using high-grade encryption.
- **Google Calendar Sync** — Automatically writes newly discovered deadlines back to your Google Calendar as all-day events.
- **Scheduled Digests** — Stay on track with automated morning lists (7:30 AM) and evening recaps (9:00 PM).

## 🛠 Project Structure

```
main.py                    # Entry point & Web server for OAuth callbacks
config.py                  # Environment configuration
startup.py                 # Intelligent credential handling (Base64 or Raw JSON)
ai/
  extractor.py             # Haiku: Converts emails/events → structured tasks
  estimator.py             # Sonnet: Project → actionable sub-task checklists
db/
  models.py                # Database schema (Multi-user, Encrypted)
  repository.py            # CRUD logic and data isolation
bot/
  telegram_bot.py          # Command & Callback handlers
  messages.py              # Clean HTML-formatted digest templates
  conversations.py         # AI checklist generation flow
integrations/
  google_calendar.py       # Calendar Read/Write logic
  gmail.py                 # Actionable email fetching
  ical_feeds.py            # Canvas/Blackboard feed parsing
utils/
  security.py              # Fernet encryption for user tokens
  format.py                # Robust Markdown escaping
```

## 📦 Setup & Deployment

### 1. Local Installation

```bash
git clone https://github.com/yeyetaut/reminder_bot.git
cd reminder_bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration (`.env`)

Create a `.env` file based on `.env.example`. Required variables:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your Telegram ID (for admin/logs) |
| `ENCRYPTION_KEY` | Generate with: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `WEB_URL` | Your Railway or local URL (e.g., `https://bot.up.railway.app`) |
| `ANTHROPIC_API_KEY` | Primary AI for extraction and estimation |

### 3. Railway Deployment

This bot is optimized for [Railway](https://railway.com).

1.  **Generate Domain:** Enable "Public Networking" in Railway settings and set your `WEB_URL`.
2.  **Add Variables:** Mirror your `.env` variables into the Railway dashboard.
3.  **Google Credentials:** Paste your `credentials.json` content (either raw JSON or Base64 encoded) into the `GOOGLE_CREDENTIALS_B64` variable. The bot will automatically detect the format.
4.  **Database:** Provision a PostgreSQL instance in your Railway project. The bot will handle migrations automatically on startup.

## 🤖 Usage

### Onboarding
1.  Run `/start` to see the menu.
2.  Run `/login` to connect your Google account.
3.  Run `/help` for a step-by-step guide on connecting Outlook and Canvas.

### Core Commands
- `/today` — View today's tasks and deadlines with interactive buttons.
- `/checklist` — Upload a PDF or notes to generate a task breakdown for a project.
- `/projects` — Overview of all active projects and their completion status.
- `/exams` — Quick list of upcoming exams.
- `/weekly` / `/monthly` — Longer-term recaps.

## 🕒 Automated Schedule

| Event | Time |
|---|---|
| **Daily Sync** | 7:00 AM |
| **Morning Digest** | 7:30 AM |
| **Evening Recap** | 9:00 PM |
| **Weekly Summary** | Friday 9:00 PM |
| **Monthly Recap** | Last day of month 9:30 PM |
| **Cleanup** | Daily 3:00 AM (Prunes old tasks) |

## ⚖️ License
MIT
