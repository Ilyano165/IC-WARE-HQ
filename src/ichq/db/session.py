"""Transaktionen mit eindeutigem Kontext.

Es gibt genau drei Arten, die Datenbank anzufassen:

* ``tenant_transaction``   — Mandantendaten. Setzt ``app.tenant_id`` per ``SET LOCAL``;
  Row-Level Security lässt nur Zeilen dieser Firma durch. Ein Zugriff ohne Kontext
  wirft ``TenantContextMissing`` statt still leere Ergebnisse zu liefern.
* ``platform_transaction`` — Control Plane: Firmen anlegen, Konten, Plattform-Audit.
  Die Rolle hat auf Mandantendaten keine Rechte.
* ``worker_transaction``   — nur zum Abholen von Outbox-Einträgen.

``SET LOCAL`` endet mit der Transaktion. Eine Verbindung aus dem Pool trägt den
Mandanten deshalb nie in die nächste Anfrage weiter (getestet).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, event, text
from sqlalchemy.orm import ORMExecuteState, Session

from ichq.core.errors import TenantContextMissing
from ichq.core.logging import tenant_id_var


class TenantSession(Session):
    """Session, die nur mit gesetztem Mandantenkontext arbeitet."""


@event.listens_for(TenantSession, "do_orm_execute")
def _kontext_pruefen(state: ORMExecuteState) -> None:
    if not state.session.info.get("tenant_id"):
        raise TenantContextMissing("Zugriff auf Mandantendaten ohne Mandantenkontext")


class PlatformSession(Session):
    pass


class WorkerSession(Session):
    pass


class AuthSession(Session):
    pass


@contextmanager
def tenant_transaction(engine: Engine, tenant_id: uuid.UUID) -> Iterator[TenantSession]:
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id muss eine UUID sein")
    with TenantSession(engine, expire_on_commit=False) as session, session.begin():
        session.connection().execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        session.info["tenant_id"] = tenant_id
        token = tenant_id_var.set(str(tenant_id))
        try:
            yield session
        finally:
            tenant_id_var.reset(token)


@contextmanager
def platform_transaction(engine: Engine) -> Iterator[PlatformSession]:
    with PlatformSession(engine, expire_on_commit=False) as session, session.begin():
        yield session


@contextmanager
def worker_transaction(engine: Engine) -> Iterator[WorkerSession]:
    with WorkerSession(engine, expire_on_commit=False) as session, session.begin():
        yield session


@contextmanager
def auth_transaction(engine: Engine, user_id: uuid.UUID | None = None) -> Iterator[AuthSession]:
    """Anmeldung. Mit ``user_id`` sieht die Rolle nur Mitgliedschaften und Firmen dieses Kontos (RLS)."""
    with AuthSession(engine, expire_on_commit=False) as session, session.begin():
        if user_id is not None:
            if not isinstance(user_id, uuid.UUID):
                raise TypeError("user_id muss eine UUID sein")
            session.connection().execute(
                text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
        yield session


def current_tenant_id(session: Session) -> uuid.UUID:
    tid: Any = session.info.get("tenant_id")
    if not isinstance(tid, uuid.UUID):
        raise TenantContextMissing("Kein Mandantenkontext in dieser Session")
    return tid
