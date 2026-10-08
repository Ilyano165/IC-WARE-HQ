"""Zentrale Sicherheitsabhängigkeiten. Keine Route regelt ihren Schutz selbst.

Jede Route MUSS genau eine dieser Markierungen tragen, sonst startet die Anwendung nicht
(``assert_routes_secured`` — fail closed):

* ``public(grund)``     — ohne Anmeldung (Login, Health)
* ``mfa_challenge()``   — nur im 2FA-Zwischenschritt nach korrektem Passwort
* ``any_session()``     — irgendeine gültige Sitzung (nur für Abmelden)
* ``signed_in()``       — angemeldet (inkl. 2FA), Firma noch egal — eigenes Konto verwalten
* ``authenticated()``   — angemeldet UND Firma gewählt (Principal)
* ``require(*rechte)``  — wie authenticated() UND alle genannten Rechte

Authentifizierung beantwortet nur „wer?". Die Rechte im Principal kommen ausschließlich aus
``ichq.authz`` (Rollen der Mitgliedschaft) — eine Anmeldung allein erlaubt gar nichts.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, cast

from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from sqlalchemy import text

from ichq.api.cookies import cookie_name
from ichq.api.state import AppState, get_state
from ichq.auth import sessions as auth_sessions
from ichq.authz.registry import is_known
from ichq.authz.service import Principal, decide, permissions_for_membership
from ichq.core.errors import AuthenticationRequired, PermissionDenied, TenantRequired
from ichq.db.session import TenantSession, auth_transaction, tenant_transaction
from ichq.tenancy.service import TenantInfo, current_tenant

_KEIN = object()


def current_session(request: Request, state: AppState = Depends(get_state)) -> auth_sessions.SessionInfo | None:
    """Sitzung aus dem Cookie — einmal pro Anfrage aus der Datenbank geprüft."""
    gecacht = getattr(request.state, "ichq_session", _KEIN)
    if gecacht is not _KEIN:
        return cast("auth_sessions.SessionInfo | None", gecacht)
    roh = request.cookies.get(cookie_name(state.settings))
    info = None
    if roh:
        with auth_transaction(state.engines.auth) as s:
            info = auth_sessions.load(s, state.settings, roh)
    request.state.ichq_session = info
    return info


def get_principal(request: Request, state: AppState = Depends(get_state)) -> Principal | None:
    """Principal = Sitzung (Authentifizierung) + Mitgliedschaft + Rechte aus Rollen (Autorisierung)."""
    info = current_session(request, state)
    if info is None or info.stage != "full" or info.active_tenant_id is None or info.active_membership_id is None:
        return None
    with tenant_transaction(state.engines.app, info.active_tenant_id) as s:
        gueltig = s.execute(text("""
            SELECT 1 FROM memberships m JOIN tenants t ON t.id = m.tenant_id
            WHERE m.id = :m AND m.user_id = :u AND m.status = 'active' AND t.status IN ('active','paused')"""),
            {"m": info.active_membership_id, "u": info.user_id}).scalar()
        if not gueltig:
            return None
        rechte = permissions_for_membership(s, info.active_membership_id)
    return Principal(user_id=info.user_id, tenant_id=info.active_tenant_id,
                     membership_id=info.active_membership_id, permissions=rechte)


def _ohne_principal(request: Request) -> Exception:
    info = getattr(request.state, "ichq_session", None)
    if info is not None and info.stage == "full":
        return TenantRequired()
    return AuthenticationRequired()


MARKE = "__ichq_security__"


def public(reason: str) -> Callable[[], None]:
    if not reason.strip():
        raise ValueError("public() braucht eine Begründung")

    def _dep() -> None:
        return None
    setattr(_dep, MARKE, ("public", reason))
    return _dep


def _sitzung_marke(art: str, stufen: tuple[str, ...]) -> Callable[..., auth_sessions.SessionInfo]:
    def _dep(info: auth_sessions.SessionInfo | None = Depends(current_session)) -> auth_sessions.SessionInfo:
        if info is None or info.stage not in stufen:
            raise AuthenticationRequired()
        return info
    setattr(_dep, MARKE, (art, stufen))
    return _dep


def signed_in() -> Callable[..., auth_sessions.SessionInfo]:
    return _sitzung_marke("signed_in", ("full",))


def mfa_challenge() -> Callable[..., auth_sessions.SessionInfo]:
    return _sitzung_marke("mfa_challenge", ("mfa_pending",))


def any_session() -> Callable[..., auth_sessions.SessionInfo]:
    return _sitzung_marke("any_session", ("full", "mfa_pending"))


def authenticated() -> Callable[..., Principal]:
    def _dep(request: Request, principal: Principal | None = Depends(get_principal)) -> Principal:
        if principal is None:
            raise _ohne_principal(request)
        return principal
    setattr(_dep, MARKE, ("authenticated", ()))
    return _dep


def require(*permissions: str) -> Callable[..., Principal]:
    if not permissions:
        raise ValueError("require() braucht mindestens ein Recht")
    unbekannt = [p for p in permissions if not is_known(p)]
    if unbekannt:
        raise ValueError(f"Unbekannte Rechte: {unbekannt}")

    def _dep(request: Request, principal: Principal | None = Depends(get_principal)) -> Principal:
        if principal is None:
            raise _ohne_principal(request)
        fehlend = [p for p in permissions if not decide(principal, p)]
        if fehlend:
            raise PermissionDenied(f"Fehlendes Recht: {', '.join(fehlend)}")
        return principal
    setattr(_dep, MARKE, ("permission", permissions))
    return _dep


def _markierungen(dep: Dependant) -> list[tuple[str, Any]]:
    gefunden = []
    if dep.call is not None and hasattr(dep.call, MARKE):
        gefunden.append(getattr(dep.call, MARKE))
    for sub in dep.dependencies:
        gefunden.extend(_markierungen(sub))
    return gefunden


def iter_api_routes(app: FastAPI) -> Iterator[tuple[str, frozenset[str], Dependant]]:
    """Alle effektiven API-Routen inklusive eingebundener Router.

    Ab FastAPI 0.14x stehen eingebundene Router als Hülle in ``app.routes``; die echten
    Routen (mit Präfix und Router-weiten Abhängigkeiten) liefert ``effective_route_contexts``.
    Ein Check, der nur ``app.routes`` durchsucht, prüft dort NICHTS — und ist trotzdem grün.
    """
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.path, frozenset(route.methods or ()), route.dependant
        elif hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                yield ctx.path, frozenset(ctx.methods or ()), ctx.dependant


def assert_routes_secured(app: FastAPI) -> int:
    """Startet die App nur, wenn jede Route genau eine Sicherheitsmarkierung hat. Gibt die Zahl
    geprüfter Routen zurück — 0 wäre selbst ein Fehler."""
    probleme, anzahl = [], 0
    for path, methods, dependant in iter_api_routes(app):
        anzahl += 1
        marken = _markierungen(dependant)
        if len(marken) != 1:
            probleme.append(f"{sorted(methods)} {path}: {len(marken)} Sicherheitsmarkierungen")
    if anzahl == 0:
        raise RuntimeError("Routenprüfung hat keine einzige Route gefunden — Prüfung wäre wirkungslos")
    if probleme:
        raise RuntimeError("Routen ohne eindeutige Sicherheitsregel:\n  " + "\n  ".join(probleme))
    return anzahl


TenantDB = Callable[[], AbstractContextManager[TenantSession]]


def _principal_pflicht(request: Request, principal: Principal | None = Depends(get_principal)) -> Principal:
    """Unmarkiert: sorgt nur dafür, dass ohne Principal nichts geöffnet wird.
    Die sichtbare Regel der Route bleibt ``require``/``authenticated``."""
    if principal is None:
        raise _ohne_principal(request)
    return principal


def tenant_db(principal: Principal = Depends(_principal_pflicht),
              state: AppState = Depends(get_state)) -> TenantDB:
    """Liefert eine Fabrik für Mandanten-Transaktionen des angemeldeten Principals.

    Die Route öffnet die Transaktion selbst (``with db() as s:``) — so ist der Commit
    abgeschlossen, bevor die Antwort rausgeht.
    """
    @contextmanager
    def oeffnen() -> Iterator[TenantSession]:
        with tenant_transaction(state.engines.app, principal.tenant_id) as s:
            yield s
    return oeffnen


def usable_tenant(session: TenantSession) -> TenantInfo:
    """Mandant muss aktiv sein (M0, Abschnitt 19, Schritt 0). 'paused' darf nur lesen."""
    info = current_tenant(session)
    if info.status not in ("active", "paused"):
        raise PermissionDenied("Diese Firma ist nicht aktiv")
    return info
