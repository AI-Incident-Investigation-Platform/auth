from uuid import UUID

from sqlalchemy import select

from src.core.db.models.session import Session
from src.core.db.repositories.base import BaseRepository


class SessionRepository(BaseRepository[Session]):
    model = Session

    async def get_for_update(self, session_id: UUID) -> Session | None:
        query = select(Session).where(Session.id == session_id).with_for_update()
        return await self._session.scalar(query)
