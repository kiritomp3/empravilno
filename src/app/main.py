import asyncio
import contextlib
import signal
import os

from app.logging import setup_logging
from app.container import build_container
from presentation.bot import build_bot, build_dispatcher
from presentation.routers import chat as chat_router_module
from presentation.routers import start as start_router_module
from presentation.routers import menu_reply as menu_reply_router_module
import uvicorn
from app.http import app as http_app

async def _run() -> None:
    container = build_container()
    setup_logging(container.settings.log_level)
    await container.telemetry.incr("app.starts_total")

    bot = build_bot(container.settings.bot_token)
    chat_router = chat_router_module.setup(container.processor, telemetry=container.telemetry)
    menu_reply_router = menu_reply_router_module.setup_menu_reply_router(
        container.processor,
        telemetry=container.telemetry,
        settings=container.settings,
    )

    start_router = start_router_module.setup_start_router(
        container.processor,
        telemetry=container.telemetry,
        settings=container.settings,
    )

    dp = build_dispatcher(chat_router, container.settings.log_level, start_router_with_processor=start_router, menu_reply_router_with_processor=menu_reply_router)

    http_config = uvicorn.Config(http_app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")),
                                 log_level=container.settings.log_level.lower(), access_log=True)
    http_server = uvicorn.Server(http_config)
    http_task = asyncio.create_task(http_server.serve())

    try:
        await dp.start_polling(bot)
    finally:
        http_server.should_exit = True
        await http_task


def main() -> None:
    with contextlib.suppress(KeyboardInterrupt):
        try:
            asyncio.run(_run())
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    # UVLoop ускоряет asyncio на Linux/macOS
    try:
        import uvloop
        uvloop.install()
    except Exception:
        pass
    main()
