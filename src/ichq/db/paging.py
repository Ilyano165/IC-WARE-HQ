"""Cursor-Paginierung (Keyset) für alle Listen der Core-Plattform.

* Keine Liste ohne Grenze: ``limit`` wird hier hart auf ``MAX_LIMIT`` begrenzt — auch wenn die API-Validierung
  umgangen würde.
* Der Cursor ist undurchsichtig (Base64-JSON), enthält nur Sortwert, interne Reihenfolge-ID und die
  Sortierung, für die er gilt. Ein manipulierter Cursor verschiebt höchstens die Startposition — Sichtbarkeit
  und Mandant werden davon nicht berührt, sie stecken in der Abfrage selbst.
"""
from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import literal, tuple_
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session
from sqlalchemy.types import Date, DateTime, Integer, String, TypeEngine

from ichq.core.errors import ValidationFailed

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
Kind = Literal["ts", "date", "int", "text"]
_TYPES: dict[str, TypeEngine[Any]] = {"ts": DateTime(timezone=True), "date": Date(), "int": Integer(),
                                      "text": String()}


@dataclass(frozen=True)
class SortKey:
    name: str
    column: Any        # Spalte oder SQL-Ausdruck (ColumnElement / InstrumentedAttribute)
    kind: Kind


@dataclass(frozen=True)
class PageRows:
    rows: list[Row[Any]]
    next_cursor: str | None


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def _wert_raus(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def _wert_rein(kind: Kind, v: Any) -> Any:
    try:
        if kind == "ts":
            return datetime.fromisoformat(str(v))
        if kind == "date":
            return date.fromisoformat(str(v))
        if kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError
            return v
        if not isinstance(v, str):
            raise ValueError
        return v
    except ValueError:
        raise ValidationFailed("cursor ist ungültig") from None


def encode_cursor(sort: SortKey, desc: bool, value: Any, row_id: uuid.UUID) -> str:
    roh = json.dumps({"s": sort.name, "d": desc, "v": _wert_raus(value), "i": row_id.hex}, separators=(",", ":"))
    return base64.urlsafe_b64encode(roh.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, sort: SortKey, desc: bool) -> tuple[Any, uuid.UUID]:
    try:
        roh = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        daten = json.loads(roh)
        if not isinstance(daten, dict) or daten.get("s") != sort.name or daten.get("d") is not desc:
            raise ValueError
        return _wert_rein(sort.kind, daten.get("v")), uuid.UUID(hex=str(daten.get("i")))
    except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationFailed("cursor ist ungültig oder gehört zu einer anderen Sortierung") from None


def keyset(session: Session, stmt: Any, sort: SortKey, id_col: Any, *, desc: bool,
           cursor: str | None, limit: int | None) -> PageRows:
    """Führt ``stmt`` sortiert und begrenzt aus. Die Zeilen tragen zusätzlich ``_sort`` und ``_id``."""
    n = clamp_limit(limit)
    stmt = stmt.add_columns(sort.column.label("_sort"), id_col.label("_id"))
    if cursor:
        wert, letzte_id = decode_cursor(cursor, sort, desc)
        links = tuple_(sort.column, id_col)
        rechts = tuple_(literal(wert, _TYPES[sort.kind]), literal(letzte_id))
        stmt = stmt.where(links < rechts if desc else links > rechts)
    ordnung = (sort.column.desc(), id_col.desc()) if desc else (sort.column.asc(), id_col.asc())
    rows = list(session.execute(stmt.order_by(*ordnung).limit(n + 1)).all())
    weiter = None
    if len(rows) > n:
        rows = rows[:n]
        letzte = rows[-1]
        weiter = encode_cursor(sort, desc, letzte._sort, letzte._id)
    return PageRows(rows=rows, next_cursor=weiter)
