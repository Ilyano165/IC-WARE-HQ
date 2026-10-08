"""Äußerste eigene Schicht: Korrelations-ID, Zugriffslog, Sicherheits-Header, Notfall-500.

Unbehandelte Ausnahmen werden HIER abgefangen — so tragen auch 500er die
Korrelations-ID, und nichts Internes erreicht den Client.
"""
from __future__ import annotations

import logging
import re
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ichq.api.problems import problem
from ichq.core.ids import uuid7
from ichq.core.logging import request_id_var

log = logging.getLogger("ichq.access")
_RID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_HEADER = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
_API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        eingehend = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = eingehend if _RID.match(eingehend) else uuid7().hex
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = {"code": 500, "started": False}
        docs = scope.get("path", "").startswith(("/docs", "/openapi"))

        async def senden(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"], status["started"] = message["status"], True
                headers = list(message.get("headers", []))
                # Standard-Header nur, wo die Antwort keine eigenen setzt (Oberfläche /app: eigene CSP, ADR-013) —
                # zwei CSP-Header würden BEIDE gelten und die strengere ('none') blockierte die App.
                gesetzt = {k.lower() for k, _ in headers}
                headers.append((b"x-request-id", rid.encode()))
                standard = [*_HEADER, *([] if docs else [_API_CSP, (b"cache-control", b"no-store")])]
                headers.extend(h for h in standard if h[0] not in gesetzt)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, senden)
        except Exception:
            log.exception("unbehandelter_fehler")
            if not status["started"]:
                await problem(500, detail="Ein interner Fehler ist aufgetreten. Bitte die request_id angeben.")(
                    scope, receive, senden)
        finally:
            route = scope.get("route")
            log.info("request", extra={
                "method": scope.get("method"),
                "route": getattr(route, "path", None) or "unmatched",   # Vorlage, nie der rohe Pfad
                "status": status["code"],
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            })
            request_id_var.reset(token)
