from __future__ import annotations
import json
from typing import Any
from domain.ports import LLMClient, ChatSessionStore, NutritionLogStore, UserProfileStore
from services.rendering import render_day_table, build_day_files  # ← ДОПОЛНЕН ИМПОРТ
from services.text_normalizer import extract_json_object
from services.payments import build_yoomoney_quickpay_link
from datetime import date

RESPONSE_KEYS = ("items",)

WELCOME_TEXT = (
    "Привет! Я бот, который поможет посчитать БЖУ. "
    "Вам начислено +7 дней подписки за регистрацию.\n\n"
    "Нажмите кнопку, чтобы начать, или задайте вопрос."
)

class MessageProcessor:
    def __init__(self, llm: LLMClient, sessions: ChatSessionStore, nutrition: NutritionLogStore, profiles: UserProfileStore, settings=None) -> None:
        self._llm = llm
        self._sessions = sessions
        self._nutrition = nutrition
        self._profiles = profiles
        self._settings = settings

    async def ensure_profile(self, *, chat_id: int, name: str | None, username: str | None) -> str:
        profile, is_new = await self._profiles.ensure(chat_id=chat_id, name=name, username=username)
        if is_new:
            await self._profiles.extend_subscription(chat_id, 7) # +7 за первую регистрацию
            return WELCOME_TEXT
        return "С возвращением! Готов продолжить."

    async def handle_referral(self, *, new_chat_id: int, ref_payload: str | None, new_username: str | None = None) -> str | None:
        """
        Ожидаем payload вида 'ref_<chat_id>'.
        Если валидный и не равен себе — начисляем рефереру +3 дня и +1 к referals.
        """
        if not ref_payload:
            return None
        ref_payload = ref_payload.strip()
        if not ref_payload.startswith("ref_"):
            return None
        try:
            ref_id = int(ref_payload.replace("ref_", "", 1))
        except ValueError:
            return None
        if ref_id == new_chat_id:
            return "Нельзя использовать собственную реферальную ссылку 🙂"
        # Начисляем рефереру
        await self._profiles.extend_subscription(ref_id, 3)
        await self._profiles.add_referral_username(ref_id, new_username)
        return "Вы зашли по реферальной ссылке — рефереру добавлено +3 дня подписки."

    async def set_calories_goal(self, chat_id: int, goal: int | None) -> str:
        if goal is not None and goal <= 0:
            return "Цель по калориям должна быть положительным числом."
        await self._profiles.set_calories_goal(chat_id, goal)
        return f"Цель по калориям обновлена: {goal if goal is not None else 'не задана'} ккал/день."

    async def build_ref_link(self, bot_username: str, chat_id: int) -> str:
        # Для deep-link: https://t.me/<bot_username>?start=ref_<chat_id>
        return f"https://t.me/{bot_username}?start=ref_{chat_id}"

    async def get_profile_text(self, chat_id: int) -> str:
        p = await self._profiles.get(chat_id)
        if not p:
            return "Профиль не найден."
        goal = f"{p.calories_goal} ккал/день" if p.calories_goal else "не задана"
        return (
            f"👤 Профиль\n"
            f"Имя: {p.name or '-'}\n"
            f"Юзернейм: @{p.username}" + ("\n" if p.username else "\n") +
            f"Цель по калориям: {goal}\n"
            f"Подписка: {p.subscribe_until or 'нет'}\n"
            f"Рефералов: {p.referals}"
        )

    async def enable_chat(self, chat_id: int) -> str:
        if not await self._has_active_subscription(chat_id):
            return self._build_payment_text(chat_id)
        await self._sessions.set_active(chat_id, True)
        return "Готов отвечать на ваши сообщения. Напишите что-нибудь!"

    async def disable_chat(self, chat_id: int) -> str:
        await self._sessions.set_active(chat_id, False)
        return "Ок, перестаю отвечать. Нажмите «Продолжить отвечать», когда захотите вернуться."

    async def clear_day(self, chat_id: int) -> str:
        await self._nutrition.clear(chat_id)
        return "Дневник очищен. Введите продукты/блюда заново."


    async def process_user_text(self, chat_id: int, text: str) -> str | dict:
        if not await self._has_active_subscription(chat_id):
            return self._build_payment_text(chat_id)

        active = await self._sessions.is_active(chat_id)
        if not active:
        # Автовключение: есть подписка → включаем автоответ и продолжаем разбор текста
            await self._sessions.set_active(chat_id, True)

        raw = await self._llm.reply(user_text=text, chat_id=chat_id)
        data = extract_json_object(raw)

        if isinstance(data, dict) and isinstance(data.get("items"), list):
            items: list[dict[str, Any]] = data["items"]
            if not items:
                return "Не смог распознать блюда. Попробуйте ещё раз (например: «я съел 200 г курицы и 150 г риса»)."

            await self._nutrition.add_items(chat_id, items)
            log = await self._nutrition.get_log(chat_id)
            files = build_day_files(log, prefer_xlsx=True)

            if files["empty"]:
                return "Записей пока нет. Добавьте блюда, и я пришлю таблицу."

            return {
                "photo": str(files["png"]),
                "caption": files["caption"],
            # "document": str(files["xlsx"])  # при желании
            }
        else:
            return raw or "…"

    async def has_items(self, chat_id: int) -> bool:
        log = await self._nutrition.get_log(chat_id)
        return bool(log)

    async def undo_last(self, chat_id: int) -> str | dict:
        removed = await self._nutrition.remove_last(chat_id)
        if not removed:
            return "Удалять нечего — дневник пуст."

        log = await self._nutrition.get_log(chat_id)
        if not log:
            return "Последняя запись удалена. Дневник пуст."

        files = build_day_files(log, prefer_xlsx=True)
        return {
            "photo": str(files["png"]),
            "caption": files["caption"],
        }
    async def has_access(self, chat_id: int) -> bool:
        p = await self._profiles.get(chat_id)
        return bool(p and p.subscribe_until and date.today() <= date.fromisoformat(p.subscribe_until))

    async def build_pay_text(self, chat_id: int) -> str:
        s = self._settings
        if not (s and s.yoomoney_receiver):
            return ("Подписка недоступна: не задан кошелёк ЮMoney. "
                    "Обратитесь к администратору.")
        label = f"sub_{chat_id}"
        link = build_yoomoney_quickpay_link(
            receiver=s.yoomoney_receiver,
            amount=s.subscription_price,
            label=label,
            targets="Подписка на бота",
            success_url=s.yoomoney_success_url,
            fail_url=s.yoomoney_fail_url,
        )
        return (
            "🔒 <b>Подписка закончилась</b>\n\n"
            f"Стоимость: <b>{s.subscription_price:.2f} ₽</b> за {s.subscription_days} дней.\n"
            f"Оплатить по ссылке:\n{link}\n\n"
            "После оплаты дни подпишки начислятся автоматически (обычно мгновенно)."
        )
    
    async def _has_active_subscription(self, chat_id: int) -> bool:
        p = await self._profiles.get(chat_id)
        return bool(p and p.subscribe_until and date.today() <= date.fromisoformat(p.subscribe_until))
    
    def _build_payment_text(self, chat_id: int) -> str:
        s = self._settings
        label = f"sub_{chat_id}"
        link = build_yoomoney_quickpay_link(
            receiver=s.yoomoney_receiver,
            amount=s.subscription_price,
            label=label,
            targets="Подписка на бота",
            success_url=s.yoomoney_success_url,
            fail_url=s.yoomoney_fail_url,
        )
        return (
            "🔒 <b>Подписка закончилась</b>\n\n"
            f"Стоимость: <b>{s.subscription_price:.2f} ₽</b> за {s.subscription_days} дней.\n"
            f"Оплатить по ссылке:\n{link}\n\n"
            "После оплаты дни подпишки начислятся автоматически (обычно мгновенно)."
        )
