"""Mails in die Outbox schreiben — in der Transaktion des Anlasses (Rollback ⇒ keine Mail).

* Mails mit Geheimnis (Reset-/Einladungs-Token): Text+HTML AES-GCM-verschlüsselt (Schlüssel aus ``secret_key``
  per HKDF, eigener Zweck), gebunden an die Mail-ID. Nach dem Versand löscht der Worker den Inhalt.
* Dedup: gleicher ``dedup_key`` ⇒ keine zweite Mail (``ON CONFLICT DO NOTHING``).
* Einfügen ohne RETURNING — App- und Auth-Rolle dürfen die Tabelle nicht lesen.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.core.ids import uuid7
from ichq.mail.templates import Rendered

VERSION = b"\x01"


def _key(secret_key: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"ichq-mail-v1", info=b"mail-body").derive(
        secret_key.encode("utf-8"))


def seal(secret_key: str, mail_id: uuid.UUID, mail: Rendered) -> bytes:
    nonce = os.urandom(12)
    klar = json.dumps({"text": mail.text, "html": mail.html}).encode("utf-8")
    return VERSION + nonce + AESGCM(_key(secret_key)).encrypt(nonce, klar, mail_id.bytes)


def unseal(secret_key: str, mail_id: uuid.UUID, blob: bytes) -> tuple[str, str]:
    if not blob or blob[:1] != VERSION:
        raise ValueError("unbekanntes Format")
    d = json.loads(AESGCM(_key(secret_key)).decrypt(blob[1:13], blob[13:], mail_id.bytes))
    return str(d["text"]), str(d["html"])


def enqueue(s: Session, *, kind: str, to: str, mail: Rendered, secret_key: str | None = None,
            dedup_key: str | None = None, tenant_id: uuid.UUID | None = None,
            expires_at: datetime | None = None) -> uuid.UUID:
    """``secret_key`` gesetzt ⇒ Inhalt wird verschlüsselt gespeichert (Pflicht für Mails mit Token)."""
    mid = uuid7()
    werte: dict[str, object] = {"id": mid, "t": tenant_id, "k": kind, "r": to.strip(), "s": mail.subject[:200],
                                "d": dedup_key, "x": expires_at, "bt": None, "bh": None, "be": None}
    if secret_key is not None:
        werte["be"] = seal(secret_key, mid, mail)
    else:
        werte["bt"], werte["bh"] = mail.text, mail.html
    s.execute(text("""INSERT INTO mail_outbox (id, tenant_id, kind, recipient, subject, body_text, body_html,
                                               body_enc, dedup_key, expires_at)
                      VALUES (:id, :t, :k, :r, :s, :bt, :bh, :be, :d, :x)
                      ON CONFLICT DO NOTHING"""), werte)   # ohne Ziel: braucht kein SELECT-Recht
    return mid
