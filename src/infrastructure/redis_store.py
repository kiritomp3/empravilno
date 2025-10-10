from __future__ import annotations
import json
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
    def __init__(self, url: str, key_prefix: str = "bot:nutrition") -> None:
        self._r = redis.from_url(url, decode_responses=True)
        self._pfx = key_prefix

    def _key(self, chat_id: int) -> str:
        return f"{self._pfx}:{chat_id}"

    async def add_items(self, chat_id: int, items: list[dict[str, Any]]) -> None:
        key = self._key(chat_id)
        cur = await self._r.get(key)
        arr = json.loads(cur) if cur else []
        arr.extend(items)
        await self._r.set(key, json.dumps(arr, ensure_ascii=False))

    async def get_log(self, chat_id: int) -> list[dict[str, Any]]:
        cur = await self._r.get(self._key(chat_id))
        return json.loads(cur) if cur else []

    async def clear(self, chat_id: int) -> None:
        await self._r.delete(self._key(chat_id))

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

        if arr:
            await self._r.set(key, json.dumps(arr, ensure_ascii=False))
        else:
            # если список опустел — просто удалим ключ
            await self._r.delete(key)

        return True


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
                subscribe_until=None,
                referals=0,
                referral_usernames=[],
            )
        p.calories_goal = int(goal) if goal is not None else None
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