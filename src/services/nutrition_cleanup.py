from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from domain.ports import NutritionLogStore
from infrastructure.telemetry import RedisTelemetry

logger = logging.getLogger(__name__)


def seconds_until_next_cleanup(
    now: datetime,
    *,
    run_hour: int,
    run_minute: int,
) -> float:
    next_run = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


async def run_cleanup_once(
    nutrition: NutritionLogStore,
    *,
    inactive_for_seconds: int,
    batch_size: int,
    telemetry: RedisTelemetry | None = None,
) -> int:
    total_cleared = 0
    while True:
        cleared = await nutrition.clear_inactive_logs(
            inactive_for_seconds=inactive_for_seconds,
            batch_size=batch_size,
        )
        total_cleared += cleared
        if cleared < batch_size:
            break

    if telemetry:
        await telemetry.incr("nutrition.cleanup_runs_total")
        if total_cleared:
            await telemetry.incr("nutrition.logs_cleared_total", total_cleared)
    return total_cleared


async def run_nutrition_cleanup_scheduler(
    nutrition: NutritionLogStore,
    *,
    timezone_name: str,
    inactive_for_hours: int = 8,
    run_hour: int = 1,
    run_minute: int = 0,
    batch_size: int = 500,
    telemetry: RedisTelemetry | None = None,
) -> None:
    tz = ZoneInfo(timezone_name)
    inactive_for_seconds = inactive_for_hours * 60 * 60

    while True:
        now = datetime.now(tz)
        sleep_seconds = seconds_until_next_cleanup(
            now,
            run_hour=run_hour,
            run_minute=run_minute,
        )
        await asyncio.sleep(sleep_seconds)

        try:
            cleared = await run_cleanup_once(
                nutrition,
                inactive_for_seconds=inactive_for_seconds,
                batch_size=batch_size,
                telemetry=telemetry,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("nutrition cleanup failed")
            if telemetry:
                await telemetry.incr("nutrition.cleanup_errors_total")
        else:
            logger.info("nutrition cleanup completed: cleared=%s", cleared)


async def stop_background_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
