import json
from datetime import UTC, datetime
from uuid import UUID, uuid7

import aio_pika
from opentelemetry import propagate

from src.config import cfg
from src.core.events.enums import UserEventType
from src.core.events.exc import EventsTimeoutError, EventsUnavailableError
from src.core.rabbitmq.client import RabbitmqClient
from src.core.rabbitmq.exc import RabbitmqTimeoutError, RabbitmqUnavailableError


class UserEventsService:
    """События о пользователях для других сервисов: регистрация и смена почты.

    Публикуется до commit: не подтверждённое брокером событие отменяет
    операцию, и потребитель не остаётся без пользователя. Событие без
    commit (сбой после публикации) потребитель переживает: оно несёт
    полное состояние, а не разницу.
    """

    def __init__(self, client: RabbitmqClient) -> None:
        self._client = client

    async def publish(self, event_type: UserEventType, user_id: UUID, email: str) -> None:
        """Публикует событие и ждёт подтверждения брокера.

        Raises:
            EventsUnavailableError: брокер недоступен или событие некому принять.
            EventsTimeoutError: брокер не подтвердил событие вовремя.
        """
        event_id = str(uuid7())
        occurred_at = datetime.now(UTC)
        body = {
            "event_id": event_id,
            "type": event_type.value,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "user_id": str(user_id),
            "email": email,
        }
        headers: dict[str, str] = {}
        propagate.inject(headers)
        message = aio_pika.Message(
            json.dumps(body).encode(),
            message_id=event_id,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            headers=dict(headers),
            timestamp=occurred_at,
        )
        context = {"event_type": event_type.value, "user_id": str(user_id)}
        try:
            await self._client.publish(
                cfg.events.exchange, aio_pika.ExchangeType.TOPIC, message, event_type.value
            )
        except RabbitmqTimeoutError as exc:
            raise EventsTimeoutError(context) from exc
        except RabbitmqUnavailableError as exc:
            raise EventsUnavailableError(context) from exc
