"""Конфигурация бота: переменные окружения из файла .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout: float
    llm_max_tokens: int
    llm_reasoning_effort: str
    history_limit: int
    history_db: str


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Не задан BOT_TOKEN.\n"
            "1. Создай бота у @BotFather и скопируй токен.\n"
            "2. Скопируй .env.example в .env и вставь токен туда."
        )

    return Config(
        bot_token=token,
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:1234/v1").strip().rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "").strip(),
        llm_api_key=os.getenv("LLM_API_KEY", "lm-studio").strip() or "lm-studio",
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "120")),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2048")),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "none").strip().lower(),
        history_limit=max(0, int(os.getenv("HISTORY_LIMIT", "16"))),
        history_db=os.getenv("HISTORY_DB", "history.db").strip() or "history.db",
    )
