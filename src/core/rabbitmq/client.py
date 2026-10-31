import asyncio

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractRobustConnection
from aio_pika.exceptions import AMQPError, DeliveryError, PublishError

from src.config import cfg
from src.core.rabbitmq.exc import RabbitmqTimeoutError, RabbitmqUnavailableError


class RabbitmqClient:
    """Публикация в RabbitMQ с подтверждением брокера.

    Соединение открывается при первой публикации: недоступный брокер не мешает
    старту и остальным ручкам. Сообщение без очереди-получателя (mandatory)
    возвращается брокером и считается неотправленным.
    """

    def __init__(self) -> None:
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._exchanges: dict[str, AbstractExchange] = {}
        self._connecting = asyncio.Lock()

    async def publish(
        self,
        exchange: str,
        exchange_type: aio_pika.ExchangeType,
        message: aio_pika.Message,
        routing_key: str,
    ) -> None:
        context = {"exchange": exchange, "routing_key": routing_key}
        try:
            target = await self._get_exchange(exchange, exchange_type)
            await target.publish(
                message,
                routing_key=routing_key,
                mandatory=True,
                timeout=cfg.rabbitmq.publish_timeout_seconds,
            )
        except TimeoutError as exc:
            raise RabbitmqTimeoutError(context) from exc
        except (DeliveryError, PublishError) as exc:
            raise RabbitmqUnavailableError({**context, "reason": "rejected"}) from exc
        except (AMQPError, OSError) as exc:
            raise RabbitmqUnavailableError(context) from exc

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()

    async def _get_exchange(
        self, name: str, exchange_type: aio_pika.ExchangeType
    ) -> AbstractExchange:
        if (exchange := self._exchanges.get(name)) is not None:
            return exchange
        async with self._connecting:
            if self._channel is None:
                connection = await aio_pika.connect_robust(
                    cfg.rabbitmq.url, timeout=cfg.rabbitmq.connect_timeout_seconds
                )
                try:
                    self._channel = await connection.channel(
                        publisher_confirms=True, on_return_raises=True
                    )
                except BaseException:
                    await connection.close()
                    raise
                self._connection = connection
            if name not in self._exchanges:
                self._exchanges[name] = await self._channel.declare_exchange(
                    name, exchange_type, durable=True
                )
            return self._exchanges[name]
