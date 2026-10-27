# auth и требования продукта

Сверка с документацией продукта
([AI-Incident-Investigation-Platform/docs](https://github.com/AI-Incident-Investigation-Platform/docs)),
редакция baseline v2 от 2026-10-25. Baseline предложен команде и ещё не
принят, поэтому расхождения записаны, а не исправлены: решение по каждому —
после принятия baseline.

Статусы: **есть** — реализовано; **частично**; **нет** — не начато;
**расходится** — сделано иначе, причина рядом.

## Вход и сессия — 12 §3, 02 UC-02, 10 §2

| Требование | Статус | Комментарий |
|---|---|---|
| Пароль → одноразовый 6-значный email OTP при каждом новом входе; `login` не выдаёт токенов до OTP | нет | `login` сразу выдаёт сессию; почтового провайдера нет |
| `otp/verify`, `otp/resend`: TTL 300 с, 5 попыток, resend не чаще 60 с и не больше 3, challenge ≤ 900 с, на сервере только digest | нет | |
| Публичный путь `/api/v1/auth/*` | есть | версия в HTTP-слое, см. [design.md](design.md#версии-api) |
| Access только в памяти браузера, выдаётся в теле ответа как `bearer` | расходится | access в `HttpOnly`-куке на `Path=/api`; Bearer принимается, но в теле не отдаётся |
| Refresh — `HttpOnly`-кука, ротация и отзыв | есть | ротация, окно 10 с для соседней вкладки, кража отзывает сессию |
| Refresh-кука `SameSite=Lax`, `Path=/api/v1/auth`, `Secure` в HTTPS | расходится | `SameSite=Strict`; `Path=/api/v1/auth` совпадает; `Secure` — по конфигу |
| CSRF-заголовок для `refresh` и `logout` | нет | `SameSite=Strict` закрывает межсайтовые запросы, отдельного CSRF нет |
| `logout` — `204`, сессия отозвана, кука очищена | есть | |
| `GET /api/v1/users/me` → `{id, email, role, project_ids}` | частично | есть `GET /api/v1/auth/me` → `{id, email, created_at}`; роли и проекты по 05 §3 живут в Main (`project_memberships`) |
| `POST /api/v1/auth/ws-ticket`: одноразовая кука на 30 с, `Path=/ws/v1/events` | нет | владелец (auth или Main) не определён |
| Регистрация | вне контракта | `POST /api/v1/auth/register` есть, в контракте 12 её нет |
| Смена пароля | вне контракта | `POST /api/v1/auth/password` есть, в контракте 12 её нет |

## Безопасность — 05 §9, 12 §2

| Требование | Статус | Комментарий |
|---|---|---|
| Токены, пароли, OTP не попадают в ответы, события и логи | есть | в логах — id и тип операции |
| Пароли хранятся хэшем | есть | Argon2id по OWASP |
| Внутренний JWT для сервисов: `aud` сервиса, `sub=service-name`, короткий TTL, своя ротация; браузерный токен на внутреннем API не принимается | нет | |
| Rate limit на principal | частично | общий лимит gateway 10/с на `/api/v1/auth`; по IP на маке не работает |
| Аудит неудачных входов | частично | отказы пишутся в лог, журнала `audit_events` нет (он в Main) |
| Отзыв сессии действует сразу на всех сервисах | есть | пропуск сессии в Dragonfly, см. [design.md](design.md) |

## Формат API — 12 §2

| Требование | Статус | Комментарий |
|---|---|---|
| Ошибка — `{"error": {code, message, request_id, details}}` | расходится | сейчас `application/problem+json` с `code`, `detail`, `request_id`; формат не выбран |
| `X-Request-ID` и `traceparent` | есть | `X-Request-ID` = `trace_id` |
| Поля `snake_case`, UUID строкой, время UTC RFC3339 с `Z` | частично | `snake_case` и UUID — да; суффикс `Z` у `created_at` не проверялся |
| Статусы 401 / 409 / 422 / 429 / 503 / 504 по категориям | частично | перегрузка — `503` с `Retry-After`, а не `429` |

## Телеметрия сервиса — 08 §3

| Требование | Статус | Комментарий |
|---|---|---|
| Метка `app`, namespace | есть | `app: auth`, `apps` |
| OTEL-ресурс `service.name`, `service.version`, `deployment.environment` | частично | только `service.name` |
| JSON-логи: `timestamp`, `level`, `event`, `request_id`, `trace_id`, `service_name`, error_code | частично | есть `timestamp`, `level`, `trace_id`; `service` вместо `service_name`; `message` — фраза, а не `event`; `request_id` совпадает с `trace_id` и отдельно не пишется |
| `/metrics` с низкой кардинальностью меток | есть | `path` — шаблон маршрута |
| W3C trace context, OTLP в Alloy | есть | |
| liveness и readiness | есть | `/health`, `/ready` |
| Секреты — Secret Kubernetes, не в git | есть | |
| Наружу — только браузерные маршруты | есть | `/health`, `/ready`, `/metrics` вне `/api` |
