from uuid import UUID

from sqlalchemy import select

from src.core.db.models.user import User
from src.core.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def get_for_update(self, user_id: UUID) -> User | None:
        return await self._session.scalar(select(User).where(User.id == user_id).with_for_update())
