from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

def day_keyboard(show_undo: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧹 Очистить день", callback_data="clear_day")
    if show_undo:
        kb.button(text="↩️ Отменить последнее", callback_data="undo_last")
    kb.adjust(1)
    return kb.as_markup()