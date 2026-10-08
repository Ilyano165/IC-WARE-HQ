"""Zufallstokens und ihre Hashes. Gespeichert wird immer nur der Hash."""
from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token(nbytes: int = 32) -> tuple[str, bytes]:
    """(roh für den Client, SHA-256 für die Datenbank). 256 Bit Zufall — ein schneller Hash genügt."""
    roh = secrets.token_urlsafe(nbytes)
    return roh, hash_token(roh)


def hash_token(roh: str) -> bytes:
    return hashlib.sha256(roh.encode("utf-8")).digest()


def keyed_hash(key: str, wert: str) -> bytes:
    """HMAC — für Login-Namen in der Drosselung und für Recovery-Codes (kurz, daher mit Schlüssel)."""
    return hmac.new(key.encode("utf-8"), wert.encode("utf-8"), hashlib.sha256).digest()


def new_recovery_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # ohne verwechselbare Zeichen
    roh = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{roh[:5]}-{roh[5:]}"


def normalize_recovery_code(code: str) -> str:
    return code.strip().upper().replace(" ", "").replace("-", "")
