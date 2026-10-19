from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.core.db.db import engine, session_maker
from src.core.db.uow import UnitOfWork


class DbProvider(Provider):
    uow = provide(UnitOfWork, scope=Scope.REQUEST)

    @provide(scope=Scope.APP)
    def get_engine(self) -> AsyncEngine:
        return engine

    @provide(scope=Scope.APP)
    def get_sessionmaker(self) -> async_sessionmaker:
        return session_maker

    @provide(scope=Scope.REQUEST)
    async def get_session(self, session_factory: async_sessionmaker) -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session
