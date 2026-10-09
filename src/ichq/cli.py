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
    ta = sub.add_parser("tenant-admin", help="Gesperrte Rolle „Company Admin“ zuweisen (Onboarding; legt Vorlagen an)")
    ta.add_argument("--email", required=True)
    ta.add_argument("--tenant", required=True, help="Slug der Firma")
    tf = sub.add_parser("tenant-feature", help="Fachmodul einer Firma an- oder abschalten (Control Plane)")
    tf.add_argument("--tenant", required=True, help="Slug der Firma")
    tf.add_argument("module")
    tf.add_argument("state", choices=["on", "off"])
    tf.add_argument("--reason", required=True)
    ma = sub.add_parser("membership-add", help="Konto einer Firma zuordnen (ohne Rollen)")
    ma.add_argument("--email", required=True)
    ma.add_argument("--tenant", required=True, help="Slug der Firma")
    ns = sub.add_parser("notifications-scan", help="Geplante Benachrichtigungsregeln (z. B. überfällige Aufgaben) "
                                                   "für alle aktiven Firmen ausführen")
    ns.add_argument("--date", help="Stichtag JJJJ-MM-TT (Standard: heute, UTC)")
    ac = sub.add_parser("auth-cleanup", help="Alte Anmeldeversuche, Sitzungen, Reset-Tokens, benutzte Recovery-Codes "
                                             "löschen (auth_events bleiben)")
    ac.add_argument("--days", type=int, default=30, help="Aufbewahrung in Tagen (Standard 30)")
    sub.add_parser("routes-doc", help="Tabelle der geschützten Endpunkte aus dem Code ausgeben (docs/authorization.md)")
    ds = sub.add_parser("documents-scan", help="Dokumente in Quarantäne mit ClamAV prüfen (ICHQ_CLAMD_HOST)")
    ds.add_argument("--loop", type=float, default=0, help="Sekunden zwischen Läufen; 0 = einmal")
    ds.add_argument("--limit", type=int, default=50, help="höchstens so viele Dokumente je Firma und Lauf")
    w = sub.add_parser("worker", help="Outbox-Worker starten (versendet auch E-Mails, wenn SMTP eingerichtet ist)")
    w.add_argument("--once", action="store_true")
    sub.add_parser("mail-status", help="E-Mail-Outbox: Zahl je Status (Exitcode 1 bei fehlgeschlagenen)")
    mr = sub.add_parser("mail-retry", help="Fehlgeschlagene E-Mails erneut zustellen")
    mr.add_argument("--id", help="nur diese Mail (sonst alle fehlgeschlagenen)")
    al = sub.add_parser("alert", help="Betreiberwarnung an ICHQ_ALERT_EMAIL senden")
    al.add_argument("--subject", required=True)
    al.add_argument("--message", required=True)
    al.add_argument("--dedup", help="gleicher Schlüssel ⇒ nur eine Mail")
    sub.add_parser("ops-check", help="Zustand von Outbox, Mail, Virenprüfung als JSON (für deploy/hq check)")
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

    if args.cmd == "routes-doc":
        from ichq.api.routes_doc import render
        from ichq.app import create_app
        print(render(create_app(settings)), end="")
        return 0

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
        if args.cmd == "documents-scan":
            return _virenscan(settings, engines, args.loop, args.limit)
        if args.cmd == "worker":
            from ichq.jobs.worker import run_forever, run_once
            from ichq.mail.delivery import build_provider, dispatch_once
            provider = build_provider(settings)
            if args.once:
                r = run_once(engines)
                mail = dispatch_once(engines, settings, provider) if provider else None
                print(f"abgeholt {r.claimed} · erledigt {r.done} · wird wiederholt {r.retrying} · "
                      f"endgültig gescheitert {r.failed}"
                      + (f" · Mails gesendet {mail.sent} · Mails gescheitert {mail.failed}" if mail else ""))
                return 0 if r.ok and (mail is None or mail.failed == 0) else 1
            if provider is None:
                print("Hinweis: SMTP nicht eingerichtet — E-Mails bleiben in der Outbox.", file=sys.stderr)
            run_forever(engines, nebenher=(lambda: dispatch_once(engines, settings, provider).claimed)
                        if provider else None)
            return 0
        if args.cmd in ("mail-status", "mail-retry", "alert", "ops-check"):
            from ichq import betrieb
            if args.cmd == "mail-status":
                return betrieb.mail_status(engines)
            if args.cmd == "mail-retry":
                return betrieb.mail_retry(engines, args.id)
            if args.cmd == "alert":
                return betrieb.alert(settings, engines, args.subject, args.message, args.dedup)
            return betrieb.print_ops_check(settings, engines)
        if args.cmd.startswith(("user-", "membership-")) or args.cmd == "tenant-admin":
            return _konten(args, settings, engines)
        if args.cmd == "tenant-feature":
            from ichq.authz.flags import set_flag
            tenant = tenancy_lookup(engines, args.tenant)
            with platform_transaction(engines.platform) as s:
                set_flag(s, tenant.id, args.module, args.state == "on", actor=_actor(), reason=args.reason)
            print(f"{tenant.slug}: {args.module} {args.state}")
            return 0
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
        if args.cmd == "tenant-status" and t.status == "active":
            from ichq.authz.templates import install
            from ichq.db.session import tenant_transaction
            with tenant_transaction(engines.app, t.id) as s:
                neu = install(s)
            if neu:
                print("Rollenvorlagen angelegt: " + ", ".join(neu))
        print(f"{t.id}  {t.slug}  {t.status}  {t.name}")
        return 0
    except AppError as e:
        print(f"Fehler ({e.code}): {e.detail}", file=sys.stderr)
        return 1
    finally:
        engines.dispose()


def _virenscan(settings: Any, engines: Any, pause: float, limit: int) -> int:
    """Exitcodes: 0 ok, 1 Firma gescheitert, 2 kein Scanner konfiguriert. Mit --loop endlos (Dienst „scanner")."""
    import time

    from ichq.documents.scan import ClamdClient, scan_pending
    from ichq.storage import build_storage
    if not settings.clamd_host:
        print("Fehler: ICHQ_CLAMD_HOST fehlt — ohne Virenscanner bleiben Dokumente in Quarantäne.", file=sys.stderr)
        return 2
    client, storage = ClamdClient(settings.clamd_host, settings.clamd_port), build_storage(settings)
    while True:
        lauf = scan_pending(engines, storage, client, limit)
        if lauf.clean or lauf.infected or lauf.pending or not pause:
            print(f"sauber {lauf.clean} · infiziert {lauf.infected} · wartend {lauf.pending} · "
                  f"Firmen fehlgeschlagen {len(lauf.failed_tenants)}", flush=True)
        if not pause:
            return 1 if lauf.failed_tenants else 0
        time.sleep(pause)


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
        from ichq.authz.templates import make_company_admin
        tenant = tenancy_lookup(engines, args.tenant)
        with tenant_transaction(engines.app, tenant.id) as s:
            mid = s.execute(text("SELECT id FROM memberships WHERE user_id = :u AND status = 'active'"),
                            {"u": gefunden}).scalar()
            if mid is None:
                print("Fehler (not_found): keine aktive Mitgliedschaft in dieser Firma", file=sys.stderr)
                return 1
            neu = make_company_admin(s, mid)
        print(f"Company Admin → {args.email} @ {tenant.slug}" + ("" if neu else " (war schon zugewiesen)"))
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
