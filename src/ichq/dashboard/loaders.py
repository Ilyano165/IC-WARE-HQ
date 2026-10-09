"""Loader der verfügbaren Widgets. Regeln:

* Zahlen kommen aus EINER Aggregat-Abfrage je Widget mit denselben Filterbedingungen wie die verlinkte Liste
  (``tasks.service.filter_clauses``, ``documents.service.filter_clauses``, ``comments.questions``) — Wert = Liste.
* Sichtbarkeit nur über ``visible_clause`` bzw. die Listen-Services; Einträge höchstens ``N`` Stück (``LIMIT``).
* Keine Zahl ohne Datenquelle: Was nicht abfragbar ist, steht nicht da.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, text

from ichq.activity.service import VERBS, FeedFilter, feed
from ichq.authz.guard import admins
from ichq.authz.service import Principal, decide
from ichq.comments import questions
from ichq.comments.models import Comment
from ichq.dashboard.registry import Context, Data, Item, Metric, register
from ichq.documents.models import Document
from ichq.documents.service import DocumentFilter
from ichq.documents.service import filter_clauses as doc_filter
from ichq.notifications.service import list_for, unread_count
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import visible_clause
from ichq.tasks.models import Task
from ichq.tasks.service import TaskFilter
from ichq.tasks.service import filter_clauses as task_filter

N = 6
OFFEN = ("open", "in_progress", "blocked")
WICHTIG = frozenset({"comment.question", "task.overdue", "document.review_pending"})
STATUS = {"open": "offen", "in_progress": "in Arbeit", "blocked": "blockiert", "done": "erledigt",
          "cancelled": "abgebrochen"}
PRIO = {"low": "niedrig", "normal": "normal", "high": "hoch", "urgent": "dringend"}
ART = {"comment.question": "Rückfrage", "comment.mention": "Erwähnung", "task.assigned": "Zuweisung",
       "task.overdue": "Überfällig", "document.review_pending": "Prüfung offen"}


def _zaehle(s: Any, basis: Any, bedingungen: dict[str, list[Any]]) -> dict[str, int]:
    """Mehrere Zahlen in EINER Abfrage: count(*) FILTER (WHERE …) je Kennzahl."""
    spalten = [func.count().filter(and_(*b)).label(k) for k, b in bedingungen.items()]
    zeile = s.execute(basis.with_only_columns(*spalten).order_by(None)).one()
    return {k: int(getattr(zeile, k) or 0) for k in bedingungen}


def _aufgaben_basis(p: Principal) -> Any:
    return (select(Task.id).join(ObjectRow, (ObjectRow.id == Task.id) & (ObjectRow.tenant_id == Task.tenant_id))
            .where(visible_clause(p)))


def _aufgabe(t: Task, o: ObjectRow, ctx: Context) -> Item:
    ueber = t.due_date is not None and t.due_date < ctx.today
    return Item(o.public_id, "task", o.title,
                detail=f"{STATUS.get(t.status, t.status)} · {PRIO.get(t.priority, t.priority)}",
                date=t.due_date.isoformat() if t.due_date else None, tone="danger" if ueber else "neutral")


def _aufgaben_liste(s: Any, p: Principal, f: TaskFilter, ctx: Context) -> tuple[Item, ...]:
    stmt = (select(Task, ObjectRow).join(ObjectRow, (ObjectRow.id == Task.id) & (ObjectRow.tenant_id == Task.tenant_id))
            .where(visible_clause(p), *task_filter(f))
            .order_by(Task.due_date.asc().nulls_last(), Task.priority.desc(), ObjectRow.created_at.desc()).limit(N))
    return tuple(_aufgabe(t, o, ctx) for t, o in s.execute(stmt).all())


@register("my_tasks", "Meine Aufgaben", ("tasks.read",))
def my_tasks(s: Any, p: Principal, ctx: Context) -> Data:
    mein = {"assignee": "me", "status": list(OFFEN)}
    f = {"open": TaskFilter(status=OFFEN, assignee_membership_id=p.membership_id),
         "overdue": TaskFilter(status=OFFEN, assignee_membership_id=p.membership_id, due_before=ctx.today),
         "urgent": TaskFilter(status=OFFEN, assignee_membership_id=p.membership_id, priority=("high", "urgent"))}
    z = _zaehle(s, _aufgaben_basis(p), {k: task_filter(v) for k, v in f.items()})
    return Data("tasks", (
        Metric("open", "Offen", z["open"], mein),
        Metric("overdue", "Überfällig", z["overdue"], {**mein, "due_before": ctx.today.isoformat()},
               "danger" if z["overdue"] else "neutral"),
        Metric("urgent", "Hoch/dringend", z["urgent"], {**mein, "priority": ["high", "urgent"]},
               "warn" if z["urgent"] else "neutral")),
        _aufgaben_liste(s, p, f["open"], ctx), "Keine offenen Aufgaben.")


@register("team_tasks", "Aufgaben der Firma", ("tasks.read", "objects.read_all"))
def team_tasks(s: Any, p: Principal, ctx: Context) -> Data:
    offen = {"status": list(OFFEN)}
    f = {"open": TaskFilter(status=OFFEN), "overdue": TaskFilter(status=OFFEN, due_before=ctx.today),
         "unassigned": TaskFilter(status=OFFEN, unassigned=True)}
    z = _zaehle(s, _aufgaben_basis(p), {k: task_filter(v) for k, v in f.items()})
    return Data("tasks", (
        Metric("open", "Offen", z["open"], offen),
        Metric("overdue", "Überfällig", z["overdue"], {**offen, "due_before": ctx.today.isoformat()},
               "danger" if z["overdue"] else "neutral"),
        Metric("unassigned", "Ohne Zuständige", z["unassigned"], {**offen, "assignee": "none"},
               "warn" if z["unassigned"] else "neutral")),
        _aufgaben_liste(s, p, f["overdue"], ctx), "Keine überfälligen Aufgaben.")


@register("questions", "Offene Rückfragen", ("comments.read",))
def open_questions(s: Any, p: Principal, ctx: Context) -> Data:
    basis = questions.base(p, open_only=True)
    zahl = int(s.scalar(basis.with_only_columns(func.count()).order_by(None)) or 0)
    zeilen = s.execute(basis.order_by(Comment.created_at.desc()).limit(N)).all()
    return Data("questions", (Metric("open", "Offen", zahl, {"open_only": True}, "warn" if zahl else "neutral"),),
                tuple(Item(o.public_id, o.type, o.title, detail=(c.body or "")[:120], date=c.created_at.isoformat())
                      for c, o in zeilen), "Keine offenen Rückfragen.")


@register("notifications", "Mitteilungen", ())
def notifications(s: Any, p: Principal, ctx: Context) -> Data:
    zahl = unread_count(s, p)
    zeilen, _ = list_for(s, p, unread_only=True, cursor=None, limit=N)
    return Data("notifications", (Metric("unread", "Ungelesen", zahl, {}, "warn" if zahl else "neutral"),),
                tuple(Item(pid, typ, n.title, detail=ART.get(n.kind, n.kind), date=n.created_at.isoformat(),
                           tone="warn" if n.kind in WICHTIG else "neutral") for n, pid, typ, *_ in zeilen),
                "Nichts Neues.")


@register("documents", "Dokumente & Belege", ("files.read",))
def documents(s: Any, p: Principal, ctx: Context) -> Data:
    seit = datetime.combine(ctx.today - timedelta(days=7), datetime.min.time(), UTC)
    f = {"pending": DocumentFilter(review_status="pending"), "quarantined": DocumentFilter(scan_status="quarantined"),
         "unlinked": DocumentFilter(unlinked=True), "new": DocumentFilter(since=seit)}
    basis = (select(Document.id).join(ObjectRow, (ObjectRow.id == Document.id)
                                      & (ObjectRow.tenant_id == Document.tenant_id)).where(visible_clause(p)))
    z = _zaehle(s, basis, {k: doc_filter(v) for k, v in f.items()})
    zeilen = s.execute(select(Document, ObjectRow).join(
        ObjectRow, (ObjectRow.id == Document.id) & (ObjectRow.tenant_id == Document.tenant_id))
        .where(visible_clause(p), *doc_filter(f["pending"])).order_by(ObjectRow.created_at.desc()).limit(N)).all()
    return Data("documents", (
        Metric("pending", "Ungeprüft", z["pending"], {"review_status": "pending"},
               "warn" if z["pending"] else "neutral"),
        Metric("new", "Neu (7 Tage)", z["new"], {"since": seit.isoformat()}),
        Metric("unlinked", "Nicht zugeordnet", z["unlinked"], {"unlinked": True}),
        Metric("quarantined", "In Virenprüfung", z["quarantined"], {"scan_status": "quarantined"})),
        tuple(Item(o.public_id, "document", o.title, detail=d.filename, date=o.created_at.isoformat())
              for d, o in zeilen), "Keine ungeprüften Dokumente.")


@register("activity", "Aktivität", ("activity.read",), size="l")
def activity(s: Any, p: Principal, ctx: Context) -> Data:
    zeilen, _ = feed(s, p, FeedFilter(), cursor=None, limit=8)
    return Data("activities", (), tuple(Item(pid, typ, titel, detail=VERBS.get(a.verb, a.verb),
                                             date=a.occurred_at.isoformat()) for a, pid, typ, titel, *_ in zeilen),
                "Noch keine Aktivität.")


@register("company", "Firma & Team", ("users.read",), size="s")
def company(s: Any, p: Principal, ctx: Context) -> Data:
    z = s.execute(text("""SELECT (SELECT count(*) FROM memberships WHERE status = 'active') AS aktiv,
        (SELECT count(*) FROM invitations WHERE accepted_at IS NULL AND revoked_at IS NULL) AS einladungen""")).one()
    kennzahlen = [Metric("members", "Aktive Mitglieder", int(z.aktiv), {"status": "active"}),
                  Metric("invitations", "Offene Einladungen", int(z.einladungen), {}, linked=False)]
    if decide(p, "roles.read"):
        n = len(admins(s))
        kennzahlen.append(Metric("admins", "Mit Verwaltungsrechten", n, {}, "warn" if n <= 1 else "neutral",
                                 linked=False))
    return Data("members", tuple(kennzahlen), (), "")


@register("warnings", "Hinweise", ())
def warnings(s: Any, p: Principal, ctx: Context) -> Data:
    """Nur aus vorhandenen Daten ableitbare Warnungen, jede mit Liste dahinter."""
    eintraege: list[Item] = []
    if ctx.tenant_status == "paused":
        eintraege.append(Item(None, None, "Die Firma ist pausiert — nur Lesen ist möglich.", tone="danger"))
    if decide(p, "tasks.read"):
        n = _zaehle(s, _aufgaben_basis(p), {"n": task_filter(TaskFilter(
            status=OFFEN, assignee_membership_id=p.membership_id, due_before=ctx.today))})["n"]
        if n:
            eintraege.append(Item(None, None, f"{n} eigene Aufgabe(n) überfällig", tone="danger", list="tasks",
                                  filter={"assignee": "me", "status": list(OFFEN),
                                          "due_before": ctx.today.isoformat()}))
    if decide(p, "files.read"):
        basis = (select(Document.id).join(ObjectRow, (ObjectRow.id == Document.id)
                                          & (ObjectRow.tenant_id == Document.tenant_id)).where(visible_clause(p)))
        n = _zaehle(s, basis, {"n": doc_filter(DocumentFilter(scan_status="infected"))})["n"]
        if n:
            eintraege.append(Item(None, None, f"{n} Dokument(e) wegen Schadsoftware gesperrt", tone="danger",
                                  list="documents", filter={"scan_status": "infected"}))
    if decide(p, "users.read") and decide(p, "roles.read") and len(admins(s)) <= 1:
        eintraege.append(Item(None, None, "Nur eine Person hat Verwaltungsrechte — Vertretung einrichten.",
                              tone="warn", list="members"))
    return Data(None, (), tuple(eintraege), "Keine Hinweise.")
