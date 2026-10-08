"""Sitzungs-Cookie: HttpOnly, SameSite=Lax, Path=/, ohne Domain. In Produktion Secure und mit
``__Host-``-Präfix — der Browser akzeptiert es dann nur über HTTPS, nur für genau diesen Host."""
from __future__ import annotations

from fastapi import Request, Response

from ichq.core.config import Settings, secure_cookies


def cookie_name(settings: Settings) -> str:
    return "__Host-ichq_session" if secure_cookies(settings) else "ichq_session"


def set_session_cookie(response: Response, settings: Settings, token: str, *, max_age: int) -> None:
    response.set_cookie(cookie_name(settings), token, max_age=max_age, httponly=True,
                        secure=secure_cookies(settings), samesite="lax", path="/")


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(cookie_name(settings), path="/", httponly=True, secure=secure_cookies(settings),
                           samesite="lax")


def client_ip(request: Request) -> str:
    """Hinter Caddy setzt uvicorn die Client-IP nur aus vertrauenswürdigen Proxys (ICHQ_TRUSTED_PROXIES)."""
    return (request.client.host if request.client else "unknown")[:64]
