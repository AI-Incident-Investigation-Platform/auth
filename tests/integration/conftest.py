from collections.abc import AsyncIterator

import aio_pika
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import cfg
from src.core.db.db import engine, session_maker
from src.core.db.models import Base
from src.main import app as auth_app
from src.main import container
from tests.support.auth import ORIGIN, Mailbox, UserEvents


@pytest.fixture(scope="session")
async def app() -> AsyncIterator[FastAPI]:
    yield auth_app
    await container.close()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers={"Origin": ORIGIN}
    ) as c:
        yield c


@pytest.fixture
async def mailbox(app: FastAPI) -> AsyncIterator[Mailbox]:
    connection = await aio_pika.connect(cfg.rabbitmq.url)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        cfg.email.exchange, aio_pika.ExchangeType.DIRECT, durable=True
    )
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange, routing_key=cfg.email.transactional_routing_key)
    box = Mailbox(connection, queue)
    yield box
    await box.close()


@pytest.fixture(autouse=True)
async def user_events(app: FastAPI) -> AsyncIterator[UserEvents]:
    """Получатель событий на месте users: без него брокер вернёт событие, и регистрация — 503."""
    connection = await aio_pika.connect(cfg.rabbitmq.url)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        cfg.events.exchange, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(exclusive=True)
    await queue.bind(exchange, routing_key="user.*")
    events = UserEvents(connection, queue)
    yield events
    await events.close()


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def clean_state(app: FastAPI) -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    await (await container.get(Redis)).flushdb()
