"""Hilfen für die M2-Tests: echte Konten mit echten Argon2id-Hashes, echte Logins über die API."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from ichq.auth import account, totp
from ichq.auth.mailer import MemoryMailer
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
from ichq.identity.service import add_membership, create_user
from tests.api_helpers import make_client
from tests.conftest import _admin

PASSWORT = "Kaffee-Wolke-Treppe-17"


def make_user(engines: Engines, settings: Settings, email: str, *, password: str | None = PASSWORT,
              username: str | None = None) -> uuid.UUID:
    with platform_transaction(engines.platform) as s:
        uid = create_user(s, email=email, display_name=email.split("@")[0])
    with auth_transaction(engines.auth) as s:
        if username:
            s.execute(text("UPDATE users SET username = :n WHERE id = :id"), {"n": username, "id": uid})
        if password:
            o = account.set_initial_password(s, settings, uid, password, actor="test")
            assert o.ok, o
    return uid


def join(engines: Engines, tenant_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    with tenant_transaction(engines.app, tenant_id) as s:
        return add_membership(s, user_id=user_id)


def client(settings: Settings, engines: Engines, **kw: Any) -> tuple[TestClient, MemoryMailer]:
    mailer = kw.pop("mailer", None) or MemoryMailer()
    c, _ = make_client(settings, engines, mailer=mailer, **kw)
    return c, mailer


def login(c: TestClient, login: str, password: str = PASSWORT, **kw: Any) -> Any:
    return c.post("/api/v1/auth/login", json={"login": login, "password": password}, **kw)


def set_token(c: TestClient, wert: str) -> None:
    """Cookie so setzen, wie ein Browser es überschreiben würde (gleiche Domain wie der Server-Cookie)."""
    c.cookies.set("ichq_session", wert, domain="testserver.local", path="/")


def token(c: TestClient) -> str | None:
    return c.cookies.get("ichq_session")


def db(engines: Engines, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Als Admin lesen/schreiben (Zeitreisen in Tests). Nie in Produktivcode."""
    with _admin(engines.app.url.database) as c:
        cur = c.execute(sql, params)
        return cur.fetchall() if cur.description else []


def events(engines: Engines, user_id: uuid.UUID | None = None) -> list[str]:
    if user_id is None:
        return [r[0] for r in db(engines, "SELECT event FROM auth_events ORDER BY occurred_at, id")]
    return [r[0] for r in db(engines, "SELECT event FROM auth_events WHERE user_id = %s ORDER BY occurred_at, id",
                             (user_id,))]


def enable_totp(c: TestClient, password: str = PASSWORT) -> tuple[str, list[str]]:
    r = c.post("/api/v1/auth/2fa/setup", json={"password": password})
    assert r.status_code == 200, r.text
    geheimnis = r.json()["secret"]
    r = c.post("/api/v1/auth/2fa/enable", json={"code": totp.code_at(geheimnis, totp.current_step())})
    assert r.status_code == 200, r.text
    return geheimnis, r.json()["recovery_codes"]


def alle_textwerte(engines: Engines) -> str:
    """Alles, was in den Auth-Tabellen steht, als ein großer Text — für die Suche nach Klartext-Geheimnissen."""
    teile = []
    for tab in ("users", "auth_sessions", "password_reset_tokens", "recovery_codes", "login_attempts", "auth_events"):
        for zeile in db(engines, f"SELECT * FROM {tab}"):
            teile.extend(str(v) for v in zeile)
            teile.extend(v.hex() for v in zeile if isinstance(v, (bytes, memoryview)) and not isinstance(v, str))
    return "\n".join(teile)

