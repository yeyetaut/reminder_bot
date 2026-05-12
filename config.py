import os
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return val


# Telegram
TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _require("TELEGRAM_CHAT_ID")

# Anthropic (primary AI)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

# Gemini (fallback AI)
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# Google
GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

# LMS iCal feeds
CANVAS_ICAL_URL: str = os.getenv("CANVAS_ICAL_URL", "")

# Scheduler
TIMEZONE: str = os.getenv("TIMEZONE", "America/New_York")


def get_today() -> date:
    """Return the current date in the configured TIMEZONE."""
    import pytz
    from datetime import datetime
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz).date()


def get_now() -> datetime:
    """Return the current datetime in the configured TIMEZONE."""
    import pytz
    from datetime import datetime
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)

# Database
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///reminder_bot.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
