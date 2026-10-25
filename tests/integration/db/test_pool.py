import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.db.db import engine
from src.core.db.error_translation import TranslatingPool
from src.core.db.exc import DatabaseUnavailableError


@pytest.mark.case(id="DB-POOL-001")
async def test_exhausted_pool_is_database_unavailable(app: FastAPI) -> None:
    small = create_async_engine(
        engine.url, poolclass=TranslatingPool, pool_size=1, max_overflow=0, pool_timeout=0.1
    )
    try:
        async with small.connect() as held:
            await held.execute(text("SELECT 1"))
            with pytest.raises(DatabaseUnavailableError):
                async with small.connect() as second:
                    await second.execute(text("SELECT 1"))
    finally:
        await small.dispose()


@pytest.mark.case(id="DB-TIMEOUT-001")
async def test_statement_timeout_is_database_unavailable(app: FastAPI) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SET statement_timeout = 50"))
        with pytest.raises(DatabaseUnavailableError):
            await connection.execute(text("SELECT pg_sleep(1)"))
