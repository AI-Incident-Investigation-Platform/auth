.PHONY: help config keys run up down ps build logs upgrade downgrade migrate \
        format lint lint-fix typecheck check test test-integration test-all

SRC := src tests
BUILD := BUILDX_NO_DEFAULT_ATTESTATIONS=1
ON_HOST := DATABASE__POSTGRES_HOST=localhost CACHE__HOST=localhost \
           TRACING__OTLP_ENDPOINT=http://localhost:4318

help:
	@echo ""
	@echo "  Первый запуск"
	@echo "    config                    config.toml из выдачи инфры (make -C ../infra service name=auth)"
	@echo "    keys                      сгенерировать RSA-ключ для подписи токенов"
	@echo "    upgrade                   применить миграции"
	@echo "    run                       запустить на хосте без Docker, инфра на localhost,"
	@echo "                              сервис на localhost:8001 мимо Traefik"
	@echo ""
	@echo "  Docker (compose-проект aiip-auth)"
	@echo "    up [N=<число>]            собрать образ, применить миграции и поочерёдно выкатить"
	@echo "                              экземпляры без простоя (docker rollout), затем довести их до N;"
	@echo "                              без N число не меняется (в первый раз 1); если новые"
	@echo "                              не стали healthy — они удаляются, старые работают дальше"
	@echo "    down                      остановить и удалить все экземпляры"
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

up: build
	@docker rollout --version >/dev/null 2>&1 || { echo "нужен docker rollout: https://github.com/wowu/docker-rollout"; exit 1; }
	docker compose run --rm --no-deps --label traefik.enable=false auth alembic upgrade head
	docker rollout auth
	$(if $(N),docker compose up -d --wait --no-recreate --scale auth=$(N) auth)

down:
	docker compose down

ps:
	@docker compose ps --format 'table {{.Name}}\t{{.Status}}'

build:
	$(BUILD) docker build -q -t aiip-auth:latest . >/dev/null

logs:
	docker compose logs -f --tail=100

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
