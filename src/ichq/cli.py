"""Kommandozeile: Konfiguration prüfen, Migrationen, Firmen verwalten, Worker und Server starten.

Firmen anlegen geht in M1 nur hier (Control-Plane-Oberfläche folgt in M17).
"""
from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config

from ichq.core.config import ConfigError, get_settings, read_secret_env
from ichq.core.errors import AppError
from ichq.models import assert_complete

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def _alembic(url: str | None = None) -> Config:
    cfg = Config(str(MIGRATIONS / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    url = url or read_secret_env("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("ICHQ_MIGRATION_DATABASE_URL (oder _FILE) fehlt.")
    cfg.attributes["url"] = url
    return cfg


def _actor() -> str:
    return f"cli:{getpass.getuser()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ichq", description="IC WARE HQ")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config", help="Konfiguration prüfen (gibt keine Geheimnisse aus)")
    m = sub.add_parser("migrate", help="Datenbank auf neuesten Stand bringen")
    m.add_argument("revision", nargs="?", default="head")
    d = sub.add_parser("downgrade", help="Migration zurückrollen")
    d.add_argument("revision")
    tc = sub.add_parser("tenant-create", help="Firma anlegen (Status pending)")
    tc.add_argument("--name", required=True)
    tc.add_argument("--slug", required=True)
    tc.add_argument("--legal-name")
    ts = sub.add_parser("tenant-show", help="Firma nachschlagen")
    ts.add_argument("ref", help="ID oder Slug")
    st = sub.add_parser("tenant-status", help="Status ändern")
    st.add_argument("tenant_id", type=uuid.UUID)
    st.add_argument("status")
    st.add_argument("--reason", required=True)
    uc = sub.add_parser("user-create", help="Konto anlegen (Status pending, ohne Passwort)")
    uc.add_argument("--email", required=True)
    uc.add_argument("--name", required=True)
    uc.add_argument("--username")
    up = sub.add_parser("user-set-password", help="Passwort setzen — wird abgefragt, nie als Argument")
    up.add_argument("--email", required=True)
    up.add_argument("--password-stdin", action="store_true", help="Passwort aus stdin lesen (für Skripte)")
    us = sub.add_parser("user-status", help="Kontostatus ändern; beendet bei Sperre alle Sitzungen")
    us.add_argument("--email", required=True)
    us.add_argument("status", choices=["active", "locked", "suspended", "deactivated", "pending"])
    us.add_argument("--reason", required=True)
    ta = sub.add_parser("tenant-admin", help="ÜBERGANG bis M4: Rolle „Company Admin“ (alle Rechte) zuweisen")
    ta.add_argument("--email", required=True)
    ta.add_argument("--tenant", required=True, help="Slug der Firma")
    ma = sub.add_parser("membership-add", help="Konto einer Firma zuordnen (ohne Rollen — Rechte kommen aus M4)")
    ma.add_argument("--email", required=True)
    ma.add_argument("--tenant", required=True, help="Slug der Firma")
    ns = sub.add_parser("notifications-scan", help="Geplante Benachrichtigungsregeln (z. B. überfällige Aufgaben) "
                                                   "für alle aktiven Firmen ausführen")
    ns.add_argument("--date", help="Stichtag JJJJ-MM-TT (Standard: heute, UTC)")
    ac = sub.add_parser("auth-cleanup", help="Alte Anmeldeversuche, Sitzungen, Reset-Tokens, benutzte Recovery-Codes "
                                             "löschen (auth_events bleiben)")
    ac.add_argument("--days", type=int, default=30, help="Aufbewahrung in Tagen (Standard 30)")
    w = sub.add_parser("worker", help="Outbox-Worker starten")
    w.add_argument("--once", action="store_true")
    sv = sub.add_parser("serve", help="API-Server starten (Produktion: hinter Reverse Proxy)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--workers", type=int, default=2)
    args = ap.parse_args(argv)
    assert_complete()

    if args.cmd == "migrate":
        command.upgrade(_alembic(), args.revision)
        return 0
    if args.cmd == "downgrade":
        command.downgrade(_alembic(), args.revision)
        return 0

    try:
        settings = get_settings()
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2

    if args.cmd == "check-config":
        print(f"Konfiguration gültig · env={settings.env} · storage={settings.storage_backend} · "
              f"log={settings.log_format}")
        return 0

    from ichq.core.logging import configure_logging
    configure_logging(settings.log_level, settings.log_format)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("ichq.asgi:app", host=args.host, port=args.port, workers=args.workers,
                    access_log=False, proxy_headers=True, forwarded_allow_ips=settings.trusted_proxies,
                    server_header=False)
        return 0

    from ichq.db.engine import build_engines
    from ichq.db.session import platform_transaction
    from ichq.tenancy import service as tenancy

    engines = build_engines(settings)
    try:
        if args.cmd in ("worker", "notifications-scan"):
            # Handler der Core-Plattform laden; fehlt einer, startet der Worker nicht (wie assert_complete)
            from ichq.notifications.handlers import assert_handlers
            assert_handlers()
        if args.cmd == "notifications-scan":
            return _scan(engines, args.date)
        if args.cmd == "auth-cleanup":
            from ichq.auth.cleanup import run_cleanup
            bericht = run_cleanup(engines, args.days)
            if bericht.skipped:
                print("übersprungen: ein anderer Aufräumlauf ist aktiv")
                return 0
            print(" · ".join(f"{k} {v}" for k, v in bericht.deleted.items()))
            return 0
        if args.cmd == "worker":
            from ichq.jobs.worker import run_forever, run_once
            if args.once:
                r = run_once(engines)
                print(f"abgeholt {r.claimed} · erledigt {r.done} · wird wiederholt {r.retrying} · "
                      f"endgültig gescheitert {r.failed}")
                return 0 if r.ok else 1
            else:
                run_forever(engines)
            return 0
        if args.cmd.startswith(("user-", "membership-")) or args.cmd == "tenant-admin":
            return _konten(args, settings, engines)
        with platform_transaction(engines.platform) as s:
            if args.cmd == "tenant-create":
                t = tenancy.create_tenant(s, name=args.name, slug=args.slug, legal_name=args.legal_name,
                                          actor=_actor())
            elif args.cmd == "tenant-show":
                try:
                    t = tenancy.get_tenant(s, uuid.UUID(args.ref))
                except ValueError:
                    t = tenancy.get_tenant_by_slug(s, args.ref)
            else:
                t = tenancy.set_status(s, args.tenant_id, args.status, actor=_actor(), reason=args.reason)
        print(f"{t.id}  {t.slug}  {t.status}  {t.name}")
        return 0
    except AppError as e:
        print(f"Fehler ({e.code}): {e.detail}", file=sys.stderr)
        return 1
    finally:
        engines.dispose()


def _scan(engines: Any, stichtag: str | None) -> int:
    """Einstiegspunkt für systemd-Timer/Cron. Exitcodes: 0 ok oder übersprungen (läuft schon), 1 Firma gescheitert."""
    from datetime import UTC, date, datetime

    from ichq.notifications.jobs import run_scan

    heute = date.fromisoformat(stichtag) if stichtag else datetime.now(UTC).date()
    r = run_scan(engines, heute)
    if r.skipped:
        print("übersprungen: ein anderer Scan läuft bereits")
        return 0
    print(f"firmen {r.tenants} · zugestellt {r.delivered} · fehlgeschlagen {len(r.failed)}")
    return 0 if r.ok else 1


def tenancy_lookup(engines: Any, slug: str) -> Any:
    from ichq.db.session import platform_transaction
    from ichq.tenancy import service as tenancy
    with platform_transaction(engines.platform) as s:
        return tenancy.get_tenant_by_slug(s, slug)


def _passwort_lesen(stdin: bool) -> str:
    if stdin:
        return sys.stdin.readline().rstrip("\n")
    eins = getpass.getpass("Neues Passwort: ")
    if eins != getpass.getpass("Wiederholen:   "):
        raise SystemExit("Die Eingaben stimmen nicht überein.")
    return eins


def _konten(args: argparse.Namespace, settings: Any, engines: Any) -> int:
    from sqlalchemy import text

    from ichq.auth import account
    from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
    from ichq.identity.service import add_membership, create_user
    from ichq.tenancy import service as tenancy

    if args.cmd == "user-create":
        with platform_transaction(engines.platform) as s:
            uid = create_user(s, email=args.email, display_name=args.name)
        if args.username:   # Benutzername schreibt nur die Auth-Rolle (Spaltenrechte)
            with auth_transaction(engines.auth) as s:
                s.execute(text("UPDATE users SET username = :n WHERE id = :id"),
                          {"n": args.username.strip().lower(), "id": uid})
        print(f"{uid}  {args.email}  pending")
        return 0

    with platform_transaction(engines.platform) as s:
        gefunden = s.execute(text("SELECT id FROM users WHERE lower(email) = lower(:e)"), {"e": args.email}).scalar()
        tenant = tenancy.get_tenant_by_slug(s, args.tenant) if args.cmd == "membership-add" else None
    if gefunden is None:
        print("Fehler (not_found): Konto nicht gefunden", file=sys.stderr)
        return 1
    if args.cmd == "tenant-admin":
        from ichq.authz.service import ensure_company_admin
        tenant = tenancy_lookup(engines, args.tenant)
        with tenant_transaction(engines.app, tenant.id) as s:
            mid = s.execute(text("SELECT id FROM memberships WHERE user_id = :u AND status = 'active'"),
                            {"u": gefunden}).scalar()
            if mid is None:
                print("Fehler (not_found): keine aktive Mitgliedschaft in dieser Firma", file=sys.stderr)
                return 1
            ensure_company_admin(s, mid)
        print(f"Company Admin (Übergang bis M4) → {args.email} @ {tenant.slug}")
        return 0
    if tenant is not None:
        with tenant_transaction(engines.app, tenant.id) as s:
            mid = add_membership(s, user_id=gefunden)
        print(f"{mid}  {args.email} → {tenant.slug}")
        return 0
    with auth_transaction(engines.auth) as s:
        if args.cmd == "user-set-password":
            o = account.set_initial_password(s, settings, gefunden, _passwort_lesen(args.password_stdin),
                                             actor=_actor())
        else:
            o = account.set_status(s, gefunden, args.status, actor=_actor(), reason=args.reason)
    if not o.ok:
        print(f"Fehler ({o.error}): {o.data.get('message', '')}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
