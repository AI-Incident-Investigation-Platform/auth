import asyncio

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractRobustConnection
from aio_pika.exceptions import AMQPError, DeliveryError, PublishError

from src.config import cfg
from src.core.email.exc import EmailTimeoutError, EmailUnavailableError


class EmailClient:
    """Публикация задач сервису email в RabbitMQ с подтверждением брокера.

    Соединение открывается при первой публикации: недоступный брокер не мешает
    старту и остальным ручкам. Задача без очереди-получателя (mandatory)
    возвращается брокером и считается неотправленной.
    """

    def __init__(self) -> None:
        self._connection: AbstractRobustConnection | None = None
        self._exchange: AbstractExchange | None = None
        self._connecting = asyncio.Lock()

    async def publish(self, message: aio_pika.Message, routing_key: str) -> None:
        try:
            exchange = await self._get_exchange()
            await exchange.publish(
                message,
                routing_key=routing_key,
                mandatory=True,
                timeout=cfg.rabbitmq.publish_timeout_seconds,
            )
        except TimeoutError as exc:
            raise EmailTimeoutError({"routing_key": routing_key}) from exc
        except (DeliveryError, PublishError) as exc:
            raise EmailUnavailableError({"routing_key": routing_key, "reason": "rejected"}) from exc
        except (AMQPError, OSError) as exc:
            raise EmailUnavailableError({"routing_key": routing_key}) from exc

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()

    async def _get_exchange(self) -> AbstractExchange:
        if self._exchange is not None:
            return self._exchange
        async with self._connecting:
            if self._exchange is None:
                connection = await aio_pika.connect_robust(
                    cfg.rabbitmq.url, timeout=cfg.rabbitmq.connect_timeout_seconds
                )
                try:
                    channel = await connection.channel(
                        publisher_confirms=True, on_return_raises=True
                    )
                    self._exchange = await channel.declare_exchange(
                        cfg.email.exchange, aio_pika.ExchangeType.DIRECT, durable=True
                    )
                except BaseException:
                    await connection.close()
                    raise
                self._connection = connection
            return self._exchange
