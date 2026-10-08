# ADR-011: M4 Rollen & Rechte auf dem C0-Fundament

**Status:** angenommen (M4) · **Grundlage:** M0 „Rechte" (Entscheidungsreihenfolge verbindlich),
`docs/reference/m4-prototyp-rbac.md` (Konzepte und Testszenarien, nicht Code), ADR-009.

## Kontext
Der Prototyp (IC·HQ 2.x) kannte Ressourcen-Freigaben nur für Projekte, Teams und Abteilungen und eine
„Hauptfirma"-Übergangslösung. Im Neubau gibt es seit C0 ein globales Objektmodell mit Objektfreigaben
(`object_grants`) und echter Mandantentrennung; Teams/Abteilungen kommen erst mit M6.

## Entscheidung

### Effektive Rechte — EINE Funktion, bei jeder Anfrage neu berechnet
`ichq.authz.effective.effective_permissions(session, membership_id)` liefert die Rechte **und** ihre Quelle je Recht.
Die M0-Reihenfolge wird so abgebildet:

| M0-Schritt | Umsetzung |
| --- | --- |
| 0 Firma/Mitgliedschaft nicht aktiv, Recht unbekannt → NEIN | `get_principal` (Status), `decide` (Registry) |
| 1 Modul per Feature-Flag aus → NEIN | `tenant_feature_flags` (Modul = Präfix vor dem Punkt); Fehlercode `feature_disabled` |
| 2 Einzelrecht DENY → NEIN | `permission_overrides.effect = 'deny'` |
| 3 Ressourcen-DENY → NEIN | `object_denies` — schlägt auch `objects.read_all`, Freigabe und Erstellerschaft (in `visible_clause`) |
| 4 Einzelrecht ALLOW → JA | `effect = 'allow'` |
| 5 Ressourcen-ALLOW → JA | `object_grants` (ADR-009) |
| 6 Rolle der Mitgliedschaft → JA | nicht archivierte Rollen; die gesperrte Systemrolle „Company Admin" hält **berechnet** alle Rechte der Registry (keine gespeicherte Liste, die veralten kann) |
| 7 sonst → NEIN | — |

Schritte 3 und 5 gelten für **Objekte** (Lesen/Sichtbarkeit). Ressourcen sind damit alle Fachobjekte des
Objektmodells (Projekt, Aufgabe, Dokument …), nicht nur Projekte. Subjekte sind vorerst nur Mitgliedschaften;
Team/Abteilung als Subjekt folgt mit M6.

### Delegationsregeln (aus dem Prototyp übernommen)
Obergrenze (nur vergeben, was man selbst effektiv hat), keine Lücken-Löschung beim Bearbeiten, Duplizieren nur mit
eigenen Rechten, kein Selbstbedienen (eigene Rollen, Einzelrechte, Status), Rang (Rollen verwalten nur mit
kleinerem Rang, vergeben bis zum eigenen Rang), Last-Admin-Schutz in derselben Transaktion. „Admin" = effektiv
`users.deactivate`, `roles.update` und `roles.assign` (vorher in M3 nur `users.deactivate` — vereinheitlicht).

### Plattform
Es gibt keine Plattform-Rechte in der Registry und keinen Plattform-Admin im Mandantenbereich (M0: kein
Generalschlüssel). Feature-Flags setzt nur die Control Plane (Rolle `ichq_platform`, heute per CLI).

### Rollenvorlagen statt CLI-Übergang
Beim Aktivieren einer Firma werden Vorlagen angelegt (idempotent): „Company Admin" (gesperrt, Rang 100),
„Geschäftsführung" (90), „Mitarbeiter" (40), „Steuerberater" (30). Die Vorlagen außer Company Admin sind
**Vorschläge** (Produktvision, Rollen) und frei änderbar. Den ersten Admin setzt die Control Plane
(`ichq tenant-admin` weist die gesperrte Rolle zu) — das ist kein Übergang mehr, sondern Onboarding bis M18.

## Verworfen
- Rechte in der Sitzung speichern: Änderungen wirkten erst nach neuem Login.
- Rechte von Company Admin als gespeicherte Liste mit „Reparatur beim Start": veraltet zwischen Deployment und Start.
- Feature-Flag als Code-Verzweigung: M0 verlangt Daten statt Code.

## Folgen
- Jede Rechteänderung wirkt sofort (nächste Anfrage).
- `permission_overrides`, `object_denies`, `tenant_feature_flags` nach der Mandanten-Checkliste.
- Neues Recht `users.override` (Einzelrechte vergeben) — wie im Prototyp, getrennt von `roles.assign`.

## Umsetzung (Nachtrag)
- Migration `0006_m4_rbac`; Code `ichq.authz.{effective,guard,roles,delegation,templates,flags}`, Doku
  `docs/authorization.md` (Routentabelle aus dem Code, `ichq routes-doc`).
- Tabelle heißt `permission_overrides` statt `membership_permission_overrides`: Die Namenskonvention der
  Fremdschlüssel hätte PostgreSQLs Grenze von 63 Zeichen überschritten. Wer ein Einzelrecht gesetzt hat, steht im
  Mandanten-Audit (keine eigene Spalte).
- Feature-Flags können Kernmodule (`company`, `users`, `roles`, `audit`, `settings`) nicht abschalten — sonst könnte
  sich eine Firma aussperren.
- Ressourcen-DENY sperrt auch die Zuweisung einer Aufgabe an die gesperrte Person (sonst entstünde eine unsichtbare
  Zuständigkeit).
