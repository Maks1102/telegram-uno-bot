# 🃏 Telegram-бот «Уно-Инструктор»

Помощник по карточной игре UNO: reply-кнопки с готовыми справками (правила, карты, версии, стратегия) + ответы через **локальную ИИ-модель** (LM Studio сейчас, llama.cpp в Docker потом). Никаких внешних API — всё работает на твоём железе.

## Возможности

- 🃏 **Быстрые кнопки** — справки по картам, правилам, версиям, стратегии и спорным ситуациям. Отвечают мгновенно, без ИИ.
- 🧠 **Викторина** — генерируется локальной моделью; бот ждёт твой вариант ответа и объясняет.
- 💬 **Любой текст** — вопрос к ИИ-модели с системным промптом «Уно-Инструктор» (дружелюбный инструктор, без выдумок, с оговорками про редакции правил).
- ✨ **Красивая разметка** — Markdown от модели (`**жирный**`, `*курсив*`, списки, заголовки, код) конвертируется в HTML Telegram; если Telegram отвергнет сообщение, бот автоматически отправит его чистым текстом.
- 🗣 **История диалога** — хранится в SQLite (`history.db`) и переживает перезапуски бота; `/reset` очищает историю пользователя.
- 🛡 **Устойчивость** — повтор при флуд-контроле Telegram, обработчик ошибок, разбивка ответов длиннее 4096 символов, отключение «мышления» thinking-моделей (иначе они отвечают пусто).

## Установка (Windows)

```powershell
# 1. Виртуальное окружение и зависимости (Python 3.11+)
py -3.13 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 2. Настройка
copy .env.example .env
notepad .env   # вставь BOT_TOKEN от @BotFather

# 3. Запуск
python bot.py
```

Linux/macOS: `python3 -m venv venv && source venv/bin/activate`, далее аналогично.

### Запуск в Docker (автоматически всё сразу)

Если Docker установлен, бот и модель поднимаются **одной командой** — без ручного `python bot.py`:

```powershell
cd docker
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

- бот собирается из `Dockerfile` в корне и сам выполняет `python bot.py`;
- `docker-compose.gpu.yml` не нужен, если GPU нет (тогда `NGL=0` в `docker/.env`);
- логи: `docker compose logs -f bot`, стоп: `docker compose down`;
- история диалогов пишется в `docker/data/history.db` и переживает пересборку;
- `BOT_TOKEN` и настройки LLM берутся из `.env` проекта (в образ не попадают — см. `.dockerignore`);
- модель и её веса в git не попадают (`.gitignore`: `docker/models/`, `*.gguf`).

⚠️ Если бот уже запущен на хосте через `python bot.py` — сначала останови его, иначе Telegram даст 409 Conflict (один токен — один polling).

## LM Studio (сейчас)

1. Установи [LM Studio](https://lmstudio.ai), скачай и **загрузи** модель (см. «Какую модель выбрать» ниже).
2. Открой вкладку **Developer (сервер)** → **Start Server** (по умолчанию `http://localhost:1234`).
3. В `.env` оставь:
   ```env
   LLM_BASE_URL=http://localhost:1234/v1
   LLM_MODEL=          # пусто = бот сам возьмёт загруженную модель
   ```

## llama.cpp в Docker (готовый набор в `docker/`)

Папка `docker/` — самодостаточный набор: его можно скопировать на любой компьютер с Docker.

```
docker/
  docker-compose.yml       сервер llama.cpp + сервис бота (всё в одном)
  docker-compose.gpu.yml   оверлей: CUDA-образ + все слои на NVIDIA GPU
  .env                     модель, контекст, слои на GPU, порт, адрес LLM для бота
  download-model.ps1       скачивание GGUF с Hugging Face
  models/                  здесь лежат файлы моделей (в git не попадает)
  data/                    history.db бота (создастся при старте)
```

**1. Скачай модель** (~4.2 ГБ, один раз):

```powershell
powershell -File docker\download-model.ps1
# другая модель:
powershell -File docker\download-model.ps1 -Repo "unsloth/Qwen3.5-9B-GGUF" -File "Qwen3.5-9B-Q4_K_M.gguf"
```

**2. Запусти всё** — модель и бота, одной командой (с NVIDIA GPU):

```powershell
cd docker
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Без GPU: `docker compose up -d` и в `docker/.env` поставь `NGL=0`. Бот собирается из `Dockerfile` и стартует сам; он ждёт, пока модель станет healthy (`depends_on`).

**3. Проверь:**

```powershell
# с корня проекта — должен ответить содержательным текстом
python tests/diagnose_lmstudio.py

# логи бота и модели
docker compose logs -f bot
docker compose logs -f llama
```

**4. Бот вне Docker?** Если запускаешь `python bot.py` на хосте, подключи его к контейнеру в `.env` проекта:

```env
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=          # пусто = авто
```

В compose адрес задаётся автоматически: `BOT_LLM_BASE_URL` в `docker/.env` (по умолчанию `http://llama:8080/v1` — имя сервиса в сети, а не localhost).

Полезные команды: `docker compose logs -f` (логи), `docker compose down` (стоп), `docker compose pull` (обновить образ).

**Перенос на другой компьютер:** скопируй папку `docker/` (модель можно не качать заново — просто переложи файл в `docker/models/`), поставь Docker, запусти по шагам 2–4. Если на той машине нет NVIDIA GPU — `NGL=0` в `docker/.env`. Бот и контейнер могут жить на разных машинах: в `LLM_BASE_URL` укажи IP сервера, например `http://192.168.1.10:8080/v1` (открой порт 8080 в брандмауэре).

Оба варианта (LM Studio и llama.cpp) отдают OpenAI-совместимый API, поэтому бот не различает их — меняется только `LLM_BASE_URL`.

## Какую модель выбрать

**По умолчанию в `docker/` лежит gemma-4-E4B (QAT, 4.2 ГБ)** — компактная, быстрая, без «мышления»; влезает в GPU с большим запасом. Скачать другую можно скриптом `docker\download-model.ps1 -Repo ... -File ...`.

Если хочется большего качества — ориентир по памяти (GGUF, квантование ~Q4_K_M), актуальность проверяй на Hugging Face:

| Память GPU/RAM | Модели | Комментарий |
|---|---|---|
| ~8 ГБ | Qwen3-8B, gpt-oss-20b | быстро, русский достойный |
| ~16 ГБ | Qwen3-14B, Mistral Small 3 24B, gpt-oss-20b | лучший баланс для бота |
| ~24–32 ГБ | Qwen3-30B-A3B, Gemma 3 27B, Qwen3-32B | сильный русский, живые ответы |

- **Qwen3** — один из лучших русских среди открытых, хорошо следует форматам.
- **Mistral Small / Gemma 3** — грамотный русский, спокойный тон.
- **gpt-oss-20b** — MoE, быстро работает даже на среднем железе.
- Для русского текста слабее подойдут Llama 3.x и совсем мелкие модели (<4B).

Параметры генерации: в LM Studio задай контекст ≥ 8192 (промпту бота хватит с запасом) и включённый шаблон чата.

## Настройки (.env)

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `BOT_TOKEN` | — | токен от @BotFather, обязателен |
| `LLM_BASE_URL` | `http://localhost:1234/v1` | адрес OpenAI-совместимого сервера |
| `LLM_MODEL` | пусто (авто) | имя модели; пусто — первая загруженная |
| `LLM_API_KEY` | `lm-studio` | любой непустой ключ (серверы не проверяют) |
| `LLM_TIMEOUT` | `120` | таймаут ответа модели, сек |
| `LLM_MAX_TOKENS` | `2048` | максимум токенов в ответе (для thinking-моделей — 4096+) |
| `LLM_REASONING_EFFORT` | `none` | «мышление» модели: `none` выкл., `minimal/low/medium/high` вкл.; пусто — не отправлять |
| `HISTORY_LIMIT` | `16` | сколько последних реплик хранить на пользователя |
| `HISTORY_DB` | `history.db` | файл SQLite с историей диалогов |

## Структура проекта

```
bot.py           точка входа (polling, закрытие сессии при остановке)
Dockerfile       образ бота: зависимости + автозапуск python bot.py
.dockerignore    что не попадает в образ (.env, модель, venv, тесты)
config.py        чтение .env
handlers.py      команды, кнопки-справки, вопросы в ИИ, обработчик ошибок
keyboards.py     reply-клавиатура
llm.py           клиент локальной LLM + системный промпт «Уно-Инструктор»
tgmd.py          Markdown от модели -> HTML Telegram (жирный, списки, код, ссылки)
history.py       история диалогов в SQLite (переживает перезапуски)
docker/          llama.cpp + бот в Docker: compose-файлы, скачивание моделей, models/, data/
knowledge/       готовые тексты справок (кнопки работают без ИИ)
  cards.md       карты: эффекты, когда играть, ошибки
  rules.md       основы классического UNO
  versions.md    обзор и сравнение версий
  strategy.md    5 практических советов
  disputes.md    спорные ситуации и где правила различаются
tests/
  test_offline.py       офлайн-проверки без Telegram и LM Studio
  diagnose_lmstudio.py  диагностика пустых ответов и лимитов токенов
  preview_md.py         предпросмотр ответа модели в разметке TG (--send — в чат)
```

## Тесты и диагностика

```powershell
# самопроверка: конфиг, справки, роутер, история, диалог с моделью-заглушкой
python tests/test_offline.py

# диагностика реального сервера: какая модель, finish_reason, reasoning, токены
python tests/diagnose_lmstudio.py [вопрос]
```

`test_offline.py` не нуждается ни в Telegram, ни в LM Studio. `diagnose_lmstudio.py` ходит в реальный LM Studio/llama.cpp и объясняет, почему ответ пустой.

## Troubleshooting

- **Connection refused** — не запущен сервер LM Studio / llama.cpp, или не тот порт в `LLM_BASE_URL`.
- **Model not found** — оставь `LLM_MODEL` пустым (авто-выбор) или укажи точное имя из `GET /v1/models`.
- **Модель тратит токены, но отвечает пусто** — thinking-модель (Qwen3 и т.п.) съедает весь `LLM_MAX_TOKENS` на внутренние рассуждения. Решение: `LLM_REASONING_EFFORT=none` в `.env` (по умолчанию) и/или `LLM_MAX_TOKENS=4096`. Проверка: `python tests/diagnose_lmstudio.py`.
- **Timeout** — модель тяжёлая для железа: увеличь `LLM_TIMEOUT` или возьми модель поменьше.
- **Ответ обрезался** — подними `LLM_MAX_TOKENS` (бот сам повторит запрос с удвоенным лимитом один раз).
- **409 Conflict при старте** — этот же токен уже слушает другой экземпляр бота или висит вебхук.
- **История** — лежит в `HISTORY_DB` (по умолчанию `history.db`) и переживает перезапуски; удали файл, чтобы начать с чистого листа.
