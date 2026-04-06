FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ==== КОД ДОЛЖЕН БЫТЬ ДО УСТАНОВКИ ПАКЕТА ====
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY miniapp /app/miniapp

# Устанавливаем зависимости и сам пакет
RUN python -m pip install --upgrade pip --root-user-action=ignore && \
    pip install --no-cache-dir .

# Непривилегированный пользователь
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8000

# Запуск приложения как модуля (ожидается app/main.py с main() или эквивалент)
CMD ["python", "-m", "app.main"]
