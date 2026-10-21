from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.db.models.base import Base


class User(Base):
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
