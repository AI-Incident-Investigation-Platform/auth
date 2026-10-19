.PHONY: help config keys run up down ps build logs upgrade downgrade migrate \
        format lint lint-fix typecheck check test test-integration test-all

SRC := src tests
N ?= 1
BUILD := BUILDX_NO_DEFAULT_ATTESTATIONS=1
ON_HOST := DATABASE__POSTGRES_HOST=localhost CACHE__HOST=localhost \
           REGISTRY__CONSUL_URL=http://localhost:8500 TRACING__OTLP_ENDPOINT=http://localhost:4318 \
           SERVICE__PUBLIC_HOST=host.docker.internal

help:
	@echo ""
	@echo "  Первый запуск"
	@echo "    config                    config.toml из выдачи инфры (make -C ../infra service name=auth)"
	@echo "    keys                      сгенерировать RSA-ключ для подписи токенов"
	@echo "    upgrade                   применить миграции"
	@echo "    run                       запустить на хосте без Docker, инфра на localhost"
	@echo "                              второй экземпляр: SERVICE__PORT=8002 make run"
	@echo ""
	@echo "  Docker"
	@echo "    up [N=1]                  собрать образ, применить миграции и держать N экземпляров в сети aiip"
	@echo "    down                      остановить все экземпляры"
	@echo "    ps                        экземпляры и их состояние"
	@echo "    logs                      логи всех экземпляров"
	@echo "    build                     пересобрать образ"
	@echo ""
	@echo "  Миграции"
	@echo "    upgrade                   применить все миграции"
	@echo "    downgrade REV=<rev>       откатить до ревизии"
	@echo "    migrate MSG=<msg>         создать автомиграцию"
	@echo ""
	@echo "  Качество кода"
	@echo "    check                     формат + линт + типы"
	@echo "    format                    форматирование ruff"
	@echo "    lint                      проверка линтером"
	@echo "    lint-fix                  форматирование + автоисправление линтера"
	@echo "    typecheck                 проверка типов mypy"
	@echo ""
	@echo "  Тесты"
	@echo "    test                      unit-тесты (без Docker)"
	@echo "    test-integration          integration-тесты (Postgres и Dragonfly в Testcontainers)"
	@echo "    test-all                  все тесты"
	@echo ""

config:
	@test -f config.toml && { echo "config.toml уже есть"; exit 1; } || true
	@{ sed -n '/^\[service\]/,/^\[database\]/p' config.toml.example | sed '$$d'; \
	   $(MAKE) -s -C ../infra service name=auth; } > config.toml
	@echo "создан config.toml"

keys:
	@test -f keys/private.pem && { echo "keys/private.pem уже есть"; exit 1; } || true
	@mkdir -p keys
	@openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out keys/private.pem 2>/dev/null
	@chmod 600 keys/private.pem
	@echo "создан keys/private.pem"

run:
	$(ON_HOST) uv run python -m src

up:
	$(BUILD) docker compose up -d --build --wait --scale auth=$(N)

down:
	docker compose down

ps:
	docker compose ps

build:
	$(BUILD) docker compose build

logs:
	docker compose logs -f --tail=100 auth

upgrade:
	$(ON_HOST) uv run alembic upgrade head

downgrade:
	$(ON_HOST) uv run alembic downgrade $(REV)

migrate:
	$(ON_HOST) uv run alembic revision --autogenerate -m "$(MSG)"

test:
	uv run pytest tests --suite=unit

test-integration:
	uv run pytest tests --suite=integration

test-all:
	uv run pytest tests --suite=full

format:
	uv run ruff format $(SRC)

lint:
	uv run ruff check $(SRC)

lint-fix:
	uv run ruff format $(SRC)
	uv run ruff check --fix $(SRC)

typecheck:
	uv run mypy $(SRC)

check:
	uv run ruff format --check $(SRC)
	uv run ruff check $(SRC)
	uv run mypy $(SRC)
