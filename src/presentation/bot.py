from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from presentation.middlewares.logging import LoggingMiddleware

def build_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

def build_dispatcher(chat_router, log_level: str, start_router_with_processor=None, menu_reply_router_with_processor=None):
    dp = Dispatcher()
    dp.message.middleware(LoggingMiddleware(level=log_level))
    dp.callback_query.middleware(LoggingMiddleware(level=log_level))

    if start_router_with_processor:
        dp.include_router(start_router_with_processor)
    else:
        from presentation.routers import start as start_router
        # Не включаем start_router.router повторно, если уже передан
        dp.include_router(start_router.router)

    if menu_reply_router_with_processor:
        dp.include_router(menu_reply_router_with_processor)

    dp.include_router(chat_router)
    return dp