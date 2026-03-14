from __future__ import annotations

import json
from datetime import date

import redis.asyncio as redis


class RedisTelemetry:
    def __init__(self, url: str | None) -> None:
        self._r = redis.from_url(url, decode_responses=True) if url else None

    @property
    def enabled(self) -> bool:
        return self._r is not None

    async def ping(self) -> bool:
        if not self._r:
            return False
        try:
            return bool(await self._r.ping())
        except Exception:
            return False

    async def incr(self, key: str, amount: int = 1) -> None:
        if not self._r:
            return
        await self._r.hincrby("metrics:counters", key, amount)

    async def incr_float(self, key: str, amount: float) -> None:
        if not self._r:
            return
        await self._r.hincrbyfloat("metrics:counters", key, amount)

    async def set_text(self, key: str, value: str) -> None:
        if not self._r:
            return
        await self._r.hset("metrics:text", key, value)

    async def count_hash(self) -> dict[str, float]:
        if not self._r:
            return {}
        raw = await self._r.hgetall("metrics:counters")
        data: dict[str, float] = {}
        for key, value in raw.items():
            try:
                data[key] = float(value)
            except ValueError:
                continue
        return data

    async def text_hash(self) -> dict[str, str]:
        if not self._r:
            return {}
        return await self._r.hgetall("metrics:text")

    async def collect_business_stats(self) -> dict[str, int]:
        if not self._r:
            return {
                "users_total": 0,
                "subscriptions_active": 0,
                "referrals_total": 0,
                "nutrition_logs_total": 0,
            }

        today = date.today()
        users_total = 0
        subscriptions_active = 0
        referrals_total = 0
        nutrition_logs_total = 0

        async for key in self._r.scan_iter(match="bot:user:*", count=500):
            raw = await self._r.get(key)
            if not raw:
                continue
            try:
                profile = json.loads(raw)
            except Exception:
                continue

            users_total += 1
            referrals_total += int(profile.get("referals", 0) or 0)

            subscribe_until = profile.get("subscribe_until")
            if subscribe_until:
                try:
                    if date.fromisoformat(subscribe_until) >= today:
                        subscriptions_active += 1
                except ValueError:
                    pass

        async for _ in self._r.scan_iter(match="bot:nutrition:*", count=500):
            nutrition_logs_total += 1

        return {
            "users_total": users_total,
            "subscriptions_active": subscriptions_active,
            "referrals_total": referrals_total,
            "nutrition_logs_total": nutrition_logs_total,
        }

    async def collect_all_stats(self) -> dict[str, object]:
        counters = await self.count_hash()
        business = await self.collect_business_stats()
        texts = await self.text_hash()
        return {
            "counters": counters,
            "business": business,
            "text": texts,
            "redis_up": await self.ping(),
        }

    async def render_prometheus(self) -> str:
        stats = await self.collect_all_stats()
        counters = stats["counters"]
        business = stats["business"]
        redis_up = 1 if stats["redis_up"] else 0

        lines = [
            "# HELP emgood_redis_up Redis availability.",
            "# TYPE emgood_redis_up gauge",
            f"emgood_redis_up {redis_up}",
        ]

        for key, value in sorted(counters.items()):
            metric = key.replace(".", "_")
            lines.append(f"# TYPE emgood_{metric} counter")
            lines.append(f"emgood_{metric} {value}")

        for key, value in sorted(business.items()):
            metric = key.replace(".", "_")
            lines.append(f"# TYPE emgood_{metric} gauge")
            lines.append(f"emgood_{metric} {value}")

        return "\n".join(lines) + "\n"
