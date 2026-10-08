from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped

SCAN_STATUS = ("quarantined", "clean", "infected")
REVIEW_STATUS = ("pending", "approved", "rejected")


class Document(TenantScoped, Base):
    """Fachtabelle zum Objekttyp ``document``. Inhalt im Speicher unter ``t/<tenant>/f/<id>/v/<n>``.

    Neue Dateien sind ``quarantined`` (M0: bis zur Prüfung kein Download). Einen Virenscanner gibt es
    noch nicht — deshalb bleibt jede hochgeladene Datei vorerst in Quarantäne.
    """

    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="document")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    scan_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="quarantined")
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    reviewed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                             ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "reviewed_by_membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="RESTRICT"),
        CheckConstraint("object_type = 'document'", name="object_type_document"),
        CheckConstraint("scan_status IN ('quarantined','clean','infected')", name="scan_status_valid"),
        CheckConstraint("review_status IN ('pending','approved','rejected')", name="review_status_valid"),
        CheckConstraint("size_bytes >= 0", name="size_positive"),
        CheckConstraint(r"sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
        CheckConstraint("(review_status = 'pending') = (reviewed_at IS NULL)", name="review_consistent"),
    )
