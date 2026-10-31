# Эндпоинты auth

Снаружи — через Traefik: `http://localhost/api/v1/auth/...`. Внутри
кластера — `http://auth:8001/api/v1/auth/...`. Служебные роуты (`/health`,
`/ready`, `/metrics`) и JWKS живут вне `/api` и через gateway не
публикуются. Как устроены версии API — в [design.md](design.md#версии-api).
Контракт — `contracts/AUTH_BOUNDARY.md` и `contracts/openapi/main-public.openapi.yaml`
в репозитории `docs`.

Gateway ограничивает весь `/api/v1/auth`: 10 запросов/с, burst 10. Сверх
предела одновременных запросов пода (`service.max_concurrent_requests`,
64) сервис отвечает `503` с `Retry-After`.

## Публичные

| Метод и путь | Кто зовёт | Вход | Ответ | Авторизация |
|---|---|---|---|---|
| `POST /api/v1/auth/register` | браузер | `{email}` | `202` `{challenge_id, masked_email, delivery_status, expires_in, resend_after}`, кук нет | нет |
| `POST /api/v1/auth/login` | браузер | `{email}` | `202` как у `register`, кук нет | нет |
| `POST /api/v1/auth/otp/verify` | браузер | `{challenge_id, code}` | `200` `{user: {id, email, created_at}, account_created}` + куки сессии | нет |
| `POST /api/v1/auth/otp/resend` | браузер | `{challenge_id}` | `202` `{challenge_id, delivery_status, expires_in, resend_after}` | нет |
| `POST /api/v1/auth/refresh` | браузер | кука `refresh_token` | `204` + новые куки | refresh-кука |
| `POST /api/v1/auth/logout` | браузер | кука `refresh_token` | `204`, куки очищены, сессия закрыта | refresh-кука |
| `GET /api/v1/auth/me` | браузер, сервисы | — | `200` `{id, email, created_at}` | access |
| `POST /api/v1/auth/email/change` | браузер | `{new_email}` | `202` `{challenge_id, masked_email, masked_new_email, delivery_status, expires_in, resend_after}` | access |
| `POST /api/v1/auth/email/change/verify` | браузер | `{challenge_id, code, new_code}` | `200` `{id, email, created_at}` | access |

- Регистрация и вход — разные запросы кода. `register` принимает только
  новую почту (иначе `409`), `login` — только зарегистрированную (иначе
  `404`); оба ставят письмо с кодом в очередь сервиса `email`. Код
  регистрации в `otp/verify` создаёт аккаунт (`account_created: true`) и
  публикует `user.registered`. `email` приводится к нижнему регистру.
- Смена почты: `email/change` шлёт код на текущую почту и второй — на
  новую; `email/change/verify` принимает оба (`code` — с текущей,
  `new_code` — с новой), меняет почту, отзывает остальные сессии
  пользователя, публикует `user.email_changed` и предупреждает старую почту
  письмом. `otp/resend` присылает оба кода заново.
- Код — 6 цифр, живёт `auth.otp_code_ttl_seconds` (300 с), неверных попыток
  `auth.otp_max_attempts` (5). Повтор — не раньше
  `auth.otp_resend_interval_seconds` (60 с) и не больше
  `auth.otp_max_resends` (3) раз. Challenge живёт
  `auth.otp_challenge_ttl_seconds` (900 с). Писем на один email —
  `auth.otp_sends_per_email_per_hour` (10) в час.
- Куки сессии: `access_token` (`Path=/`, 15 минут) и `refresh_token`
  (`Path=/api/v1/auth`, 30 дней); обе `HttpOnly`, `SameSite=Strict`,
  `Secure` — по `auth.cookie_secure`. В теле ответа токенов нет.
- Изменяющий запрос к `/api` принимается только с `Origin` из
  `auth.allowed_origins`; иначе `403`. Запрос с `Authorization` (вызов
  другого сервиса) не проверяется по `Origin`.
- Access принимается из куки `access_token` или из `Authorization: Bearer`
  (так его передают между сервисами).
- `refresh` по токену, ротированному меньше 10 секунд назад (соседняя
  вкладка), выдаёт только access, без нового refresh.

## Служебные

| Метод и путь | Кто зовёт | Ответ |
|---|---|---|
| `GET /.well-known/jwks.json` | сервисы, внутри кластера | `200` `{keys: [{kty, n, e, kid, use, alg}]}`, без версии и авторизации |
| `GET /health` | kubelet: liveness, startup | `200 {status: "ok"}`, зависимостей не проверяет |
| `GET /ready` | kubelet: readiness | `200`, если доступны Postgres и Dragonfly; иначе `503` |
| `GET /metrics` | Alloy | метрики Prometheus |

## Ошибки

Тело — конверт `error`:

```json
{
  "error": {
    "code": "auth.otp_invalid",
    "message": "Неверный код",
    "request_id": "4bf92f3577b34da6a3ce929d0e0e4736",
    "details": {"attempts_left": 3}
  }
}
```

`request_id` — `trace_id` запроса, он же в заголовке `X-Request-ID`
каждого ответа. `details` — только у ошибок, где он описан ниже; у `422` в
нём `errors` — список полей.

| Код | Статус | Когда |
|---|---|---|
| `auth.otp_invalid` | 401 | неверный код; `details.attempts_left` — сколько попыток осталось |
| `auth.otp_expired` | 410 | срок кода истёк; нужен `otp/resend` или новый запрос кода |
| `auth.challenge_invalid` | 410 | challenge использован, исчерпан, истёк, выдан для другой ручки или другой сессии; при смене почты — почту уже сменили |
| `auth.email_not_registered` | 404 | `login` на почту без аккаунта |
| `auth.email_taken` | 409 | `register`, `email/change` или их подтверждение на занятую почту |
| `auth.email_unchanged` | 422 | `email/change` на текущую почту |
| `events.unavailable`, `events.timeout` | 503, 504 | брокер не подтвердил событие о пользователе; регистрация или смена почты не выполнены |
| `auth.otp_rate_limited` | 429 | лимит писем на email, повтор раньше интервала или сверх лимита; заголовок `Retry-After` |
| `email.unavailable`, `email.timeout` | 503, 504 | брокер недоступен или задачу некому принять; письмо не отправлено |
| `security.origin_forbidden` | 403 | изменяющий запрос без разрешённого `Origin` |
| `auth.invalid_refresh_token` | 401 | refresh нет, просрочен или неизвестен |
| `auth.refresh_token_reused` | 401 | старый refresh предъявлен позже 10 секунд: кража, сессия отозвана |
| `auth.account_not_found` | 401 | токен валиден, но пользователя уже нет |
| `security.not_authenticated` | 401 | access нет, подпись или срок неверны, пропуска сессии нет |
| `request.invalid` | 422 | тело не прошло валидацию, поля — в `details.errors` |
| `db.unavailable`, `cache.unavailable` | 503 | Postgres или Dragonfly недоступны |
| `service.overloaded` | 503 | под перегружен; заголовок `Retry-After` |
| `internal_error` | 500 | всё непредусмотренное; подробности только в логе |
