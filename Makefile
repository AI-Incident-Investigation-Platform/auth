.PHONY: help config keys run up down ps build secret migrate-job deploy logs upgrade downgrade migrate \
        format lint lint-fix typecheck check test test-integration test-all

SRC := src tests
BUILD := BUILDX_NO_DEFAULT_ATTESTATIONS=1
CLUSTER := aiip
CONTEXT := k3d-$(CLUSTER)
KUBECTL := kubectl --context $(CONTEXT) -n apps
IMAGE := aiip-auth:$(shell date +%Y%m%d%H%M%S)
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
	@echo "  Kubernetes (кластер k3d aiip, namespace apps)"
	@echo "    up [N=<число>]            собрать образ, загрузить в кластер, обновить секрет, применить"
	@echo "                              миграции Job'ом и выкатить RollingUpdate без простоя, затем"
	@echo "                              довести число подов до N; без N число не меняется (в первый"
	@echo "                              раз 1); если новые поды не стали готовы — откат"
	@echo "    down                      удалить Deployment, Service и маршрут, секрет остаётся"
	@echo "    ps                        поды и их состояние"
	@echo "    logs                      логи всех подов"
	@echo "    build                     собрать образ и загрузить в кластер"
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

up: build secret migrate-job deploy

down:
	$(KUBECTL) delete -k k8s --ignore-not-found

ps:
	$(KUBECTL) get pods -l app=auth -o wide

build:
	$(BUILD) docker build -q -t $(IMAGE) . >/dev/null
	k3d image import $(IMAGE) -c $(CLUSTER)

secret:
	@test -f config.toml -a -f keys/private.pem || { echo "нужны config.toml и keys/private.pem: make config keys"; exit 1; }
	@$(KUBECTL) create secret generic auth --from-file=config.toml --from-file=private.pem=keys/private.pem \
		--dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null

migrate-job:
	@$(KUBECTL) delete job auth-migrate --ignore-not-found >/dev/null
	@sed 's|aiip-auth:latest|$(IMAGE)|' k8s/migrate.yaml | $(KUBECTL) apply -f - >/dev/null
	@$(KUBECTL) wait --for=condition=complete job/auth-migrate --timeout=120s || { $(KUBECTL) logs job/auth-migrate; exit 1; }

deploy:
	kubectl kustomize k8s | sed 's|aiip-auth:latest|$(IMAGE)|' | kubectl --context $(CONTEXT) apply -f -
	$(if $(N),$(KUBECTL) scale deploy/auth --replicas=$(N))
	@$(KUBECTL) rollout status deploy/auth --timeout=150s || { echo "новые поды не стали готовы, откатываю"; $(KUBECTL) rollout undo deploy/auth; exit 1; }

logs:
	$(KUBECTL) logs -l app=auth --prefix --tail=100 -f

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
