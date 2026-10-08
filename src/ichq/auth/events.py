from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.core.ids import uuid7
from ichq.core.logging import redact_value, request_id_var


def record(s: Session, event: str, *, user_id: uuid.UUID | None = None, session_id: uuid.UUID | None = None,
           ip: str | None = None, **data: Any) -> None:
    """Auth-Audit. Niemals Passwörter oder Tokens übergeben — und falls doch, schwärzt der Filter sie."""
    sauber = {k: redact_value(k, v) for k, v in data.items()}
    s.execute(text("""INSERT INTO auth_events(id, event, user_id, session_id, ip, request_id, data)
                      VALUES (:id, :e, :u, :s, :ip, :r, CAST(:d AS jsonb))"""),
              {"id": uuid7(), "e": event, "u": user_id, "s": session_id, "ip": ip, "r": request_id_var.get(),
               "d": json.dumps(sauber, default=str)})
