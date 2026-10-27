# auth

Сервис аутентификации AIIP: регистрация, вход по email и паролю, сессии
устройств, refresh с ротацией, смена пароля, выход. Подписывает RS256 JWT
и отдаёт публичный ключ как JWKS — по нему остальные сервисы проверяют
токен сами, без похода в `auth`.

Работает в namespace `apps` кластера `aiip`, снаружи — за Traefik на
`/api/v1/auth`. Данные — свои БД в Postgres и префикс `auth:` в Dragonfly.

## Документация

- [docs/endpoints.md](docs/endpoints.md) — карта эндпоинтов: что, кому, с
  какими ошибками.
- [docs/design.md](docs/design.md) — как устроены токены и сессии, слои
  кода, ресурсы и масштабирование, принятые решения.
- [docs/requirements.md](docs/requirements.md) — что требует документация
  продукта и что из этого реализовано.

## Стек

Python 3.14, uv, FastAPI, dishka, SQLAlchemy 2.0 async + asyncpg, Alembic,
pydantic-settings, redis-клиент к Dragonfly, argon2, PyJWT, OpenTelemetry,
prometheus-client; httpx — только в тестах.

## Запуск

Нужны Docker, `k3d`, `kubectl` и поднятая инфра (`make -C ../infra up`).

```bash
make config keys     # первый раз: config.toml из выдачи инфры и RSA-ключ
make up              # образ → кластер, миграции Job'ом, RollingUpdate с откатом
make ps              # поды, нагрузка, решение автоскейлера
make logs
make down            # убрать Deployment, Service и маршрут; секрет остаётся
```

На хосте без Docker: `make -C ../infra forward` в соседнем терминале, затем
`make upgrade` и `make run` — сервис на `localhost:8001`, мимо Traefik.

## Проверка

```bash
make check             # ruff format --check + ruff check + mypy
make test              # unit, без Docker
make test-integration  # Postgres и Dragonfly в Testcontainers
make test-all
```

Миграции: `make migrate MSG="..."` (нужен `forward`), `make upgrade`,
`make downgrade REV=<rev>`. Полный список целей — `make help`.

## Конфиг и секреты

`config.toml` (не в git) собирается из `config.toml.example` и блока,
который печатает `make -C ../infra service name=auth`. Переменные окружения
перекрывают его (вложенность через `__`). Ключ подписи — `keys/private.pem`
(не в git). В кластере оба лежат в Secret `auth` и монтируются файлами.
