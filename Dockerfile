FROM python:3.12-slim

WORKDIR /app

# Устанавливаем uv для быстрой установки зависимостей
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Копируем зависимости и устанавливаем
COPY pyproject.toml .
RUN uv pip install --system --no-cache -e .

# Копируем код
COPY . .

EXPOSE 8000

# entrypoint: сначала миграции, потом сервер
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
