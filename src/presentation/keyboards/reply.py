from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

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

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Цель, рост и вес")],
            [KeyboardButton(text="Подписка"), KeyboardButton(text="Реф. ссылка")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите пункт меню"
    )
