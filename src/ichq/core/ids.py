"""UUIDv7 (RFC 9562): zufällig, nicht erratbar, zeitlich sortierbar.

Python 3.12 bringt uuid7 noch nicht mit, daher diese kleine Umsetzung.
"""
from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    zufall = int.from_bytes(os.urandom(10), "big")
    rand_a = (zufall >> 62) & 0xFFF
    rand_b = zufall & ((1 << 62) - 1)
    wert = ((ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=wert)
