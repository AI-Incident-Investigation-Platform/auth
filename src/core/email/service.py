import json
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import aio_pika
from opentelemetry import propagate

from src.config import cfg
from src.core.email.dto import EmailLetter
from src.core.email.exc import EmailTimeoutError, EmailUnavailableError
from src.core.rabbitmq.client import RabbitmqClient
from src.core.rabbitmq.exc import RabbitmqTimeoutError, RabbitmqUnavailableError


class EmailService:
    def __init__(self, client: RabbitmqClient) -> None:
        self._client = client

    async def send(self, letter: EmailLetter) -> None:
        """Ставит срочное письмо в очередь сервиса email; возвращается после подтверждения брокера.

        Raises:
            EmailUnavailableError: брокер недоступен или задачу некому принять.
            EmailTimeoutError: брокер не подтвердил задачу вовремя.
        """
        message_id = str(uuid7())
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(seconds=letter.ttl_seconds)
        body: dict[str, object] = {
            "message_id": message_id,
            "template": letter.template.value,
            "to": letter.to,
            "locale": cfg.email.locale,
            "params": dict(letter.params),
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        }
        if letter.collapse_key is not None:
            body["collapse_key"] = letter.collapse_key
        headers: dict[str, str] = {}
        propagate.inject(headers)
        message = aio_pika.Message(
            json.dumps(body).encode(),
            message_id=message_id,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            expiration=letter.ttl_seconds,
            headers=dict(headers),
            timestamp=created_at,
        )
        try:
            await self._client.publish(
                cfg.email.exchange,
                aio_pika.ExchangeType.DIRECT,
                message,
                cfg.email.transactional_routing_key,
            )
        except RabbitmqTimeoutError as exc:
            raise EmailTimeoutError({"template": letter.template.value}) from exc
        except RabbitmqUnavailableError as exc:
            raise EmailUnavailableError({"template": letter.template.value}) from exc
