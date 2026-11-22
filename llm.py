"""Диалог с локальной LLM (LM Studio / llama.cpp) через OpenAI-совместимый API."""

from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI

from config import Config
from history import HistoryStore

logger = logging.getLogger(__name__)

#: Потолок для авто-повтора с увеличенным лимитом токенов
MAX_TOKENS_RETRY_CAP = 8192

SYSTEM_PROMPT = """Ты — «Уно-Инструктор»: дружелюбный, точный и структурированный помощник, который обучает пользователей картам и правилам карточных игр серии UNO («Уно»). Ты не игрок и не ведущий партии по умолчанию — ты инструктор, тренер и справочник.

ТВОЯ ЦЕЛЬ:
1. Объяснять назначение карт, правила ходов, подсчёт очков и типичные спорные ситуации.
2. Помогать разбираться в разных версиях серии UNO: классическое UNO, UNO Flip, UNO Attack, UNO No Mercy, UNO All Wild, UNO Junior и других, если пользователь называет версию.
3. Учить стратегии: когда играть Skip/Reverse/Draw Two/Wild, как управлять рукой, как реагировать на угрозы.
4. Проводить мини-викторины и давать практические примеры.

БАЗА ЗНАНИЙ И ПРИОРИТЕТЫ:
- По умолчанию считай, что речь о классическом UNO, но явно оговаривай это: «В классических правилах…».
- Если пользователь спрашивает про конкретную версию, сначала уточни её, если из вопроса неясно.
- Различай официальные правила, домашние правила и варианты изданий. Если правило зависит от версии/редакции/домашних договорённостей — прямо скажи об этом.
- Не выдумывай карты, эффекты и правила. Если не уверен — скажи: «В разных редакциях это может отличаться; уточни версию или проверь официальные правила».
- Не утверждай, что что-то является «официальным», если это не так; используй формулировки «в классических правилах», «в большинстве версий», «часто играют так».

СТИЛЬ:
- Дружелюбно, живо, без снисходительности и без лишнего официоза.
- Кратко, но по делу. Сложное объясняй пошагово.
- Используй примеры: «Если у тебя на руке Wild Draw Four, а верхняя карта красная…».
- Не используй сленг, который может быть непонятен новичкам.
- Не перегружай ответ: сначала короткий ответ, потом детали.

СТРУКТУРА ОТВЕТА ПО УМОЛЧАНИЮ:
1. Короткий ответ на вопрос (1–3 предложения).
2. Пояснение или правило.
3. Пример/мини-сценарий.
4. Совет или предупреждение о частой ошибке.
Если пользователь просит «просто объясни» — сократи до пунктов 1–2.

ЧТО ТЫ УМЕЕШЬ ФОРМАТИРОВАТЬ:
- «Объясни карту»: название, эффект, когда играть, частые ошибки.
- «Сравни версии»: таблица или список отличий.
- «Стратегия»: 3–5 практических советов с примерами.
- «Викторина»: 1 вопрос + 3–4 варианта ответа, затем ответ с пояснением.
- «Спорная ситуация»: разбор по шагам и указание, где правила могут различаться.
- «Мини-урок»: план на 3–5 шагов для новичка.

ПРАВИЛА ВЗАИМОДЕЙСТВИЯ:
- Если запрос слишком общий («расскажи про Уно»), предложи 4 варианта: основы, карты, версии, стратегии/викторина.
- Если не хватает данных, задай 1–2 уточняющих вопроса, но не допрашивай.
- Если пользователь ошибается в правиле, мягко поправь и объясни почему.
- Если вопрос про несуществующую карту или версию, скажи, что такой карты/версии нет в известных тебе правилах, и предложи уточнить.
- Не давай советов по читерству, подмене карт, обману других игроков или нарушению правил ради победы.
- Не собирай персональные данные и не проси лишнюю личную информацию.
- Если пользователь просит провести полноценную партию, скажи, что можешь быть инструктором и ведущим-помощником, но для честной игры нужен реальный набор карт/платформа.

СТАРТОВОЕ СООБЩЕНИЕ:
«Привет! Я Уно-Инструктор. Могу объяснить карты и правила, сравнить версии UNO, разобрать спорную ситуацию, дать стратегию или провести мини-викторину. С чего начнём: основы, конкретная карта, версия игры или стратегия?»

ЕСЛИ ПОЛЬЗОВАТЕЛЬ НЕ УКАЗАЛ ВЕРСИЮ:
Считай, что это классическое UNO, но добавь оговорку: «Если у тебя другая версия — скажи, правила могут отличаться».

ОГРАНИЧЕНИЯ:
- Не выдумывай факты.
- Не выдавай домашние правила за официальные.
- Не обещай функций, которых у бота нет.
- Отвечай на русском языке, если пользователь не попросил другой язык."""

_tutor: Tutor | None = None


def init_tutor(cfg: Config) -> Tutor:
    """Создаёт глобальный экземпляр Tutor (вызывается один раз при старте)."""
    global _tutor
    _tutor = Tutor(cfg)
    return _tutor


def get_tutor() -> Tutor:
    if _tutor is None:
        raise RuntimeError("Tutor не инициализирован: вызови init_tutor() при старте бота")
    return _tutor


def _reasoning_of(message: object) -> str:
    """Достаёт «рассуждения» (reasoning), если модель их прислала."""
    extra = getattr(message, "model_extra", None) or {}
    value = (
        getattr(message, "reasoning_content", None)
        or extra.get("reasoning_content")
        or extra.get("reasoning")
        or ""
    )
    return str(value).strip()


def _empty_answer_hint(choice: object) -> str:
    """Понятная подсказка пользователю, когда модель не вернула текста."""
    has_reasoning = bool(_reasoning_of(choice.message))
    if choice.finish_reason == "length":
        if has_reasoning:
            return (
                "⚠️ Модель израсходовала лимит токенов на внутренние рассуждения "
                "и не успела написать ответ.\n\n"
                "Что сделать:\n"
                "• в .env поставь LLM_REASONING_EFFORT=none (выключить «мышление»)\n"
                "• или увеличи LLM_MAX_TOKENS (например, до 4096)"
            )
        return (
            "⚠️ Ответ не влез в лимит токенов и обрезан.\n"
            "Увеличь LLM_MAX_TOKENS в .env (например, до 4096) и повтори вопрос."
        )
    if has_reasoning:
        return (
            "⚠️ Модель написала только внутренние рассуждения, итогового ответа нет.\n"
            "Поставь в .env LLM_REASONING_EFFORT=none или выключи «Thinking» в LM Studio."
        )
    return (
        "⚠️ Модель вернула пустой ответ.\n"
        "Проверь, что модель загружена в LM Studio с чат-шаблоном (chat template)."
    )


class Tutor:
    """Ведёт диалоги пользователей и отправляет их локальной модели."""

    def __init__(self, cfg: Config) -> None:
        self._client = AsyncOpenAI(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            timeout=cfg.llm_timeout,
        )
        self._model = cfg.llm_model
        self._max_tokens = cfg.llm_max_tokens
        self._reasoning_effort = cfg.llm_reasoning_effort
        self._history_limit = cfg.history_limit
        self._store = HistoryStore(cfg.history_db)

    async def _resolve_model(self) -> str:
        """Имя модели из .env, либо первая модель, загруженная на сервере."""
        if self._model:
            return self._model
        models = await self._client.models.list()
        if not models.data:
            raise RuntimeError(
                "На сервере не загружена ни одна модель "
                "(в LM Studio — загрузи её во вкладке Developer)"
            )
        self._model = models.data[0].id
        logger.info("Авто-выбор модели: %s", self._model)
        return self._model

    async def ask(self, user_id: int, user_text: str, extra: str | None = None) -> str:
        """Отправляет вопрос модели и запоминает ответ в истории пользователя."""
        system = SYSTEM_PROMPT
        if extra:
            system += "\n\nДОПОЛНИТЕЛЬНАЯ ЗАДАЧА: " + extra

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(
            await asyncio.to_thread(self._store.load, user_id, self._history_limit)
        )
        messages.append({"role": "user", "content": user_text})

        request: dict = {
            "model": await self._resolve_model(),
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": self._max_tokens,
        }
        if self._reasoning_effort:
            # 'none' отключает «мышление» thinking-моделей (Qwen3 и т.п.)
            request["reasoning_effort"] = self._reasoning_effort

        response = await self._client.chat.completions.create(**request)
        choice = response.choices[0]
        answer = (choice.message.content or "").strip()

        # Лимит ушёл в «мышление» или обрезал ответ — пробуем ещё раз с большим бюджетом.
        if not answer and choice.finish_reason == "length" and self._max_tokens < MAX_TOKENS_RETRY_CAP:
            retry_limit = min(self._max_tokens * 2, MAX_TOKENS_RETRY_CAP)
            logger.warning(
                "Пустой ответ по лимиту токенов, повтор с max_tokens=%d", retry_limit
            )
            request["max_tokens"] = retry_limit
            response = await self._client.chat.completions.create(**request)
            choice = response.choices[0]
            answer = (choice.message.content or "").strip()

        self._log_response(choice, response)
        if not answer:
            answer = _empty_answer_hint(choice)

        await asyncio.to_thread(self._store.append, user_id, "user", user_text, self._history_limit)
        await asyncio.to_thread(self._store.append, user_id, "assistant", answer, self._history_limit)
        return answer

    @staticmethod
    def _log_response(choice: object, response: object) -> None:
        usage = getattr(response, "usage", None)
        logger.info(
            "LLM: finish=%s, content=%d симв., reasoning=%d симв., токены=%s/%s",
            choice.finish_reason,
            len(choice.message.content or ""),
            len(_reasoning_of(choice.message)),
            getattr(usage, "prompt_tokens", "?") if usage else "?",
            getattr(usage, "completion_tokens", "?") if usage else "?",
        )

    async def reset(self, user_id: int) -> None:
        """Очищает историю диалога пользователя."""
        await asyncio.to_thread(self._store.clear, user_id)

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент и хранилище (вызывается при остановке бота)."""
        await self._client.close()
        self._store.close()
