"""Typ-Registry des globalen Objektmodells (ADR-008).

Ein Objekttyp oder Verknüpfungstyp, der hier nicht steht, existiert nicht. Die Datenbank prüft
dieselben Listen per CHECK — wer hier etwas ergänzt, braucht eine Migration (Test:
``test_core_objects.py::test_registry_und_datenbank_stimmen_ueberein``).
"""
from __future__ import annotations

from dataclasses import dataclass

from ichq.authz.registry import is_known

GROUPS: tuple[str, ...] = ("persons", "companies", "projects", "receipts", "invoices", "tasks", "documents")


@dataclass(frozen=True)
class ObjectType:
    code: str
    label: str
    group: str
    read: str          # Modulrecht zum Lesen
    update: str        # Modulrecht zum Ändern/Verknüpfen
    implemented: bool  # False: Typ reserviert, Fachmodul folgt — die API legt solche Objekte nicht an


_T = ObjectType
OBJECT_TYPES: dict[str, ObjectType] = {t.code: t for t in (
    _T("company", "Firma", "companies", "customers.read", "customers.update", False),
    _T("customer", "Kunde", "companies", "customers.read", "customers.update", False),
    _T("supplier", "Lieferant", "companies", "suppliers.read", "suppliers.update", False),
    _T("employee", "Mitarbeiter", "persons", "users.read", "users.update", False),
    _T("project", "Projekt", "projects", "projects.read", "projects.update", False),
    _T("task", "Aufgabe", "tasks", "tasks.read", "tasks.update", True),
    _T("receipt", "Beleg", "receipts", "finance.read", "finance.update", False),
    _T("invoice", "Rechnung", "invoices", "invoices.read", "invoices.update", False),
    _T("payment", "Zahlung", "invoices", "finance.read", "finance.update", False),
    _T("trip", "Fahrt", "receipts", "vehicles.read", "vehicles.update", False),
    _T("travel", "Reise", "receipts", "travel.read", "travel.update", False),
    _T("entertainment", "Bewirtung", "receipts", "hospitality.read", "hospitality.update", False),
    _T("contract", "Vertrag", "documents", "contracts.read", "contracts.update", False),
    _T("asset", "Anlage", "receipts", "finance.read", "finance.update", False),
    _T("website", "Website", "projects", "projects.read", "projects.update", False),
    _T("document", "Dokument", "documents", "files.read", "files.update", True),
)}

ANY = "*"


@dataclass(frozen=True)
class LinkType:
    code: str
    label: str
    sources: frozenset[str] | str   # ANY oder Menge von Objekttypen
    targets: frozenset[str] | str

    def allows(self, source: str, target: str) -> bool:
        return ((self.sources == ANY or source in self.sources)
                and (self.targets == ANY or target in self.targets))


def _f(*codes: str) -> frozenset[str]:
    return frozenset(codes)


LINK_TYPES: dict[str, LinkType] = {lt.code: lt for lt in (
    LinkType("related", "verknüpft mit", ANY, ANY),
    LinkType("attachment", "Anhang", ANY, _f("document")),
    LinkType("part_of", "gehört zu Projekt", _f("task", "document", "receipt", "invoice", "contract", "website"),
             _f("project")),
    LinkType("billed_to", "berechnet an", _f("invoice"), _f("customer", "company")),
    LinkType("pays", "bezahlt", _f("payment"), _f("invoice", "receipt")),
    LinkType("evidence", "Nachweis für", _f("receipt", "document"),
             _f("trip", "travel", "entertainment", "invoice", "payment", "asset", "contract")),
    LinkType("party", "Vertragspartei", _f("contract"), _f("customer", "supplier", "company", "employee")),
)}


def object_type(code: str) -> ObjectType | None:
    return OBJECT_TYPES.get(code)


def readable_types(permissions: frozenset[str]) -> frozenset[str]:
    return frozenset(t.code for t in OBJECT_TYPES.values() if t.read in permissions)


for _t in OBJECT_TYPES.values():
    assert is_known(_t.read) and is_known(_t.update), f"Objekttyp {_t.code}: unbekanntes Recht"
    assert _t.group in GROUPS, f"Objekttyp {_t.code}: unbekannte Suchgruppe"
for _l in LINK_TYPES.values():
    for _menge in (_l.sources, _l.targets):
        assert _menge == ANY or set(_menge) <= set(OBJECT_TYPES), f"Verknüpfung {_l.code}: unbekannter Typ"
