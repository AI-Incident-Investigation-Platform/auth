from enum import StrEnum


class UserEventType(StrEnum):
    """Событие о пользователе; значение — routing key в exchange событий auth."""

    REGISTERED = "user.registered"
    EMAIL_CHANGED = "user.email_changed"
