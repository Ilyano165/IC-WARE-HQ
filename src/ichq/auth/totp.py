"""TOTP nach RFC 6238 (SHA-1, 6 Stellen, 30 s) — kompatibel zu gängigen Authenticator-Apps.

* Zeitfenster ±1 Schritt gegen Uhrabweichung.
* Wiederverwendung desselben Codes ist ausgeschlossen (``totp_last_step``).
* Das Geheimnis liegt AES-256-GCM-verschlüsselt in der Datenbank; der Schlüssel wird per HKDF
  aus ICHQ_SECRET_KEY abgeleitet und nie gespeichert.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

STEP = 30
DIGITS = 6
VERSION = b"\x01"


def new_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    wert = struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF
    return str(wert % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def code_at(secret: str, step: int) -> str:
    return _code(secret, step)


def verify(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """Gibt den verwendeten Zeitschritt zurück oder None. Ein Schritt <= last_step zählt nie."""
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    jetzt = current_step(now)
    for step in (jetzt - 1, jetzt, jetzt + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_code(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "IC WARE HQ") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def _key(secret_key: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"ichq-totp-v1", info=b"totp-secret").derive(
        secret_key.encode("utf-8"))


def encrypt(secret_key: str, secret: str, user_id: str) -> bytes:
    nonce = os.urandom(12)
    return VERSION + nonce + AESGCM(_key(secret_key)).encrypt(nonce, secret.encode("ascii"), user_id.encode())


def decrypt(secret_key: str, blob: bytes, user_id: str) -> str:
    if not blob or blob[:1] != VERSION:
        raise ValueError("unbekanntes Format")
    return AESGCM(_key(secret_key)).decrypt(blob[1:13], blob[13:], user_id.encode()).decode("ascii")
