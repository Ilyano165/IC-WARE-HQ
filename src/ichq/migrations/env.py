"""Alembic-Umgebung. Verbindung kommt aus ICHQ_MIGRATION_DATABASE_URL (oder _FILE)."""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from ichq.core.config import read_secret_env
from ichq.db.base import Base
from ichq.models import assert_complete

assert_complete()

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("url") or read_secret_env("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("ICHQ_MIGRATION_DATABASE_URL (oder _FILE) fehlt.")
    return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool,
                           connect_args={"application_name": "ichq-migration"})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
