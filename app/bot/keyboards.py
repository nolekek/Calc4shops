from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from app.config import settings


def get_main_reply_keyboard(webapp_url: str | None = None) -> ReplyKeyboardMarkup:
    """Главная клавиатура бота с кнопкой запуска Mini App."""
    url = webapp_url or settings.WEBAPP_URL or "http://localhost:8000"
    
    keyboard = [
        [
            KeyboardButton(
                text="📱 Открыть калькулятор сделок",
                web_app=WebAppInfo(url=url)
            )
        ],
        [
            KeyboardButton(text="⚡ Быстрый расчет"),
            KeyboardButton(text="📁 Массовый расчёт (CSV)")
        ],
        [
            KeyboardButton(text="📊 Моя история"),
            KeyboardButton(text="⚙️ Настройки")
        ]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Введите /calc или откройте калькулятор"
    )


def get_start_inline_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Инлайн-кнопки под приветственным сообщением."""
    url = webapp_url or settings.WEBAPP_URL or "http://localhost:8000"
    
    buttons = [
        [
            InlineKeyboardButton(
                text="🚀 Открыть Mini App (в 1 клик)",
                web_app=WebAppInfo(url=url)
            )
        ],
        [
            InlineKeyboardButton(text="📊 История", callback_data="btn_history"),
            InlineKeyboardButton(text="⚙️ Пресеты", callback_data="btn_settings"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_platforms_inline_keyboard() -> InlineKeyboardMarkup:
    """Выбор площадки для быстрого расчёта."""
    buttons = [
        [
            InlineKeyboardButton(text="🛒 Plati / Digiseller", callback_data="plat_plati"),
            InlineKeyboardButton(text="🎮 Playerok", callback_data="plat_playerok")
        ],
        [
            InlineKeyboardButton(text="🤝 FunPay", callback_data="plat_funpay"),
            InlineKeyboardButton(text="⚙️ Своя комиссия", callback_data="plat_custom")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
