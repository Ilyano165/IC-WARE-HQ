# ADR-021: Unternehmensverwaltung in der Oberfläche (Betreiber, Ersteinrichtung mit Einmalcode)

**Status:** angenommen (16.11.2026) · ergänzt ADR-011 (Rechte), ADR-015 (Betrieb), ADR-018 (Server auf Windows)

## Kontext

Bisher entsteht eine Firma nur über die Linux-Konsole: `hq setup-admin` (auf Windows: Startmenü „Erste Firma
anlegen“ → Konsole) ruft sieben CLI-Schritte hintereinander auf (Ablauf: `docs/unternehmensverwaltung.md`). Das ist
für den normalen Betrieb ungeeignet: Tippfehler brechen mitten im Ablauf ab, es bleiben Halbzustände, und jede
weitere Firma braucht wieder die Konsole. Der M0-Bericht kennt bewusst **keine Plattform-Rechte** in der Anwendung
(„Plattform-Rechte gibt es nicht“, M4) — die Verwaltung von Firmen lag ausschließlich beim Server-Zugang.

## Entscheidungen

1. **Betreiber der Installation** (`platform_operators`) sind Konten, die Firmen verwalten dürfen — sonst nichts.
   Die Eigenschaft ist **kein Recht im Sinne von `ichq.authz`**: sie gibt keinen Zugriff auf Daten einer Firma. Wer
   in einer Firma arbeiten will, braucht dort eine Mitgliedschaft mit Rolle wie jeder andere.
2. **Eigene Sicherheitsmarke `operator()`**: volle Sitzung + Eintrag in `platform_operators`, bei **jeder** Anfrage
   aus der Datenbank geprüft (nichts in der Sitzung). Entzug wirkt sofort.
3. **Ersteinrichtung mit Einmalcode.** Solange es keinen Betreiber gibt, stellt `ichq setup-code` (nur am Server)
   einen Code aus: 24 Stunden gültig, nur als SHA-256 gespeichert, ein neuer Code entwertet ältere, nach der
   Einrichtung gibt es keinen neuen. `POST /api/v1/setup` (öffentlich) löst ihn ein und legt in einem Zug Betreiber,
   erste Firma und Administrator an. Falscher, abgelaufener, verbrauchter Code → dieselbe Antwort 403.
   Ohne Code ist die Route wertlos — eine frisch ins Netz gestellte Installation kann nicht von Fremden übernommen werden.
4. **Erst prüfen, dann schreiben.** Kürzel, Zeitzone, Module, Passwortregeln und Konto werden vollständig geprüft,
   bevor die erste Zeile entsteht. Technisch bleiben es drei Transaktionen (Plattform → Auth → Mandant), weil keine
   DB-Rolle alles darf; die Reihenfolge ist so gewählt, dass ein Abbruch höchstens eine Firma im Zustand `pending`
   hinterlässt, die in der Liste sichtbar ist — nie eine aktive Firma ohne Administrator.
5. **Nach außen Kürzel und E-Mail**, keine internen IDs. Das Kürzel ist nach dem Anlegen unveränderlich.
6. **Deaktivieren statt Löschen.** Die Oberfläche kennt Pausieren, Sperren, Deaktivieren (endgültig), jeweils mit
   Begründung im Plattform-Audit. Löschen von Firmendaten bleibt ein eigener, noch nicht gebauter Vorgang
   (Aufbewahrungsfristen).
7. **Letzter Betreiber** kann nicht entfernt werden (Sperre + Prüfung in einer Transaktion).
8. Die CLI-Befehle bleiben als Notweg (`ichq operator-add`, `tenant-*`), sind aber nicht mehr der Normalweg.

## Abweichung vom M0-Bericht / M4

„Plattform-Rechte gibt es nicht“ gilt weiter für `ichq.authz`. Neu ist eine **getrennte** Betreiber-Eigenschaft mit
eigener Tabelle, eigener Marke und eigener DB-Rolle (`ichq_platform`); `ichq_app` hat keinerlei Zugriff auf die
beiden neuen Tabellen.

## Folgen

- Wer Betreiber ist, kann jeder Firma einen Administrator zuweisen — auch sich selbst — und kommt so an deren Daten.
  Das war mit Server-Zugang schon immer so; neu ist, dass es über die Weboberfläche geht. Deshalb: jede Zuweisung im
  Plattform-Audit, Betreiber-Konten brauchen 2FA (Empfehlung; erzwungen wird sie noch **nicht**).
- Die Tabellen sind nicht mandantenbezogen (keine `tenant_id`); die Dreifach-Regel greift hier nicht. Stattdessen:
  RLS mit FORCE, Policy nur für `ichq_platform`.

## Geprüft durch

`tests/test_control.py` (Ersteinrichtung, Code-Verfall, Verwaltung, 401/403 für jede `/platform`-Route, DB-Rechte,
letzter Betreiber); Mutationen `mutation_control` in `scripts/mutation-check.sh`.
