from fastapi import Response

from src.api.auth.dto import IssuedTokens
from src.config import cfg
from src.core.security.enums import AuthCookie


def set_auth_cookies(response: Response, tokens: IssuedTokens) -> None:
    response.set_cookie(
        AuthCookie.ACCESS_TOKEN,
        tokens.access_token,
        max_age=cfg.auth.access_token_ttl_minutes * 60,
        path="/",
        secure=cfg.auth.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        AuthCookie.REFRESH_TOKEN,
        tokens.refresh_token,
        max_age=cfg.auth.refresh_token_ttl_days * 24 * 60 * 60,
        path=cfg.service.route_prefix,
        secure=cfg.auth.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        AuthCookie.ACCESS_TOKEN,
        path="/",
        secure=cfg.auth.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        AuthCookie.REFRESH_TOKEN,
        path=cfg.service.route_prefix,
        secure=cfg.auth.cookie_secure,
        httponly=True,
        samesite="lax",
    )
