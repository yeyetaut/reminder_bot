import logging

import config
from startup import prepare_google_credentials
from db.models import init_db
from bot.telegram_bot import build_bot
from scheduler.jobs import build_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application):
    """Called after the bot is initialized — start the scheduler."""
    engine = application.bot_data["engine"]
    scheduler = build_scheduler(application.bot, engine)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler


async def post_shutdown(application):
    """Called on shutdown — stop the scheduler cleanly."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def _migrate(engine):
    """Apply incremental schema migrations for SQLite."""
    from sqlalchemy import text
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE task ADD COLUMN gcal_synced INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists


def main():
    prepare_google_credentials()
    logger.info("Bot starting...")

    engine = init_db(config.DATABASE_URL)
    _migrate(engine)
    logger.info(f"Database ready at: {config.DATABASE_URL}")

    app = build_bot(engine, post_init=post_init, post_shutdown=post_shutdown)

    logger.info("Polling for Telegram messages...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
