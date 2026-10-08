"""Effektive Rechte einer Mitgliedschaft — die EINE Berechnung (ADR-011), bei jeder Anfrage neu.

Reihenfolge (M0 „Rechte", verbindlich); die erste zutreffende Regel entscheidet je Recht:

0. Recht unbekannt / Mitgliedschaft oder Firma nicht aktiv → NEIN   (``decide`` bzw. ``get_principal``)
1. Modul per Feature-Flag aus                               → NEIN   (``feature_disabled``)
2. Einzelrecht DENY                                         → NEIN   (``deny``)
3. Ressourcen-DENY                                          → NEIN   (je Objekt: ``ichq.objects.visibility``)
4. Einzelrecht ALLOW                                        → JA     (``allow``)
5. Ressourcen-ALLOW (Objektfreigabe)                        → JA     (je Objekt: ``ichq.objects.visibility``)
6. Nicht archivierte Rolle der Mitgliedschaft               → JA     (``role``; „Company Admin" hält alle)
7. sonst                                                    → NEIN   (``none``)

Schritte 3 und 5 betreffen einzelne Objekte und stehen deshalb in der Sichtbarkeit; hier wird die Menge der
Rechte berechnet, die für die ganze Firma gelten.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.authz.registry import FLAGGABLE_MODULES, PERMISSIONS, module_of

FEATURE_DISABLED, DENY, ALLOW, ROLE, NONE = "feature_disabled", "deny", "allow", "role", "none"


@dataclass(frozen=True)
class Decision:
    permission: str
    granted: bool
    decided_by: str                      # eine der Konstanten oben
    roles: tuple[str, ...] = ()          # Rollen (public_id), die das Recht enthalten — auch wenn es verboten ist


@dataclass(frozen=True)
class Effective:
    decisions: dict[str, Decision]
    rank: int                                        # höchster Rang der nicht archivierten Rollen, sonst 0
    role_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    disabled_modules: frozenset[str] = field(default_factory=frozenset)

    @property
    def permissions(self) -> frozenset[str]:
        return frozenset(p for p, d in self.decisions.items() if d.granted)


def disabled_modules(session: Session) -> frozenset[str]:
    """Abgeschaltete Fachmodule der aktuellen Firma (RLS). Kernmodule lassen sich nicht abschalten."""
    rows = session.execute(text("SELECT module FROM tenant_feature_flags WHERE NOT enabled")).scalars()
    return frozenset(rows) & FLAGGABLE_MODULES


def effective(session: Session, membership_id: uuid.UUID) -> Effective:
    """Rechte mit Quelle je Recht. Läuft in einer Mandanten-Transaktion (RLS)."""
    aus = disabled_modules(session)
    einzel: dict[str, str] = {r.permission: r.effect for r in session.execute(text(
        "SELECT permission, effect FROM permission_overrides WHERE membership_id = :m"), {"m": membership_id})}
    rollen = session.execute(text("""
        SELECT r.id, r.public_id, r.priority, r.grants_all, rp.permission
        FROM membership_roles mr
        JOIN roles r ON r.id = mr.role_id AND r.tenant_id = mr.tenant_id AND r.archived_at IS NULL
        LEFT JOIN role_permissions rp ON rp.role_id = r.id AND rp.tenant_id = r.tenant_id
        WHERE mr.membership_id = :m"""), {"m": membership_id}).all()
    aus_rollen: dict[str, list[str]] = {}
    rang, ids = 0, set()
    for rid, pub, prio, alle, perm in rollen:
        rang = max(rang, prio)
        ids.add(rid)
        for p in (PERMISSIONS if alle else ({perm} if perm else set())):
            if p in PERMISSIONS and pub not in aus_rollen.setdefault(p, []):
                aus_rollen[p].append(pub)
    entscheidungen = {}
    for p in sorted(PERMISSIONS):
        r = tuple(sorted(aus_rollen.get(p, ())))
        if module_of(p) in aus:
            d = Decision(p, False, FEATURE_DISABLED, r)
        elif einzel.get(p) == "deny":
            d = Decision(p, False, DENY, r)
        elif einzel.get(p) == "allow":
            d = Decision(p, True, ALLOW, r)
        elif r:
            d = Decision(p, True, ROLE, r)
        else:
            d = Decision(p, False, NONE)
        entscheidungen[p] = d
    return Effective(entscheidungen, rang, frozenset(ids), aus)
