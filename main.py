import logging
import asyncio
from aiohttp import web

import config
from startup import prepare_google_credentials
from db.models import init_db, User
from db.repository import TaskRepo, ProjectRepo
from bot.telegram_bot import build_bot
from scheduler.jobs import build_scheduler
from utils.security import encrypt_json
from sqlalchemy.orm import Session
from sqlalchemy import text, select
from sqlalchemy.exc import ProgrammingError, InternalError, OperationalError
from google_auth_oauthlib.flow import Flow

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def oauth2callback(request):
    """Handle Google OAuth2 callback."""
    code = request.query.get('code')
    state = request.query.get('state')  # This is the telegram_id
    
    if not code or not state:
        return web.Response(text="Missing code or state.", status=400)
    
    try:
        telegram_id = int(state)
    except ValueError:
        return web.Response(text="Invalid state parameter.", status=400)

    engine = request.app['engine']
    bot = request.app['bot']

    try:
        flow = Flow.from_client_secrets_file(
            config.GOOGLE_CREDENTIALS_FILE,
            scopes=[
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/gmail.readonly",
            ],
            redirect_uri=f"{config.WEB_URL.rstrip('/')}/oauth2callback"
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        creds_data = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        encrypted_creds = encrypt_json(creds_data)
        
        with Session(engine) as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user:
                user.google_credentials_encrypted = encrypted_creds
                session.commit()
                logger.info(f"Successfully saved credentials for user {telegram_id}")
                
                # Try to send a success message to the user
                try:
                    asyncio.create_task(bot.send_message(
                        chat_id=user.telegram_chat_id,
                        text="✅ Google Account linked successfully! You can now use the bot's full features."
                    ))
                except Exception as e:
                    logger.warning(f"Could not send success message to user {telegram_id}: {e}")
                    
                return web.Response(text="Success! Your Google account has been connected. You can close this window.", content_type='text/html')
            else:
                return web.Response(text="User not found in database.", status=404)

    except Exception as e:
        logger.exception(f"Error in oauth2callback: {e}")
        return web.Response(text=f"An error occurred: {e}", status=500)


async def start_web_server(application):
    app = web.Application()
    app.router.add_get('/oauth2callback', oauth2callback)
    app['engine'] = application.bot_data['engine']
    app['bot'] = application.bot
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', config.PORT)
    await site.start()
    logger.info(f"Web server started on port {config.PORT}")
    application.bot_data['web_runner'] = runner


async def post_init(application):
    """Called after the bot is initialized — start the scheduler and web server."""
    engine = application.bot_data["engine"]
    scheduler = build_scheduler(application.bot, engine)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    
    # Start web server
    await start_web_server(application)


async def post_shutdown(application):
    """Called on shutdown — stop the scheduler and web server cleanly."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        
    web_runner = application.bot_data.get("web_runner")
    if web_runner:
        await web_runner.cleanup()
        logger.info("Web server stopped")


def _migrate(engine):
    """Apply incremental schema migrations robustly."""
    stmts = [
        "ALTER TABLE tasks ADD COLUMN gcal_synced INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE projects ADD COLUMN context_notes VARCHAR",
        "ALTER TABLE tasks ADD COLUMN completed_at TIMESTAMP",
        "ALTER TABLE tasks ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE projects ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE processed_sources ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE daily_plans ADD COLUMN user_id INTEGER REFERENCES users(id)",
    ]

    for stmt in stmts:
        with engine.connect() as conn:
            try:
                conn.execute(text(stmt))
                conn.commit()
                logger.info(f"Migration successful: {stmt}")
            except (ProgrammingError, InternalError, OperationalError):
                logger.debug(f"Migration skipped (likely already applied): {stmt}")
            except Exception as e:
                logger.warning(f"Migration error for '{stmt}': {e}")
                
    with Session(engine) as s:
        user = s.scalar(select(User).order_by(User.id).limit(1))
        
        if not user:
            try:
                telegram_id = int(config.TELEGRAM_CHAT_ID)
            except (ValueError, TypeError):
                telegram_id = 0
                
            user = User(
                telegram_id=telegram_id,
                telegram_chat_id=telegram_id,
                canvas_ical_url=config.CANVAS_ICAL_URL,
                timezone=config.TIMEZONE
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            logger.info(f"Created default user with ID {user.id}")
            
        if user:
            uid = user.id
            tables_to_update = ['tasks', 'projects', 'processed_sources', 'daily_plans']
            for table in tables_to_update:
                try:
                    with engine.connect() as conn:
                        res = conn.execute(
                            text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
                            {"uid": uid}
                        )
                        conn.commit()
                        if res.rowcount > 0:
                            logger.info(f"Updated {res.rowcount} rows in {table} to user_id {uid}")
                except Exception as e:
                    logger.warning(f"Error migrating data for table {table}: {e}")


def main():
    prepare_google_credentials()
    logger.info("Bot starting...")

    engine = init_db(config.DATABASE_URL)
    _migrate(engine)
    TaskRepo(engine).run_migrations()
    logger.info(f"Database ready at: {config.DATABASE_URL}")

    app = build_bot(engine, post_init=post_init, post_shutdown=post_shutdown)

    logger.info("Polling for Telegram messages...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
