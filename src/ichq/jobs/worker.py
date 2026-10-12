"""Worker: holt fällige Outbox-Einträge und führt Handler im Mandantenkontext der Firma aus.

* Abholen über ``FOR UPDATE SKIP LOCKED`` — mehrere Worker kommen sich nicht in die Quere.
* Handler laufen in ``tenant_transaction`` derselben Firma — mit RLS wie jede Anfrage.
* Fehlschläge: wachsender Abstand (2^Versuch Sekunden), danach ``failed``.
* Hängengebliebene Einträge (``processing`` älter als ``STALE_SECONDS``) werden wieder freigegeben.
* Payloads werden nie geloggt.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.audit.service import record
from ichq.core.logging import redact_text
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction, worker_transaction

log = logging.getLogger("ichq.worker")
STALE_SECONDS = 300


@dataclass(frozen=True)
class Job:
    id: uuid.UUID
    tenant_id: uuid.UUID
    type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class RunResult:
    claimed: int = 0
    done: int = 0
    retrying: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return self.retrying == 0 and self.failed == 0


Handler = Callable[[Session, Job], None]
HANDLERS: dict[str, Handler] = {}


def handler(event_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        if event_type in HANDLERS:
            raise RuntimeError(f"Handler für {event_type} doppelt registriert")
        HANDLERS[event_type] = fn
        return fn
    return deco


@handler("system.ping")
def _ping(session: Session, job: Job) -> None:
    """Beispieljob: beweist, dass der Worker im richtigen Mandantenkontext arbeitet."""
    record(session, "system.ping_processed", target_type="outbox_event", target_id=str(job.id))


def _claim(engines: Engines, limit: int) -> list[Job]:
    with worker_transaction(engines.worker) as s:
        s.execute(text("""UPDATE outbox_events SET status='pending', locked_at=NULL
                          WHERE status='processing' AND locked_at < now() - make_interval(secs => :stale)"""),
                  {"stale": STALE_SECONDS})
        rows = s.execute(text("""
            UPDATE outbox_events SET status='processing', locked_at=now(), attempts=attempts+1
            WHERE id IN (SELECT id FROM outbox_events
                         WHERE status='pending' AND available_at <= now()
                         ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT :n)
            RETURNING id, tenant_id, type, payload, attempts, max_attempts"""), {"n": limit}).all()
    return [Job(r.id, r.tenant_id, r.type, r.payload, r.attempts, r.max_attempts) for r in rows]


def _abschliessen(engines: Engines, job: Job, fehler: str | None) -> str:
    with worker_transaction(engines.worker) as s:
        if fehler is None:
            s.execute(text("UPDATE outbox_events SET status='done', processed_at=now(), locked_at=NULL, "
                           "last_error=NULL WHERE id=:id"), {"id": job.id})
            return "done"
        endgueltig = job.attempts >= job.max_attempts
        s.execute(text("""UPDATE outbox_events SET status=:st, locked_at=NULL, last_error=:err,
                          available_at = now() + make_interval(secs => :wait)
                          WHERE id=:id"""),
                  {"st": "failed" if endgueltig else "pending", "err": redact_text(fehler)[:500],
                   "wait": min(2 ** job.attempts, 3600), "id": job.id})
    return "failed" if endgueltig else "retrying"


def run_once(engines: Engines, limit: int = 20) -> RunResult:
    """Einen Durchgang verarbeiten und ehrlich berichten, was daraus wurde."""
    jobs = _claim(engines, limit)
    zaehler = {"done": 0, "retrying": 0, "failed": 0}
    for job in jobs:
        fn = HANDLERS.get(job.type)
        if fn is None:
            zaehler[_abschliessen(engines, job, f"Kein Handler für {job.type}")] += 1
            log.warning("outbox_ohne_handler", extra={"job_id": str(job.id), "event_type": job.type})
            continue
        try:
            with tenant_transaction(engines.app, job.tenant_id) as s:
                fn(s, job)
        except Exception as e:
            zaehler[_abschliessen(engines, job, f"{e.__class__.__name__}: {e}")] += 1
            log.exception("outbox_fehler", extra={"job_id": str(job.id), "event_type": job.type,
                                                   "attempt": job.attempts})
        else:
            zaehler[_abschliessen(engines, job, None)] += 1
            log.info("outbox_erledigt", extra={"job_id": str(job.id), "event_type": job.type})
    return RunResult(claimed=len(jobs), **zaehler)


def run_forever(engines: Engines, poll_seconds: float = 1.0,
                nebenher: Callable[[], int] | None = None) -> None:  # pragma: no cover - Endlosschleife
    """``nebenher``: weitere Arbeit je Runde (Mailversand), gibt die Zahl erledigter Einträge zurück."""
    log.info("worker_gestartet")
    while True:
        arbeit = run_once(engines).claimed
        if nebenher is not None:
            try:
                arbeit += nebenher()
            except Exception as e:   # Mailversand darf die Outbox-Verarbeitung nie anhalten
                log.error("worker_nebenarbeit_fehler", extra={"exc_type": e.__class__.__name__})
        heartbeat()
        if arbeit == 0:
            time.sleep(poll_seconds)


HEARTBEAT = "/tmp/ichq-worker.heartbeat"   # noqa: S108 — nur Lebenszeichen für den Container-Healthcheck


def heartbeat(pfad: str = HEARTBEAT) -> None:
    try:
        with open(pfad, "w") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass
