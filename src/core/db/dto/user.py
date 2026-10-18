from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.core.db.dto.base import BaseDTO
from src.core.db.enums import UserRole


@dataclass(frozen=True)
class UserDTO(BaseDTO):
    id: UUID
    email: str
    role: UserRole
    created_at: datetime
