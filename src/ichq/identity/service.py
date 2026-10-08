from __future__ import annotations

import re
import uuid

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ichq.core.errors import Conflict, ValidationFailed
from ichq.core.ids import uuid7
from ichq.db.session import current_tenant_id
from ichq.identity.models import Membership, User

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")


def create_user(session: Session, *, email: str, display_name: str) -> uuid.UUID:
    """Konto anlegen (Control Plane / Onboarding). Ohne Passwort — das kommt in M2."""
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise ValidationFailed("email ist ungültig")
    if not display_name.strip():
        raise ValidationFailed("display_name fehlt")
    # Bewusst nur Stammdaten-Spalten: Die Plattform-Rolle darf Passwort- und 2FA-Spalten weder lesen
    # noch schreiben (Spaltenrechte seit M2). Ein ORM-Insert würde alle Spalten senden.
    uid = uuid7()
    try:
        with session.begin_nested():
            session.execute(insert(User).values(id=uid, email=email, display_name=display_name.strip()))
    except IntegrityError:
        raise Conflict("Für diese E-Mail gibt es bereits ein Konto") from None
    return uid


def add_membership(session: Session, *, user_id: uuid.UUID, title: str | None = None) -> uuid.UUID:
    """Mitgliedschaft in der Firma des aktuellen Mandantenkontexts."""
    m = Membership(tenant_id=current_tenant_id(session), user_id=user_id, title=title, status="active")
    session.add(m)
    try:
        session.flush()
    except IntegrityError:
        raise Conflict("Mitgliedschaft existiert bereits oder Konto unbekannt") from None
    return m.id
