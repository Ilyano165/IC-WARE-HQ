# ADR-015: Einzelserver mit Installer, Launcher, lokalem Dateispeicher und Virenscanner

**Status:** angenommen · **Datum:** 08.10.2026 · **Grundlage:** M0 Abschnitt 29, ADR-005 · **Ergänzt:** ADR-005

## Kontext

Auftrag: „ein Launcher/Installer, auf dem die Website über eine feste Domain permanent laufen kann — löse dafür alle
Probleme". Ein echter Lauf des Compose-Stacks (bis dahin nie ausgeführt, siehe `docs/server-setup.md` alt) hat
folgende Fehler gezeigt:

| Problem | Folge |
| --- | --- |
| Image `minio/minio` nicht mehr ziehbar („pull access denied") | Stack startet nicht |
| Secret-Dateien gehören root (600), Container laufen als UID 10001 | `migrate` scheitert: `PermissionError` |
| Caddy mit leerem `email` | Neustart-Schleife („wrong argument count") |
| kein Virenscanner | jedes hochgeladene Dokument bleibt für immer in Quarantäne (Download 409) |
| keine Rolle darf `documents.scan_status` schreiben | auch mit Scanner kein Ergebnis speicherbar |
| geplante Jobs nur als systemd-Timer auf dem Host | ohne Handarbeit laufen keine Benachrichtigungs-/Aufräumjobs |
| `HEAD /app/` → 405 | Monitoring/Uptime-Prüfungen melden Fehler |
| Rollen-Passwörter nur beim ersten Anlegen gesetzt | Wiederherstellung mit gesicherten Secrets: Anmeldung der Dienste scheitert |
| Superuser-Passwort fest seit Cluster-Erstellung | Wiederherstellung auf frischem Server: `db-init` scheitert (im Test gefunden) |

## Entscheidung

1. **Dateien auf einem Docker-Volume** (`ICHQ_STORAGE_BACKEND=local`, Volume `filedata`), alle App-Dienste binden
   dasselbe Volume ein. Abweichung von M0 („S3-kompatibel"): Auf einem Einzelserver bringt ein S3-Dienst keine
   Sicherheit, nur einen weiteren Prozess. Der S3-Code bleibt und ist per Umgebung wieder einschaltbar
   (`ICHQ_STORAGE_BACKEND=s3`); der Schlüsselaufbau `t/<tenant>/f/<file>/v/<n>` ist identisch.
2. **Virenprüfung mit ClamAV** (M0: „Virenscan (ClamAV), Status quarantined bis geprüft"):
   Dienst `clamav` + Dienst `scanner` (`ichq documents-scan --loop 10`), Protokoll clamd `INSTREAM` ohne Zusatzbibliothek
   (`ichq.documents.scan`). Regeln: nur `stream: OK` ist sauber; jede andere, leere oder abgebrochene Antwort lässt
   das Dokument in Quarantäne. Fällt ClamAV mitten im Stapel aus, bleibt bereits Geprüftes gespeichert.
   Migration `0007`: Der Scanner arbeitet als **`ichq_worker`** im Mandantenkontext (RLS je Firma) und darf **nur** die
   Spalte `scan_status` ändern; die Web-App (`ichq_app`) darf das Ergebnis gar nicht schreiben. Ein Trigger erlaubt nur
   `quarantined → clean|infected` — ein infiziertes Dokument kann auch durch einen Programmfehler nie freigegeben werden.
   Ergebnis im Mandanten-Audit (`document.scanned`, mit Signatur).
3. **Geplante Jobs als Compose-Dienst `jobs`** (Schleife, stündlich `notifications-scan` + `auth-cleanup`) statt
   Host-Timer. Beide Jobs sind idempotent und per Advisory-Lock gegen Parallellauf geschützt (C0-Regel). Die
   systemd-Timer in `deploy/systemd/` bleiben als Alternative für Installationen ohne Compose — nicht beides aktivieren.
4. **Secrets bleiben Dateien** (`./secrets`, nie im Repository). `deploy/fix-secret-permissions.sh`: App-Secrets
   gehören UID 10001 (Modus 400), PostgreSQL-Passwörter root (400), Ordner 700. Compose ohne Swarm kann Besitzer nicht
   setzen — daher dieses Skript statt Docker-Optionen.
5. **Die Secret-Dateien sind die einzige Quelle der Datenbank-Passwörter:** `init-roles.sql` gleicht bei jedem Start
   alle Rollen-Passwörter an; die Wiederherstellung setzt zusätzlich das Superuser-Passwort über den lokalen Socket
   (Passwort wird im Container gelesen, steht in keiner Befehlszeile).
6. **Let's-Encrypt-Kontakt ist Pflicht** (`ICHQ_ACME_EMAIL`); Compose bricht ohne ihn mit klarer Meldung ab.
7. **Installer `deploy/install.sh` + Launcher `deploy/hq`** (Bash, keine weitere Abhängigkeit):
   * Installer prüft Eingaben (strenge Zeichenliste — Domain/E-Mail werden vor dem Parsen ins Caddyfile eingesetzt),
     RAM, Ports 80/443, DNS gegen die eigenen Adressen; installiert Docker auf Debian/Ubuntu aus dem offiziellen
     Repository; erzeugt Secrets **nur, wenn keine da sind**; baut, startet, wartet auf Bereitschaft und HTTPS;
     richtet `ichq.service` (Start beim Booten) und `ichq-backup.timer` (täglich 03:15) ein; optional ufw.
     Wiederholbar (Domain ändern = erneut ausführen).
   * `hq`: `status`, `start/stop/restart`, `logs`, `build`, `update` (Sicherung → `git pull --ff-only` → Bau → Start;
     Migration läuft vor der App), `backup`, `restore … --yes`, `setup-admin`, `ichq …`.
   * Image wird **auf dem Server gebaut** (`ic-ware-hq:local`, `pull_policy: never`) — keine Registry, kein
     Zugangsschlüssel, Lockfile mit Hashes wie in CI.
8. **Sicherung = ein Archiv** (`ichq-backup-<UTC>.tar`, Modus 600): `pg_dump -Fc`, Dateien-Volume (nach der Datenbank
   gesichert — Speicherschlüssel sind versioniert, also enthält die Sicherung jede referenzierte Datei), Secrets,
   `.env`, Manifest (Git-Stand, Migration). Die neuesten 14 bleiben. **Wiederherstellung ist vollständig**
   (Datenbank neu, Dateien, Secrets), verlangt `--yes` und bewahrt die vorherigen Secrets als `secrets.vor-restore-*`.
9. **Ende-zu-Ende-Test als Skript und CI-Job** (`deploy/smoke-test.sh`, Job `betrieb`) — siehe „Belege".

## Verworfen

* **Kubernetes / Nomad:** wie ADR-005 — unverhältnismäßig für einen Server.
* **Ansible/Terraform:** zusätzliche Werkzeugkette für genau einen Rechner; Bash-Installer ist les- und prüfbar
  (shellcheck in CI).
* **Ersatz-S3 (SeaweedFS, Garage, neues MinIO-Image):** löst auf einem Server kein Problem und wäre ungetestet.
* **Fertige Images aus einer Registry:** bräuchte Registry-Zugang/Signierung; erst sinnvoll mit Release-Prozess (M26).
* **Virenscan synchron beim Upload:** Upload würde Minuten blockieren, solange ClamAV Signaturen lädt; Quarantäne +
  Hintergrunddienst ist M0-konform und fällt sicher (gesperrt) statt offen aus.

## Folgen und offene Grenzen (ehrlich)

* **Tor 2 ist damit NICHT erfüllt.** M0 verlangt verschlüsselte Sicherung an einem zweiten Standort, WAL-Archivierung
  und einen wöchentlichen automatischen Restore-Test. Die Sicherung hier ist unverschlüsselt, liegt auf demselben
  Server und ist täglich (bis zu 24 h Datenverlust). Sie enthält die Secrets — wer sie hat, hat alles.
  → bis M22: Sicherung verschlüsselt auf einen zweiten Standort kopieren (manuell), danach automatisieren.
* **Ein Server, keine Hochverfügbarkeit.** Update = kurze Unterbrechung (Neustart der App-Container).
* **Kein Monitoring/Alarm.** `hq status` und `/readiness` sind da, niemand wird benachrichtigt.
* **ClamAV braucht ~1,5 GB RAM** (Server ≥ 4 GB) und lädt beim ersten Start Signaturen; bis dahin bleibt alles in
  Quarantäne. Doppelte Scanner-Instanzen sind per `FOR UPDATE SKIP LOCKED` vorgesehen, aber nicht getestet.
* **Docker-Hub-Limit:** Anonyme Pulls sind begrenzt (im Test aufgetreten: 429). `install.sh --dockerhub-mirror
  mirror.gcr.io` baut das Basis-Image über Googles Docker-Hub-Spiegel (getestet), `--no-build` nutzt ein vorhandenes
  Image; dauerhaft hilft `docker login`. `hq update` holt zusätzlich neue PostgreSQL-16-/Caddy-/ClamAV-Images —
  scheitert der Bau, läuft die bisherige Version weiter (getestet).
* **Nicht geprüft:** echtes Let's-Encrypt-Zertifikat (in der Testumgebung nur `localhost` mit Caddys interner CA),
  DNS-Prüfung gegen eine echte Domain, Docker-Installation per apt, ufw, systemd-Units im echten Betrieb
  (nur `systemd-analyze verify`), Neustart des ganzen Servers.

## Belege (08.10.2026, Testumgebung mit Docker 28, ohne systemd)

* `deploy/install.sh --domain localhost …` auf leerem Docker: läuft in 1:29 min durch, HTTPS ok; zweiter Lauf
  idempotent (Secrets unverändert).
* `deploy/smoke-test.sh --wegwerf`: **26 Prüfungen bestanden, 0 fehlgeschlagen** — u. a. EICAR mit echtem ClamAV
  `infected` + 409, sauberes Dokument 200 mit gleichem Inhalt, App läuft als UID 10001, echte Client-IP in
  `auth_events`, App aus → Caddy 503, keine Passwörter/Sitzungs-Token/Query-Strings in Logs, Sicherung →
  `down -v` + Secrets gelöscht → Neuinstallation → Wiederherstellung → Anmeldung mit altem Passwort, Aufgabe und
  Dokument wieder da.
* Neustart von `dockerd`: alle 7 Dienste kamen ohne Eingriff zurück, HTTPS ok (von Hand; in CI mit
  `--docker-neustart` über `systemctl restart docker`).
* `hq update`: Sicherung → `git pull --ff-only` → Bau → Start ok; Aufbewahrung (`HQ_BACKUP_KEEP=2`) löscht die älteste.
