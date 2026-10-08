# M4 · Rollen & Rechte — Statusbericht (08.10.2026)

Grundlage: Prompt-Abschnitt 4 (`docs/claude-code-prompts.md`), M0 „Rechte", ADR-011, Prototyp-Konzepte
(`docs/reference/m4-prototyp-rbac.md` — Konzepte und Szenarien übernommen, kein Code, keine „Hauptfirma").
Ausführlich: `docs/authorization.md`.

## Implemented
| Auftrag | Umsetzung |
| --- | --- |
| 1 Rollen-CRUD, Vorlagen, gesperrter Company Admin | `ichq.authz.roles` (anlegen, bearbeiten, duplizieren, archivieren, wiederherstellen, löschen nur archiviert + unbenutzt); `ichq.authz.templates` (Company Admin 100 gesperrt, Geschäftsführung 90, Mitarbeiter 40, Steuerberater 30); Rechte von Company Admin **berechnet**, DB-Trigger sperren Änderungen |
| 2 Zuweisung, mehrere Rollen, Rang | `ichq.authz.delegation.assign/unassign`; Rang = höchste nicht archivierte Rolle |
| 3 Einzelrechte ALLOW/DENY | Tabelle `permission_overrides` (RLS FORCE, zusammengesetzter FK), `set_override/clear_override` |
| 4 Ressourcen-Freigaben | ALLOW = `object_grants` (C0), DENY = neue Tabelle `object_denies`, in `visible_clause` — schlägt `read_all`, Freigabe, Erstellerschaft. Ressourcen sind die echten Fachobjekte (Aufgabe, Dokument …), keine Testtabelle nötig. Team/Abteilung als Subjekt: M6 |
| 5 Feature-Flags vorbereitet | Tabelle `tenant_feature_flags`, nur `ichq_platform` schreibt (`ichq tenant-feature`), Kernmodule nicht abschaltbar, Fehlercode `feature_disabled` |
| 6 Delegationsregeln | Obergrenze, keine Lücken-Löschung, Duplizieren nur eigene Rechte, kein Selbstbedienen, Rang, Last-Admin in einer Transaktion (`ichq.authz.guard`, für jeden Weg); keine Plattform-Rechte, keine Route zur Control Plane |
| 7 API + Audit | 18 neue Routen (`docs/authorization.md`), Vorschau mit Quelle je Recht (`/members/{m}/permissions`, `/me/permissions`); jede Änderung im Mandanten-Audit, Flags im Plattform-Audit |
| 8 M3-Übergang ersetzt | `ensure_company_admin` entfernt; `ichq tenant-admin` weist die gesperrte Rolle zu; Migration 0006 macht aus der Übergangsrolle die gesperrte (gespeicherte Liste gelöscht) |
| Doku | `docs/authorization.md` mit **aus dem Code erzeugter** Endpunkt-Tabelle (`ichq routes-doc`, Test vergleicht) |

Eine Berechnung für alles: `ichq.authz.effective` (pro Anfrage, auch für Benachrichtigungen, Aufgaben-Zuweisung,
Last-Admin). M3-Last-Admin nutzt jetzt dieselbe Admin-Definition (vorher nur `users.deactivate`).

## Tested (lokal, PostgreSQL 16, nicht CI)
| Prüfung | Ergebnis |
| --- | --- |
| pytest gesamt | **415 passed**, 0 failed |
| davon neu M4 | `test_m4_decision.py` 12 · `test_m4_delegation.py` 14 · `test_m4_boundaries.py` 7 · `test_m4_setup.py` 3 · `test_m4_docs.py` 1 |
| Mutationen | voller Lauf **erkannt 120 · unbemerkt 0 · ungültig 0**; danach eine weitere (Sperre im Last-Admin-Schutz) einzeln: erkannt 1 → **121**. M4 hat 31 eigene, 2 M3-Mutationen auf den neuen Ort umgezogen (jede Stufe der Reihenfolge, jede Delegationsregel, Sperre, Trigger, Grants, Migration) |
| ruff / mypy strict / lint-imports | sauber |

Gefunden durch Mutation: Die Prüfung „Kernmodul nicht abschaltbar" war doppelt und damit nicht testbar; jetzt eine
Prüfung beim Setzen plus Sicherung in der Berechnung (direkt geschriebene Kernmodul-Zeile wirkt nicht), beides mit
eigener Mutation.

Zweiter Fund: Der erste Nebenläufigkeitstest war auch OHNE Sperre grün (Verzögerung an der falschen Stelle — die
zweite Transaktion sah den Commit der ersten schon). Korrigiert und per Gegenprobe belegt: ohne Sperre rot, mit Sperre
dreimal grün; als Mutation eingetragen.

## Not Tested
- Last/Performance der Berechnung je Anfrage (3 Abfragen) und des Last-Admin-Schutzes bei großen Firmen.
- Oberfläche (U1 fehlt) — alles nur über die API geprüft.

## Known Issues / Grenzen
- Vorlagen-Zuschnitt (außer Company Admin) ist **[ANNAHME]** nach Produktvision 1.4.
- Rang ist grob (gleichrangige Personen sind gegenseitig verwaltbar) — wie im Prototyp.
- Subjekte nur Mitgliedschaften; Team/Abteilung mit M6. Feature-Flags ohne Pläne (M19).
- `permission_overrides` hat keine Spalte „gesetzt von" (Grund: Bezeichnerlänge); steht im Audit.

## Security Review (eigene Durchsicht, kein externer Review)
- **Eskalation:** Plattform-Rechte existieren nicht; unbekannte Rechte und Zusatzfelder (`grants_all`, `tenant_id`)
  → 400/422; eigene Rechte nicht änderbar; Company Admin nur vergebbar mit allen Rechten. Getestet.
- **Mandantengrenzen:** fremde Rollen/Personen 404, Kreuzzuweisung scheitert am zusammengesetzten FK, Flags per RLS
  getrennt, App-Rolle kann Flags nicht schreiben. Getestet + IDOR-Generator deckt alle neuen Pfad-ID-Routen ab.
- **Defense in depth:** gesperrte Rolle zusätzlich per Trigger; Flag-Zweitsicherung in `decide` und `effective`.
- **Nebenläufigkeit:** zwei Admins entziehen sich gleichzeitig die Rechte → genau einer scheitert (`last_admin`). Getestet.
- **Offen:** kein externer Pentest; CI-Lauf für M4 steht noch aus (wird mit diesem Push gestartet).
