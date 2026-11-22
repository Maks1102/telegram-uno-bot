"""Точка входа: запуск Telegram-бота «Уно-Инструктор»."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import load_config
from handlers import router
from llm import get_tutor, init_tutor


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)

    cfg = load_config()
    init_tutor(cfg)

    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    dp.include_router(router)

    logging.info("Бот запущен (long polling). LLM: %s", cfg.llm_base_url)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await get_tutor().aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
