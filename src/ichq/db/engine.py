"""Je Datenbankrolle eine eigene Engine. Es gibt keine Engine mit Superuser-Rechten zur Laufzeit."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine

from ichq.core.config import Settings


def _url(roh: str) -> str:
    if roh.startswith("postgresql://"):
        return "postgresql+psycopg://" + roh[len("postgresql://"):]
    return roh


def make_engine(url: str, name: str, pool_size: int = 5, statement_timeout_ms: int = 15_000) -> Engine:
    return create_engine(
        _url(url),
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "application_name": f"ichq-{name}",
            "connect_timeout": 5,
            "options": f"-c statement_timeout={statement_timeout_ms}",
        },
    )


@dataclass(frozen=True)
class Engines:
    app: Engine        # ichq_app — Mandantendaten, nur mit Mandantenkontext
    platform: Engine   # ichq_platform — Firmen, Konten, Plattform-Audit
    worker: Engine     # ichq_worker — Outbox-Verteilung
    auth: Engine       # ichq_auth — Anmeldung, Sitzungen, Passwort-Hashes

    def dispose(self) -> None:
        for e in (self.app, self.platform, self.worker, self.auth):
            e.dispose()


def build_engines(settings: Settings) -> Engines:
    kw = {"pool_size": settings.db_pool_size, "statement_timeout_ms": settings.db_statement_timeout_ms}
    return Engines(
        app=make_engine(settings.database_url.get_secret_value(), "app", **kw),
        platform=make_engine(settings.platform_database_url.get_secret_value(), "platform", **kw),
        worker=make_engine(settings.worker_database_url.get_secret_value(), "worker", **kw),
        auth=make_engine(settings.auth_database_url.get_secret_value(), "auth", **kw),
    )
