"""Speicher-Schnittstelle und Schlüsselschema (M0, Abschnitt 23).

Schlüssel: ``t/<tenant_id>/f/<file_id>/v/<version>`` — Mandant immer im Pfad,
nie ein Originalname, nie eine Benutzereingabe. Andere Schlüssel werden abgelehnt.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Protocol

_SCHLUESSEL = re.compile(
    r"^(t/[0-9a-f-]{36}/f/[0-9a-f-]{36}/v/[1-9][0-9]{0,5}|_health/[a-z0-9-]{1,64})$")


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


def object_key(tenant_id: uuid.UUID, file_id: uuid.UUID, version: int = 1) -> str:
    if not (isinstance(tenant_id, uuid.UUID) and isinstance(file_id, uuid.UUID)):
        raise TypeError("tenant_id und file_id müssen UUIDs sein")
    if not 1 <= version <= 999_999:
        raise ValueError("version außerhalb des Bereichs")
    return f"t/{tenant_id}/f/{file_id}/v/{version}"


def check_key(key: str) -> str:
    if not isinstance(key, str) or not _SCHLUESSEL.match(key):
        raise StorageError("Ungültiger Speicherschlüssel")
    return key


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def check(self) -> None:
        """Schreiben, Lesen, Löschen eines Prüfobjekts. Wirft bei Problemen."""
        ...
