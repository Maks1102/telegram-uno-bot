"""Офлайн-проверка бота без Telegram и LM Studio.

Поднимает заглушечный OpenAI-совместимый сервер и проверяет:
  1. чтение справок и разбивку длинных сообщений;
  2. порядок роутера (specific -> generic) и служебные кнопки;
  3. хранилище истории (SQLite);
  4. Tutor: авто-выбор модели, системный промпт, историю и сброс.

Запуск из корня проекта:  python tests/test_offline.py
"""

from __future__ import annotations

import asyncio
import json
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


class StubOpenAIHandler(BaseHTTPRequestHandler):
    """Мини-заглушка OpenAI-совместимого API (models + chat/completions)."""

    def log_message(self, *_args) -> None:
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
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


def main() -> None:
    test_knowledge()
    test_routing()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_history_store(tmp_path / "history.db")

        server = ThreadingHTTPServer(("127.0.0.1", 0), StubOpenAIHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
        try:
            asyncio.run(test_tutor(base_url, tmp_path / "tutor.db"))
        finally:
            server.shutdown()
    print("\nВсе офлайн-проверки пройдены ✅")


if __name__ == "__main__":
    main()
