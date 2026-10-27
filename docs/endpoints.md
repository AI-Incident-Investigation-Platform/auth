# Эндпоинты auth

Снаружи — через Traefik: `http://localhost/api/v1/auth/...`. Внутри
кластера — `http://auth:8001/api/v1/auth/...`. Служебные роуты (`/health`,
`/ready`, `/metrics`) и JWKS живут вне `/api` и через gateway не
публикуются. Как устроены версии API — в [design.md](design.md#версии-api).

Gateway ограничивает весь `/api/v1/auth`: 10 запросов/с, burst 10. Сверх
предела одновременных запросов пода (`service.max_concurrent_requests`,
32) сервис отвечает `503` с `Retry-After`.

## Публичные

| Метод и путь | Кто зовёт | Вход | Ответ | Авторизация |
|---|---|---|---|---|
| `POST /api/v1/auth/register` | браузер | `{email, password}` | `201` `{id, email, created_at}` + куки сессии | нет |
| `POST /api/v1/auth/login` | браузер | `{email, password}` | `200` `{id, email, created_at}` + куки сессии | нет |
| `POST /api/v1/auth/refresh` | браузер | кука `refresh_token` | `204` + новые куки | refresh-кука |
| `POST /api/v1/auth/logout` | браузер | кука `refresh_token` | `204`, куки очищены, сессия закрыта | refresh-кука |
| `POST /api/v1/auth/password` | браузер | `{current_password, new_password}` | `204`, остальные сессии закрыты | access |
| `GET /api/v1/auth/me` | браузер, сервисы | — | `200` `{id, email, created_at}` | access |

- `email` приводится к нижнему регистру. Длина нового пароля — от
  `auth.password_min_length` до `auth.password_max_length`.
- Куки сессии: `access_token` (`Path=/api`, 15 минут) и `refresh_token`
  (`Path=/api/v1/auth`, 30 дней); обе `HttpOnly`, `SameSite=Strict`, `Secure` —
  по `auth.cookie_secure`.
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

Тело — `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Unauthorized",
  "status": 401,
  "code": "auth.invalid_credentials",
  "detail": "Неверный email или пароль",
  "request_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

`request_id` — `trace_id` запроса, он же в заголовке `X-Request-ID`
каждого ответа. У `422` есть поле `errors` со списком полей.

| Код | Статус | Когда |
|---|---|---|
| `auth.email_already_registered` | 409 | регистрация на занятый email |
| `auth.invalid_credentials` | 401 | неверная пара email и пароль |
| `auth.invalid_refresh_token` | 401 | refresh нет, просрочен или неизвестен |
| `auth.refresh_token_reused` | 401 | старый refresh предъявлен позже 10 секунд: кража, сессия отозвана |
| `auth.account_not_found` | 401 | токен валиден, но пользователя уже нет |
| `auth.wrong_current_password` | 422 | смена пароля с неверным текущим |
| `security.not_authenticated` | 401 | access нет, подпись или срок неверны, пропуска сессии нет |
| `request.invalid` | 422 | тело не прошло валидацию, поля — в `errors` |
| `db.unavailable`, `cache.unavailable` | 503 | Postgres или Dragonfly недоступны |
| `service.overloaded`, `security.password_hashing_overloaded` | 503 | под перегружен; заголовок `Retry-After` |
| `internal_error` | 500 | всё непредусмотренное; подробности только в логе |
