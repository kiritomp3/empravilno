from aiogram import Router, types
from aiogram.filters import Command, CommandStart
from presentation.keyboards.reply import start_kb


router = Router(name="start")

def setup_start_router(processor):
    @router.message(CommandStart())
    async def on_start(msg: types.Message):
        # извлечём deep-link payload (если есть)
        payload = None
        if msg.text:
            parts = msg.text.strip().split(maxsplit=1)
            if len(parts) == 2:
                payload = parts[1].strip()

        # создадим/обновим профиль и начислим +7 (если новый)
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

        has_access = await processor.has_access(msg.chat.id)
        await msg.answer(text, reply_markup=start_kb(has_access=has_access))

    @router.message(Command("help"))
    async def on_help(msg: types.Message):
        await msg.answer(
            "Команды:\n"
            "/start — начать/вернуться к боту\n"
            "/setgoal <ккал> — задать цель по калориям (например, /setgoal 2200)\n"
            "/me — показать ваш профиль\n"
            "/reflink — получить вашу реферальную ссылку\n"
            "Также используйте кнопки на клавиатуре под сообщением."
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
    

    return router