from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

def day_keyboard(show_undo: bool = True) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Завершить день", callback_data="finish_day")
    if show_undo:
        kb.button(text="🗑 Убрать", callback_data="remove_items")
    kb.adjust(1)
    return kb.as_markup()
