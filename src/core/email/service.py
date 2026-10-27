import json
from datetime import UTC, datetime, timedelta
from uuid import uuid7

import aio_pika
from opentelemetry import propagate

from src.config import cfg
from src.core.email.client import EmailClient
from src.core.email.dto import EmailLetter


class EmailService:
    def __init__(self, client: EmailClient) -> None:
        self._client = client

    async def send(self, letter: EmailLetter) -> None:
        """Ставит срочное письмо в очередь сервиса email; возвращается после подтверждения брокера.

        Raises:
            EmailUnavailableError: брокер недоступен или задачу некому принять.
            EmailTimeoutError: брокер не подтвердил задачу вовремя.
        """
        message_id = str(uuid7())
        expires_at = datetime.now(UTC) + timedelta(seconds=letter.ttl_seconds)
        body = {
            "message_id": message_id,
            "template": letter.template.value,
            "to": letter.to,
            "locale": cfg.email.locale,
            "params": dict(letter.params),
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        }
        headers: dict[str, str] = {}
        propagate.inject(headers)
        message = aio_pika.Message(
            json.dumps(body).encode(),
            message_id=message_id,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            expiration=letter.ttl_seconds,
            headers=dict(headers),
            timestamp=datetime.now(UTC),
        )
        await self._client.publish(message, cfg.email.transactional_routing_key)
