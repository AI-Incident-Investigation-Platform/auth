from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.db.repositories.session import SessionRepository
from src.core.db.repositories.user import UserRepository


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(self.session)
        self.sessions = SessionRepository(self.session)

    async def ping(self) -> None:
        await self.session.execute(text("SELECT 1"))

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()
