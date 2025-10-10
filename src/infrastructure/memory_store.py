from __future__ import annotations
from typing import Iterable
from asyncio import Lock

class InMemoryChatSessionStore:
    def __init__(self) -> None:
        self._active: set[int] = set()
        self._lock = Lock()

    async def set_active(self, chat_id: int, active: bool) -> None:
        async with self._lock:
            (self._active.add if active else self._active.discard)(chat_id)

    async def is_active(self, chat_id: int) -> bool:
        async with self._lock:
            return chat_id in self._active

    async def list_active(self) -> Iterable[int]:
        async with self._lock:
            return set(self._active)