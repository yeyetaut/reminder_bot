import logging

import config
from startup import prepare_google_credentials
from db.models import init_db
from db.repository import TaskRepo, ProjectRepo
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
    """Apply incremental schema migrations robustly."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError, InternalError

    stmts = [
        "ALTER TABLE tasks ADD COLUMN gcal_synced INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN context_notes VARCHAR",
    ]

    for stmt in stmts:
        # Open a fresh connection for each statement to ensure transaction isolation.
        # In Postgres, if a statement fails inside a transaction, the connection 
        # is poisoned until a rollback/new connection.
        with engine.connect() as conn:
            try:
                conn.execute(text(stmt))
                conn.commit()
                logger.info(f"Migration successful: {stmt}")
            except (ProgrammingError, InternalError):
                # This usually means the column already exists
                logger.debug(f"Migration skipped (likely already applied): {stmt}")
            except Exception as e:
                logger.warning(f"Migration error for '{stmt}': {e}")


def main():
    prepare_google_credentials()
    logger.info("Bot starting...")

    engine = init_db(config.DATABASE_URL)
    _migrate(engine)
    TaskRepo(engine).run_migrations()
    logger.info(f"Database ready at: {config.DATABASE_URL}")

    app = build_bot(engine, post_init=post_init, post_shutdown=post_shutdown)

    logger.info("Polling for Telegram messages...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
