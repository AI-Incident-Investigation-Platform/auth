from uuid import UUID

from sqlalchemy import select

from src.core.db.models.user import User
from src.core.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def get_by_email_for_share(self, email: str) -> User | None:
        query = select(User).where(User.email == email).with_for_update(read=True)
        return await self._session.scalar(query)

    async def get_for_update(self, user_id: UUID) -> User | None:
        query = select(User).where(User.id == user_id).with_for_update()
        return await self._session.scalar(query)
