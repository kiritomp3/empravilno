# emgood/src/presentation/routers/menu_reply.py
from __future__ import annotations
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from presentation.keyboards.reply import start_kb, main_menu_kb

class GoalEdit(StatesGroup):
    waiting_number = State()


class BodyMetricsEdit(StatesGroup):
    waiting_height = State()
    waiting_weight = State()

def setup_menu_reply_router(processor, telemetry=None, settings=None):
    router = Router(name="menu_reply")

    def _fmt_goal(v: int | None) -> str:
        return f"{v} ккал/день" if v else "не задана"

    # Команда /menu как дубликат «Главное меню»
    @router.message(Command("menu"))
    async def cmd_menu(msg: types.Message):
        await msg.answer("Главное меню:", reply_markup=main_menu_kb())

    # Открыть главное меню кнопкой
    @router.message(F.text.casefold() == "главное меню")
    async def open_menu(msg: types.Message, state: FSMContext):
        await state.clear()
        await msg.answer("Главное меню:", reply_markup=main_menu_kb())

    # Назад в стартовые кнопки
    @router.message(F.text == "⬅️ Назад")
    async def back_to_start(msg: types.Message, state: FSMContext):
        await state.clear()
        has_access = await processor.has_access(msg.chat.id)
        await msg.answer(
            "Можно просто написать, что вы съели или какую активность сделали.",
            reply_markup=start_kb(has_access=has_access),
        )

    # Профиль
    @router.message(F.text.casefold() == "профиль")
    async def show_profile(msg: types.Message):
        text = await processor.get_profile_text(msg.chat.id)
        await msg.answer(text, reply_markup=main_menu_kb())

    # Реферальная ссылка
    @router.message(F.text.casefold() == "реф. ссылка")
    async def show_reflink(msg: types.Message):
        me = await msg.bot.get_me()
        link = await processor.build_ref_link(me.username, msg.chat.id)
        await msg.answer(f"Ваша реферальная ссылка:\n{link}", reply_markup=main_menu_kb())

    # Изменение цели по калориям: запрос числа
    @router.message(F.text.casefold() == "цель по калориям")
    async def ask_goal(msg: types.Message, state: FSMContext):
        p = await processor._profiles.get(msg.chat.id)
        current = _fmt_goal(p.calories_goal if p else None)
        await state.set_state(GoalEdit.waiting_number)
        await msg.answer(
            "🎯 Изменение цели по калориям\n\n"
            f"Текущая цель: <b>{current}</b>\n\n"
            "Введите новое целое значение ккал (800–6000), например: 2200.\n"
            "Чтобы отменить, нажмите «⬅️ Назад».",
            reply_markup=main_menu_kb()
        )

    # Принимаем число и сохраняем
    @router.message(GoalEdit.waiting_number, F.text)
    async def receive_goal(msg: types.Message, state: FSMContext):
        raw = (msg.text or "").strip().replace(" ", "")
        if not raw.isdigit():
            await msg.answer("Пожалуйста, введите целое число ккал. Диапазон 800–6000.")
            return
        goal = int(raw)
        if goal < 800 or goal > 6000:
            await msg.answer("Слишком мало/много. Введите число в пределах 800–6000.")
            return
        await processor.set_calories_goal(msg.chat.id, goal)
        await state.clear()
        await msg.answer(f"Цель по калориям обновлена: <b>{goal} ккал/день</b> ✅", reply_markup=main_menu_kb())

    @router.message(F.text.casefold() == "рост и вес")
    async def ask_body_metrics(msg: types.Message, state: FSMContext):
        p = await processor._profiles.get(msg.chat.id)
        current_height = f"{p.height_cm} см" if p and p.height_cm else "не указан"
        current_weight = (
            f"{p.weight_kg:.1f}".rstrip("0").rstrip(".") + " кг" if p and p.weight_kg else "не указан"
        )
        await state.set_state(BodyMetricsEdit.waiting_height)
        await msg.answer(
            "📐 Параметры профиля\n\n"
            f"Текущий рост: <b>{current_height}</b>\n"
            f"Текущий вес: <b>{current_weight}</b>\n\n"
            "Введите рост в сантиметрах. Например: 178",
            reply_markup=main_menu_kb()
        )

    @router.message(BodyMetricsEdit.waiting_height, F.text)
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
        await state.set_state(BodyMetricsEdit.waiting_weight)
        await msg.answer("Теперь введите вес в килограммах. Например: 72.5")

    @router.message(BodyMetricsEdit.waiting_weight, F.text)
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
        await processor.set_body_metrics(
            msg.chat.id,
            height_cm=data.get("height_cm"),
            weight_kg=weight_kg,
        )
        await state.clear()
        await msg.answer("Рост и вес сохранены ✅", reply_markup=main_menu_kb())

    @router.message(F.text.casefold() == "оплатить подписку")
    async def pay_now(msg: types.Message):
        if telemetry:
            await telemetry.incr("payments.intent_total")
        pay_text = await processor.build_pay_text(msg.chat.id)
        await msg.answer(pay_text, reply_markup=start_kb(has_access=False))

    @router.message(F.text.casefold() == "докупить подписку")
    async def topup_subscription(msg: types.Message):
        if telemetry:
            await telemetry.incr("payments.topup_intent_total")
        pay_text = await processor.build_topup_pay_text(msg.chat.id)
        await msg.answer(pay_text, reply_markup=main_menu_kb())

    return router
