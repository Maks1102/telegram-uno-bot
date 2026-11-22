"""Reply-клавиатура с быстрыми ответами и служебными кнопками."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from knowledge import CARDS, DISPUTES, RULES, STRATEGY, VERSIONS

QUIZ_BUTTON = "🧠 Викторина"
RESET_BUTTON = "🔄 Сброс чата"


def main_keyboard() -> ReplyKeyboardMarkup:
    """Кнопки: пять справок + викторина через ИИ + сброс истории."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CARDS), KeyboardButton(text=RULES)],
            [KeyboardButton(text=VERSIONS), KeyboardButton(text=STRATEGY)],
            [KeyboardButton(text=DISPUTES), KeyboardButton(text=QUIZ_BUTTON)],
            [KeyboardButton(text=RESET_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Спроси про карты, правила или версию Уно…",
    )
