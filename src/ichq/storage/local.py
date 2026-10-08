"""Lokaler Speicher für Entwicklung und Einzelserver. Atomar schreiben, nie außerhalb der Wurzel."""
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from ichq.storage.base import StorageError, StoredObject, check_key


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _pfad(self, key: str) -> Path:
        pfad = (self.root / check_key(key)).resolve()
        if self.root not in pfad.parents:
            raise StorageError("Pfad außerhalb des Speichers")
        return pfad

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> StoredObject:
        ziel = self._pfad(key)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_name(f".{ziel.name}.{secrets.token_hex(6)}.tmp")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, ziel)
        return StoredObject(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    def get(self, key: str) -> bytes:
        try:
            return self._pfad(key).read_bytes()
        except FileNotFoundError:
            raise StorageError("Objekt nicht gefunden") from None

    def delete(self, key: str) -> None:
        self._pfad(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._pfad(key).is_file()

    def check(self) -> None:
        key = f"_health/probe-{secrets.token_hex(4)}"
        inhalt = secrets.token_bytes(16)
        self.put(key, inhalt)
        try:
            if self.get(key) != inhalt:
                raise StorageError("Prüfobjekt fehlerhaft gelesen")
        finally:
            self.delete(key)
