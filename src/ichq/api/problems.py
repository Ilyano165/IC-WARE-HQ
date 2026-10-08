"""Einheitliches Fehlerformat (RFC 9457, application/problem+json).

Jede Fehlerantwort trägt ``request_id`` — dieselbe ID steht im Log. Interne Fehler
geben nie Stacktraces, Ausnahmetexte oder Eingabewerte heraus.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from ichq.core.logging import request_id_var

STATUS_CODES = {400: "bad_request", 401: "authentication_required", 403: "permission_denied",
                404: "not_found", 405: "method_not_allowed", 409: "conflict", 413: "payload_too_large",
                415: "unsupported_media_type", 422: "validation_failed", 429: "rate_limited",
                500: "internal_error", 503: "service_unavailable"}
STATUS_TITLES = {400: "Ungültige Anfrage", 401: "Anmeldung erforderlich", 403: "Keine Berechtigung",
                 404: "Nicht gefunden", 405: "Methode nicht erlaubt", 409: "Konflikt",
                 413: "Anfrage zu groß", 415: "Medientyp nicht unterstützt", 422: "Eingabe ungültig",
                 429: "Zu viele Anfragen", 500: "Interner Fehler", 503: "Dienst nicht verfügbar"}


def problem(status: int, code: str | None = None, title: str | None = None, detail: str | None = None,
            **extra: Any) -> JSONResponse:
    code = code or STATUS_CODES.get(status, "error")
    body: dict[str, Any] = {
        "type": f"urn:ichq:problem:{code}",
        "title": title or STATUS_TITLES.get(status, "Fehler"),
        "status": status,
        "code": code,
        "request_id": request_id_var.get(),
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    resp = JSONResponse(body, status_code=status, media_type="application/problem+json")
    if status == 401:
        resp.headers["WWW-Authenticate"] = 'Bearer realm="ichq"'
    return resp
