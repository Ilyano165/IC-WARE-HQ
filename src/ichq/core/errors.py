"""Fachliche Fehler. Die API übersetzt sie zentral in RFC-9457-Antworten (ichq.api.errors)."""
from __future__ import annotations


class AppError(Exception):
    status: int = 400
    code: str = "bad_request"
    title: str = "Ungültige Anfrage"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title


class NotFound(AppError):
    status, code, title = 404, "not_found", "Nicht gefunden"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Konflikt"


class ValidationFailed(AppError):
    status, code, title = 422, "validation_failed", "Eingabe ungültig"


class AuthenticationRequired(AppError):
    status, code, title = 401, "authentication_required", "Anmeldung erforderlich"


class PermissionDenied(AppError):
    status, code, title = 403, "permission_denied", "Keine Berechtigung"


class TenantRequired(AppError):
    status, code, title = 403, "tenant_required", "Bitte zuerst eine Firma auswählen"


class TooManyAttempts(AppError):
    status, code, title = 429, "too_many_attempts", "Zu viele Versuche"


class TenantContextMissing(RuntimeError):
    """Programmierfehler: Zugriff auf Mandantendaten ohne Mandantenkontext. Wird nie still ignoriert."""
