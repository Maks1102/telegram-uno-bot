# Бот «Уно-Инструктор» — автоматический запуск python bot.py
#
# Сборка и запуск — одной командой из папки docker/ (см. docker-compose.yml):
#   docker compose up -d
#
# Или вручную из корня проекта:
#   docker build -t uno-bot .
#   docker run --rm --env-file .env uno-bot

FROM python:3.13-slim

# логи сразу в stdout (без буфера) + не плодим __pycache__ в контейнере
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала зависимости — слой кешируется, пока не поменялся requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код бота (секреты сюда не попадают: .env исключён в .dockerignore,
# на лету он приходит через env_file в docker-compose.yml)
COPY . .

# knowledge/*.md обязан быть в образе — кнопки-справки читают его без ИИ
CMD ["python", "bot.py"]
