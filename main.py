"""
main.py
~~~~~~~
InstaVault Bot — entry point.

MODE DETECTION (automatic):
  • Replit dev  (REPLIT_DEV_DOMAIN is set) → Long polling
    - No proxy routing needed; bot pulls updates directly from Telegram.
    - aiohttp still binds on $PORT so Replit workflow health-check passes.
  • Production  (Render.com / any host without REPLIT_DEV_DOMAIN) → Webhooks
    - aiohttp server receives POST updates at /webhook/<BOT_TOKEN>.
    - Bind to 0.0.0.0:$PORT as required by Render.
"""

import asyncio
import logging
import os
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import config as _config
from config import BOT_TOKEN, WEBAPP_HOST, WEBAPP_PORT, WEBHOOK_PATH, WEBHOOK_URL
from database.firebase_init import init_firebase
from handlers import main_menu, orders, referrals, start

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

IS_REPLIT = bool(os.getenv("REPLIT_DEV_DOMAIN"))


# ---------------------------------------------------------------------------
# Shared initialisation helper
# ---------------------------------------------------------------------------

def _init_services() -> None:
    """Initialise Firebase (and any future shared services)."""
    try:
        init_firebase()
        logger.info("Firebase initialised.")
    except Exception as e:
        logger.error("Firebase init failed: %s", e)


# ---------------------------------------------------------------------------
# Shared bot / dispatcher factory
# ---------------------------------------------------------------------------

def _build_bot_and_dispatcher():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers (most-specific first)
    dp.include_router(start.router)
    dp.include_router(main_menu.router)
    dp.include_router(orders.router)
    dp.include_router(referrals.router)

    return bot, dp


# ---------------------------------------------------------------------------
# POLLING mode  (Replit development)
# ---------------------------------------------------------------------------

async def _run_polling() -> None:
    """
    Start a minimal aiohttp health-check server AND run long polling
    concurrently so Replit's port-watcher stays happy.
    """
    bot, dp = _build_bot_and_dispatcher()

    _init_services()

    # Cache bot username once at startup so all handlers can use it instantly
    bot_info = await bot.get_me()
    _config.BOT_USERNAME = bot_info.username
    logger.info("Bot username cached: @%s", _config.BOT_USERNAME)

    # Delete any stale webhook so polling works cleanly
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Stale webhook cleared — switching to polling mode.")
    except Exception as e:
        logger.warning("Could not clear webhook: %s", e)

    # Minimal aiohttp app just to keep port 8000 open for Replit health checks
    health_app = web.Application()
    health_app.router.add_get("/healthz", health_check)

    runner = web.AppRunner(health_app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    logger.info("Health-check server running on %s:%s", WEBAPP_HOST, WEBAPP_PORT)

    logger.info("🔄 Polling mode active — bot is listening for updates.")
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await runner.cleanup()
        await bot.session.close()
        logger.info("Bot session closed.")


# ---------------------------------------------------------------------------
# WEBHOOK mode  (production — Render.com)
# ---------------------------------------------------------------------------

async def _on_startup_webhook(bot: Bot) -> None:
    """Called by aiogram after the aiohttp server starts."""
    _init_services()

    # Cache bot username once at startup
    bot_info = await bot.get_me()
    _config.BOT_USERNAME = bot_info.username
    logger.info("Bot username cached: @%s", _config.BOT_USERNAME)

    if not WEBHOOK_URL:
        logger.warning("WEBHOOK_URL not set — webhook will not be registered.")
        return

    webhook_full_url = f"{WEBHOOK_URL}{WEBHOOK_PATH}"
    try:
        await bot.set_webhook(url=webhook_full_url, drop_pending_updates=True)
        logger.info("✅ Webhook set: %s", webhook_full_url)
    except Exception as e:
        logger.error("Failed to set webhook: %s", e)


async def _on_shutdown_webhook(bot: Bot) -> None:
    """Called by aiogram before the aiohttp server stops."""
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted.")
    except Exception as e:
        logger.error("Error deleting webhook: %s", e)
    finally:
        await bot.session.close()
        logger.info("Bot session closed.")


def _create_webhook_app() -> web.Application:
    if not WEBHOOK_URL:
        raise ValueError("WEBHOOK_URL is required for webhook mode.")

    bot, dp = _build_bot_and_dispatcher()

    dp.startup.register(_on_startup_webhook)
    dp.shutdown.register(_on_shutdown_webhook)

    app = web.Application()
    app.router.add_get("/healthz", health_check)

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    return app


# ---------------------------------------------------------------------------
# Health-check endpoint (shared)
# ---------------------------------------------------------------------------

async def health_check(request: web.Request) -> web.Response:
    mode = "polling" if IS_REPLIT else "webhook"
    return web.json_response({"status": "ok", "service": "InstaVault Bot", "mode": mode})


# --------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if IS_REPLIT:
        logger.info("🔧 Replit environment detected — starting in POLLING mode.")
        asyncio.run(_run_polling())
    else:
        logger.info("🚀 Production environment — starting in WEBHOOK mode.")
        app = _create_webhook_app()
        web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)
