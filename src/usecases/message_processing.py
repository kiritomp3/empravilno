from __future__ import annotations
from typing import Any
from domain.ports import LLMClient, ChatSessionStore, NutritionLogStore, UserProfileStore
from services.rendering import DaySummary, build_day_files
from services.text_normalizer import extract_json_object
from services.payments import build_yoomoney_quickpay_link
from datetime import date

RESPONSE_KEYS = ("items",)

WELCOME_TEXT = (
    "Привет! Я бот, который поможет считать питание и спорт. "
    "Вам начислено +2 дня подписки за регистрацию.\n\n"
    "Сначала давайте заполним рост и вес, чтобы рекомендации были точнее."
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


    async def process_user_text(self, chat_id: int, text: str) -> str | dict:
        if not await self._has_active_subscription(chat_id):
            return self._build_payment_text(chat_id)

        active = await self._sessions.is_active(chat_id)
        if not active:
        # Автовключение: есть подписка → включаем автоответ и продолжаем разбор текста
            await self._sessions.set_active(chat_id, True)

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

        raw = await self._llm.reply_with_image(
            chat_id=chat_id,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
            user_text=caption,
        )
        return await self._build_nutrition_reply(chat_id, raw)

    async def _build_nutrition_reply(self, chat_id: int, raw: str) -> str | dict:
        data = extract_json_object(raw)

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

    def _build_day_caption(self, summary: DaySummary, profile) -> str:
        recommendation = self._build_recommendation(summary, profile)
        return (
            "Итоги за день\n\n"
            f"Всего калорий: {summary.consumed_kcal} ккал\n"
            f"Всего белков: {summary.protein_g:.1f} г\n"
            f"Всего жиров: {summary.fat_g:.1f} г\n"
            f"Всего углеводов: {summary.carb_g:.1f} г\n"
            f"Сожжено калорий: {summary.burned_kcal} ккал\n"
            f"Итог калорий: {summary.net_kcal} ккал\n"
            f"Краткая рекомендация: {recommendation}"
        )

    def _build_recommendation(self, summary: DaySummary, profile) -> str:
        goal = getattr(profile, "calories_goal", None) if profile else None
        height_cm = getattr(profile, "height_cm", None) if profile else None
        weight_kg = getattr(profile, "weight_kg", None) if profile else None

        if goal is not None:
            delta = summary.net_kcal - goal
            if delta > 250:
                return "Сегодня вы заметно выше цели. Если хотите дефицит, следующий приём пищи лучше сделать легче."
            if delta < -250:
                return "Сегодня вы заметно ниже цели. Добавьте сытный приём пищи или перекус с белком."
            return "Баланс дня близок к цели. Старайтесь удерживать такой ритм и добирать белок равномерно."

        if height_cm and weight_kg:
            height_m = height_cm / 100
            bmi = weight_kg / (height_m * height_m)
            if bmi < 18.5:
                return "Вес выглядит невысоким относительно роста. Не занижайте калорийность и следите за регулярным питанием."
            if bmi > 27:
                return "Если цель в снижении веса, держите умеренный дефицит и продолжайте добавлять активность без перегруза."
            return "День выглядит сбалансированно. Для более точных советов задайте цель по калориям в профиле."

        if summary.burned_kcal > 0:
            return "Активность учтена. После тренировочного дня особенно полезно следить за водой и белком."
        return "Заполните рост, вес и цель по калориям, и рекомендации станут заметно точнее."
