from __future__ import annotations
import json
import time
import redis.asyncio as redis
from typing import Any
from domain.models import UserProfile
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo  # py>=3.9

# бизнес-таймзона для вычисления "сегодня"
BUSINESS_TZ = ZoneInfo("Europe/Helsinki")


class RedisChatSessionStore:
    def __init__(self, url: str, key: str = "bot:active_chats") -> None:
        self._r = redis.from_url(url, decode_responses=True)
        self._key = key

    async def set_active(self, chat_id: int, active: bool) -> None:
        if active:
            await self._r.sadd(self._key, chat_id)
        else:
            await self._r.srem(self._key, chat_id)

    async def is_active(self, chat_id: int) -> bool:
        return await self._r.sismember(self._key, chat_id)

    async def list_active(self):
        members = await self._r.smembers(self._key)
        return {int(m) for m in members}


class RedisNutritionLogStore:
    def __init__(
        self,
        url: str,
        key_prefix: str = "bot:nutrition",
        activity_key: str = "bot:nutrition:last_activity",
    ) -> None:
        self._r = redis.from_url(url, decode_responses=True)
        self._pfx = key_prefix
        self._activity_key = activity_key

    def _key(self, chat_id: int) -> str:
        return f"{self._pfx}:{chat_id}"

    async def _touch(self, chat_id: int) -> None:
        await self._r.zadd(self._activity_key, {str(chat_id): time.time()})

    async def add_items(self, chat_id: int, items: list[dict[str, Any]]) -> None:
        key = self._key(chat_id)
        cur = await self._r.get(key)
        arr = json.loads(cur) if cur else []
        arr.extend(items)
        payload = json.dumps(arr, ensure_ascii=False)
        async with self._r.pipeline(transaction=False) as pipe:
            pipe.set(key, payload)
            pipe.zadd(self._activity_key, {str(chat_id): time.time()})
            await pipe.execute()

    async def get_log(self, chat_id: int) -> list[dict[str, Any]]:
        cur = await self._r.get(self._key(chat_id))
        return json.loads(cur) if cur else []

    async def clear(self, chat_id: int) -> None:
        async with self._r.pipeline(transaction=False) as pipe:
            pipe.delete(self._key(chat_id))
            pipe.zrem(self._activity_key, str(chat_id))
            await pipe.execute()

    async def remove_last(self, chat_id: int) -> bool:
        """
        Удаляет последнюю запись из массива в Redis-ключе.
        Возвращает True, если что-то удалили.
        """
        key = self._key(chat_id)
        cur = await self._r.get(key)
        if not cur:
            return False

        try:
            arr = json.loads(cur)
        except Exception:
            # в ключе невалидный JSON — считаем, что удалять нечего
            return False

        if not isinstance(arr, list) or not arr:
            return False

        arr.pop()  # снять последнюю добавленную запись

        async with self._r.pipeline(transaction=False) as pipe:
            if arr:
                pipe.set(key, json.dumps(arr, ensure_ascii=False))
                pipe.zadd(self._activity_key, {str(chat_id): time.time()})
            else:
                # если список опустел — просто удалим ключ
                pipe.delete(key)
                pipe.zrem(self._activity_key, str(chat_id))
            await pipe.execute()

        return True

    async def remove_by_indices(self, chat_id: int, indices: set[int]) -> int:
        """
        Удаляет записи по 1-based индексам исходного журнала.
        Возвращает количество удаленных записей.
        """
        if not indices:
            return 0

        key = self._key(chat_id)
        cur = await self._r.get(key)
        if not cur:
            return 0

        try:
            arr = json.loads(cur)
        except Exception:
            return 0

        if not isinstance(arr, list) or not arr:
            return 0

        valid_positions = {i for i in indices if 1 <= i <= len(arr)}
        if not valid_positions:
            return 0

        filtered = [item for pos, item in enumerate(arr, start=1) if pos not in valid_positions]
        removed_count = len(arr) - len(filtered)

        async with self._r.pipeline(transaction=False) as pipe:
            if filtered:
                pipe.set(key, json.dumps(filtered, ensure_ascii=False))
                pipe.zadd(self._activity_key, {str(chat_id): time.time()})
            else:
                pipe.delete(key)
                pipe.zrem(self._activity_key, str(chat_id))
            await pipe.execute()

        return removed_count

    async def clear_inactive_logs(self, *, inactive_for_seconds: int, batch_size: int = 500) -> int:
        threshold = time.time() - inactive_for_seconds
        stale_chat_ids = await self._r.zrangebyscore(
            self._activity_key,
            min=0,
            max=threshold,
            start=0,
            num=batch_size,
        )
        if not stale_chat_ids:
            return 0

        async with self._r.pipeline(transaction=False) as pipe:
            for chat_id in stale_chat_ids:
                pipe.delete(self._key(int(chat_id)))
            pipe.zrem(self._activity_key, *stale_chat_ids)
            await pipe.execute()

        return len(stale_chat_ids)


class RedisUserProfileStore:
    def __init__(self, url: str, key_prefix: str = "bot:user:") -> None:
        self._r = redis.from_url(url, decode_responses=True)
        self._prefix = key_prefix

    def _key(self, chat_id: int) -> str:
        return f"{self._prefix}{chat_id}"

    async def get(self, chat_id: int) -> UserProfile | None:
        data = await self._r.get(self._key(chat_id))
        if not data:
            return None
        try:
            obj = json.loads(data)

            referral_usernames = obj.get("referral_usernames") or []
            if not isinstance(referral_usernames, list):
                referral_usernames = []
            # базовая десериализация новой схемы
            profile = UserProfile(
                chat_id=chat_id,
                name=obj.get("name"),
                username=obj.get("username"),
                calories_goal=obj.get("calories_goal"),
                height_cm=obj.get("height_cm"),
                weight_kg=obj.get("weight_kg"),
                subscribe_until=(obj.get("subscribe_until") or None),
                referals=int(obj.get("referals", 0)),
                referral_usernames=referral_usernames,
            )

            # ленивая миграция со старого поля subscribe_days -> subscribe_until
            if profile.subscribe_until is None and "subscribe_days" in obj:
                try:
                    sd = int(obj.get("subscribe_days") or 0)
                except Exception:
                    sd = 0
                if sd > 0:
                    base = datetime.now(BUSINESS_TZ).date()
                    profile.subscribe_until = (base + timedelta(days=sd)).isoformat()
                    # сохраним уже в новом формате, выпилив старое поле
                    await self.upsert(profile)

            return profile
        except Exception:
            return None

    async def upsert(self, profile: UserProfile) -> None:
        obj = {
            "name": profile.name,
            "username": profile.username,
            "calories_goal": profile.calories_goal,
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
            "subscribe_until": profile.subscribe_until,  # новое поле
            "referals": profile.referals,
            "referral_usernames": profile.referral_usernames,
        }
        await self._r.set(self._key(profile.chat_id), json.dumps(obj, ensure_ascii=False))

    async def ensure(self, *, chat_id: int, name: str | None, username: str | None) -> tuple[UserProfile, bool]:
        existing = await self.get(chat_id)
        if existing:
            # обновим name/username, если изменились
            changed = False
            if existing.name != name:
                existing.name = name
                changed = True
            if existing.username != username:
                existing.username = username
                changed = True
            if changed:
                await self.upsert(existing)
            return existing, False

        # Новый профиль — с дефолтами (subscribe_until отсутствует)
        profile = UserProfile(
            chat_id=chat_id,
            name=name,
            username=username,
            calories_goal=None,
            height_cm=None,
            weight_kg=None,
            subscribe_until=None,
            referals=0,
            referral_usernames=[],
        )
        await self.upsert(profile)
        return profile, True

    # Новый метод продления подписки датой (заменяет increment_subscribe_days)
    async def extend_subscription(self, chat_id: int, days: int) -> str:
        p = await self.get(chat_id)
        if not p:
            # если профиля нет — создадим с нуля
            p = UserProfile(
                chat_id=chat_id,
                name=None,
                username=None,
                calories_goal=None,
                height_cm=None,
                weight_kg=None,
                subscribe_until=None,
                referals=0,
                referral_usernames=[],
            )

        today = datetime.now(BUSINESS_TZ).date()
        base = today
        if p.subscribe_until:
            try:
                until = date.fromisoformat(p.subscribe_until)
                base = until if until >= today else today
            except ValueError:
                base = today

        new_until = (base + timedelta(days=int(days))).isoformat()
        p.subscribe_until = new_until
        await self.upsert(p)
        return new_until

    async def set_calories_goal(self, chat_id: int, goal: int | None) -> None:
        p = await self.get(chat_id)
        if not p:
            p = UserProfile(
                chat_id=chat_id,
                name=None,
                username=None,
                calories_goal=None,
                height_cm=None,
                weight_kg=None,
                subscribe_until=None,
                referals=0,
                referral_usernames=[],
            )
        p.calories_goal = int(goal) if goal is not None else None
        await self.upsert(p)

    async def set_body_metrics(self, chat_id: int, *, height_cm: int | None, weight_kg: float | None) -> None:
        p = await self.get(chat_id)
        if not p:
            p = UserProfile(
                chat_id=chat_id,
                name=None,
                username=None,
                calories_goal=None,
                height_cm=None,
                weight_kg=None,
                subscribe_until=None,
                referals=0,
                referral_usernames=[],
            )
        p.height_cm = int(height_cm) if height_cm is not None else None
        p.weight_kg = float(weight_kg) if weight_kg is not None else None
        await self.upsert(p)
    
    async def add_referral_username(self, chat_id: int, referred_username: str | None) -> None:
        """
        Добавляет запись о новом реферале: увеличивает referals += 1 и
        записывает username (с ведущим '@') или пустую строку, если username скрыт/отсутствует.
        Этот метод устойчив к старым профилям (когда referral_usernames может отсутствовать).
        """
        p = await self.get(chat_id)
        if not p:
            p = UserProfile(
                chat_id=chat_id,
                name=None,
                username=None,
                calories_goal=None,
                height_cm=None,
                weight_kg=None,
                subscribe_until=None,
                referals=0,
                referral_usernames=[],
            )

        # Убедимся, что поле referral_usernames определено и это список
        if not hasattr(p, "referral_usernames") or p.referral_usernames is None:
            p.referral_usernames = []

        # Подготовим строку username:
        # - если None или пустая строка -> сохраняем "" (пустую строку)
        # - иначе приведём к форме "@name" (если уже начинается с '@', оставим её)
        if referred_username is None:
            rname = ""
        else:
            r = str(referred_username).strip()
            if not r:
                rname = ""
            else:
                rname = r if r.startswith("@") else f"@{r}"

        # Увеличиваем счётчик рефералов на 1 (гарантированно int)
        try:
            p.referals = int(p.referals) + 1
        except Exception:
            p.referals = 1

        # Добавляем запись в историю (добавляем даже если rname == "")
        p.referral_usernames.append(rname)

        # Сохраняем профиль
        await self.upsert(p)


class RedisDiaryStreakStore:
    """
    Хранит даты (YYYY-MM-DD), когда пользователь сделал первую запись в дневник за день.
    Использует Redis Sorted Set: score = числовая дата, member = 'YYYY-MM-DD'.
    Хранится не более 400 последних дат на пользователя.
    """

    MAX_DATES = 400

    def __init__(self, url: str, key_prefix: str = "bot:streak:") -> None:
        self._r = redis.from_url(url, decode_responses=True)
        self._prefix = key_prefix

    def _key(self, chat_id: int) -> str:
        return f"{self._prefix}{chat_id}"

    def _date_score(self, date_str: str) -> float:
        return float(date_str.replace("-", ""))

    async def mark_today(self, chat_id: int, tz: str = "Europe/Helsinki") -> bool:
        """
        Отмечает сегодняшний день как день с записью.
        Возвращает True если это первая отметка за день, False если уже была.
        """
        today_str = datetime.now(ZoneInfo(tz)).date().isoformat()
        key = self._key(chat_id)
        score = self._date_score(today_str)
        added = await self._r.zadd(key, {today_str: score}, nx=True)
        if added:
            total = await self._r.zcard(key)
            if total > self.MAX_DATES:
                await self._r.zremrangebyrank(key, 0, total - self.MAX_DATES - 1)
        return bool(added)

    async def get_dates(self, chat_id: int) -> list[str]:
        """Все отмеченные даты ['YYYY-MM-DD', ...] по возрастанию."""
        return list(await self._r.zrange(self._key(chat_id), 0, -1))

    async def get_stats(self, chat_id: int, tz: str = "Europe/Helsinki") -> dict:
        """Возвращает dates, current_streak, best_streak, total."""
        dates = await self.get_dates(chat_id)
        dates_set = set(dates)
        total = len(dates)

        current_streak = 0
        cur = datetime.now(ZoneInfo(tz)).date()
        while cur.isoformat() in dates_set:
            current_streak += 1
            cur = cur.fromordinal(cur.toordinal() - 1)

        best_streak = 0
        if dates:
            run = 1
            best_streak = 1
            for i in range(1, len(dates)):
                d1 = date.fromisoformat(dates[i - 1])
                d2 = date.fromisoformat(dates[i])
                if (d2 - d1).days == 1:
                    run += 1
                    best_streak = max(best_streak, run)
                else:
                    run = 1

        return {
            "dates": dates,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "total": total,
        }
