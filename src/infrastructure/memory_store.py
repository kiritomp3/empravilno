from __future__ import annotations
from datetime import datetime, timedelta, UTC
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


class InMemoryNutritionLogStore:
    def __init__(self) -> None:
        self._logs: dict[int, list[dict]] = {}
        self._last_activity: dict[int, datetime] = {}
        self._lock = Lock()

    def _touch(self, chat_id: int) -> None:
        self._last_activity[chat_id] = datetime.now(UTC)

    async def add_items(self, chat_id: int, items: list[dict]) -> None:
        async with self._lock:
            log = self._logs.setdefault(chat_id, [])
            log.extend(items)
            self._touch(chat_id)

    async def get_log(self, chat_id: int) -> list[dict]:
        async with self._lock:
            return list(self._logs.get(chat_id, []))

    async def clear(self, chat_id: int) -> None:
        async with self._lock:
            self._logs.pop(chat_id, None)
            self._last_activity.pop(chat_id, None)

    async def remove_last(self, chat_id: int) -> bool:
        async with self._lock:
            log = self._logs.get(chat_id)
            if not log:
                return False

            log.pop()
            if log:
                self._touch(chat_id)
            else:
                self._logs.pop(chat_id, None)
                self._last_activity.pop(chat_id, None)
            return True

    async def remove_by_indices(self, chat_id: int, indices: set[int]) -> int:
        async with self._lock:
            log = self._logs.get(chat_id)
            if not log or not indices:
                return 0

            valid_positions = {i for i in indices if 1 <= i <= len(log)}
            if not valid_positions:
                return 0

            filtered = [item for pos, item in enumerate(log, start=1) if pos not in valid_positions]
            removed_count = len(log) - len(filtered)

            if filtered:
                self._logs[chat_id] = filtered
                self._touch(chat_id)
            else:
                self._logs.pop(chat_id, None)
                self._last_activity.pop(chat_id, None)

            return removed_count

    async def clear_inactive_logs(self, *, inactive_for_seconds: int, batch_size: int = 500) -> int:
        async with self._lock:
            cutoff = datetime.now(UTC) - timedelta(seconds=inactive_for_seconds)
            stale_chat_ids = [
                chat_id
                for chat_id, last_activity in self._last_activity.items()
                if last_activity <= cutoff
            ]
            stale_chat_ids = stale_chat_ids[:batch_size]
            for chat_id in stale_chat_ids:
                self._logs.pop(chat_id, None)
                self._last_activity.pop(chat_id, None)
            return len(stale_chat_ids)
