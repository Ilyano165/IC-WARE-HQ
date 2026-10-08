# ADR-006: Brute-Force-Schutz in PostgreSQL statt Redis

**Status:** angenommen (M2, nachträglich dokumentiert) · **Abweichung von:** M0 („Login-Sperre in Redis")

## Kontext
M0 sah Redis für Queue und Login-Sperren vor. M1 hat die Queue bereits als Transactional Outbox in PostgreSQL
umgesetzt (keine zweite Infrastruktur). Für M2 stellte sich dieselbe Frage für Drosselung und Kontosperre.

## Entscheidung
Fehlversuche, Drosselung und Sperren liegen in PostgreSQL:
- `login_attempts` (Art, gehashtes Subjekt per HMAC, IP, Erfolg, Zeit) — Drosselung je IP und je Login-Name im
  Zeitfenster (Standard 15 min: 30 je IP, 10 je Name, auch für Namen ohne Konto).
- Kontosperre am Konto (`users.failed_logins`, `status = 'locked'`, `locked_until`; Standard 5 Fehlversuche → 15 min).
- Der Fehlversuch wird in **derselben Transaktion** geschrieben wie die Prüfung; Auth-Funktionen geben `Outcome`
  zurück statt Ausnahmen zu werfen, damit kein Rollback den Versuch verschluckt (CLAUDE.md, Fallstricke).
- Aufräumen alter Versuche: `ichq auth-cleanup` (systemd-Timer, 30 Tage).

## Abwägung
| | PostgreSQL | Redis |
| --- | --- | --- |
| Infrastruktur | vorhanden | zusätzlicher Dienst, Backup, Monitoring, Absicherung |
| Konsistenz mit Konto/Sitzung | gleiche Transaktion | zwei Systeme, kein gemeinsamer Commit |
| Überlebt Neustart | ja | nur mit Persistenz |
| Last je Login | 1 INSERT + 1 Zählabfrage über Index (`kind, subject_hash, occurred_at` / `kind, ip, occurred_at`) | O(1) im Speicher |
| Angreifbar durch Massenanfragen | Schreiblast auf DB | Speicherlast auf Redis |

## Verworfen
- **Redis jetzt:** zusätzlicher Betriebsaufwand für zwei Personen ohne gemessenen Bedarf.
- **Nur In-Memory im App-Prozess:** gilt nicht über mehrere Worker/Prozesse, verliert alles beim Neustart.
- **Nur am Rand (Caddy) drosseln:** kennt keine Login-Namen, keine Kontosperre; bleibt als zusätzliche Schicht sinnvoll.

## Folgen und Grenzen
- **Sperr-DoS:** Wer einen Login-Namen kennt, kann das Konto mit 5 falschen Passwörtern für 15 Minuten sperren.
  Bewusst in Kauf genommen (bekannte Grenze, `docs/authentication.md`).
- **Ab wann Redis (oder Rand-Drosselung) nötig wird — Schätzung, nicht gemessen:** wenn Login-Anfragen dauerhaft
  in die Größenordnung hunderter pro Sekunde kommen oder ein Angriff die Datenbank messbar belastet (p95 der
  Login-Abfrage > 50 ms, Anteil der Auth-Schreiblast an der DB > 10 %). Vor Tor 4 einen Lasttest (M24) mit diesem
  Kriterium fahren. Ein Umstieg betrifft nur `ichq.auth.throttle` (zwei Funktionen).
