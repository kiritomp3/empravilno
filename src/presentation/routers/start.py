from aiogram import Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from presentation.keyboards.reply import start_kb


router = Router(name="start")

POST_REGISTRATION_INSTRUCTION = (
    "Как пользоваться ботом:\n\n"
    "1. Просто отправляйте одним сообщением еду, напитки или спорт.\n"
    "2. Можно писать свободно, без строгого формата.\n"
    "3. В ответ придёт красивая таблица и краткий итог за день.\n\n"
    "Примеры:\n"
    "• «2 яйца, овсянка и латте»\n"
    "• «сегодня 8500 шагов и бег 1 км»\n"
    "• «жим 50 кг 3 подхода по 12, бабочка 36 кг 3x12»\n"
    "• «плавание брассом 1.5 часа»\n\n"
    "Если нужно, откройте «Главное меню» для профиля, цели по калориям и роста/веса."
)


class RegistrationBodyMetrics(StatesGroup):
    waiting_height = State()
    waiting_weight = State()

def setup_start_router(processor, telemetry=None, settings=None):
    @router.message(CommandStart())
    async def on_start(msg: types.Message, state: FSMContext):
        if telemetry:
            await telemetry.incr("telegram.start_total")
        # извлечём deep-link payload (если есть)
        payload = None
        if msg.text:
            parts = msg.text.strip().split(maxsplit=1)
            if len(parts) == 2:
                payload = parts[1].strip()

        # создадим/обновим профиль и начислим +2 (если новый)
        welcome = await processor.ensure_profile(
            chat_id=msg.chat.id,
            name=msg.from_user.full_name if msg.from_user else None,
            username=msg.from_user.username if msg.from_user else None
        )

        # обработаем реферал (если есть payload вида ref_<id>)
        ref_notice = await processor.handle_referral(
            new_chat_id=msg.chat.id,
            ref_payload=payload,
            new_username=(msg.from_user.username if msg.from_user else None)
        )

        text = welcome
        if ref_notice:
            text += "\n\n" + ref_notice

        profile = await processor._profiles.get(msg.chat.id)
        needs_metrics = bool(profile and (profile.height_cm is None or profile.weight_kg is None))
        if needs_metrics:
            await state.set_state(RegistrationBodyMetrics.waiting_height)
            await msg.answer(
                text + "\n\n📏 Введите ваш рост в сантиметрах. Например: 178",
                reply_markup=types.ReplyKeyboardRemove(),
            )
            return

        has_access = await processor.has_access(msg.chat.id)
        await msg.answer(
            text + "\n\n" + POST_REGISTRATION_INSTRUCTION,
            reply_markup=start_kb(has_access=has_access),
        )

    @router.message(Command("setbody"))
    async def on_setbody(msg: types.Message, state: FSMContext):
        await state.set_state(RegistrationBodyMetrics.waiting_height)
        await msg.answer(
            "Обновим параметры профиля.\n\n📏 Введите рост в сантиметрах. Например: 178",
            reply_markup=types.ReplyKeyboardRemove(),
        )

    @router.message(RegistrationBodyMetrics.waiting_height)
    async def on_height(msg: types.Message, state: FSMContext):
        raw = (msg.text or "").strip().replace(",", ".")
        if not raw.isdigit():
            await msg.answer("Введите рост целым числом в сантиметрах. Например: 178")
            return

        height_cm = int(raw)
        if not 100 <= height_cm <= 250:
            await msg.answer("Рост должен быть в диапазоне 100-250 см. Попробуйте ещё раз.")
            return

        await state.update_data(height_cm=height_cm)
        await state.set_state(RegistrationBodyMetrics.waiting_weight)
        await msg.answer("⚖️ Теперь введите вес в килограммах. Например: 72.5")

    @router.message(RegistrationBodyMetrics.waiting_weight)
    async def on_weight(msg: types.Message, state: FSMContext):
        raw = (msg.text or "").strip().replace(",", ".").replace(" ", "")
        try:
            weight_kg = float(raw)
        except ValueError:
            await msg.answer("Введите вес числом. Например: 72.5")
            return

        if not 30 <= weight_kg <= 350:
            await msg.answer("Вес должен быть в диапазоне 30-350 кг. Попробуйте ещё раз.")
            return

        data = await state.get_data()
        height_cm = data.get("height_cm")
        await processor.set_body_metrics(msg.chat.id, height_cm=height_cm, weight_kg=weight_kg)
        await state.clear()

        has_access = await processor.has_access(msg.chat.id)
        await msg.answer(
            "Параметры сохранены.\n\n" + POST_REGISTRATION_INSTRUCTION,
            reply_markup=start_kb(has_access=has_access),
        )

    @router.message(Command("help"))
    async def on_help(msg: types.Message):
        await msg.answer(
            "Команды:\n"
            "/start — начать/вернуться к боту\n"
            "/setgoal <ккал> — задать цель по калориям (например, /setgoal 2200)\n"
            "/setbody — обновить рост и вес\n"
            "/me — показать ваш профиль\n"
            "/reflink — получить вашу реферальную ссылку\n"
            "Еду и спорт можно просто отправлять обычным сообщением."
        )

    @router.message(Command("setgoal"))
    async def on_setgoal(msg: types.Message):
        goal = None
        if msg.text:
            parts = msg.text.split(maxsplit=1)
            if len(parts) == 2:
                try:
                    goal = int(parts[1])
                except ValueError:
                    return await msg.answer("Введите число: например, /setgoal 2200")
        reply = await processor.set_calories_goal(msg.chat.id, goal)
        await msg.answer(reply)

    @router.message(Command("me"))
    async def on_me(msg: types.Message):
        await msg.answer(await processor.get_profile_text(msg.chat.id))

    @router.message(Command("reflink"))
    async def on_reflink(msg: types.Message):
        bot = msg.bot
        me = await bot.get_me()
        link = await processor.build_ref_link(me.username, msg.chat.id)
        await msg.answer(f"Ваша реферальная ссылка:\n{link}")

    @router.message(Command("stats"))
    async def on_stats(msg: types.Message):
        if not telemetry or not settings or msg.chat.id not in settings.admin_chat_ids:
            await msg.answer("Команда недоступна.")
            return

        stats = await telemetry.collect_all_stats()
        business = stats["business"]
        counters = stats["counters"]
        text = (
            "Продакшн-статистика\n\n"
            f"Пользователей: {business['users_total']}\n"
            f"Активных подписок: {business['subscriptions_active']}\n"
            f"Рефералов: {business['referrals_total']}\n"
            f"Дневников: {business['nutrition_logs_total']}\n"
            f"Успешных оплат: {int(counters.get('payments.success_total', 0))}\n"
            f"Неуспешных оплат: {int(counters.get('payments.failed_total', 0))}\n"
            f"Webhook дублей: {int(counters.get('payments.duplicate_total', 0))}\n"
            f"Сообщений пользователей: {int(counters.get('telegram.user_messages_total', 0))}"
        )
        await msg.answer(text)
    

    return router
