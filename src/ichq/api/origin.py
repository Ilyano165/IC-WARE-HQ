"""Schutz gegen Cross-Site-Anfragen (CSRF) für Cookie-Sitzungen.

Für POST/PUT/PATCH/DELETE gilt: Schickt der Browser einen ``Origin``-Header, muss er zur eigenen
Herkunft passen; meldet er ``Sec-Fetch-Site: cross-site``, wird abgelehnt. Zusammen mit SameSite=Lax
und JSON-Pflicht für Bodies ist das die Abwehr. Nicht-Browser-Clients senden keinen Origin und sind
kein CSRF-Angriffsweg.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from ichq.api.problems import problem

UNSICHER = {"POST", "PUT", "PATCH", "DELETE"}


class OriginGuardMiddleware:
    def __init__(self, app: ASGIApp, public_origin: str | None) -> None:
        self.app = app
        self.public_origin = public_origin.rstrip("/") if public_origin else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSICHER:
            h = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers") or []}
            origin = h.get("origin")
            erlaubt = self.public_origin or f"{scope.get('scheme', 'http')}://{h.get('host', '')}"
            if h.get("sec-fetch-site") == "cross-site" or (origin and origin.rstrip("/") != erlaubt):
                await problem(403, "cross_site_request", "Anfrage von fremder Herkunft",
                              "Diese Anfrage kam nicht von dieser Anwendung.")(scope, receive, send)
                return
        await self.app(scope, receive, send)
