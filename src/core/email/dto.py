from collections.abc import Mapping
from dataclasses import dataclass

from src.core.email.enums import EmailTemplate


@dataclass(frozen=True)
class EmailLetter:
    """Задача на письмо; params попадают в шаблон и в логи не пишутся.

    Письма с одинаковым `collapse_key` вытесняют друг друга: пока старое ждёт отправки,
    воркер отправит только самое новое.
    """

    template: EmailTemplate
    to: str
    params: Mapping[str, str | int]
    ttl_seconds: int
    collapse_key: str | None = None
