"""Обработчики сообщений: кнопки-справки и вопросы к локальной ИИ-модели."""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import ErrorEvent, Message

from knowledge import TOPICS, get_topic, split_message
from keyboards import QUIZ_BUTTON, RESET_BUTTON, main_keyboard
from llm import get_tutor
from tgmd import md_to_html, split_html, strip_tags

router = Router(name="uno-instructor")
logger = logging.getLogger(__name__)

WELCOME = (
    "Привет! Я Уно-Инструктор. Могу объяснить карты и правила, сравнить версии UNO, "
    "разобрать спорную ситуацию, дать стратегию или провести мини-викторину. "
    "С чего начнём: основы, конкретная карта, версия игры или стратегия?"
)

HELP = (
    "Я — Уно-Инструктор, помощник по картам и правилам UNO.\n"
    "\n"
    "📌 Кнопки внизу — готовые справки (отвечают мгновенно, без ИИ):\n"
    "• 🃏 Карты, 📜 Правила, 🕹 Версии, ⚔ Стратегия, 🤔 Спорные ситуации\n"
    "\n"
    "💬 Любой твой текст — вопрос к локальной ИИ-модели (LM Studio / llama.cpp).\n"
    "\n"
    "Команды:\n"
    "/start — приветствие\n"
    "/reset — очистить историю диалога\n"
    "/help — эта справка"
)

RESET_DONE = "🗑 История очищена. С чего начнём: основы, карта, версия или стратегия?"

QUIZ_REQUEST = (
    "Проведи мини-викторину по правилам UNO: один вопрос и 3–4 варианта ответа, "
    "пронумерованный 1, 2, 3, 4. Не пиши правильный ответ сразу — дождись, "
    "когда я выберу вариант, и только потом дай ответ с коротким пояснением."
)

LLM_ERROR = (
    "⚠️ Не удалось получить ответ от локальной модели.\n"
    "\n"
    "Проверь:\n"
    "• LM Studio запущен, модель загружена, сервер включён (вкладка Developer)\n"
    "• в .env указан верный LLM_BASE_URL (для llama.cpp — http://адрес:8080/v1)\n"
    "• в LLM_MODEL пусто или записано точное имя модели"
)

INTERNAL_ERROR = "⚠️ Внутренняя ошибка. Попробуй ещё раз позже."


async def _answer(message: Message, text: str, parse_mode: str | None = None) -> Message | None:
    """Отправляет сообщение, повторяя при флуд-контроле Telegram.

    Если Telegram не смог распарсить разметку — повторяет отправку очищенным
    текстом: важнее доставить ответ, чем сохранить форматирование.
    """
    for _ in range(3):
        try:
            return await message.answer(
                text, reply_markup=main_keyboard(), parse_mode=parse_mode
            )
        except TelegramRetryAfter as e:
            logger.warning("Flood control: ждём %s с перед повтором", e.retry_after)
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest as e:
            if parse_mode:
                logger.warning("Telegram отверг разметку (%s) — шлю без неё", e)
                text, parse_mode = strip_tags(text), None
                continue
            logger.exception("Telegram отклонил сообщение (chat_id=%s)", message.chat.id)
            return None
    return None


async def _replace(placeholder: Message | None, message: Message, text: str) -> None:
    """Меняет «⏳ Думаю…» на текст или отправляет сообщение заново."""
    if placeholder is None:
        await _answer(message, text)
        return
    try:
        await placeholder.edit_text(text)
    except TelegramBadRequest:
        await _answer(message, text)


async def _ask_ai(message: Message, user_text: str, extra: str | None = None) -> None:
    """Отправляет вопрос локальной модели и отвечает результатом."""
    user_id = message.from_user.id if message.from_user else 0
    placeholder = await _answer(message, "⏳ Думаю…")
    try:
        answer = await get_tutor().ask(user_id, user_text, extra=extra)
    except Exception:
        logger.exception("Ошибка запроса к локальной LLM (user_id=%s)", user_id)
        await _replace(placeholder, message, LLM_ERROR)
        return

    if placeholder is not None:
        try:
            await placeholder.delete()
        except TelegramBadRequest:
            logger.debug("Не удалось удалить placeholder", exc_info=True)

    # Markdown от модели -> HTML Telegram; режем с учётом незакрытых тегов
    for part in split_html(md_to_html(answer)):
        await _answer(message, part, parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await _answer(message, WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _answer(message, HELP)


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    await get_tutor().reset(message.from_user.id)
    await _answer(message, RESET_DONE)


@router.message(F.text.in_(TOPICS))
async def send_topic(message: Message) -> None:
    """Быстрый ответ из локальной справки, без ИИ."""
    for part in split_message(get_topic(message.text)):
        await _answer(message, part)


@router.message(F.text == QUIZ_BUTTON)
async def start_quiz(message: Message) -> None:
    """Викторина генерируется локальной моделью с учётом истории диалога."""
    await _ask_ai(message, QUIZ_REQUEST, extra="Пользователь нажал кнопку «Викторина».")


@router.message(F.text == RESET_BUTTON)
async def reset_chat(message: Message) -> None:
    await get_tutor().reset(message.from_user.id)
    await _answer(message, RESET_DONE)


@router.message(F.text)
async def ask_ai(message: Message) -> None:
    """Весь остальной текст уходит в локальную LLM (регистрируется последним)."""
    text = (message.text or "").strip()
    if not text:
        return
    await _ask_ai(message, text)


@router.errors()
async def on_error(event: ErrorEvent) -> None:
    """Последний рубеж: логируем сбой и не роняем бота."""
    exc = event.exception
    logger.error("Ошибка обработки апдейта: %s: %s", type(exc).__name__, exc, exc_info=exc)
    tg_message = event.update.message
    if tg_message is not None:
        try:
            await tg_message.answer(INTERNAL_ERROR)
        except TelegramBadRequest:
            logger.debug("Не удалось отправить сообщение об ошибке", exc_info=True)
