from enum import StrEnum


class AuthCookie(StrEnum):
    ACCESS_TOKEN = "access_token"
    REFRESH_TOKEN = "refresh_token"


class OtpPurpose(StrEnum):
    """Зачем выдан код: от этого зависят письмо и ручка, которая его принимает."""

    LOGIN = "login"
    REGISTER = "register"
    EMAIL_CHANGE = "email_change"
