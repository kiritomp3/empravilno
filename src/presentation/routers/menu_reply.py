# emgood/src/presentation/routers/menu_reply.py
from __future__ import annotations
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from presentation.keyboards.reply import start_kb, main_menu_kb

class GoalEdit(StatesGroup):
    waiting_number = State()

def setup_menu_reply_router(processor):
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
        await msg.answer("Вы в стартовом меню.", reply_markup=start_kb())

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

    # Добавить приём пищи — просто просим ввести текст
    @router.message(F.text.casefold() == "добавить приём пищи")
    async def add_meal(msg: types.Message):
        # Без FSM: следующее обычное текстовое сообщение поймает ваш существующий чат-роутер и распарсит как обычно
        await msg.answer(
            "Напишите, что вы съели (пример: «я съел 200 г курицы и 150 г риса»).",
            reply_markup=start_kb()
        )
    
    @router.message(F.text.casefold() == "добавить приём пищи")
    async def add_meal(msg: types.Message):
        if not await processor.has_access(msg.chat.id):
            pay_text = await processor.build_pay_text(msg.chat.id)
            await msg.answer(pay_text, reply_markup=start_kb(has_access=False))
            return
        await msg.answer(
            "Напишите, что вы съели (пример: «я съел 200 г курицы и 150 г риса»).",
            reply_markup=start_kb(has_access=True)
        )

    @router.message(F.text.casefold() == "оплатить подписку")
    async def pay_now(msg: types.Message):
        pay_text = await processor.build_pay_text(msg.chat.id)
        await msg.answer(pay_text, reply_markup=start_kb(has_access=False))

    return router