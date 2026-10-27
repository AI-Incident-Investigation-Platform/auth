from dataclasses import dataclass

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response


@dataclass(frozen=True)
class Account:
    email: str
    password: str


async def register(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post("/api/v1/auth/register", json={"email": email, "password": password})


async def login(client: AsyncClient, email: str, password: str) -> Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


def client_with_cookies(app: FastAPI, cookies: dict[str, str]) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", cookies=cookies
    )


def error_code(response: Response) -> str:
    return response.json()["code"]
