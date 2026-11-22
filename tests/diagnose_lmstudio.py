"""Диагностика пустых ответов локальной модели (LM Studio / llama.cpp).

Показывает: какие модели на сервере, что вернул запрос (finish_reason,
наличие reasoning, длину content) и сколько токенов израсходовано.

Запуск:  python tests/diagnose_lmstudio.py [вопрос]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI

from config import load_config


def main() -> None:
    cfg = load_config()
    print(f"Сервер:   {cfg.llm_base_url}")
    client = OpenAI(
        base_url=cfg.llm_base_url,
        api_key=cfg.llm_api_key,
        timeout=max(cfg.llm_timeout, 180.0),
    )

    try:
        models = client.models.list()
    except Exception as e:
        raise SystemExit(
            f"Сервер недоступен: {e}\n"
            "Проверь, что LM Studio запущен и Start Server включён (вкладка Developer)."
        )

    ids = [m.id for m in models.data]
    print(f"Модели на сервере: {ids or 'НЕТ'}")
    if not ids:
        raise SystemExit("На сервере не загружена ни одна модель — загрузи её в LM Studio.")

    model = cfg.llm_model or ids[0]
    question = sys.argv[1] if len(sys.argv) > 1 else "Что такое карта Пропуск (Skip) в UNO?"
    print(f"Модель:   {model}")
    print(f"Вопрос:   {question}")
    print(
        f"Запрос:   max_tokens={cfg.llm_max_tokens}, "
        f"reasoning_effort={cfg.llm_reasoning_effort or '(не отправляется)'}, "
        f"timeout={cfg.llm_timeout}s — генерация, жди…"
    )

    request: dict = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Ты — «Уно-Инструктор», помощник по правилам UNO. Отвечай по-русски, кратко.",
            },
            {"role": "user", "content": question},
        ],
        "temperature": 0.7,
        "max_tokens": cfg.llm_max_tokens,
    }
    if cfg.llm_reasoning_effort:
        request["reasoning_effort"] = cfg.llm_reasoning_effort

    resp = client.chat.completions.create(**request)

    choice = resp.choices[0]
    message = choice.message
    content = message.content or ""
    extra = getattr(message, "model_extra", None) or {}
    reasoning = str(
        getattr(message, "reasoning_content", None)
        or extra.get("reasoning_content")
        or extra.get("reasoning")
        or ""
    )
    fields = sorted(set(getattr(message, "model_fields_set", [])) | set(extra))

    print()
    print(f"finish_reason: {choice.finish_reason}")
    print(f"content:       {len(content)} симв.")
    if content:
        print(f"  начало: {content[:200]!r}")
    print(f"reasoning:     {len(reasoning)} симв.")
    if reasoning:
        print(f"  начало: {reasoning[:150]!r}")
    if resp.usage:
        print(
            f"токены:        prompt={resp.usage.prompt_tokens}, "
            f"completion={resp.usage.completion_tokens}"
        )
    print(f"поля message:  {fields}")

    print()
    if not content.strip():
        if choice.finish_reason == "length":
            print("ВЫВОД: ответ упёрся в лимит токенов" + (
                " — почти всё съело «мышление» (reasoning)." if reasoning else " (обрезан по длине)."
            ))
            print(
                "ЛЕЧЕНИЕ: увеличь LLM_MAX_TOKENS в .env (4096+)"
                + (" и выключи «Thinking» в LM Studio при загрузке модели." if reasoning else ".")
            )
        elif reasoning:
            print("ВЫВОД: модель записала только внутренние рассуждения, итогового ответа нет.")
            print("ЛЕЧЕНИЕ: выключи «Thinking» при загрузке модели в LM Studio или выбери обычную модель.")
        else:
            print("ВЫВОД: сервер вернул пустой content, причина не видна в метаданных.")
            print("ЛЕЧЕНИЕ: проверь, что модель загружена с чат-шаблоном (chat template) в LM Studio.")
    else:
        print("ВЫВОД: ответ есть — при обычном запуске бота проблема в чём-то другом.")


if __name__ == "__main__":
    main()
