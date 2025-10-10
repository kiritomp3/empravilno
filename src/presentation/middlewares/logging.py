from __future__ import annotations
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from typing import Any, Callable, Dict, Awaitable
import structlog

log = structlog.get_logger(__name__)

class LoggingMiddleware(BaseMiddleware):
    def __init__(self, level: str = "INFO") -> None:
        self._level = level

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        log.info("incoming_event", type=event.__class__.__name__)
        try:
            return await handler(event, data)
        finally:
            log.info("handled_event", type=event.__class__.__name__)