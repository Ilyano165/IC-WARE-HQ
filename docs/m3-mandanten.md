# M3 — Mandanten

Grundlage: M3-Auftrag in `docs/claude-code-prompts.md` (Abschnitt 3), M0 „Daten" und „Rechte".
Ziel: **Tor 1 — „Isolation bewiesen: Fremd-ID-Tests je Endpunkt grün, RLS greift."**

## Was M3 liefert

| Bereich | Umsetzung |
| --- | --- |
| Firmenprofil | `GET/PATCH /api/v1/company` — Name, rechtlicher Name, Zeitzone, Sprache, Währung. Gleiche Prüfungen wie beim Anlegen. Slug, Status, Plan nur über die Control Plane. Die App-Rolle hat dafür **Spaltenrechte** auf genau diese fünf Spalten und eine UPDATE-Policy nur für die eigene Firma. Jede Änderung im Mandanten-Audit (`company.updated`, alt → neu). |
| Pausierte Firma | **zentral** in `ichq.api.security`: Jede Route mit Principal (`require`/`authenticated`) lehnt bei `tenant_status = paused` alle POST/PUT/PATCH/DELETE mit 403 `tenant_paused` ab. Lesen bleibt erlaubt. Zweite Linie: `writing()` prüft den Status in der schreibenden Transaktion. |
| Mitglieder | auflisten (`users.read`, Filter Status/Suche, Cursor), deaktivieren (`users.deactivate` → `suspended`), Firma verlassen (→ `left`). Wirkung sofort: `get_principal` prüft die Mitgliedschaft bei jeder Anfrage. |
| Einladungen | `users.create`; Token 256 Bit, nur SHA-256 in der DB, 7 Tage, einmalig, widerrufbar; höchstens eine offene Einladung je E-Mail und Firma; Link `…/invite#token=…` ohne Firma, Name, E-Mail. Versand nur mit eingerichtetem Mailer (sonst 503). Audit enthält nur die E-Mail-Domain. |
| Annehmen | **neues Konto**: öffentlich, mit Token + Name + Passwort (gleiche Passwortregel wie überall); gibt es zur E-Mail schon ein Konto → 409 `account_exists`. **Bestehendes Konto**: nur angemeldet mit genau dem Konto der eingeladenen E-Mail (`accept-existing`) — ein bestehendes Konto wird nie ohne eigene Handlung verknüpft. Einladung verbrauchen + Mitgliedschaft anlegen in **einer** Mandanten-Transaktion. Eine Einladung gibt **keine** Rechte. |
| Schutzregeln | Niemand deaktiviert sich selbst (403). Die letzte aktive Mitgliedschaft mit Verwaltungsrecht (`users.deactivate` über eine nicht archivierte Rolle) kann weder deaktiviert werden noch austreten (409 `last_admin`) — geprüft unter Sperre aller Mitgliedschaften der Firma. |
| Übergang bis M4 | `ichq tenant-admin --email … --tenant <slug>` legt die Systemrolle „Company Admin" mit allen Rechten der Registry an (idempotent, zieht neue Rechte nach) und weist sie zu. **Wird mit M4 entfernt.** |

## Routen

| Methode | Pfad | Marke / Recht |
| --- | --- | --- |
| `GET` | `/api/v1/me` | authenticated |
| `GET` | `/api/v1/company` | company.read |
| `PATCH` | `/api/v1/company` | company.update |
| `GET` | `/api/v1/members` | users.read |
| `POST` | `/api/v1/members/{member}/deactivate` | users.deactivate (+ nicht selbst, nicht letzter Admin) |
| `POST` | `/api/v1/membership/leave` | authenticated (+ nicht letzter Admin) |
| `GET` | `/api/v1/invitations` | users.read |
| `POST` | `/api/v1/invitations` | users.create |
| `DELETE` | `/api/v1/invitations/{ref}` | users.create |
| `POST` | `/api/v1/invitations/accept` | public |
| `POST` | `/api/v1/invitations/accept-existing` | signed_in (+ E-Mail muss passen) |

Firmenwechsel ist seit M2 `POST /api/v1/auth/tenant` (prüft aktive Mitgliedschaft + Firmenstatus, rotiert die Sitzung).

## Datenbank

Migration `0004_m3_tenancy`: Spaltenrechte + UPDATE-Policy auf `tenants`; Tabelle `invitations` (Mandanten-Checkliste:
`tenant_id`, zusammengesetzte Fremdschlüssel auf `memberships`, RLS `ENABLE`+`FORCE`, Policy mit `USING` und
`WITH CHECK`). Zusätzlich darf die Auth-Rolle ausgewählte Spalten von `invitations` **lesen** (Token-Hash-Suche,
die Firma ist beim Annehmen unbekannt) — schreiben kann sie dort nichts.

## Tor 1 — Stand

| Kriterium | Beleg |
| --- | --- |
| Fremd-ID-Test je Endpunkt | `tests/test_core_security.py::test_idor_jede_route_mit_id_liefert_404_fuer_fremde_firma` läuft über **alle** `/api/v1`-Routen mit Pfadparametern (Core + M3); neue Route ohne Zuordnung ⇒ rot. Gegenprobe mit eigenen IDs ⇒ nie 404. |
| IDs in Body/Query | Ziel, Mitglied, Dokument (Generator „Gemischt"), Filter `subject`/`assignee`/`actor`, Erwähnungen — eigene Tests |
| RLS greift | `test_core_objects.py::test_rls_erzwungen_und_ohne_kontext_leer` (alle Core-Tabellen), `test_isolation.py`, `test_migrations.py::test_jede_mandantentabelle_hat_erzwungene_rls` |
| Gegenprobe Mutation | „Route mandantenblind" (RLS-Policy `USING (true)`) ⇒ Generator rot — `scripts/mutation-check.sh`, Abschnitt M3 |
| CI-Protokoll | **fehlt.** M0: „Ein Tor ist erst passiert, wenn sein Kriterium im CI-Protokoll belegt ist." Die CI läuft auf Pull Requests; es gibt noch keinen PR. Lokal belegt, im CI nicht. |

Nicht in M3 (bleibt M4): Rollen anlegen/ändern/zuweisen per API, Einzelrechte, Ressourcen-DENY, Rollenvorlagen.
Ohne M4 vergibt nur der CLI-Übergang Rechte.

## Bekannte Grenzen
- Annehmen mit neuem Konto ist nicht vollständig atomar: Konto (Plattform-Rolle) und Passwort (Auth-Rolle) entstehen
  vor der Mandanten-Transaktion. Scheitert diese (z. B. Einladung zeitgleich widerrufen), bleibt ein Konto ohne
  Firma zurück. Die Einladung wird dabei nie doppelt verbraucht.
- Keine Drosselung für `invitations/accept`. Tokens haben 256 Bit Zufall (nicht erratbar); eine Drosselung wie beim
  Login fehlt trotzdem und gehört vor den Produktivbetrieb.
- `notifications/read` ist in pausierten Firmen ebenfalls gesperrt (zentrale Regel kennt keine Ausnahmen).
