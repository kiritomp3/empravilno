from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def start_kb(has_access: bool = True) -> ReplyKeyboardMarkup:
    if has_access:
        # доступ есть
        keyboard = [[KeyboardButton(text="Главное меню"),
                     KeyboardButton(text="Добавить приём пищи")]]
    else:
        # доступа нет — предлагаем оплатить
        keyboard = [[KeyboardButton(text="Главное меню"),
                     KeyboardButton(text="Оплатить подписку")]]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или напишите, что вы съели" if has_access
                                else "Подписка закончилась — оплатите, чтобы продолжить"
    )

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Цель по калориям")],
            [KeyboardButton(text="Реф. ссылка")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите пункт меню"
    )