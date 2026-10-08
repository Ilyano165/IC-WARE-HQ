"""Globale Suche.

* Läuft in der Mandanten-Transaktion (RLS) UND über ``visible_clause`` — fremde Firmen und nicht freigegebene
  Objekte tauchen nie auf, auch nicht als Anzahl.
* Volltext über ``objects.search_vector`` (PostgreSQL ``simple``-Konfiguration, Präfixsuche je Wort).
* Ergebnisse gruppiert nach ``GROUPS``; Personen = Mitglieder dieser Firma (``users.read``) + Objekte vom Typ
  ``employee``.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import and_, bindparam, func, select, text
from sqlalchemy.orm import Session

from ichq.authz.service import Principal, decide
from ichq.core.errors import ValidationFailed
from ichq.objects.models import ObjectRow
from ichq.objects.registry import GROUPS, OBJECT_TYPES
from ichq.objects.visibility import types_for, visible_clause

MIN_LEN, MAX_LEN, MAX_TOKENS = 2, 100, 8
DEFAULT_PER_GROUP, MAX_PER_GROUP = 5, 20


def tokens(q: str) -> list[str]:
    q = q.strip()
    if not MIN_LEN <= len(q) <= MAX_LEN:
        raise ValidationFailed(f"q: {MIN_LEN}–{MAX_LEN} Zeichen")
    teile = [t[:40] for t in re.findall(r"\w+", q.lower())][:MAX_TOKENS]
    if not teile:
        raise ValidationFailed("q enthält keine suchbaren Wörter")
    return teile


def _tsquery(teile: list[str]) -> str:
    # Nur \w-Zeichen: keine tsquery-Operatoren aus der Eingabe möglich
    return " & ".join(f"{t}:*" for t in teile)


def search(session: Session, principal: Principal, q: str, *, per_group: int = DEFAULT_PER_GROUP,
           groups: tuple[str, ...] = GROUPS) -> dict[str, Any]:
    teile = tokens(q)
    n = max(1, min(per_group, MAX_PER_GROUP))
    unbekannt = [g for g in groups if g not in GROUPS]
    if unbekannt:
        raise ValidationFailed(f"Unbekannte Gruppen: {unbekannt}")
    lesbar = types_for(principal)
    tsq = func.to_tsquery(text("'simple'::regconfig"), bindparam("tsq", _tsquery(teile)))
    ergebnis: dict[str, Any] = {}
    for gruppe in groups:
        typen = sorted(t.code for t in OBJECT_TYPES.values() if t.group == gruppe and t.code in lesbar)
        treffer: list[dict[str, Any]] = []
        mehr = False
        if typen:
            rows = session.execute(
                select(ObjectRow.public_id, ObjectRow.type, ObjectRow.title, ObjectRow.created_at)
                .where(ObjectRow.type.in_(typen), ObjectRow.archived_at.is_(None),
                       ObjectRow.search_vector.op("@@")(tsq), visible_clause(principal))
                .order_by(func.ts_rank(ObjectRow.search_vector, tsq).desc(), ObjectRow.created_at.desc(),
                          ObjectRow.id.desc())
                .limit(n + 1)).all()
            mehr = len(rows) > n
            treffer = [{"id": r.public_id, "type": r.type, "title": r.title} for r in rows[:n]]
        if gruppe == "persons" and decide(principal, "users.read") and len(treffer) < n:
            rest = n - len(treffer)
            bedingungen = and_(*[text(f"u.display_name ILIKE :t{i}") for i in range(len(teile))])
            sql = select(text("m.public_id, u.display_name")).select_from(
                text("memberships m JOIN users u ON u.id = m.user_id")).where(
                text("m.status = 'active'"), bedingungen).order_by(text("u.display_name, m.id")).limit(rest + 1)
            params = {f"t{i}": "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                      for i, t in enumerate(teile)}
            mitglieder = session.execute(sql, {f"t{i}": params[f"t{i}"] for i in range(len(teile))}).all()
            mehr = mehr or len(mitglieder) > rest
            treffer += [{"id": m.public_id, "type": "member", "title": m.display_name} for m in mitglieder[:rest]]
        ergebnis[gruppe] = {"items": treffer, "has_more": mehr}
    return {"query": " ".join(teile), "groups": ergebnis}
