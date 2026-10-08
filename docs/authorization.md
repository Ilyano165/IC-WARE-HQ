# Autorisierung (M4 · Rollen & Rechte)

Grundlage: M0 „Rechte" (Reihenfolge verbindlich), [ADR-011](adr/011-m4-rechte-auf-dem-c0-fundament.md),
[ADR-009](adr/009-sichtbereich-und-objektfreigaben.md), Prototyp-Konzepte in `docs/reference/m4-prototyp-rbac.md`.
Code: `src/ichq/authz/` (Berechnung, Rollen, Delegation, Vorlagen, Flags), Sichtbarkeit `src/ichq/objects/visibility.py`.

**Ein Satz:** Rollen gewähren Rechte; Einzelrechte und Ressourcen-Regeln können gewähren oder verbieten;
ein Verbot schlägt alles; wer etwas vergibt, muss es selbst haben.

## Hierarchie

- **Rechte** haben die Form `modul.aktion` und stehen alle in `ichq.authz.registry.PERMISSIONS`. Keine Platzhalter,
  keine impliziten Ketten (`invoices.delete` schließt `invoices.read` nicht ein). Unbekannte Rechte lehnt `require()`
  beim Programmstart ab. Es gibt **keine Plattform-Rechte** in der Registry.
- **Rollen** gehören genau einer Firma, haben einen **Rang** (1–999, höher = mächtiger) und sind Bündel von Rechten.
  Mehrere Rollen je Person addieren sich. Eine Rolle kann nichts verbieten.
- **Company Admin** (`grants_all`) ist gesperrt: hält berechnet **alle** Rechte der Registry — auch künftige —, ist nicht
  umbenennbar, nicht archivierbar, nicht löschbar, hat Rang 100 und speichert keine Rechteliste. Durchgesetzt im
  Service **und** per DB-Trigger (`tr_roles_locked`, `tr_role_permissions_locked`), höchstens eine je Firma
  (Unique-Index).
- **Einzelrechte** je Mitgliedschaft: `allow` oder `deny` (Tabelle `permission_overrides`).
- **Ressourcen-Regeln** je Objekt: Freigabe (`object_grants`, ADR-009) und Sperre (`object_denies`).
- **Feature-Flags** je Firma und Modul (`tenant_feature_flags`), nur von der Control Plane gesetzt.

## Priorität — die eine Berechnung

`ichq.authz.effective.effective()` berechnet bei **jeder Anfrage** neu (keine Rechte in der Sitzung — eine Änderung
wirkt ab der nächsten Anfrage). Erste zutreffende Regel je Recht:

| # | Regel | Ergebnis | Quelle in der Vorschau |
| --- | --- | --- | --- |
| 0 | Recht unbekannt, Mitgliedschaft/Firma nicht aktiv | NEIN | — (kein Principal) |
| 1 | Modul per Feature-Flag aus | NEIN (`403 feature_disabled`) | `feature_disabled` |
| 2 | Einzelrecht DENY | NEIN | `deny` |
| 3 | Ressourcen-DENY auf dem Objekt | unsichtbar (404) | — (je Objekt) |
| 4 | Einzelrecht ALLOW | JA | `allow` |
| 5 | Ressourcen-ALLOW (Freigabe) | sichtbar | — (je Objekt) |
| 6 | nicht archivierte Rolle (Company Admin: alle) | JA | `role` + Rollen |
| 7 | sonst | NEIN | `none` |

Schritte 3 und 5 gelten je Objekt und stehen in `visible_clause`: Ein Ressourcen-DENY schlägt `objects.read_all`,
jede Freigabe und die eigene Erstellerschaft. Kernmodule (`company`, `users`, `roles`, `audit`, `settings`) lassen
sich nicht abschalten — sonst könnte eine Firma sich nicht mehr verwalten.

## Delegationsregeln (Schutz gegen Rechteausweitung)

1. **Obergrenze:** Rechte in eine Rolle schreiben, Rollen vergeben, duplizieren, wiederherstellen und Einzelrechte
   (auch DENY und Zurücksetzen) nur für Rechte, die man **selbst effektiv** hat. Company Admin vergeben kann damit nur,
   wer selbst alle Rechte hat.
2. **Keine Lücken-Löschung:** Beim Bearbeiten einer Rolle bleiben Rechte, die man selbst nicht hat, unverändert.
3. **Duplizieren** kopiert nur eigene Rechte (die übrigen stehen im Audit als `not_copied`).
4. **Kein Selbstbedienen:** eigene Rollen und eigene Einzelrechte ändert niemand selbst; Selbst-Deaktivieren
   gibt es nicht (dafür „Firma verlassen").
5. **Rang:** eigener Rang = höchster Rang der eigenen nicht archivierten Rollen. Rollen bearbeiten/archivieren/löschen
   und neue Ränge nur **unter** dem eigenen; Rollen vergeben/entziehen **bis** zum eigenen; Personen verwalten nur mit
   Rang höchstens dem eigenen. Archivierte Rollen dürfen immer entzogen werden.
6. **Letzter Admin:** „Admin" = effektiv `users.deactivate` + `roles.update` + `roles.assign`. Jede Änderung, die Rechte
   kosten kann (Rolle entziehen, bearbeiten, archivieren, Einzelrecht DENY/Zurücksetzen, Deaktivieren, Verlassen),
   läuft in einer Transaktion unter Sperre aller aktiven Mitgliedschaften; fiele die Zahl der Admins von > 0 auf 0 →
   `409 last_admin`, nichts wird geschrieben (`ichq.authz.guard`).
7. **Kein Weg zum Plattform-Admin:** Es gibt kein Plattform-Recht, kein Flag am Konto und keine Route, die
   Control-Plane-Rechte vergibt. Company Admin per `ichq tenant-admin` und Feature-Flags per `ichq tenant-feature`
   setzt nur, wer Zugang zur Control Plane hat.

Archivieren entzieht allen Trägern die Rechte der Rolle sofort; Löschen geht nur archiviert und unbenutzt.
Jede Änderung steht im Mandanten-Audit (`role.*`, `permission.override_*`, `object.denied`, `object.deny_lifted`);
Feature-Flags im Plattform-Audit (`tenant.feature_flag_set`).

## Rollenvorlagen

Beim Aktivieren einer Firma (`ichq tenant-status <id> active`) und bei `ichq tenant-admin` idempotent angelegt;
eine vorhandene Rolle gleichen Namens wird nie überschrieben.

| Rolle | Rang | Zuschnitt |
| --- | --- | --- |
| Company Admin | 100 | gesperrt, alle Rechte (berechnet) |
| Geschäftsführung | 90 | alles außer Rechteverwaltung (`roles.create/update/delete/assign`, `users.override/update/deactivate`) |
| Mitarbeiter | 40 | eigene Aufgaben, Fahrten, Reisen, Bewirtung, Termine, Chat, Dateien lesen/hochladen; **ohne** `objects.read_all` |
| Steuerberater | 30 | Finanzen/Rechnungen lesen und exportieren, Belege, Rückfragen als Aufgaben, Kommentare; **ohne** `objects.read_all` |

Der Zuschnitt außer Company Admin ist **[ANNAHME]** nach Produktvision 1.4 — frei änderbar je Firma.

## Mandantengrenzen

- Rollen, Einzelrechte, Sperren und Flags sind Mandantentabellen: RLS mit `FORCE`, zusammengesetzte Fremdschlüssel
  `(tenant_id, …)`, Service-Kontext. Rollen und Personen anderer Firmen sind **404** (nie 403).
- Eine Rolle aus Firma A wirkt nie für eine Mitgliedschaft in Firma B (zusammengesetzter Fremdschlüssel;
  `effective` liest nur unter RLS der eigenen Firma).
- Rechte gelten je Mitgliedschaft: Wer in zwei Firmen Mitglied ist, hat in jeder nur die dortigen Rechte.

## Routen (M4)

| Methode | Pfad | Regel |
| --- | --- | --- |
| `GET` | `/api/v1/permissions` | roles.read |
| `GET` | `/api/v1/roles` | roles.read |
| `POST` | `/api/v1/roles` | roles.create (+ Obergrenze, Rang unter dem eigenen) |
| `GET` | `/api/v1/roles/{role}` | roles.read |
| `PATCH` | `/api/v1/roles/{role}` | roles.update (+ Rang, gesperrt, keine Lücken-Löschung, letzter Admin) |
| `POST` | `/api/v1/roles/{role}/duplicate` | roles.create (+ nur eigene Rechte) |
| `POST` | `/api/v1/roles/{role}/archive` | roles.delete (+ Rang, gesperrt, letzter Admin) |
| `POST` | `/api/v1/roles/{role}/restore` | roles.delete (+ Obergrenze) |
| `DELETE` | `/api/v1/roles/{role}` | roles.delete (+ nur archiviert und unbenutzt) |
| `GET` | `/api/v1/me/permissions` | authenticated |
| `GET` | `/api/v1/members/{member}/permissions` | users.read, roles.read |
| `PUT` | `/api/v1/members/{member}/roles/{role}` | roles.assign (+ nicht selbst, Rang, Obergrenze) |
| `DELETE` | `/api/v1/members/{member}/roles/{role}` | roles.assign (+ nicht selbst, Rang, letzter Admin) |
| `PUT` | `/api/v1/members/{member}/overrides/{permission}` | users.override (+ nicht selbst, Rang, Obergrenze, letzter Admin) |
| `DELETE` | `/api/v1/members/{member}/overrides/{permission}` | users.override (+ wie oben) |
| `GET` | `/api/v1/objects/{ref}/denies` | objects.share (+ Objekt sichtbar) |
| `PUT` | `/api/v1/objects/{ref}/denies/{member}` | objects.share (+ Objekt sichtbar, Person verwaltbar) |
| `DELETE` | `/api/v1/objects/{ref}/denies/{member}` | objects.share (+ wie oben) |

## Geschützte Endpunkte (aus dem Code erzeugt)

Erzeugt mit `ichq routes-doc` — **nicht von Hand ändern**; `tests/test_m4_docs.py` vergleicht mit dem Code.
Die Zusatzregeln der Services (Sichtbarkeit, Rang, Obergrenze …) stehen in den Tabellen oben und in
`docs/core-permissions.md` / `docs/m3-mandanten.md`.

<!-- routen:start -->
| Pfad | Methode | Marke | Regel |
| --- | --- | --- | --- |
| `/` | GET | public | öffentlich — Weiterleitung zur Oberfläche |
| `/api/v1/activities` | GET | permission | `activity.read` |
| `/api/v1/audit` | GET | permission | `audit.read` |
| `/api/v1/audit/export` | GET | permission | `audit.export` |
| `/api/v1/auth/2fa/disable` | POST | signed_in | angemeldet |
| `/api/v1/auth/2fa/enable` | POST | signed_in | angemeldet |
| `/api/v1/auth/2fa/recovery-codes` | POST | signed_in | angemeldet |
| `/api/v1/auth/2fa/setup` | POST | signed_in | angemeldet |
| `/api/v1/auth/login` | POST | public | öffentlich — Anmeldung |
| `/api/v1/auth/logout` | POST | any_session | jede Sitzung |
| `/api/v1/auth/logout-all` | POST | signed_in | angemeldet |
| `/api/v1/auth/mfa` | POST | mfa_challenge | 2FA-Zwischenschritt |
| `/api/v1/auth/password` | POST | signed_in | angemeldet |
| `/api/v1/auth/password-reset/confirm` | POST | public | öffentlich — Passwort neu setzen |
| `/api/v1/auth/password-reset/request` | POST | public | öffentlich — Passwort vergessen |
| `/api/v1/auth/session` | GET | signed_in | angemeldet |
| `/api/v1/auth/tenant` | POST | signed_in | angemeldet |
| `/api/v1/comments/{ref}` | DELETE | permission | `comments.create` |
| `/api/v1/comments/{ref}` | PATCH | permission | `comments.create` |
| `/api/v1/comments/{ref}/revisions` | GET | permission | `audit.read` |
| `/api/v1/comments/{ref}/tasks` | POST | permission | `tasks.create` |
| `/api/v1/company` | GET | permission | `company.read` |
| `/api/v1/company` | PATCH | permission | `company.update` |
| `/api/v1/dashboard` | GET | permission | `dashboard.read` |
| `/api/v1/documents` | GET | permission | `files.read` |
| `/api/v1/documents` | POST | permission | `files.upload` |
| `/api/v1/documents/{ref}` | GET | permission | `files.read` |
| `/api/v1/documents/{ref}/content` | GET | permission | `files.read` |
| `/api/v1/documents/{ref}/review` | POST | permission | `files.update` |
| `/api/v1/invitations` | GET | permission | `users.read` |
| `/api/v1/invitations` | POST | permission | `users.create` |
| `/api/v1/invitations/accept` | POST | public | öffentlich — Einladung annehmen — neues Konto |
| `/api/v1/invitations/accept-existing` | POST | signed_in | angemeldet |
| `/api/v1/invitations/{ref}` | DELETE | permission | `users.create` |
| `/api/v1/links/{ref}` | DELETE | authenticated | angemeldet + Firma |
| `/api/v1/me` | GET | authenticated | angemeldet + Firma |
| `/api/v1/me/permissions` | GET | authenticated | angemeldet + Firma |
| `/api/v1/members` | GET | permission | `users.read` |
| `/api/v1/members/{member}/deactivate` | POST | permission | `users.deactivate` |
| `/api/v1/members/{member}/overrides/{permission}` | DELETE | permission | `users.override` |
| `/api/v1/members/{member}/overrides/{permission}` | PUT | permission | `users.override` |
| `/api/v1/members/{member}/permissions` | GET | permission | `users.read` + `roles.read` |
| `/api/v1/members/{member}/roles/{role}` | DELETE | permission | `roles.assign` |
| `/api/v1/members/{member}/roles/{role}` | PUT | permission | `roles.assign` |
| `/api/v1/membership/leave` | POST | authenticated | angemeldet + Firma |
| `/api/v1/notifications` | GET | authenticated | angemeldet + Firma |
| `/api/v1/notifications/read-all` | POST | authenticated | angemeldet + Firma |
| `/api/v1/notifications/{ref}/read` | POST | authenticated | angemeldet + Firma |
| `/api/v1/objects/{ref}` | GET | authenticated | angemeldet + Firma |
| `/api/v1/objects/{ref}/activities` | GET | permission | `activity.read` |
| `/api/v1/objects/{ref}/comments` | GET | permission | `comments.read` |
| `/api/v1/objects/{ref}/comments` | POST | permission | `comments.create` |
| `/api/v1/objects/{ref}/denies` | GET | permission | `objects.share` |
| `/api/v1/objects/{ref}/denies/{member}` | DELETE | permission | `objects.share` |
| `/api/v1/objects/{ref}/denies/{member}` | PUT | permission | `objects.share` |
| `/api/v1/objects/{ref}/grants` | GET | permission | `objects.share` |
| `/api/v1/objects/{ref}/grants` | POST | permission | `objects.share` |
| `/api/v1/objects/{ref}/grants/{member}` | DELETE | permission | `objects.share` |
| `/api/v1/objects/{ref}/links` | GET | authenticated | angemeldet + Firma |
| `/api/v1/objects/{ref}/links` | POST | authenticated | angemeldet + Firma |
| `/api/v1/objects/{ref}/tasks` | POST | permission | `tasks.create` |
| `/api/v1/permissions` | GET | permission | `roles.read` |
| `/api/v1/questions` | GET | permission | `comments.read` |
| `/api/v1/roles` | GET | permission | `roles.read` |
| `/api/v1/roles` | POST | permission | `roles.create` |
| `/api/v1/roles/{role}` | DELETE | permission | `roles.delete` |
| `/api/v1/roles/{role}` | GET | permission | `roles.read` |
| `/api/v1/roles/{role}` | PATCH | permission | `roles.update` |
| `/api/v1/roles/{role}/archive` | POST | permission | `roles.delete` |
| `/api/v1/roles/{role}/duplicate` | POST | permission | `roles.create` |
| `/api/v1/roles/{role}/restore` | POST | permission | `roles.delete` |
| `/api/v1/search` | GET | authenticated | angemeldet + Firma |
| `/api/v1/tasks` | GET | permission | `tasks.read` |
| `/api/v1/tasks` | POST | permission | `tasks.create` |
| `/api/v1/tasks/{ref}` | GET | permission | `tasks.read` |
| `/api/v1/tasks/{ref}` | PATCH | permission | `tasks.update` |
| `/api/v1/tasks/{ref}/attachments` | POST | permission | `tasks.update` |
| `/app` | GET | public | öffentlich — Weiterleitung zur Oberfläche |
| `/app/{pfad:path}` | GET | public | öffentlich — Oberfläche: statische Dateien, keine Daten |
| `/health` | GET | public | öffentlich — Liveness für Orchestrierung |
| `/invite` | GET | public | öffentlich — Einladungslink → Oberfläche |
| `/readiness` | GET | public | öffentlich — Bereitschaft für Load Balancer |
| `/reset` | GET | public | öffentlich — Passwort-Link → Oberfläche |
<!-- routen:end -->

## Bekannte Grenzen

- **Subjekte nur Mitgliedschaften.** Team/Abteilung als Subjekt einer Freigabe/Sperre folgt mit M6 (ADR-011).
- **Feature-Flags ohne Plan.** Nur die Schalter; Pläne/Abrechnung folgen mit M19.
- **Vorlagen-Zuschnitt ist Annahme** (siehe oben) — mit echten Nutzern prüfen.
- **Rang ist grob:** Wer Rang 90 hat, kann alle Personen bis Rang 90 verwalten, auch gleichrangige. Bewusst wie im
  Prototyp; feinere Regeln erst bei Bedarf.
- **Effektive Rechte je Anfrage** kosten drei kleine Abfragen; der Last-Admin-Schutz berechnet sie für alle aktiven
  Mitglieder (Firmen 1–20 Personen: unkritisch; bei großen Firmen messen, M24).
