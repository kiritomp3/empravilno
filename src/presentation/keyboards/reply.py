from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

def start_kb(has_access: bool = True) -> ReplyKeyboardMarkup:
    if has_access:
        keyboard = [[KeyboardButton(text="Главное меню")]]
    else:
        keyboard = [[KeyboardButton(text="Главное меню"),
                     KeyboardButton(text="Подписка")]]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Напишите, что съели или какую активность сделали" if has_access
                                else "Подписка закончилась — оплатите, чтобы продолжить"
    )

def main_menu_kb(miniapp_url: str = "https://yourdomain.com/miniapp") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Профиль", callback_data="profile")
    kb.button(text="Цель, рост и вес", callback_data="goal_height_weight")
    kb.button(text="Подписка", callback_data="subscription")
    kb.button(text="Реф. ссылка", callback_data="ref_link")
    kb.button(text="Посмотреть прогресс", web_app=WebAppInfo(url=miniapp_url))
    kb.button(text="⬅️ Назад", callback_data="back")
    kb.adjust(2)
    return kb.as_markup()
