"""Показывает, как ответ локальной модели будет выглядеть в Telegram.

Бот конвертирует Markdown модели в HTML (модуль tgmd.py) и шлёт сообщения
с parse_mode="HTML". Скрипт спрашивает модель, прогоняет ответ через
конвертер, проверяет баланс тегов и печатает итог до и после разбивки.

Флаг --send дополнительно отправляет результат в реальный чат (chat_id
берётся из истории — в личных сообщениях он совпадает с user_id), чтобы
доказать, что Telegram принимает разметку.

Запуск из корня проекта:
  python tests/preview_md.py [вопрос]
  python tests/preview_md.py --send
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import OpenAI

from config import load_config
from llm import SYSTEM_PROMPT
from tgmd import LIMIT, _open_tags, md_to_html, split_html, strip_tags

DEFAULT_QUESTION = (
    "Объясни новичку карту Wild Draw Four: эффект, когда играть, частые ошибки. "
    "Используй заголовки, маркированный и нумерованный списки, жирный текст и код."
)


def ask_model(question: str) -> str:
    """Задаёт вопрос модели и возвращает сырой Markdown-ответ."""
    cfg = load_config()
    client = OpenAI(base_url=cfg.llm_base_url, api_key=cfg.llm_api_key, timeout=cfg.llm_timeout)
    model = cfg.llm_model or client.models.list().data[0].id
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        temperature=0.7,
        max_tokens=cfg.llm_max_tokens,
        reasoning_effort=cfg.llm_reasoning_effort,
    )
    return (response.choices[0].message.content or "").strip()


def last_user_id() -> int | None:
    """Последний user_id из истории (host- и docker-база)."""
    candidates = [Path("history.db"), Path("docker/data/history.db")]
    for path in candidates:
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT user_id FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row:
            return int(row[0])
    return None


def send_telegram(chat_id: int, text: str) -> dict:
    """Отправляет HTML-сообщение через Bot API, возвращает ответ Telegram."""
    from config import load_config as _load  # токен не печатаем

    token = _load().bot_token
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "description": body}


def main() -> None:
    parser = argparse.ArgumentParser(description="Предпросмотр ответа модели в разметке Telegram")
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    parser.add_argument("--send", action="store_true", help="отправить результат в Telegram")
    args = parser.parse_args()

    markdown = ask_model(args.question)
    html_text = md_to_html(markdown)
    parts = split_html(html_text)

    print(f"Markdown модели:  {len(markdown)} симв.")
    print(f"HTML для TG:      {len(html_text)} симв.")
    print(f"Частей сообщения: {len(parts)} (лимит {LIMIT})")
    problems = [p[:60] for p in parts if _open_tags(p)]
    assert not problems, f"незакрытые теги: {problems}"
    for p in parts:
        assert len(p) <= LIMIT, f"часть длиннее лимита: {len(p)}"
    print("Теги:             сбалансированы, каждая часть в лимите")

    print("\n--- КАК УЙДЁТ В TELEGRAM (первые 900 симв.) ---")
    print(parts[0][:900])
    print("\n--- ТЕКСТ БЕЗ РАЗМЕТКИ (запасной вариант) ---")
    print(strip_tags(parts[0])[:400])

    if args.send:
        chat_id = last_user_id()
        if chat_id is None:
            print("\nИстория пуста — chat_id неизвестен, отправка отменена")
            return
        print(f"\nОтправляю в Telegram (chat_id={chat_id})…")
        for i, part in enumerate(parts, 1):
            result = send_telegram(chat_id, part)
            status = "OK" if result.get("ok") else f"ОШИБКА: {result.get('description')}"
            print(f"  часть {i}/{len(parts)}: {status}")


if __name__ == "__main__":
    main()
