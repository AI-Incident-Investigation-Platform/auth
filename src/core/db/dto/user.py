from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.core.db.dto.base import BaseDTO


@dataclass(frozen=True)
class UserDTO(BaseDTO):
    id: UUID
    email: str
    created_at: datetime
