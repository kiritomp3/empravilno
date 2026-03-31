from datetime import UTC, datetime, timedelta

import asyncio

from infrastructure.memory_store import InMemoryNutritionLogStore
from services.nutrition_cleanup import run_cleanup_once, seconds_until_next_cleanup


def test_seconds_until_next_cleanup_same_day():
    now = datetime(2026, 3, 30, 0, 15, tzinfo=UTC)

    seconds = seconds_until_next_cleanup(now, run_hour=1, run_minute=0)

    assert seconds == 45 * 60


def test_seconds_until_next_cleanup_next_day_after_run_time():
    now = datetime(2026, 3, 30, 1, 1, tzinfo=UTC)

    seconds = seconds_until_next_cleanup(now, run_hour=1, run_minute=0)

    assert seconds == (23 * 60 + 59) * 60


def test_run_cleanup_once_clears_only_stale_logs():
    store = InMemoryNutritionLogStore()

    asyncio.run(store.add_items(1, [{"name": "apple"}]))
    asyncio.run(store.add_items(2, [{"name": "pear"}]))

    store._last_activity[1] = datetime.now(UTC) - timedelta(hours=9)
    store._last_activity[2] = datetime.now(UTC) - timedelta(hours=2)

    cleared = asyncio.run(
        run_cleanup_once(
            store,
            inactive_for_seconds=8 * 60 * 60,
            batch_size=100,
        )
    )

    assert cleared == 1
    assert asyncio.run(store.get_log(1)) == []
    assert asyncio.run(store.get_log(2)) == [{"name": "pear"}]


def test_run_cleanup_once_processes_all_stale_logs_in_batches():
    store = InMemoryNutritionLogStore()

    for chat_id in (1, 2):
        asyncio.run(store.add_items(chat_id, [{"name": f"item-{chat_id}"}]))
        store._last_activity[chat_id] = datetime.now(UTC) - timedelta(hours=9)

    cleared = asyncio.run(
        run_cleanup_once(
            store,
            inactive_for_seconds=8 * 60 * 60,
            batch_size=1,
        )
    )

    remaining_logs = [
        asyncio.run(store.get_log(1)),
        asyncio.run(store.get_log(2)),
    ]

    assert cleared == 2
    assert remaining_logs == [[], []]
