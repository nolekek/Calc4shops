import logging
from typing import Optional
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.bot.handlers import router as bot_router

logger = logging.getLogger(__name__)

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None


def get_bot() -> Optional[Bot]:
    global bot
    if bot is None and settings.BOT_TOKEN:
        proxy = settings.get_telegram_proxy()
        session = None
        if proxy:
            logger.info(f"Telegram Bot using dedicated proxy/VPN tunnel: {proxy}")
            session = AiohttpSession(proxy=proxy)

        bot = Bot(
            token=settings.BOT_TOKEN,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
    return bot


def get_dispatcher() -> Dispatcher:
    global dp
    if dp is None:
        dp = Dispatcher()
        dp.include_router(bot_router)
    return dp


async def start_bot_polling():
    b = get_bot()
    if not b:
        logger.warning("No BOT_TOKEN found. Bot polling not started.")
        return
    d = get_dispatcher()
    logger.info("Bot starting polling...")
    try:
        await b.delete_webhook(drop_pending_updates=True)
        await d.start_polling(b)
    except Exception as e:
        logger.error(f"Error in bot polling: {e}")


async def stop_bot_polling():
    b = get_bot()
    d = get_dispatcher()
    if d and b:
        await d.stop_polling()
        await b.session.close()
        logger.info("Bot polling stopped.")
