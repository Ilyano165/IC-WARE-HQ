# ADR-008: Globales Objektmodell mit Supertyp-Tabelle `objects`

**Status:** angenommen (C0) · **Grundlage:** M0 „Daten" (zusammengesetzte Fremdschlüssel, RLS), C0-Auftrag Punkt 1 und 7

## Kontext
Kommentare, Aktivitäten, Aufgaben, Benachrichtigungen, Suche und Verknüpfungen müssen auf *beliebige*
Fachobjekte zeigen (Beleg, Rechnung, Fahrt, Vertrag …). Die naheliegende Lösung — `target_type` + `target_id`
als freie Spalten (Rails/Django „generic relations") — hat drei Schwächen, die bei uns existenzbedrohend sind:

1. **Kein Fremdschlüssel.** Die Datenbank kann nicht prüfen, ob das Ziel existiert, ob es den Typ hat und
   — entscheidend — ob es zur **selben Firma** gehört. Mandantenisolation hinge allein am Code.
2. **Kein Typschutz.** Jeder Tippfehler in `target_type` erzeugt still verwaiste Zeilen.
3. **Migrationen.** Umbenennen/Aufteilen eines Typs ist eine Datenmigration ohne Netz.

## Entscheidung
**Supertyp-Tabelle** (Class-Table-Inheritance):

- `objects(tenant_id, id, type, public_id, title, search_text, search_vector, created_by_membership_id, …)`
  ist die eine Identität jedes Fachobjekts. `type` ist per **CHECK** auf die Registry
  (`ichq/objects/registry.py`) beschränkt.
- Jede **Fachtabelle** verwendet dieselbe `id` und verweist mit
  `(tenant_id, id, object_type) → objects(tenant_id, id, type)` darauf; `object_type` ist per CHECK fest
  (`tasks.object_type = 'task'`). Damit garantiert die Datenbank: Eine Aufgabe ist ein Objekt vom Typ `task`
  derselben Firma.
- **Beziehungen** (`comments`, `activities`, `object_links`, `object_grants`, `notifications`,
  `tasks.subject_object_id`) verweisen mit zusammengesetztem Fremdschlüssel `(tenant_id, object_id)`
  auf `objects`. Verknüpfungen tragen zusätzlich die Typen beider Seiten — per Fremdschlüssel abgesichert —
  und eine **CHECK-Regel** erlaubter Kombinationen (`link_rule_sql()`, in der Migration eingefroren).
- **Öffentliche IDs:** `public_id` = 128 Bit Zufall (32 Hex-Zeichen), unabhängig vom Primärschlüssel
  (UUIDv7 enthält einen Zeitstempel). Die API nimmt und liefert ausschließlich `public_id`, auch für
  Mitgliedschaften (`memberships.public_id`, neu). Formfehler werden wie „nicht gefunden" behandelt.
- **Neue Typen** kommen über die Registry + eine Migration, die den CHECK erweitert (Expand). Der Test
  `test_registry_und_datenbank_stimmen_ueberein` bricht, wenn Code und Datenbank auseinanderlaufen.
- Reservierte Typen (`implemented=False`: Kunde, Rechnung, Fahrt …) existieren im Schema, die API legt sie
  aber erst an, wenn ihr Fachmodul gebaut ist.

## Verworfen
- **`target_type` + `target_id` ohne Fremdschlüssel:** siehe Kontext. Mandantenleck nur durch Code verhindert.
- **Je Beziehungsart eine Spalte pro Zieltyp** (`comment.invoice_id`, `comment.task_id`, … mit
  „genau eine ist gesetzt"-CHECK): typsicher, aber jede neue Objektart ändert *alle* Beziehungstabellen.
- **Je Zieltyp eine eigene Kommentar-/Aktivitätstabelle:** vervielfacht Code, Suche und Rechteprüfung.
- **JSONB-Dokumente mit Typfeld:** keine referentielle Integrität, keine zusammengesetzten Schlüssel.

## Folgen
- Jedes Fachmodul legt zuerst ein `objects`-Zeile an (`create_object`) und dann seine Fachzeile — in
  derselben Transaktion. Titel/Suchtext pflegt das Fachmodul in `objects`.
- Objekte werden nicht hart gelöscht (`archived_at`); `DELETE` auf `objects` hat die App-Rolle nicht.
- Die Suche braucht keinen Index pro Modul: ein GIN-Index auf `objects.search_vector`.
- Kosten: ein Join mehr pro Fachabfrage. Bei großen Datenmengen Index `(tenant_id, type, created_at)` prüfen.
