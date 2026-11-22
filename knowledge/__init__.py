"""Тексты быстрых ответов: бот отдаёт их без обращения к локальной ИИ-модели."""

from __future__ import annotations

from pathlib import Path

CARDS = "🃏 Карты"
RULES = "📜 Правила"
VERSIONS = "🕹 Версии"
STRATEGY = "⚔ Стратегия"
DISPUTES = "🤔 Спорные ситуации"

#: Название кнопки -> файл со справкой
TOPICS: dict[str, str] = {
    CARDS: "cards.md",
    RULES: "rules.md",
    VERSIONS: "versions.md",
    STRATEGY: "strategy.md",
    DISPUTES: "disputes.md",
}

_FILES_DIR = Path(__file__).resolve().parent
_MESSAGE_LIMIT = 4096


def get_topic(title: str) -> str:
    """Возвращает текст справки по названию кнопки."""
    filename = TOPICS[title]
    return (_FILES_DIR / filename).read_text(encoding="utf-8").strip()


def split_message(text: str, limit: int = _MESSAGE_LIMIT) -> list[str]:
    """Режет длинный текст на части, каждая влезает в лимит Telegram."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    chunk = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{chunk}\n\n{paragraph}" if chunk else paragraph
        if len(candidate) <= limit:
            chunk = candidate
            continue
        if chunk:
            parts.append(chunk)
            chunk = ""
        # абзац длиннее лимита — режем его принудительно
        while len(paragraph) > limit:
            parts.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        chunk = paragraph
    if chunk:
        parts.append(chunk)
    return parts or [text[:limit]]
