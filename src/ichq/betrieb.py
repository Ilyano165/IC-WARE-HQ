"""Betriebsbefehle der CLI: Mail-Status, erneut zustellen, Betreiberwarnung, Betriebsprüfung (ADR-016).

Kein Web-Endpunkt: Betreiberinformationen (Warteschlangen, Fehler, Speicher) erreichen nur, wer Zugriff auf den
Server hat — normale Firmenmitglieder sehen sie nie.
"""
from __future__ import annotations

import json
import socket
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, worker_transaction
from ichq.mail import templates
from ichq.mail.delivery import Provider, build_provider, retry_failed, status_counts
from ichq.mail.outbox import enqueue


def mail_status(engines: Engines) -> int:
    d = status_counts(engines)
    print(" · ".join(f"{k} {v}" for k, v in sorted(d.items())))
    return 1 if d.get("failed", 0) else 0


def mail_retry(engines: Engines, mail_id: str | None) -> int:
    n = retry_failed(engines, uuid.UUID(mail_id) if mail_id else None)
    print(f"erneut eingereiht: {n}")
    return 0


def alert(settings: Settings, engines: Engines, betreff: str, nachricht: str, dedup: str | None,
          provider: Provider | None = None) -> int:
    """Betreiberwarnung an ICHQ_ALERT_EMAIL. Erst über die Outbox (Wiederholung, Dedup); ist die Datenbank weg,
    direkt per SMTP — eine Warnung über einen DB-Ausfall darf nicht an der DB scheitern."""
    if not settings.alert_email:
        print("Fehler: ICHQ_ALERT_EMAIL fehlt — Warnung nicht zustellbar.", file=sys.stderr)
        return 2
    mail = templates.alert(betreff[:120], nachricht[:2000], socket.gethostname())
    try:
        with platform_transaction(engines.platform) as s:
            enqueue(s, kind="alert", to=settings.alert_email, mail=mail,
                    dedup_key=f"alert:{dedup}" if dedup else None)
        print("Warnung eingereiht")
        return 0
    except Exception as e:
        print(f"Outbox nicht erreichbar ({e.__class__.__name__}) — sende direkt", file=sys.stderr)
    provider = provider or build_provider(settings)
    if provider is None:
        print("Fehler: SMTP nicht eingerichtet — Warnung nicht zustellbar.", file=sys.stderr)
        return 2
    try:
        provider.send(settings.alert_email, mail.subject, mail.text, mail.html)
    except Exception as e:
        print(f"Fehler: Direktversand gescheitert ({e.__class__.__name__})", file=sys.stderr)
        return 1
    print("Warnung direkt gesendet")
    return 0


def _alter(sek: Any) -> int:
    return int(sek) if sek is not None else 0


def ops_check(settings: Settings, engines: Engines) -> dict[str, Any]:
    """Zustand der Hintergrundarbeit aus Sicht der Datenbank. Wird von ``deploy/hq check`` ausgewertet."""
    from ichq.documents.scan import ClamdClient
    with worker_transaction(engines.worker) as s:
        outbox = s.execute(text("""SELECT
              count(*) FILTER (WHERE status = 'failed') AS failed,
              extract(epoch FROM now() - min(available_at) FILTER (WHERE status = 'pending'))::int AS pending_age
            FROM outbox_events""")).one()
        mails = s.execute(text("""SELECT
              count(*) FILTER (WHERE status = 'failed') AS failed,
              extract(epoch FROM now() - min(available_at) FILTER (WHERE status = 'pending'))::int AS pending_age
            FROM mail_outbox""")).one()
    with platform_transaction(engines.platform) as s:
        firmen = list(s.scalars(text("SELECT id FROM tenants WHERE status IN ('active','paused')")))
    quarantaene, aeltestes = 0, 0
    for tid in firmen:   # Worker-Rolle sieht Dokumente nur im Mandantenkontext (Migration 0007)
        from ichq.db.session import tenant_transaction
        with tenant_transaction(engines.worker, tid) as s:
            z = s.execute(text("""SELECT count(*) AS n, extract(epoch FROM now() - min(o.created_at))::int AS alt
                                  FROM documents d JOIN objects o ON o.id = d.id AND o.tenant_id = d.tenant_id
                                  WHERE d.scan_status = 'quarantined'""")).one()
            quarantaene += int(z.n)
            aeltestes = max(aeltestes, _alter(z.alt))
    clamd = ClamdClient(settings.clamd_host, settings.clamd_port, timeout=5).ping() if settings.clamd_host else None
    return {"zeit": datetime.now(UTC).isoformat(timespec="seconds"),
            "outbox_failed": int(outbox.failed), "outbox_pending_age_s": _alter(outbox.pending_age),
            "mail_failed": int(mails.failed), "mail_pending_age_s": _alter(mails.pending_age),
            "mail_configured": build_provider(settings) is not None,
            "quarantine": quarantaene, "quarantine_oldest_s": aeltestes, "clamd_ok": clamd}


def print_ops_check(settings: Settings, engines: Engines) -> int:
    print(json.dumps(ops_check(settings, engines)))
    return 0
