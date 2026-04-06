from __future__ import annotations
from typing import Any
from domain.ports import LLMClient, ChatSessionStore, NutritionLogStore, UserProfileStore
from services.rendering import DaySummary, build_day_files
from services.text_normalizer import extract_json_object
from services.subscription_plans import (
    format_subscription_expired_text,
    format_subscription_offer_text,
    format_subscription_topup_text,
)
from datetime import date

RESPONSE_KEYS = ("items",)

WELCOME_TEXT = (
    "Привет! Я бот, который поможет считать питание и спорт. "
    "Вам начислено +2 дня подписки за регистрацию.\n\n"
    "Сначала давайте заполним рост и вес, чтобы рекомендации были точнее."
)

class MessageProcessor:
    def __init__(self, llm: LLMClient, sessions: ChatSessionStore, nutrition: NutritionLogStore, profiles: UserProfileStore, settings=None, streak=None) -> None:
        self._llm = llm
        self._sessions = sessions
        self._nutrition = nutrition
        self._profiles = profiles
        self._settings = settings
        self._streak = streak

    def _is_admin(self, chat_id: int) -> bool:
        settings = self._settings
        return bool(settings and chat_id in settings.admin_chat_ids)

    async def ensure_profile(self, *, chat_id: int, name: str | None, username: str | None) -> str:
        profile, is_new = await self._profiles.ensure(chat_id=chat_id, name=name, username=username)
        if is_new:
            await self._profiles.extend_subscription(chat_id, 2) # +2 за первую регистрацию
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

    async def set_body_metrics(self, chat_id: int, *, height_cm: int | None, weight_kg: float | None) -> str:
        if height_cm is not None and not 100 <= height_cm <= 250:
            return "Рост должен быть в диапазоне 100-250 см."
        if weight_kg is not None and not 30 <= weight_kg <= 350:
            return "Вес должен быть в диапазоне 30-350 кг."
        await self._profiles.set_body_metrics(chat_id, height_cm=height_cm, weight_kg=weight_kg)
        return "Данные профиля обновлены."

    async def build_ref_link(self, bot_username: str, chat_id: int) -> str:
        # Для deep-link: https://t.me/<bot_username>?start=ref_<chat_id>
        return f"https://t.me/{bot_username}?start=ref_{chat_id}"

    async def get_profile_text(self, chat_id: int) -> str:
        p = await self._profiles.get(chat_id)
        if not p:
            return "Профиль не найден."
        goal = f"{p.calories_goal} ккал/день" if p.calories_goal else "не задана"
        height = f"{p.height_cm} см" if p.height_cm else "не указан"
        weight = f"{p.weight_kg:.1f}".rstrip("0").rstrip(".") + " кг" if p.weight_kg else "не указан"
        username = f"@{p.username}" if p.username else "-"
        return (
            f"👤 Профиль\n"
            f"Имя: {p.name or '-'}\n"
            f"Юзернейм: {username}\n"
            f"Рост: {height}\n"
            f"Вес: {weight}\n"
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

    async def finish_day(self, chat_id: int) -> str:
        log = await self._nutrition.get_log(chat_id)
        if not log:
            return "День пока пустой. Сначала добавьте еду или активность."

        files = build_day_files(log, prefer_xlsx=False)
        profile = await self._profiles.get(chat_id)
        summary = files["summary"]
        recommendation = await self._generate_day_recommendation(chat_id, summary, profile)
        await self._nutrition.clear(chat_id)
        return (
            "День завершён.\n\n"
            f"Набрано калорий: {summary.consumed_kcal} ккал\n"
            f"Сожжено калорий: {summary.burned_kcal} ккал\n"
            f"Итог калорий: {summary.net_kcal} ккал\n"
            f"Краткая рекомендация: {recommendation}"
        )


    async def process_user_text(self, chat_id: int, text: str) -> str | dict:
        if not await self._has_active_subscription(chat_id):
            return self._build_payment_text(chat_id)

        active = await self._sessions.is_active(chat_id)
        if not active:
        # Автовключение: есть подписка → включаем автоответ и продолжаем разбор текста
            await self._sessions.set_active(chat_id, True)

        # Отмечаем день в streak (только при первой записи за день)
        if self._streak:
            await self._streak.mark_today(chat_id)

        raw = await self._llm.reply(user_text=text, chat_id=chat_id)
        return await self._build_nutrition_reply(chat_id, raw)

    async def process_user_photo(
        self,
        chat_id: int,
        image_bytes: bytes,
        image_mime_type: str,
        caption: str = "",
    ) -> str | dict:
        if not await self._has_active_subscription(chat_id):
            return self._build_payment_text(chat_id)

        active = await self._sessions.is_active(chat_id)
        if not active:
            await self._sessions.set_active(chat_id, True)

        # Отмечаем день в streak (только при первой записи за день)
        if self._streak:
            await self._streak.mark_today(chat_id)

        raw = await self._llm.reply_with_image(
            chat_id=chat_id,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            user_text=caption,
        )
        return await self._build_nutrition_reply(chat_id, raw)

    async def _build_nutrition_reply(self, chat_id: int, raw: str) -> str | dict:
        try:
            data = extract_json_object(raw)
        except Exception:
            return (
                "Не смог аккуратно разобрать ответ. Попробуйте отправить сообщение ещё раз "
                "чуть короче или разделить еду и активность на два сообщения."
            )

        if isinstance(data, dict) and (
            isinstance(data.get("items"), list) or isinstance(data.get("activities"), list)
        ):
            items: list[dict[str, Any]] = list(data.get("items") or [])
            activities = data.get("activities")
            if isinstance(activities, list):
                items.extend(activities)

            if not items:
                return (
                    "Не смог распознать еду или активность. Попробуйте ещё раз текстом "
                    "или пришлите более понятное фото еды."
                )

            for item in items:
                if item.get("entry_type") not in {"food", "activity"}:
                    item["entry_type"] = "food"

            await self._nutrition.add_items(chat_id, items)
            log = await self._nutrition.get_log(chat_id)
            files = build_day_files(log, prefer_xlsx=True)

            if files["empty"]:
                return "Записей пока нет. Добавьте блюда, и я пришлю таблицу."

            profile = await self._profiles.get(chat_id)
            return {
                "photo": str(files["png"]),
                "caption": self._build_day_caption(files["summary"], profile),
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
        profile = await self._profiles.get(chat_id)
        return {
            "photo": str(files["png"]),
            "caption": self._build_day_caption(files["summary"], profile),
        }

    async def remove_items_by_input(self, chat_id: int, raw_indices: str) -> str | dict:
        log = await self._nutrition.get_log(chat_id)
        if not log:
            return "Удалять нечего — дневник пуст."

        parsed = self._parse_indices(raw_indices)
        if not parsed:
            return "Не понял номера. Введите, например: 1 или 1,3,5"

        removed_count = await self._nutrition.remove_by_indices(chat_id, parsed)
        if removed_count == 0:
            return "Не нашёл записей с такими номерами."

        log = await self._nutrition.get_log(chat_id)
        if not log:
            return f"Удалено записей: {removed_count}. Дневник пуст."

        files = build_day_files(log, prefer_xlsx=True)
        profile = await self._profiles.get(chat_id)
        return {
            "photo": str(files["png"]),
            "caption": f"{self._build_day_caption(files['summary'], profile)} | Удалено: {removed_count}",
        }

    def _parse_indices(self, raw: str) -> set[int]:
        parts = [p.strip() for p in (raw or "").replace(";", ",").split(",")]
        result: set[int] = set()
        for part in parts:
            if not part:
                continue
            if not part.isdigit():
                return set()
            value = int(part)
            if value <= 0:
                return set()
            result.add(value)
        return result
    async def has_access(self, chat_id: int) -> bool:
        if self._is_admin(chat_id):
            return True
        p = await self._profiles.get(chat_id)
        return bool(p and p.subscribe_until and date.today() <= date.fromisoformat(p.subscribe_until))

    async def build_pay_text(self, chat_id: int) -> str:
        s = self._settings
        if not (s and s.yoomoney_receiver):
            return ("Подписка недоступна: не задан кошелёк ЮMoney. "
                    "Обратитесь к администратору.")
        return format_subscription_offer_text(s, chat_id)

    async def build_topup_pay_text(self, chat_id: int) -> str:
        """Ссылки на оплату для пользователя с активной подпиской (продление от текущей даты)."""
        s = self._settings
        if not (s and s.yoomoney_receiver):
            return ("Подписка недоступна: не задан кошелёк ЮMoney. "
                    "Обратитесь к администратору.")
        current_until: str | None = None
        if await self._has_active_subscription(chat_id):
            p = await self._profiles.get(chat_id)
            if p and p.subscribe_until:
                current_until = p.subscribe_until
        return format_subscription_topup_text(s, chat_id, current_until=current_until)
    
    async def _has_active_subscription(self, chat_id: int) -> bool:
        if self._is_admin(chat_id):
            return True
        p = await self._profiles.get(chat_id)
        return bool(p and p.subscribe_until and date.today() <= date.fromisoformat(p.subscribe_until))
    
    def _build_payment_text(self, chat_id: int) -> str:
        return format_subscription_expired_text()

    def _build_day_caption(self, summary: DaySummary, profile) -> str:
        return f"Итог калорий: {summary.net_kcal} ккал"

    async def _generate_day_recommendation(self, chat_id: int, summary: DaySummary, profile) -> str:
        summary_payload = {
            "consumed_kcal": summary.consumed_kcal,
            "burned_kcal": summary.burned_kcal,
            "net_kcal": summary.net_kcal,
            "protein_g": summary.protein_g,
            "fat_g": summary.fat_g,
            "carb_g": summary.carb_g,
            "foods_count": summary.foods_count,
            "activities_count": summary.activities_count,
        }
        profile_payload = {
            "calories_goal": getattr(profile, "calories_goal", None) if profile else None,
            "height_cm": getattr(profile, "height_cm", None) if profile else None,
            "weight_kg": getattr(profile, "weight_kg", None) if profile else None,
        }

        try:
            recommendation = await self._llm.recommend_day(
                chat_id=chat_id,
                summary=summary_payload,
                profile=profile_payload,
            )
        except Exception:
            recommendation = ""

        recommendation = (recommendation or "").strip()
        if recommendation:
            return recommendation

        return (
            "День уже зафиксирован, и это хороший шаг. Старайтесь держать рацион ровным, "
            "добирать белок и добавлять посильную активность без перегруза."
        )
