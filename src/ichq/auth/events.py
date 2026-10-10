from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.core.ids import uuid7
from ichq.core.logging import redact_value, request_id_var
from ichq.mail import templates
from ichq.mail.outbox import enqueue

log = logging.getLogger("ichq.auth")


def record(s: Session, event: str, *, user_id: uuid.UUID | None = None, session_id: uuid.UUID | None = None,
           ip: str | None = None, **data: Any) -> None:
    """Auth-Audit. Niemals Passwörter oder Tokens übergeben — und falls doch, schwärzt der Filter sie."""
    sauber = {k: redact_value(k, v) for k, v in data.items()}
    s.execute(text("""INSERT INTO auth_events(id, event, user_id, session_id, ip, request_id, data)
                      VALUES (:id, :e, :u, :s, :ip, :r, CAST(:d AS jsonb))"""),
              {"id": uuid7(), "e": event, "u": user_id, "s": session_id, "ip": ip, "r": request_id_var.get(),
               "d": json.dumps(sauber, default=str)})
    if event in templates.SICHERHEIT and user_id is not None:
        _sicherheitshinweis(s, event, user_id)


def _sicherheitshinweis(s: Session, event: str, user_id: uuid.UUID) -> None:
    """Sicherheitsrelevante Kontoänderung ⇒ Hinweismail an das Konto (Outbox, gleiche Transaktion).
    Im Savepoint: ein Fehler hier darf den Auth-Eintrag (z. B. einen Fehlversuch) nie zurückrollen."""
    jetzt = datetime.now(UTC)
    takt = "%Y%m%d%H" if event == "account_locked" else "%Y%m%d%H%M"   # Sperr-Hinweis höchstens stündlich
    try:
        with s.begin_nested():
            konto = s.execute(text("SELECT email, status FROM users WHERE id = :u"), {"u": user_id}).one_or_none()
            if konto is None or not konto.email or konto.status == "deactivated":
                return
            enqueue(s, kind=f"security.{event}", to=konto.email, mail=templates.security_notice(event, jetzt),
                    dedup_key=f"sec:{event}:{user_id}:{jetzt.strftime(takt)}")
    except Exception as e:
        log.error("sicherheitshinweis_nicht_eingereiht", extra={"event": event, "exc_type": e.__class__.__name__})
