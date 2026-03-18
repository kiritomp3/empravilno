# emgood/src/presentation/routers/chat.py
from io import BytesIO
from aiogram import Router, F, types
from aiogram.types import CallbackQuery
from usecases.message_processing import MessageProcessor
from presentation.keyboards.common import day_keyboard

router = Router(name="chat")

def setup(processor: MessageProcessor, telemetry=None) -> Router:

    @router.callback_query(F.data == "clear_day")
    async def on_clear_day(cb: CallbackQuery):
        reply = await processor.clear_day(cb.message.chat.id)
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

    @router.callback_query(F.data == "undo_last")
    async def on_undo_last(cb: CallbackQuery):
        reply = await processor.undo_last(cb.message.chat.id)
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
