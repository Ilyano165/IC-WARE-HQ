# Unternehmensverwaltung (ADR-021)

Firmen werden in HQ selbst angelegt und verwaltet — unter **Firmen verwalten** (nur für Betreiber der Installation).
Die Linux-Konsole ist dafür nicht mehr nötig; sie bleibt als Notweg.

## Bisheriger Ablauf („Commander“) — Bestandsaufnahme

Bis 1.0.0rc1 gab es genau einen Weg: `hq setup-admin` auf dem Server (Windows: Startmenü **Erste Firma anlegen** →
`steuerung.ps1 -Aktion ErsteFirma` → Linux-Konsole). Das Skript fragt Firma, Kürzel, E-Mail, Name und Passwort ab und
ruft nacheinander sieben Befehle im App-Container auf:

| # | Befehl | Wirkung | DB-Rolle |
| --- | --- | --- | --- |
| 1 | `ichq tenant-create` | Firma im Zustand `pending` | `ichq_platform` |
| 2 | `ichq tenant-status … active` | aktivieren, Rollenvorlagen anlegen | `ichq_platform`, `ichq_app` |
| 3 | `ichq user-create` | Konto im Zustand `invited` | `ichq_platform` |
| 4 | `ichq user-set-password --password-stdin` | Passwort (Argon2id) | `ichq_auth` |
| 5 | `ichq user-status … active` | Konto aktivieren | `ichq_auth` |
| 6 | `ichq membership-add` | Mitgliedschaft | `ichq_app` |
| 7 | `ichq tenant-admin` | Rolle Company Admin | `ichq_app` |

Schwächen: bricht ein Schritt ab (z. B. Passwort zu schwach in Schritt 4), bleiben Firma und Konto halb angelegt
zurück; ein zweiter Lauf scheitert dann am vergebenen Kürzel. Jede weitere Firma braucht wieder die Konsole.
Bearbeiten, Pausieren, Module schalten ging nur per Einzelbefehl mit interner UUID.

## Neuer Ablauf

### Ersteinrichtung (einmal je Installation)

1. Am Server: `hq setup-code` (Windows: **Erste Firma anlegen**) stellt einen Einrichtungscode aus — 24 Stunden
   gültig, einmal verwendbar, nur als Hash gespeichert — und zeigt die Adresse `https://<adresse>/app/#/einrichtung`.
2. Im Browser führt der Assistent durch: **Code → Firma → Ihr Zugang → Prüfen**.
3. Ergebnis: erste Firma (aktiv, Rollenvorlagen angelegt), das eigene Konto als Company Admin **und** Betreiber.

Sobald es einen Betreiber gibt, lehnt `hq setup-code` ab; `GET /api/v1/setup` meldet `needed: false`.

### Weitere Firmen

**Firmen verwalten → Firma anlegen**, vier Schritte:

1. **Firma** — Name, rechtlicher Name, Kürzel (Vorschlag aus dem Namen, Umlaute umgeschrieben, auf Eindeutigkeit geprüft)
2. **Einstellungen** — Zeitzone, Sprache, Währung, Module (abwählbar; Kernmodule nicht)
3. **Administrator** — ich selbst · bestehendes Konto (E-Mail) · neues Konto mit Startpasswort
4. **Prüfen & anlegen** — Zusammenfassung; erst hier wird geschrieben

Alles wird geprüft, bevor die erste Zeile entsteht. Ein schwaches Passwort legt nichts an.

### Verwalten

Je Firma: Stammdaten ändern (Kürzel bleibt), Status ändern (aktiv ⇄ pausiert/gesperrt → deaktiviert; immer mit
Begründung, Deaktivieren ist endgültig), Module ein-/ausschalten, Administrator zuweisen, Verlauf aus dem
Plattform-Audit. **Löschen gibt es nicht** — Deaktivieren sperrt den Zugang, die Daten bleiben
(Aufbewahrungsfristen; ein Löschkonzept ist offen).

### Betreiber

Betreiber verwalten Firmen — sie haben **keine Rechte in einer Firma**, solange sie dort nicht Mitglied sind.
Weitere Betreiber: bestehendes Konto per E-Mail hinzufügen. Der letzte Betreiber kann nicht entfernt werden.
Notweg am Server: `hq ichq operator-add --email …`.

## Endpunkte

| Methode | Pfad | Schutz |
| --- | --- | --- |
| `GET` | `/api/v1/setup` | public (nur „Einrichtung nötig?“) |
| `POST` | `/api/v1/setup` | public (+ gültiger Einrichtungscode, sonst 403) |
| `GET` | `/api/v1/platform/companies` | operator |
| `POST` | `/api/v1/platform/companies` | operator |
| `GET` | `/api/v1/platform/slug-suggestion` | operator |
| `GET` | `/api/v1/platform/accounts` | operator (nur exakte E-Mail, keine Suche) |
| `GET` | `/api/v1/platform/companies/{slug}` | operator |
| `PATCH` | `/api/v1/platform/companies/{slug}` | operator |
| `POST` | `/api/v1/platform/companies/{slug}/status` | operator (+ Begründung) |
| `PUT` | `/api/v1/platform/companies/{slug}/modules/{module}` | operator (+ Begründung) |
| `POST` | `/api/v1/platform/companies/{slug}/admins` | operator |
| `GET` | `/api/v1/platform/operators` | operator |
| `POST` | `/api/v1/platform/operators` | operator |
| `POST` | `/api/v1/platform/operators/remove` | operator (+ nie der letzte) |

## Was nicht geprüft ist

- Auf einem echten Windows-PC wurde der Ablauf **nicht** ausgeführt (nur automatisierte Tests gegen PostgreSQL und
  Browsertests mit Chromium).
- 2FA für Betreiber wird empfohlen, aber nicht erzwungen.
