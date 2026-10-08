# Prompts für Claude Code

Jeder Prompt ist eine eigene Sitzung. Zwischen den Meilensteinen `/clear`, damit der Kontext frisch ist.
Claude Code liest `CLAUDE.md` automatisch — die Regeln dort musst du nicht wiederholen.

**Arbeitsweise, die sich bewährt hat:**
- Für größere Aufgaben zuerst den **Plan-Modus** (Shift+Tab) nutzen und den Plan prüfen, bevor Code entsteht.
- Pro Meilenstein ein eigener Branch und ein Pull Request. Die CI muss grün sein, bevor gemergt wird.
- Ergebnisse nie glauben, nur prüfen: Testzahl, Mutationszahl, CI-Link.

---

## 0 · Einstieg — Bestandsaufnahme ohne Änderungen

```
Lies CLAUDE.md, README.md, docs/architecture.md und docs/m0-zielarchitektur.md.

Richte die Entwicklungsumgebung ein (PostgreSQL 16 per Docker, Abhängigkeiten aus requirements.lock)
und führe aus: pytest, ruff, mypy, lint-imports, scripts/mutation-check.sh.

Ändere KEINEN Code. Berichte mir danach:
1. Exakte Ergebnisse jeder Prüfung (Zahlen, keine Zusammenfassung wie „alles gut").
2. Was in deiner Umgebung anders lief als dokumentiert.
3. Die offenen Punkte aus CLAUDE.md in sinnvoller Reihenfolge, mit deiner Aufwandsschätzung.
Wenn etwas fehlschlägt: Ursache finden und berichten, nicht reparieren.
```

---

## 1 · M2 abschließen

```
Schließe M2 (Authentication) ab. Arbeite die „Offenen Punkte aus M2" in CLAUDE.md vollständig ab:

1. Migrationstest mit echten M1-Altdaten: Datenbank auf 0001 bringen, Konten mit Status 'active' ohne
   Passwort und 'disabled' anlegen, auf 0002 migrieren, prüfen dass daraus 'pending' bzw. 'deactivated'
   wird. Danach Downgrade und erneut Upgrade.
2. Aufräum-Job: alte login_attempts (> 30 Tage), abgelaufene und widerrufene Sitzungen (> 30 Tage),
   benutzte/abgelaufene Reset-Tokens. Als Outbox-Handler oder Scheduler-Aufgabe — begründe die Wahl.
   Mit Tests, dass nur Altes gelöscht wird. auth_events bleiben (nur anhängend).
3. ADR-006: Brute-Force-Schutz in PostgreSQL statt Redis — Kontext, Entscheidung, verworfene
   Alternativen, Folgen, ab welcher Last Redis nötig wird.
4. docs/authentication.md: Abläufe (Login, 2FA, Firmenwahl, Reset, Einladung), Sitzungsregeln,
   Sperren und Drosselung mit Zahlen, Cookie-Regeln, Datenbankrolle ichq_auth, Auth-Ereignisse.
5. README, docs/configuration.md (alle neuen ICHQ_*-Variablen), docs/server-setup.md (ichq_auth,
   ICHQ_PUBLIC_ORIGIN, ICHQ_TRUSTED_PROXIES), docs/testing.md (neue Testdateien, Mutationen).
6. Bekannte Grenzen dokumentieren (Liste in CLAUDE.md) und für jede sagen, ob und wann sie behoben wird.

Prüfe danach alles: pytest, ruff, mypy, lint-imports, mutation-check.

Zum Schluss der vollständige M2-Statusbericht:
Implemented / Tested (mit Zahlen) / Not Tested / Known Issues / Security Review Required /
Production Readiness: NOT READY — und eine konkrete Empfehlung für M3.
Aktualisiere den Stand in CLAUDE.md. STOP.
```

---

## 2 · Docker Compose wirklich laufen lassen

Das ist der größte ungeprüfte Teil. In der ursprünglichen Bauumgebung gab es kein Docker.

```
Bringe deploy/docker-compose.yml auf diesem Rechner tatsächlich zum Laufen und beweise es.

1. deploy/generate-secrets.sh ausführen, Stack starten (ICHQ_DOMAIN=localhost).
2. Prüfe und berichte mit echten Ausgaben:
   - Startreihenfolge: postgres → db-init → migrate → app (healthy) → caddy
   - https://localhost/health und /readiness über Caddy
   - App-Container läuft nicht als root (Nutzer-ID zeigen)
   - Konto + Firma per `docker compose exec app ichq …` anlegen, Login über HTTPS, Cookie __Host-…
   - Upload/Download eines Objekts nach MinIO über den S3-Code (kleines Python-Skript im Container)
   - Worker verarbeitet ein Outbox-Ereignis
   - App stoppen → Caddy liefert 503; App starten → wieder 200
   - Neustart des ganzen Stacks: Daten bleiben erhalten
   - Logs aller Container: keine Passwörter, Tokens, Query-Strings
3. Behebe Fehler in Dockerfile/Compose/Caddyfile. Jede Änderung mit Begründung.
4. Ergänze ein Skript scripts/compose-smoke-test.sh, das diese Prüfungen automatisiert,
   und einen CI-Job dafür.
5. Prüfe ICHQ_TRUSTED_PROXIES: Kommt die echte Client-IP in auth_events an? Wenn nicht, beheben.

Berichte, was jetzt bewiesen ist und was weiterhin nicht. STOP.
```

---

## 3 · M3 — Mandanten

```
Implementiere ausschließlich M3 (Mandanten). Grundlage: docs/m0-zielarchitektur.md, CLAUDE.md.
Lies vorher den bestehenden Code von tenancy, identity, authz, auth und api.

Ziel: Tor 1 — „Isolation bewiesen: Fremd-ID-Tests je Endpunkt grün, RLS greift."

1. Isolationstest-Generator: Ein Test, der ALLE Routen aus iter_api_routes() durchläuft und für jede
   Route mit Pfadparametern prüft, dass eine ID aus Firma B mit einer Sitzung aus Firma A
   404 liefert (nie 200, nie 403, nie Daten). Neue Routen werden automatisch erfasst.
   Eine Route, die der Generator nicht abdecken kann, muss explizit begründet ausgenommen werden.
   Mit Gegenprobe: Mutation, die eine Route mandantenblind macht, muss den Test rot machen.
2. Baustein für alle späteren Module: Muster für mandantengebundene Ressourcen (Laden per ID im
   Kontext → 404, Auflisten mit Cursor-Paginierung, Anlegen/Ändern mit Audit und Outbox-Ereignis).
   Mit Vorlage in docs/ und einem Beispielmodul, das nur zum Testen existiert.
3. Firmenprofil: GET/PATCH /api/v1/company (company.read/company.update), Validierung wie bei
   tenancy.create_tenant. Firma im Status 'paused' darf lesen, aber keine schreibenden Anfragen —
   zentral durchgesetzt, nicht pro Route (Fehlercode tenant_paused).
4. Mitglieder: auflisten (users.read), einladen per E-Mail mit einmaligem, gehashtem, befristetem
   Token (users.create), Einladung annehmen (neues Konto oder bestehendes Konto verknüpfen),
   Mitgliedschaft deaktivieren (users.deactivate), Firma verlassen. Alles mit Mandanten-Audit.
   Niemand kann sich selbst deaktivieren; die letzte aktive Mitgliedschaft mit Admin-Rechten
   kann nicht entfernt werden.
5. Übergangslösung bis M4: CLI-Befehl, der in einer Firma eine Systemrolle „Company Admin" mit allen
   Rechten der Registry anlegt und einer Mitgliedschaft zuweist. Klar als Übergang markieren.

NICHT in M3: Rollenverwaltung (M4), Oberfläche (M5), Teams/Abteilungen (M6), Control Plane (M17).

Sicherheitstests (wirklich ausführen): fremde IDs, Einladungs-Token-Missbrauch (wiederverwenden,
abgelaufen, fremde Firma, erraten), Einladung an bestehendes Konto ohne dessen Zustimmung,
Schreiben in pausierter Firma, Selbst-Deaktivierung, letzte Admin-Mitgliedschaft.
Für jede Schutzregel eine Mutation in scripts/mutation-check.sh.

Am Ende: vollständiger Statusbericht + Aussage, ob Tor 1 erreicht ist (mit Beleg). STOP.
```

---

## 4 · M4 — Rollen und Rechte

```
Implementiere ausschließlich M4 (RBAC) auf dem bestehenden Fundament.

Grundlagen:
- docs/m0-zielarchitektur.md, Abschnitt „Rechte" — Entscheidungsreihenfolge ist verbindlich.
- docs/reference/m4-prototyp-rbac.md — Konzepte und Testszenarien aus dem Prototyp übernehmen,
  NICHT den Code und NICHT die „Hauptfirma 1"-Übergangslösung.
- Bestehende Tabellen roles, role_permissions, membership_roles und ichq.authz.

Umfang:
1. Rollen je Firma: anlegen, bearbeiten, duplizieren, archivieren, löschen (nur archiviert + unbenutzt).
   Vorlagen beim Aktivieren einer Firma; „Company Admin" gesperrt und hält immer alle Rechte.
2. Zuweisung an Mitgliedschaften, mehrere Rollen, Rang.
3. Einzelrechte ALLOW/DENY je Mitgliedschaft (neue Tabelle, Mandanten-Checkliste beachten).
4. Ressourcen-Freigaben (Projekt/Aufgabe/Datei/Team/Abteilung) als Schema + Entscheidungslogik;
   die Ressourcen selbst entstehen erst in späteren Meilensteinen — mit Testtabelle beweisen.
5. Feature-Flag-Schritt der Entscheidung vorbereiten (Tabelle tenant_feature_flags, Plan folgt M19).
6. Delegationsregeln: nur vergeben, was man selbst hat; Rang; keine Selbständerung;
   Last-Admin-Schutz in einer Transaktion. Kein Weg zum Plattform-Admin.
7. API: Registry lesen, Rollen-CRUD, Zuweisung, Einzelrechte, Vorschau „was darf diese Person"
   mit Quelle je Recht. Jede Änderung im Mandanten-Audit.
8. Die M3-Übergangsrolle durch das echte System ersetzen und den CLI-Übergang entfernen.

Tests: die Szenarien aus dem Prototyp-Bericht als pytest-Fälle portieren (Rechteausweitung,
Rollenmanipulation, Einzelrechte-Missbrauch, Admin-Eskalation, Bypass, Direktzugriff, Rollenlöschung,
letzter Admin, Mandantengrenzen). Mutationstests für jede Stufe der Entscheidungsreihenfolge.

Dokumentation: docs/authorization.md (Hierarchie, Priorität, Mandantengrenzen, geschützte Endpunkte —
die Tabelle aus dem Code erzeugen, nicht von Hand). Statusbericht. STOP.
```

---

## 5 · Vorlage für jeden weiteren Meilenstein

```
Implementiere ausschließlich M<N> — <Name>.
Grundlage: docs/m0-zielarchitektur.md, CLAUDE.md, bestehender Code. Keine Architektur erfinden,
die M0 widerspricht; Abweichungen als ADR begründen.

Ziel: <ein Satz>

Umfang:
1. …
2. …

Nicht in diesem Meilenstein: …

Pflicht:
- Jede neue Tabelle nach der Mandanten-Checkliste in docs/migrations.md.
- Jede neue Route mit genau einer Sicherheitsmarke; der Isolationstest-Generator muss sie abdecken.
- Rechte nur über require(); neue Rechte in der Registry.
- Ereignisse über die Outbox, Änderungen im Mandanten-Audit.
- Sicherheitstests für: <Liste>. Für jede Schutzregel eine Mutation.
- Doku aktualisieren.

Zum Schluss: Implemented / Tested (mit Zahlen) / Not Tested / Known Issues /
Security Review Required / Production Readiness: NOT READY / Empfehlung für M<N+1>. STOP.
```

---

## 6 · Gegenprüfung (in einer frischen Sitzung nach jedem Meilenstein)

```
Du bist Prüfer, nicht Autor. Prüfe den Stand von M<N> kritisch, ohne Code zu ändern.

1. Führe alle Prüfungen selbst aus und vergleiche mit dem Statusbericht im letzten PR.
   Jede Abweichung benennen.
2. Suche Tests, die nicht rot werden können (z. B. Erwartung aus dem geprüften Code gelesen,
   Prüfung über eine leere Menge, Assertion die immer stimmt). Beweise es mit einer Mutation.
3. Suche Mandantenlecks: jede neue Route, jede neue Abfrage, jede neue Tabelle.
4. Suche Geheimnisse in Logs, Fehlermeldungen, Audit-Daten, Antworten.
5. Prüfe, ob die Doku dem Code entspricht.

Liefere eine priorisierte Befundliste (kritisch / hoch / mittel / niedrig) mit Beleg je Befund. STOP.
```
