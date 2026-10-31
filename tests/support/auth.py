import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika.abc import AbstractConnection, AbstractQueue
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

ORIGIN = "http://testserver"


@dataclass(frozen=True)
class Account:
    email: str


@dataclass(frozen=True)
class Letter:
    body: dict[str, Any]
    message: aio_pika.abc.AbstractIncomingMessage

    @property
    def code(self) -> str:
        return str(self.body["params"]["code"])


class CapturedQueue:
    """Очередь теста на месте получателя: забирает то, что публикует auth."""

    def __init__(self, connection: AbstractConnection, queue: AbstractQueue) -> None:
        self._connection = connection
        self._queue = queue

    async def next_message(self, timeout: float = 5) -> aio_pika.abc.AbstractIncomingMessage:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            message = await self._queue.get(no_ack=True, fail=False)
            if message is not None:
                return message
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("auth ничего не опубликовал")
            await asyncio.sleep(0.05)

    async def is_empty(self) -> bool:
        return await self._queue.get(no_ack=True, fail=False) is None

    async def detach(self) -> None:
        await self._queue.delete(if_unused=False, if_empty=False)

    async def close(self) -> None:
        await self._connection.close()


class Mailbox(CapturedQueue):
    """На месте сервиса email: задачи на письма."""

    async def next_letter(self, timeout: float = 5) -> Letter:
        message = await self.next_message(timeout)
        return Letter(body=json.loads(message.body), message=message)


class UserEvents(CapturedQueue):
    """На месте сервиса users: события о пользователях."""

    async def next_event(self, timeout: float = 5) -> dict[str, Any]:
        message = await self.next_message(timeout)
        body: dict[str, Any] = json.loads(message.body)
        return body


async def start_login(client: AsyncClient, email: str) -> Response:
    return await client.post("/api/v1/auth/login", json={"email": email})


async def start_registration(client: AsyncClient, email: str) -> Response:
    return await client.post("/api/v1/auth/register", json={"email": email})


async def verify(client: AsyncClient, challenge_id: str, code: str) -> Response:
    return await client.post(
        "/api/v1/auth/otp/verify", json={"challenge_id": challenge_id, "code": code}
    )


async def sign_in(client: AsyncClient, mailbox: Mailbox, email: str) -> Response:
    started = await start_login(client, email)
    assert started.status_code == 202, started.text
    letter = await mailbox.next_letter()
    return await verify(client, started.json()["challenge_id"], letter.code)


async def register(client: AsyncClient, mailbox: Mailbox, email: str) -> Response:
    started = await start_registration(client, email)
    assert started.status_code == 202, started.text
    letter = await mailbox.next_letter()
    return await verify(client, started.json()["challenge_id"], letter.code)


def client_with_cookies(app: FastAPI, cookies: dict[str, str]) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        cookies=cookies,
        headers={"Origin": ORIGIN},
    )


def error_code(response: Response) -> str:
    return str(response.json()["error"]["code"])
