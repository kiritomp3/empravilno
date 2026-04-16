# emgood/src/presentation/routers/menu_reply.py
from __future__ import annotations
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from presentation.keyboards.reply import start_kb, main_menu_kb
from services.subscription_plans import (
    build_plan_payment_link,
    format_subscription_choice_text,
    get_subscription_plans,
)

class ProfileEdit(StatesGroup):
    waiting_goal = State()
    waiting_height = State()
    waiting_weight = State()

def setup_menu_reply_router(processor, telemetry=None, settings=None):
    router = Router(name="menu_reply")
    miniapp_url = settings.miniapp_url if settings else "http://localhost:8000/miniapp"

    def _fmt_goal(v: int | None) -> str:
        return f"{v} ккал/день" if v else "не задана"

    # Команда /menu как дубликат «Главное меню»
    @router.message(Command("menu"))
    async def cmd_menu(msg: types.Message):
        await msg.answer("Главное меню:", reply_markup=main_menu_kb(miniapp_url=miniapp_url))

    # Открыть главное меню кнопкой
    @router.message(F.text.casefold() == "главное меню")
    async def open_menu(msg: types.Message, state: FSMContext):
        await state.clear()
        await msg.answer("Главное меню:", reply_markup=main_menu_kb(miniapp_url=miniapp_url))

    # Назад в стартовые кнопки
    @router.callback_query(F.data == "back")
    async def back_to_start(callback: CallbackQuery, state: FSMContext):
        await state.clear()
        has_access = await processor.has_access(callback.from_user.id)
        await callback.message.edit_text(
            "Можно просто написать, что вы съели или какую активность сделали.",
            reply_markup=start_kb(has_access=has_access),
        )
        await callback.answer()

    # Профиль
    @router.callback_query(F.data == "profile")
    async def show_profile(callback: CallbackQuery):
        text = await processor.get_profile_text(callback.from_user.id)
        await callback.message.edit_text(text, reply_markup=main_menu_kb(miniapp_url=miniapp_url))
        await callback.answer()

    # Реферальная ссылка
    @router.callback_query(F.data == "ref_link")
    async def show_reflink(callback: CallbackQuery):
        me = await callback.bot.get_me()
        link = await processor.build_ref_link(me.username, callback.from_user.id)
        await callback.message.edit_text(f"Ваша реферальная ссылка:\n{link}", reply_markup=main_menu_kb(miniapp_url=miniapp_url))
        await callback.answer()

    @router.callback_query(F.data == "goal_height_weight")
    async def ask_profile_params(callback: CallbackQuery, state: FSMContext):
        p = await processor._profiles.get(callback.from_user.id)
        current = _fmt_goal(p.calories_goal if p else None)
        current_height = f"{p.height_cm} см" if p and p.height_cm else "не указан"
        current_weight = (
            f"{p.weight_kg:.1f}".rstrip("0").rstrip(".") + " кг" if p and p.weight_kg else "не указан"
        )
        await state.set_state(ProfileEdit.waiting_goal)
        await callback.message.edit_text(
            "🎯📐 Обновление цели и параметров\n\n"
            f"Текущая цель: <b>{current}</b>\n\n"
            f"Текущий рост: <b>{current_height}</b>\n"
            f"Текущий вес: <b>{current_weight}</b>\n\n"
            "Введите новое целое значение ккал (800–6000), например: 2200.\n"
            "Чтобы отменить, нажмите «⬅️ Назад».",
            reply_markup=main_menu_kb(miniapp_url=miniapp_url)
        )
        await callback.answer()

    @router.message(ProfileEdit.waiting_goal, F.text)
    async def receive_goal(msg: types.Message, state: FSMContext):
        raw = (msg.text or "").strip().replace(" ", "")
        if not raw.isdigit():
            await msg.answer("Пожалуйста, введите целое число ккал. Диапазон 800–6000.")
            return
        goal = int(raw)
        if goal < 800 or goal > 6000:
            await msg.answer("Слишком мало/много. Введите число в пределах 800–6000.")
            return
        await state.update_data(goal=goal)
        await state.set_state(ProfileEdit.waiting_height)
        await msg.answer("Введите рост в сантиметрах. Например: 178")

    @router.message(ProfileEdit.waiting_height, F.text)
    async def receive_height(msg: types.Message, state: FSMContext):
        raw = (msg.text or "").strip().replace(",", ".")
        if not raw.isdigit():
            await msg.answer("Введите рост целым числом в сантиметрах. Например: 178")
            return

        height_cm = int(raw)
        if not 100 <= height_cm <= 250:
            await msg.answer("Рост должен быть в пределах 100-250 см.")
            return

        await state.update_data(height_cm=height_cm)
        await state.set_state(ProfileEdit.waiting_weight)
        await msg.answer("Теперь введите вес в килограммах. Например: 72.5")

    @router.message(ProfileEdit.waiting_weight, F.text)
    async def receive_weight(msg: types.Message, state: FSMContext):
        raw = (msg.text or "").strip().replace(",", ".").replace(" ", "")
        try:
            weight_kg = float(raw)
        except ValueError:
            await msg.answer("Введите вес числом. Например: 72.5")
            return

        if not 30 <= weight_kg <= 350:
            await msg.answer("Вес должен быть в пределах 30-350 кг.")
            return

        data = await state.get_data()
        await processor.set_calories_goal(msg.chat.id, data.get("goal"))
        await processor.set_body_metrics(
            msg.chat.id,
            height_cm=data.get("height_cm"),
            weight_kg=weight_kg,
        )
        await state.clear()
        await msg.answer("Цель, рост и вес сохранены ✅", reply_markup=main_menu_kb(miniapp_url=miniapp_url))

    @router.callback_query(F.data == "subscription")
    async def open_subscription(callback: CallbackQuery):
        if telemetry:
            await telemetry.incr("payments.intent_total")
        profile = await processor._profiles.get(callback.from_user.id)
        has_access = await processor.has_access(callback.from_user.id)
        current_until = profile.subscribe_until if (profile and has_access) else None

        kb = InlineKeyboardBuilder()
        for plan in get_subscription_plans(processor._settings):
            kb.button(
                text=f"{plan.title} ({plan.price_rub:.0f} ₽)",
                callback_data=f"sub_plan:{plan.slug}",
            )
        kb.adjust(1)
        await callback.message.edit_text(
            format_subscription_choice_text(current_until=current_until),
            reply_markup=kb.as_markup(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("sub_plan:"))
    async def on_subscription_plan_selected(cb: CallbackQuery):
        slug = (cb.data or "").split(":", 1)[1]
        plans = {p.slug: p for p in get_subscription_plans(processor._settings)}
        plan = plans.get(slug)
        if plan is None:
            await cb.answer("Тариф не найден", show_alert=True)
            return
        link = build_plan_payment_link(processor._settings, cb.message.chat.id, plan)
        await cb.message.answer(
            f"💳 <b>{plan.title}</b> — <b>{plan.price_rub:.0f} ₽</b>\n\n"
            f"Ссылка на оплату:\n{link}"
        )
        await cb.answer()

    @router.message(F.text.casefold() == "оплатить подписку")
    async def legacy_pay_alias(msg: types.Message):
        await open_subscription(msg)

    @router.message(F.text.casefold() == "докупить подписку")
    async def legacy_topup_alias(msg: types.Message):
        await open_subscription(msg)

    return router
