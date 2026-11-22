"""Офлайн-проверка бота без Telegram и LM Studio.

Поднимает заглушечный OpenAI-совместимый сервер и проверяет:
  1. сборку конфигурации;
  2. чтение справок и разбивку длинных сообщений;
  3. порядок роутера (specific -> generic) и служебные кнопки;
  4. хранилище истории (SQLite);
  5. конвертер Markdown модели в HTML Telegram (tgmd.py);
  6. Tutor: авто-выбор модели, системный промпт, историю, сброс,
     подсказку при пустом ответе и повтор с увеличенным лимитом.

Запуск из корня проекта:  python tests/test_offline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Dispatcher

from config import Config
from history import HistoryStore
from knowledge import TOPICS, get_topic, split_message
from llm import SYSTEM_PROMPT, Tutor

STUB_LAST_PAYLOAD: dict = {}
STUB_PAYLOADS: list[dict] = []


class StubOpenAIHandler(BaseHTTPRequestHandler):
    """Мини-заглушка OpenAI-совместимого API (models + chat/completions)."""

    def log_message(self, *_args) -> None:
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._send({"object": "list", "data": [{"id": "stub-model"}]})
        else:
            self._send({"error": {"message": "not found"}}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send({"error": {"message": "not found"}}, status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        STUB_LAST_PAYLOAD.clear()
        STUB_LAST_PAYLOAD.update(payload)
        STUB_PAYLOADS.append(payload)

        # имитация thinking-модели, упёршейся в лимит токенов
        if any("ПУСТОЙ_ОТВЕТ" in str(m.get("content", "")) for m in payload.get("messages", [])):
            self._send(
                {
                    "id": "stub-1",
                    "object": "chat.completion",
                    "created": 0,
                    "model": payload.get("model", "stub-model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "reasoning_content": "я долго думал над правилами…",
                            },
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": payload.get("max_tokens", 0),
                        "total_tokens": 1,
                    },
                }
            )
            return

        self._send(
            {
                "id": "stub-1",
                "object": "chat.completion",
                "created": 0,
                "model": payload.get("model", "stub-model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ОТВЕТ ЗАГЛУШКИ"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )


def test_load_config() -> None:
    """load_config() должен собирать Config целиком, включая все поля."""
    from config import load_config

    env = {
        "BOT_TOKEN": "123:TEST",
        "LLM_BASE_URL": "http://localhost:1234/v1/",
        "LLM_MODEL": "",
        "LLM_MAX_TOKENS": "2048",
        "LLM_REASONING_EFFORT": "none",
        "HISTORY_LIMIT": "8",
        "HISTORY_DB": "test-history.db",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        cfg = load_config()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    assert cfg.bot_token == "123:TEST"
    assert cfg.llm_base_url == "http://localhost:1234/v1"  # слэш обрезан
    assert cfg.llm_model == ""
    assert cfg.llm_max_tokens == 2048
    assert cfg.llm_reasoning_effort == "none"
    assert cfg.history_limit == 8
    assert cfg.history_db == "test-history.db"
    print("ok: load_config собирает Config целиком")


def test_knowledge() -> None:
    for title in TOPICS:
        text = get_topic(title)
        assert len(text) > 200, f"справка {title!r} слишком короткая: {len(text)} симв."
    parts = split_message("x" * 10000)
    assert [len(p) for p in parts] == [4096, 4096, 1808], [len(p) for p in parts]
    print("ok: справки и разбивка сообщений")


def test_routing() -> None:
    from handlers import router
    from keyboards import QUIZ_BUTTON, RESET_BUTTON

    names = [h.callback.__name__ for h in router.message.handlers]
    assert names[0] == "cmd_start", names
    assert names[-1] == "ask_ai", f"catch-all должен быть последним: {names}"
    assert len(router.error.handlers) >= 1, "не зарегистрирован обработчик ошибок"
    assert QUIZ_BUTTON not in TOPICS and RESET_BUTTON not in TOPICS
    assert hasattr(Dispatcher, "resolve_used_update_types")
    print(f"ok: роутер {router.name!r}, порядок {names}")


def test_history_store(db_path: Path) -> None:
    store = HistoryStore(db_path)
    uid = 42
    for i in range(5):
        store.append(uid, "user" if i % 2 == 0 else "assistant", f"msg{i}", limit=4)
    loaded = store.load(uid, 4)
    # после подрезки история не должна начинаться с ответа ассистента
    assert [m["content"] for m in loaded] == ["msg2", "msg3", "msg4"], loaded
    assert loaded[0]["role"] == "user", loaded
    store.clear(uid)
    assert store.load(uid, 4) == []
    store.close()
    print("ok: хранилище истории (SQLite)")


def _config(base_url: str, db_path: Path) -> Config:
    return Config(
        bot_token="test",
        llm_base_url=base_url,
        llm_model="",
        llm_api_key="test",
        llm_timeout=10,
        llm_max_tokens=200,
        llm_reasoning_effort="none",
        history_limit=8,
        history_db=str(db_path),
    )


async def test_tutor(base_url: str, db_path: Path) -> None:
    tutor = Tutor(_config(base_url, db_path))

    answer = await tutor.ask(7, "Что такое карта Пропуск?")
    assert answer == "ОТВЕТ ЗАГЛУШКИ", answer
    assert STUB_LAST_PAYLOAD["messages"][0]["role"] == "system"
    assert "Уно-Инструктор" in STUB_LAST_PAYLOAD["messages"][0]["content"]
    # LLM_MODEL пуст — модель подхватилась автоматически
    assert STUB_LAST_PAYLOAD["model"] == "stub-model"
    # «мышление» отключено настроением из конфига
    assert STUB_LAST_PAYLOAD["reasoning_effort"] == "none"

    await tutor.ask(7, "А в игре вдвоём?")
    roles = [m["role"] for m in STUB_LAST_PAYLOAD["messages"]]
    assert roles == ["system", "user", "assistant", "user"], roles

    # «перезапущенный» бот подхватывает историю из SQLite
    tutor2 = Tutor(_config(base_url, db_path))
    await tutor2.ask(7, "Спасибо")
    roles = [m["role"] for m in STUB_LAST_PAYLOAD["messages"]]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"], roles

    await tutor2.reset(7)
    tutor3 = Tutor(_config(base_url, db_path))
    await tutor3.ask(7, "Начнём заново")
    roles = [m["role"] for m in STUB_LAST_PAYLOAD["messages"]]
    assert roles == ["system", "user"], roles
    await tutor3.aclose()
    await tutor2.aclose()
    await tutor.aclose()
    print("ok: диалог с моделью, история и сброс")


async def test_empty_answer(base_url: str, db_path: Path) -> None:
    """Пустой ответ из-за лимита токенов: повтор и понятная подсказка."""
    STUB_PAYLOADS.clear()
    tutor = Tutor(_config(base_url, db_path))

    answer = await tutor.ask(9, "ПУСТОЙ_ОТВЕТ что будет с правилами?")

    assert len(STUB_PAYLOADS) == 2, f"ожидался повтор: {len(STUB_PAYLOADS)} запросов"
    assert STUB_PAYLOADS[0]["max_tokens"] == 200
    assert STUB_PAYLOADS[1]["max_tokens"] == 400  # бюджет удвоен
    assert STUB_PAYLOADS[0]["reasoning_effort"] == "none"
    assert "внутренние рассуждения" in answer, answer
    assert "LLM_REASONING_EFFORT" in answer, answer
    await tutor.aclose()
    print("ok: подсказка при пустом ответе + повтор с увеличенным лимитом")


def test_tgmd() -> None:
    """Markdown от модели -> HTML Telegram: разбор, экранирование, разбивка."""
    from tgmd import LIMIT, _open_tags, md_to_html, split_html, strip_tags

    # инлайн-разметка
    h = md_to_html("**Жирный** и *курсив*, `код` и ~~зачёркнутый~~")
    assert "<b>Жирный</b>" in h, h
    assert "<i>курсив</i>" in h, h
    assert "<code>код</code>" in h, h
    assert "<s>зачёркнутый</s>" in h, h
    assert "**" not in h and "~~" not in h, h

    # блочная разметка: заголовки, маркированные и нумерованные списки
    h = md_to_html("## Правила UNO\n\n- первый\n- второй\n\n1. раз\n2. два")
    assert "<b>Правила UNO</b>" in h and "#" not in h, h
    assert "• первый" in h and "• второй" in h, h
    assert "1. раз" in h and "2. два" in h, h

    # экранирование: сырой < или & Telegram отвергает целиком
    raw = "5 < 6 & 7 > 2, кавычки \"тут\""
    assert strip_tags(md_to_html(raw)) == raw, md_to_html(raw)

    # блок кода не разбирается как markdown внутри
    h = md_to_html("```python\n**не жирный**\n```")
    assert "<pre>" in h and "<b>" not in h, h
    assert "**не жирный**" in h, h

    # непарные ** от модели просто убираются
    assert "**" not in md_to_html("**не закрылось"), md_to_html("**не закрылось")

    # ссылка, включая & в URL
    h = md_to_html("[UNO](https://example.com/a?b=1&c=2)")
    assert '<a href="https://example.com/a?b=1&amp;c=2">UNO</a>' in h, h

    # разбивка длинного HTML: каждая часть в лимите, теги закрыты, пустых нет
    long = md_to_html("Абзац с **жирным** и кодом `x`.\n\n" * 400)
    parts = split_html(long)
    assert len(parts) > 1, "длинный ответ не разбился"
    for p in parts:
        assert len(p) <= LIMIT, len(p)
        assert p.strip(), "пустая часть"
        assert not _open_tags(p), f"незакрытые теги: {_open_tags(p)}"
        assert not re.search(r"<(b|i|s|code|a)\b[^>]*></\1>", p), "пустая сущность"

    # один кусок без разметки и пустой ввод
    assert split_html("коротко") == ["коротко"]
    assert md_to_html("") == ""
    print("ok: конвертер Markdown -> HTML Telegram")


def main() -> None:
    test_load_config()
    test_knowledge()
    test_routing()
    test_tgmd()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_history_store(tmp_path / "history.db")

        server = ThreadingHTTPServer(("127.0.0.1", 0), StubOpenAIHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        try:
            asyncio.run(test_tutor(base_url, tmp_path / "tutor.db"))
            asyncio.run(test_empty_answer(base_url, tmp_path / "tutor2.db"))
        finally:
            server.shutdown()
    # без эмодзи: консоль Windows с cp1251 не умеет их печатать и падает
    print("\nВсе офлайн-проверки пройдены (OK)")


if __name__ == "__main__":
    main()
