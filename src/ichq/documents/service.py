"""Dokumente: Upload (Quarantäne), Prüfung („Beleg geprüft"), Liste, Download nur nach Virenprüfung."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import AppError, Conflict, NotFound, ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.documents.models import REVIEW_STATUS, SCAN_STATUS, Document
from ichq.jobs.service import emit_event
from ichq.objects.models import ObjectLink, ObjectRow
from ichq.objects.service import create_object, resolve
from ichq.storage import Storage, object_key

MAX_BYTES = 20 * 1024 * 1024
CONTENT_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "application/xml", "text/xml",
                           "text/plain", "text/csv"})
SORTS = {"created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
         "title": SortKey("title", ObjectRow.title, "text")}


class UnsupportedMediaType(AppError):
    status, code, title = 415, "unsupported_media_type", "Medientyp nicht unterstützt"


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload_too_large", "Anfrage zu groß"


class Quarantined(AppError):
    status, code, title = 409, "document_quarantined", "Dokument noch nicht freigegeben"


def clean_filename(name: str) -> str:
    """Nur zur Anzeige — der Speicherschlüssel enthält nie einen Dateinamen."""
    name = unicodedata.normalize("NFC", name).replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    if not name or len(name) > 255:
        raise ValidationFailed("filename: 1–255 Zeichen")
    return name


def upload(session: Session, storage: Storage, principal: Principal, *, filename: str, content_type: str,
           data: bytes) -> tuple[Document, ObjectRow]:
    typ = content_type.split(";", 1)[0].strip().lower()
    if typ not in CONTENT_TYPES:
        raise UnsupportedMediaType(f"Erlaubt: {', '.join(sorted(CONTENT_TYPES))}")
    if len(data) > MAX_BYTES:
        raise PayloadTooLarge(f"Höchstens {MAX_BYTES // (1024 * 1024)} MiB")
    if not data:
        raise ValidationFailed("Leere Datei")
    name = clean_filename(filename)
    obj = create_object(session, type_="document", title=name, actor_membership_id=principal.membership_id)
    key = object_key(obj.tenant_id, obj.id, 1)
    doc = Document(id=obj.id, tenant_id=obj.tenant_id, filename=name, content_type=typ, size_bytes=len(data),
                   sha256=hashlib.sha256(data).hexdigest(), storage_key=key)
    session.add(doc)
    session.flush()
    # Datei erst nach erfolgreichem Flush schreiben; scheitert der Speicher, rollt die Transaktion zurück.
    storage.put(key, data, typ)
    activity(session, obj.id, "document.uploaded", actor_membership_id=principal.membership_id)
    audit(session, "document.uploaded", actor_membership_id=principal.membership_id, target_type="document",
          target_id=obj.public_id, data={"size": len(data), "sha256": doc.sha256, "content_type": typ})
    emit_event(session, "document.uploaded", {"document_id": str(obj.id)})
    return doc, obj


def get(session: Session, principal: Principal, ref: str) -> tuple[Document, ObjectRow]:
    obj = resolve(session, principal, ref, type_="document")
    doc = session.get(Document, obj.id)
    if doc is None:
        raise NotFound()
    return doc, obj


def review(session: Session, principal: Principal, ref: str, decision: str) -> tuple[Document, ObjectRow]:
    if decision not in REVIEW_STATUS or decision == "pending":
        raise ValidationFailed("decision muss 'approved' oder 'rejected' sein")
    doc, obj = get(session, principal, ref)
    if doc.review_status != "pending":
        raise Conflict("Dokument wurde bereits geprüft")
    jetzt = session.scalar(select(func.now()))      # vor der Änderung: Autoflush darf keinen Halbzustand schreiben
    doc.review_status, doc.reviewed_by_membership_id, doc.reviewed_at = decision, principal.membership_id, jetzt
    session.flush()
    activity(session, obj.id, "document.reviewed", actor_membership_id=principal.membership_id,
             data={"decision": decision})
    audit(session, "document.reviewed", actor_membership_id=principal.membership_id, target_type="document",
          target_id=obj.public_id, data={"decision": decision})
    return doc, obj


def content(session: Session, storage: Storage, principal: Principal, ref: str) -> tuple[Document, bytes]:
    doc, _ = get(session, principal, ref)
    if doc.scan_status != "clean":
        raise Quarantined("Die Datei ist noch nicht auf Schadsoftware geprüft (Quarantäne).")
    return doc, storage.get(doc.storage_key)


@dataclass(frozen=True)
class DocumentFilter:
    review_status: str | None = None
    scan_status: str | None = None
    since: datetime | None = None          # hochgeladen ab
    unlinked: bool = False                 # keinem anderen Objekt zugeordnet (keine Verknüpfung)


def filter_clauses(f: DocumentFilter) -> list[Any]:
    """Filter der Dokumentliste — dieselben nutzt das Dashboard für seine Zahlen."""
    if f.review_status is not None and f.review_status not in REVIEW_STATUS:
        raise ValidationFailed("review_status ist ungültig")
    if f.scan_status is not None and f.scan_status not in SCAN_STATUS:
        raise ValidationFailed("scan_status ist ungültig")
    teile: list[Any] = [ObjectRow.archived_at.is_(None)]
    if f.review_status is not None:
        teile.append(Document.review_status == f.review_status)
    if f.scan_status is not None:
        teile.append(Document.scan_status == f.scan_status)
    if f.since is not None:
        teile.append(ObjectRow.created_at >= f.since)
    if f.unlinked:
        teile.append(~exists().where(ObjectLink.tenant_id == ObjectRow.tenant_id,
                                     or_(ObjectLink.source_id == ObjectRow.id,
                                         ObjectLink.target_id == ObjectRow.id)))
    return teile


def list_documents(session: Session, visible: Any, f: DocumentFilter, *, sort: str, desc: bool,
                   cursor: str | None, limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = (select(Document, ObjectRow)
            .join(ObjectRow, (ObjectRow.id == Document.id) & (ObjectRow.tenant_id == Document.tenant_id))
            .where(visible, *filter_clauses(f)))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
