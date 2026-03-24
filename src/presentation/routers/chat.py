# emgood/src/presentation/routers/chat.py
from io import BytesIO
from aiogram import Router, F, types
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from usecases.message_processing import MessageProcessor
from presentation.keyboards.common import day_keyboard

router = Router(name="chat")

class RemoveItemsState(StatesGroup):
    waiting_for_indices = State()

def setup(processor: MessageProcessor, telemetry=None) -> Router:

    @router.callback_query(F.data == "finish_day")
    async def on_finish_day(cb: CallbackQuery):
        reply = await processor.finish_day(cb.message.chat.id)
        show_undo = await processor.has_items(cb.message.chat.id) if hasattr(processor, "has_items") else True

        if isinstance(reply, dict) and "photo" in reply:
            await cb.message.answer_photo(
                types.FSInputFile(reply["photo"]),
                caption=reply.get("caption") or None,
                reply_markup=day_keyboard(show_undo)
            )
        else:
            await cb.message.answer(str(reply), reply_markup=day_keyboard(show_undo))
        await cb.answer()

    @router.callback_query(F.data == "remove_items")
    async def on_remove_items(cb: CallbackQuery, state: FSMContext):
        await state.set_state(RemoveItemsState.waiting_for_indices)
        await cb.message.answer(
            "Введите номер записи из таблицы для удаления.\n"
            "Можно перечислить несколько через запятую: 1,3,5"
        )
        await cb.answer()

    @router.message(RemoveItemsState.waiting_for_indices, F.text)
    async def on_remove_items_input(msg: types.Message, state: FSMContext):
        reply = await processor.remove_items_by_input(msg.chat.id, msg.text or "")
        await state.clear()
        show_undo = await processor.has_items(msg.chat.id) if hasattr(processor, "has_items") else True

        if isinstance(reply, dict) and "photo" in reply:
            await msg.answer_photo(
                types.FSInputFile(reply["photo"]),
                caption=reply.get("caption") or None,
                reply_markup=day_keyboard(show_undo)
            )
        else:
            await msg.answer(str(reply), reply_markup=day_keyboard(show_undo))

    @router.message(F.text)
    async def on_text(msg: types.Message):
        if telemetry:
            await telemetry.incr("telegram.user_messages_total")
        reply = await processor.process_user_text(msg.chat.id, msg.text or "")

        show_undo = True
        if hasattr(processor, "has_items"):
            try:
                show_undo = await processor.has_items(msg.chat.id)
            except Exception:
                show_undo = True

        if isinstance(reply, dict) and "photo" in reply:
            await msg.answer_photo(
                types.FSInputFile(reply["photo"]),
                caption=reply.get("caption") or None,
                reply_markup=day_keyboard(show_undo)
            )
        else:
            await msg.answer(str(reply), reply_markup=day_keyboard(show_undo))

    @router.message(F.photo)
    async def on_photo(msg: types.Message):
        if telemetry:
            await telemetry.incr("telegram.user_messages_total")

        largest_photo = msg.photo[-1]
        file = await msg.bot.get_file(largest_photo.file_id)
        buffer = BytesIO()
        await msg.bot.download_file(file.file_path, destination=buffer)
        reply = await processor.process_user_photo(
            msg.chat.id,
            image_bytes=buffer.getvalue(),
            image_mime_type="image/jpeg",
            caption=msg.caption or "",
        )

        show_undo = True
        if hasattr(processor, "has_items"):
            try:
                show_undo = await processor.has_items(msg.chat.id)
            except Exception:
                show_undo = True

        if isinstance(reply, dict) and "photo" in reply:
            await msg.answer_photo(
                types.FSInputFile(reply["photo"]),
                caption=reply.get("caption") or None,
                reply_markup=day_keyboard(show_undo)
            )
        else:
            await msg.answer(str(reply), reply_markup=day_keyboard(show_undo))

    return router
