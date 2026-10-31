# auth и требования продукта

Сверка с документацией продукта
([AI-Incident-Investigation-Platform/docs](https://github.com/AI-Incident-Investigation-Platform/docs)),
редакция baseline v3 с машинными контрактами в `contracts/`. Контракт
`auth` в `docs` приведён к реализации; оставшиеся расхождения записаны
здесь.

Статусы: **есть** — реализовано; **частично**; **нет** — не начато;
**расходится** — сделано иначе, причина рядом.

## Вход и сессия — `contracts/AUTH_BOUNDARY.md`, 12 §3, 02 UC-02

| Требование | Статус | Комментарий |
|---|---|---|
| Пароля нет; вход и регистрация — одно окно: `login {email}` → `202` challenge, одинаковый для известного и нового email, без кук | есть | |
| `otp/verify` открывает сессию и создаёт аккаунт нового email (`account_created`) | есть | |
| `otp/resend`; TTL кода 300 с, 5 попыток, повтор не чаще 60 с и не больше 3, challenge ≤ 900 с, на сервере только digest | есть | digest — HMAC-SHA256 |
| Лимит писем по email и клиенту, `429` + `Retry-After` | частично | по email — да; по IP нет: на маке у всех запросов один адрес |
| Письмо с кодом — задача сервису `email` через RabbitMQ, `202` после подтверждения брокера, иначе `503` | есть | |
| Публичный путь `/api/v1/auth/*` | есть | версия в HTTP-слое, см. [design.md](design.md#версии-api) |
| Access и refresh только в HttpOnly-куках, `SameSite=Strict`, access на `Path=/`, refresh на `Path=/api/v1/auth`, токенов в теле нет | есть | |
| CSRF — проверка `Origin` у изменяющих запросов | есть | |
| Refresh — ротация и отзыв, `204` | есть | окно 10 с для соседней вкладки, кража отзывает сессию |
| `logout` — `204`, сессия отозвана, куки очищены | есть | |
| `GET /api/v1/auth/me` → `{id, email, created_at}` | есть | проекты и права — в сервисе проектов |

## Безопасность — 05 §9, 12 §2

| Требование | Статус | Комментарий |
|---|---|---|
| Токены и OTP не попадают в ответы, события и логи | есть | в логах — id и событие |
| Внутренний JWT для сервисов: `aud` сервиса, `sub=service-name`, короткий TTL, своя ротация; браузерный токен на внутреннем API не принимается | нет | |
| Rate limit на principal | частично | общий лимит gateway 10/с на `/api/v1/auth`; по IP на маке не работает |
| Аудит неудачных входов | частично | отказы пишутся в лог, журнала `audit_events` нет (он в Main) |
| Отзыв сессии действует сразу на всех сервисах | есть | пропуск сессии в Dragonfly, см. [design.md](design.md) |

## Формат API — 12 §2

| Требование | Статус | Комментарий |
|---|---|---|
| Ошибка — `{"error": {code, message, request_id, details}}` | есть | |
| `X-Request-ID` и `traceparent` | есть | `X-Request-ID` = `trace_id` |
| Поля `snake_case`, UUID строкой, время UTC RFC3339 с `Z` | частично | `snake_case` и UUID — да; суффикс `Z` у `created_at` не проверялся |
| Статусы 401 / 403 / 409 / 410 / 422 / 429 / 503 / 504 по категориям | есть | перегрузка пода — `503` с `Retry-After`, лимит клиента — `429` |

## Телеметрия сервиса — 08 §3

| Требование | Статус | Комментарий |
|---|---|---|
| Метка `app`, namespace | есть | `app: auth`, `apps` |
| OTEL-ресурс `service.name`, `service.version`, `deployment.environment` | расходится | `service.version` — тег образа; `deployment.environment` не пишется: окружение одно |
| JSON-логи: `timestamp`, `level`, `event`, `request_id`, `trace_id`, `service_name`, error_code | есть | плюс `service_version` и `message` — фраза для человека; `request_id` совпадает с `trace_id` и отдельно не пишется |
| `/metrics` с низкой кардинальностью меток | есть | `path` — шаблон маршрута |
| W3C trace context, OTLP в Alloy | есть | |
| liveness и readiness | есть | `/health`, `/ready` |
| Секреты — Secret Kubernetes, не в git | есть | |
| Наружу — только браузерные маршруты | есть | `/health`, `/ready`, `/metrics` вне `/api` |
