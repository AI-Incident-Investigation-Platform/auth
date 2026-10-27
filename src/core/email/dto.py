from collections.abc import Mapping
from dataclasses import dataclass

from src.core.email.enums import EmailTemplate


@dataclass(frozen=True)
class EmailLetter:
    """Задача на письмо; params попадают в шаблон и в логи не пишутся."""

    template: EmailTemplate
    to: str
    params: Mapping[str, str | int]
    ttl_seconds: int
