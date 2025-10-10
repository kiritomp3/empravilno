# ---------- Конфиг ----------
PYTHON      ?= python3
PIP         ?= pip3
APP_MODULE  ?= app.main                    # модуль запуска
PYTHONPATH  ?= src                         # src-layout: пакеты живут в ./src
ENV_FILE    ?= .env

# ---------- Вспомогательные ----------
.PHONY: help
help:
	@echo "Доступные команды:"
	@echo "  make dev           — установка зависимостей (editable + [dev])"
	@echo "  make env           — создать .env из .env.example (если нет)"
	@echo "  make run           — запустить бота локально (polling)"
	@echo "  make lint          — ruff lint"
	@echo "  make format        — ruff format (исправление стиля)"
	@echo "  make typecheck     — mypy типизация"
	@echo "  make test          — pytest"
	@echo "  make docker-build  — собрать docker-образ"
	@echo "  make docker-up     — поднять docker-compose (бот+redis)"
	@echo "  make docker-down   — остановить docker-compose"
	@echo "  make logs          — логи сервиса bot"

# ---------- Установка ----------
.PHONY: dev
dev: ## Установка зависимостей в editable-режиме + dev-экстры
	$(PIP) install --upgrade pip
	# В zsh скобки надо экранировать или брать в кавычки:
	$(PIP) install -e '.[dev]'

.PHONY: env
env: ## Сгенерировать .env из примера, если отсутствует
	@test -f $(ENV_FILE) || cp .env.example $(ENV_FILE)
	@echo "OK: $(ENV_FILE) готов. Отредактируй значения при необходимости."

# ---------- Локальный запуск ----------
.PHONY: run
run: ## Запуск локально через python -m
	# src-layout: добавляем PYTHONPATH, чтобы импортировался пакет app из ./src
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m $(APP_MODULE)

# ---------- Качество кода ----------
.PHONY: lint
lint:
	ruff check .

.PHONY: format
format:
	ruff format .

.PHONY: typecheck
typecheck:
	mypy src

.PHONY: test
test:
	pytest -q

# ---------- Docker ----------
.PHONY: docker-build
docker-build:
	docker compose build

.PHONY: docker-up
docker-up: env
	# Удалите строку `version:` в docker-compose.yml, если видите warning
	docker compose up -d

.PHONY: docker-down
docker-down:
	docker compose down

.PHONY: logs
logs:
	docker compose logs -f bot