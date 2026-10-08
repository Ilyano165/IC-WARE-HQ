# Anmeldung (M2)

Code: `src/ichq/auth/`, Routen `src/ichq/api/v1/auth.py`. Authentifizierung beantwortet nur „wer?" —
Rechte kommen ausschließlich aus Rollen der Mitgliedschaft (`ichq.authz`, CLAUDE.md Regel 5).

## Abläufe

**Login** `POST /api/v1/auth/login {login, password}` — `login` ist E-Mail oder Benutzername (ohne Groß/klein).
1. Drosselung prüfen (IP, Login-Name). Gedrosselt → 429 mit `Retry-After`.
2. Konto laden (`FOR UPDATE`), Passwort prüfen — bei unbekanntem Konto gegen einen Dummy-Hash (gleiche Laufzeit).
3. Fehlschlag: Versuch speichern, Zähler erhöhen; beim 5. Fehlversuch Sperre 15 min. Antwort immer
   „E-Mail/Benutzername oder Passwort ist falsch" (401) — kein Hinweis, ob das Konto existiert.
4. Erfolg: Zähler zurück, ggf. Hash mit neuen Argon2-Parametern neu schreiben, Sitzung anlegen.
   Mit 2FA: Sitzung im Zustand `mfa_pending` (5 min), sonst `full`.

**2FA** `POST /auth/mfa {code}` — TOTP (RFC 6238, 30 s, 6 Stellen, ±1 Schritt) oder einer von 10 Recovery-Codes.
Ein Code ist nur einmal gültig (letzter Schritt wird gespeichert). 5 falsche Codes → Zwischensitzung widerrufen.
Erfolg → neue Sitzung `full`, alte widerrufen.

**Firmenwahl** `POST /auth/tenant {tenant_id}` — nur mit aktiver Mitgliedschaft in einer Firma `active`/`paused`.
Neue Sitzung mit Firma und Mitgliedschaft (Rotation gegen Session Fixation). Vorher: `/me`, `/company` … → 403 `tenant_required`.

**Abmelden** `/auth/logout` (diese Sitzung), `/auth/logout-all` (alle Sitzungen des Kontos).

**Passwort ändern** `POST /auth/password` — altes Passwort nötig; alle anderen Sitzungen enden, neue Sitzung.

**Passwort vergessen** `POST /auth/password-reset/request {login}` → immer 202 (kein Hinweis auf Existenz), Mail mit
Link `…/reset#token=…` (Token im Fragment, nicht im Serverlog), 30 min gültig, einmalig, ältere Tokens werden
ungültig. `…/confirm {token, new_password}` → alle Sitzungen enden. Ohne Mailer: 503.

**Einladung** (M3) — siehe `docs/m3-mandanten.md`.

**2FA einrichten/ausschalten** `/auth/2fa/setup` (Passwort) → `/2fa/enable` (erster Code) → 10 Recovery-Codes (einmal
angezeigt); `/2fa/disable` und `/2fa/recovery-codes` verlangen Passwort **und** Code.

## Sitzungsregeln
- Browser hält nur ein Zufallstoken (256 Bit) im Cookie; die DB nur dessen SHA-256.
- Ende bei: absolut 12 h (`ICHQ_SESSION_ABSOLUTE_HOURS`), Leerlauf 30 min (`ICHQ_SESSION_IDLE_MINUTES`), Abmelden,
  Passwortwechsel/-reset, Kontostatus nicht mehr `active` — **bei jeder Anfrage geprüft**.
- Jeder Stufenwechsel (Passwort → 2FA → Firma) erzeugt eine neue Sitzung.
- Cookie: `HttpOnly`, `SameSite=Lax`, `Path=/`; mit `Secure` (Produktion bzw. `ICHQ_COOKIE_SECURE=true`) heißt er
  `__Host-ichq_session`, sonst `ichq_session`. Token nie im Antworttext.
- CSRF: unsichere Methoden mit fremdem `Origin` oder `Sec-Fetch-Site: cross-site` → 403 (`OriginGuardMiddleware`).

## Passwortregel (NIST SP 800-63B)
12–128 Zeichen; nicht unter den 10.000 häufigsten Passwörtern (auch nicht mit angehängten Ziffern/`!`/`.`);
enthält nicht E-Mail-Namen oder Benutzernamen; nicht nur ein Zeichen. Keine Pflicht zu Sonderzeichen.
Speicherung Argon2id (Produktion ≥ 64 MiB Speicher).

## Sperren und Drosselung (Standardwerte)
| Grenze | Wert | Variable |
| --- | --- | --- |
| Fehlversuche je Konto bis Sperre | 5 | `ICHQ_LOGIN_MAX_FAILURES` |
| Sperrdauer | 15 min | `ICHQ_LOCKOUT_MINUTES` |
| Fenster der Drosselung | 15 min | `ICHQ_THROTTLE_WINDOW_MINUTES` |
| Fehlversuche je IP im Fenster | 30 | `ICHQ_IP_MAX_FAILURES` |
| Fehlversuche je Login-Name im Fenster | 10 (auch ohne Konto) | `ICHQ_IDENTIFIER_MAX_FAILURES` |
| 2FA-Fehlversuche je Zwischensitzung | 5 | fest |

Begründung PostgreSQL statt Redis: ADR-006.

## Datenbankrolle `ichq_auth`
Liest/schreibt `users` (auch Passwort- und 2FA-Spalten), `auth_sessions`, `password_reset_tokens`, `recovery_codes`,
`login_attempts`; schreibt `auth_events` (nur anhängend). Mitgliedschaften und Firmen sieht sie per RLS nur für das
Konto in `app.user_id`. Einladungen nur lesend (Token-Hash-Suche, M3). Keine andere Rolle sieht Passwort-Hashes.

## Auth-Ereignisse (`auth_events`, nur anhängend)
Vollständige Liste aus dem Code: `login_succeeded`, `login_failed` (mit Grund), `login_throttled`, `mfa_required`,
`mfa_failed`, `mfa_locked_out`, `recovery_code_used`, `account_locked`, `account_unlocked`,
`account_status_changed`, `tenant_selected`, `tenant_selection_denied`, `logout`, `logout_all`, `session_ended`,
`password_changed`, `password_change_failed`, `password_reset_requested`, `password_reset_throttled`,
`password_reset_failed`, `password_reset_completed`, `password_set_by_operator`, `password_set_by_invitation`,
`totp_setup_started`, `totp_setup_failed`, `totp_enabled`, `totp_enable_failed`, `totp_disabled`,
`totp_disable_failed`, `recovery_codes_regenerated`, `recovery_codes_failed`.
Werden nie gelöscht; Aufbewahrungsfrist offen (`docs/datenschutzkonzept.md`).

## Aufräumen
`ichq auth-cleanup [--days 30]` (systemd-Timer `deploy/systemd/ichq-auth-cleanup.*`): alte Anmeldeversuche,
seit > 30 Tagen widerrufene/abgelaufene Sitzungen, benutzte/abgelaufene Reset-Tokens, benutzte Recovery-Codes.

## Bekannte Grenzen — und ob/wann sie behoben werden
| Grenze | Entscheidung |
| --- | --- |
| Tastaturmuster außerhalb der 10k-Liste (z. B. `qwertzuiopü1`) kommen durch | bleibt; optional größere Liste/zxcvbn vor Tor 3 |
| Sperr-DoS: 5 Fehlversuche sperren ein fremdes Konto 15 min | bewusst (ADR-006); Abhilfe erst mit 2FA-Pflicht/Captcha nach Messung |
| `ICHQ_TRUSTED_PROXIES="*"` in Compose | vertretbar, solange der App-Port nur im internen Netz erreichbar ist (so in Compose); bei anderem Aufbau auf Caddy-IP setzen |
| Wechsel von `ICHQ_SECRET_KEY` macht TOTP-Geheimnisse unlesbar | bleibt bis Schlüsselrotation (Versionsbyte ist vorbereitet); vor Tor 3 Rotationsverfahren |
| `invitations/accept` ohne Drosselung (M3) | vor Produktivbetrieb nachziehen |
