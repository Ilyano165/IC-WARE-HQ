# ADR-016: Launch-Betrieb — E-Mail-Outbox, verschlüsselte externe Sicherung, Monitoring

**Status:** angenommen · **Datum:** 09.10.2026 · **Ergänzt:** ADR-015 · **Grundlage:** M0 Abschnitte 29 (Backup) und
Tor 2, Launch-Auftrag vom 09.10.2026

## Kontext

Nach ADR-015 lief die Plattform auf einem Server, aber für einen Launch fehlten: E-Mail mit Wiederholung (Reset und
Einladung gingen per `BackgroundTasks` raus — ein SMTP-Fehler verlor die Mail still), eine Sicherung, die den Verlust
des Servers übersteht (bisher unverschlüsselt auf demselben Server, inklusive Secrets), und eine Überwachung, die
jemanden benachrichtigt.

## Entscheidungen

### 1. E-Mail über eine Outbox (`ichq.mail`, Migration 0008)
* Jede Mail wird in **derselben Transaktion** wie ihr Anlass in `mail_outbox` geschrieben (Rollback ⇒ keine Mail);
  der Worker versendet. Ausnahme Passwort-Reset: Einreihen **nach** der Antwort, damit bekannte und unbekannte Konten
  gleich schnell antworten (Enumeration).
* **Token-Mails nur verschlüsselt** (AES-GCM, Schlüssel per HKDF aus `ICHQ_SECRET_KEY`, an die Mail-ID gebunden);
  nach Versand oder Ablauf wird der Inhalt gelöscht. Der Klartext eines Reset-Links liegt nie in der Datenbank.
* Wiederholung mit wachsender Wartezeit (1, 4, 16 … min, höchstens 6 h, 6 Versuche) ⇒ `failed`, sichtbar in
  `ichq mail-status` und `deploy/hq check`; `ichq mail-retry` stellt erneut zu. Ablauf: Mails mit abgelaufenem Token
  werden nicht mehr gesendet. Dedup über `dedup_key`. Ratenlimit je Empfänger (Standard 10/h) — darüber
  **zurückgestellt**, nicht verworfen.
* RLS mit FORCE: App-Rolle darf nur für die eigene Firma **einfügen**, Auth-Rolle nur ohne Firma; beide dürfen
  nichts lesen. Lesen/ändern: Worker, Plattform. `ON CONFLICT DO NOTHING` ohne Ziel, weil ein Ziel SELECT-Rechte
  verlangt (im Test gefunden).
* Sicherheitshinweise (Passwort geändert/zurückgesetzt, 2FA an/aus, neue Recovery-Codes, Sperre) entstehen an EINER
  Stelle: `auth.events.record` — im Savepoint, damit ein Mail-Fehler nie einen Fehlversuch zurückrollt.
* SMTP mit STARTTLS (Standard) oder SMTPS; Anmeldung ohne TLS verweigert die Konfiguration. Einladungen nennen keine
  Firma (M3-Entscheidung: eine vertippte Adresse erfährt nichts über Geschäftsbeziehungen).
* Betreiberwarnung `ichq alert`: über die Outbox; ist die Datenbank weg, **direkt** per SMTP.

### 2. Sicherung mit restic (`deploy/lib/sicherung.sh`, Image `ic-ware-hq-backup`)
* **restic** statt eigener Kryptografie: authentifiziert verschlüsselt (AES-256 + Poly1305), dedupliziert, S3 und
  lokale Ziele, `forget/prune`, `check`. Binärdatei aus dem offiziellen, fest versionierten Image `restic/restic:0.18.1`.
* **Schlüssel getrennt**: `/etc/ichq/backup.key` (root, 600), nie in der Sicherung, nie in `secrets/`. `install.sh`
  zeigt ihn einmal an; der Betreiber verwahrt ihn außerhalb des Servers. Ohne ihn ist keine Sicherung lesbar.
* Inhalt: `pg_dump -Fc` (vor dem Hochladen mit `pg_restore --list` geprüft), Dateien-Volume, `secrets/`, `.env`,
  Manifest mit SHA-256 und Datei-Zählern. Externes Ziel per `HQ_BACKUP_REPOSITORY` (S3-kompatibel); ohne Angabe ein
  lokales restic-Repository mit Warnung „nicht extern".
* Alle 6 Stunden (RPO ≤ 6 h), Aufbewahrung 7 täglich / 5 wöchentlich / 12 monatlich, danach `restic check`.
* **Wöchentlicher automatischer Wiederherstellungstest** (`backup-verify`, M0-Forderung): Daten-Stichprobe lesen,
  neueste Sicherung in eine Wegwerf-PostgreSQL ohne Netz einspielen (originalgetreu mit Rollen, Besitzern, RLS),
  Prüfsummen und Zähler vergleichen, **jede `storage_key` der Datenbank als Datei nachweisen**.
* Wiederherstellung: prüft Prüfsummen und den Inhalt von `secrets.tar` (nur `secrets/<name>`, keine Links) vor dem
  Entpacken, bewahrt alte Secrets, gleicht DB-Passwörter an.
* Das Repository wird **nur** angelegt, wenn restic ausdrücklich „existiert nicht" meldet — nie bei falschem
  Schlüssel oder Netzfehler (im Test gefunden: falscher Schlüssel ⇒ Versuch einer Neuanlage).
* Fehlerbehandlung in einem **eigenen Prozess**: Bash ignoriert `set -e` in Funktionen im `if`-Zusammenhang — im
  Test meldete die Prüfung „ok", obwohl `pg_restore` scheiterte. Regressionstest + Mutation.

### 3. Monitoring (`deploy/lib/pruefung.sh`, `hq check --alert`, alle 5 min)
* Prüft: Dauerdienste + Healthchecks (neu: Lebenszeichen für Worker, Scanner und Jobs — ein hängender oder dauerhaft
  scheiternder Prozess wird „unhealthy"), App-Bereitschaft, HTTPS und Restlaufzeit des Zertifikats, Outbox/Mail
  (Fehler, Rückstau), Quarantäne-Rückstau, ClamAV, Platte, RAM, Alter und Ergebnis von Sicherung und
  Wiederherstellungstest, ob das Sicherungsziel extern ist.
* Alarm-Mail bei neuem Problem, tägliche Erinnerung, Entwarnung bei Behebung. **Totmannschalter**: bei fehlerfreier
  Prüfung wird `HQ_HEARTBEAT_URL` angepingt (z. B. healthchecks.io); fällt der ganze Server aus, meldet sich der
  externe Dienst — eine Überwachung auf dem Server selbst kann das nicht.
* Betreiberinformationen gibt es nur auf dem Server (CLI/Mail), keinen Web-Endpunkt — Firmenmitglieder sehen sie nie.

### 4. Entscheidungen aus der Sicherheitsprüfung (Details: `docs/security-review.md`)
* Selbstprüfung eines Belegs bleibt erlaubt (Ein-Personen-Firma), wird aber in Audit und Aktivität markiert;
  Freigabe erst nach bestandener Virenprüfung.
* Wiedereintritt nach Austritt: ohne alte Rollen, Einzelrechte, manuelle Freigaben.
* Paging-Cursor AES-GCM-verschlüsselt (keine interne UUID nach außen, Manipulation wird abgewiesen).

## Verworfen
* **WAL-Archivierung/PITR (pgBackRest, WAL-G)** jetzt: weiterer Dienst, eigene Wiederherstellungsprozedur, eigene
  Tests. Stattdessen Sicherung alle 6 h. **Folge: bis zu 6 h Datenverlust** im schlimmsten Fall. Neu bewerten, sobald
  Kunden mit hohem Buchungsvolumen da sind oder Tor S (Steuerfunktionen) näher rückt.
* Eigene AES-Verschlüsselung der Sicherungsdateien: restic ist geprüft, authentifiziert und dedupliziert.
* Mail-Versand direkt aus dem Webprozess: keine Wiederholung, Verlust bei Neustart.
* Monitoring-Stack (Prometheus/Grafana): für einen Server unverhältnismäßig; `hq check` + externer Totmannschalter
  deckt Ausfall, Fehler und Rückstau ab.

## Folgen und offene Grenzen
* Ohne `HQ_BACKUP_REPOSITORY` (extern) und ohne verwahrten Schlüssel ist ein Serververlust weiterhin Datenverlust —
  `deploy/hq check` warnt dauerhaft.
* Ohne SMTP: kein Reset, keine Einladung, keine Alarm-Mails (Monitoring meldet das als Warnung).
* Der Schlüssel liegt zusätzlich auf dem Server (sonst keine automatische Sicherung). Wer root auf dem Server hat,
  kann Sicherungen lesen — wie die Live-Daten auch.
* Nicht real geprüft: echter S3-Anbieter (nur S3-kompatibler Test-Server moto), echter SMTP-Anbieter (nur Test-Senke),
  `HQ_HEARTBEAT_URL` gegen einen echten Dienst, systemd-Timer im Betrieb.
