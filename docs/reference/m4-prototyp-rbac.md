> **Referenz, nicht Code-Vorlage.** Dokumentation des RBAC-Prototyps aus IC·HQ 2.x (Flask/SQLite). Laut M0 werden Konzepte und Testszenarien übernommen, der Code wird in M4 auf dem neuen Fundament neu gebaut. Die „Hauptfirma 1"-Übergangslösung gilt NICHT mehr.

# IC·HQ — M4: Rollen & Berechtigungen (RBAC)

Stand: Oktober 2026. Die Tabellen in Abschnitt 2, 3 und 7 sind automatisch aus dem
Code erzeugt, nicht von Hand geschrieben.

---

## 1. Das Modell in einem Satz

**Rollen gewähren Rechte. Einzelrechte und Ressourcen-Freigaben können gewähren oder
verbieten. Ein Verbot schlägt alles. Wer etwas vergibt, muss es selbst haben.**

Es gibt im Code keine einzige Abfrage der Form `if user.role == "ceo"`. Die alte Spalte
`users.rolle` existiert noch (wegen Rückwärtskompatibilität der Datenbank), wird aber
für keine Entscheidung mehr gelesen.

---

## 2. Permission-Hierarchie

Rechte haben die Form `modul.aktion` und stehen alle in einer zentralen Registry
(`RECHTE` in `ic_hq.py`). Es gibt **keine Platzhalter** wie `finance.*` — jedes Recht
wird einzeln vergeben, damit in der Matrix immer sichtbar ist, was genau gilt.

Ein Recht hat vier Eigenschaften:

- **scope** — `company` (in Rollen vergebbar) oder `platform` (nie in Rollen, nur Plattform-Admin)
- **mandantenfähig** — ob die zugehörigen Daten schon je Firma getrennt sind (siehe Abschnitt 5)
- **kritisch** — in der Oberfläche gelb markiert (Rechteverwaltung, Festschreiben, Backup …)
- **vorbereitet** — Recht existiert, die Funktion dahinter noch nicht (gestrichelt in der Matrix)

Es gibt keine implizite Hierarchie zwischen Rechten: `invoices.delete` schließt
`invoices.read` **nicht** ein. Eine Rolle braucht beide, wenn sie beides können soll.
Das ist Absicht — implizite Ketten sind die häufigste Quelle für unbemerkte Rechte.

| Recht | Modul | Bedeutung | Eigenschaften |
|---|---|---|---|
| `dashboard.read` | Dashboard | Dashboard sehen |  |
| `dashboard.feed` | Dashboard | Team-Aktivität sehen |  |
| `users.read` | Benutzer | Benutzer sehen | mandantenfähig |
| `users.create` | Benutzer | Benutzer anlegen | mandantenfähig |
| `users.update` | Benutzer | Benutzer bearbeiten, Passwort zurücksetzen | mandantenfähig, kritisch |
| `users.deactivate` | Benutzer | Benutzer deaktivieren | mandantenfähig, kritisch |
| `users.override` | Benutzer | Einzelrechte (ALLOW/DENY) vergeben | mandantenfähig, kritisch |
| `roles.read` | Rollen | Rollen sehen | mandantenfähig |
| `roles.create` | Rollen | Rollen anlegen und duplizieren | mandantenfähig, kritisch |
| `roles.update` | Rollen | Rollen bearbeiten | mandantenfähig, kritisch |
| `roles.delete` | Rollen | Rollen archivieren und löschen | mandantenfähig, kritisch |
| `roles.assign` | Rollen | Rollen an Benutzer vergeben | mandantenfähig, kritisch |
| `customers.read` | Kunden | Kunden sehen |  |
| `customers.create` | Kunden | Kunden anlegen |  |
| `customers.update` | Kunden | Kunden bearbeiten |  |
| `customers.delete` | Kunden | Kunden löschen |  |
| `customers.export` | Kunden | Kundenliste exportieren |  |
| `inquiries.read` | Anfragen | Anfragen sehen |  |
| `inquiries.create` | Anfragen | Anfragen anlegen |  |
| `inquiries.update` | Anfragen | Anfragen bearbeiten |  |
| `inquiries.delete` | Anfragen | Anfragen löschen |  |
| `projects.read` | Projekte | Projekte sehen |  |
| `projects.create` | Projekte | Projekte anlegen |  |
| `projects.update` | Projekte | Projekte bearbeiten |  |
| `projects.delete` | Projekte | Projekte löschen |  |
| `projects.assign` | Projekte | Projektzugriff an Personen vergeben | kritisch |
| `tasks.read` | Aufgaben | Aufgaben sehen |  |
| `tasks.create` | Aufgaben | Aufgaben anlegen |  |
| `tasks.update` | Aufgaben | Aufgaben abhaken |  |
| `tasks.delete` | Aufgaben | Aufgaben löschen |  |
| `tasks.assign` | Aufgaben | Aufgaben anderen zuweisen |  |
| `notes.read` | Notizen | Notizen sehen |  |
| `notes.create` | Notizen | Notizen anlegen |  |
| `notes.update` | Notizen | Notizen bearbeiten |  |
| `notes.delete` | Notizen | Notizen löschen |  |
| `calendar.read` | Kalender | Termine sehen |  |
| `calendar.create` | Kalender | Termine anlegen |  |
| `calendar.update` | Kalender | Termine bearbeiten |  |
| `calendar.delete` | Kalender | Termine löschen |  |
| `files.read` | Dateien | Dateien sehen und herunterladen |  |
| `files.upload` | Dateien | Dateien hochladen |  |
| `files.update` | Dateien | Ordner anlegen |  |
| `files.delete` | Dateien | Dateien und Ordner löschen |  |
| `files.share` | Dateien | Dateien teilen | vorbereitet |
| `chat.read` | Chat | Chat lesen |  |
| `chat.create` | Chat | Nachrichten schreiben |  |
| `chat.moderate` | Chat | Kanäle anlegen |  |
| `mail.read` | Postfach | Postfach lesen |  |
| `mail.send` | Postfach | Mails senden |  |
| `mail.delete` | Postfach | Mails löschen |  |
| `finance.read` | Finanzen | Finanzen sehen (Ausgaben, EÜR, Entnahmen) |  |
| `finance.create` | Finanzen | Ausgaben und Entnahmen erfassen |  |
| `finance.update` | Finanzen | Ausgaben bearbeiten, Dauerkosten schalten |  |
| `finance.delete` | Finanzen | Ausgaben löschen |  |
| `finance.approve` | Finanzen | Finanzen freigeben | vorbereitet |
| `finance.export` | Finanzen | Finanzdaten exportieren (Steuerberater-CSV) |  |
| `finance.configure` | Finanzen | Firmen- und Bankdaten ändern | kritisch |
| `invoices.read` | Rechnungen | Rechnungen sehen und als PDF öffnen |  |
| `invoices.create` | Rechnungen | Rechnungen und Angebote anlegen |  |
| `invoices.update` | Rechnungen | Bezahlt markieren, mahnen, versenden |  |
| `invoices.delete` | Rechnungen | Rechnungsentwürfe löschen |  |
| `invoices.approve` | Rechnungen | Rechnungen festschreiben und stornieren | kritisch |
| `invoices.export` | Rechnungen | E-Rechnung (XRechnung) exportieren |  |
| `website.read` | Webseite | Webseiten-Auswertung sehen |  |
| `website.export` | Webseite | Besuchsdaten exportieren |  |
| `website.delete` | Webseite | Besuchsdaten löschen |  |
| `audit.read` | Audit-Log | Audit-Log lesen |  |
| `settings.read` | Einstellungen | Systemeinstellungen sehen |  |
| `settings.update` | Einstellungen | Systemeinstellungen ändern (Mail-Zugang) | kritisch |
| `system.backup` | System | Datenbank-Backup herunterladen | kritisch |
| `platform.companies.read` | Plattform · Firmen | Firmen sehen | Plattform |
| `platform.companies.manage` | Plattform · Firmen | Firmen anlegen | Plattform |
| `platform.users.manage` | Plattform · Benutzer | Benutzer firmenübergreifend verwalten | Plattform |

**Abweichungen von der Liste im Auftrag** (bewusst, nicht übersehen):
`customers.export`, `inquiries.*`, `notes.*`, `mail.*`, `website.*`, `finance.delete`,
`finance.configure`, `tasks.delete`, `users.override`, `roles.assign`, `dashboard.feed`,
`system.backup` sind hinzugekommen, weil IC·HQ diese Funktionen hat und sie sonst
unkontrolliert wären. `roles.assign` ist von `roles.update` getrennt: „Rollen definieren"
und „Rollen an Menschen geben" sind verschiedene Befugnisse.

Eine Registry aus „M0/M1" gab es nicht — weder im Code noch in früheren Chats.
Diese Registry ist neu angelegt.

---

## 3. Rollen-Hierarchie

Jede Rolle gehört genau einer Firma und hat einen **Rang** (1–999, höher = mächtiger).

Der Rang regelt nur **Verwaltung**, nicht Rechte:

- Eine Person darf Rollen **bearbeiten, archivieren, löschen** nur, wenn deren Rang
  **unter** ihrem eigenen liegt (strikt kleiner).
- Eine Person darf Rollen **vergeben**, wenn deren Rang **höchstens** ihrem eigenen
  entspricht **und** sie jedes Recht der Rolle selbst besitzt.
- Eine Person darf Rollen **entziehen**, wenn deren Rang höchstens ihrem eigenen
  entspricht. (Archivierte Rollen dürfen immer entzogen werden — sie wirken ohnehin nicht.)
- Eine Person darf eine andere Person nur verwalten, wenn deren Rang höchstens
  ihrem eigenen entspricht.
- Der eigene Rang ist der höchste Rang der eigenen aktiven Rollen.

Mehrere Rollen pro Person addieren sich (Vereinigungsmenge). Eine Rolle kann nichts
verbieten.

### Vorlagen (beim Anlegen einer Firma erzeugt)

| Rolle | Rang | gesperrt | Rechte | Zweck |
|---|---|---|---|---|
| Company Admin | 100 | ja | 70 | Verwaltet Benutzer, Rollen und Einstellungen. Hat immer alle Firmenrechte. |
| CEO | 90 | nein | 60 | Sieht und entscheidet alles Geschäftliche, verwaltet aber keine Rechte. |
| Project Manager | 60 | nein | 30 | Projekte, Aufgaben, Kunden und Termine. |
| Finance Advisor | 50 | nein | 10 | Finanzen und Rechnungen — ohne Löschen und Freigeben. |
| Team | 40 | nein | 55 | Entspricht dem bisherigen „Team“-Konto: alles Geschäftliche, keine Verwaltung. |
| Editor | 30 | nein | 13 | Inhalte und Dateien in Projekten bearbeiten. |
| Cutter | 20 | nein | 9 | Dateien hochladen, Aufgaben abhaken, Chat. |

„Company Admin" ist **gesperrt**: Niemand aus der Firma kann sie bearbeiten oder
archivieren. Sie wird bei jedem Start repariert, hält also immer genau alle Firmenrechte
— auch solche, die eine spätere Version neu einführt. Alle anderen Vorlagen sind
Startpunkte und frei veränderbar.

### Archivieren und Löschen

- **Archivieren** entzieht allen Trägern die Rechte der Rolle sofort, behält sie aber für
  das Audit. Wiederherstellen ist möglich (mit derselben Obergrenzen-Prüfung wie Vergeben).
- **Löschen** geht nur bei archivierten Rollen, die niemand mehr hat.

---

## 4. Override-Priorität

Einzelrechte pro Person haben drei Zustände:

| Zustand | Bedeutung | Speicherung |
|---|---|---|
| **INHERITED** | Kommt aus den Rollen | keine Zeile |
| **ALLOW** | Gilt zusätzlich, auch ohne Rolle | Zeile mit `ALLOW` |
| **DENY** | Gilt nie, egal was eine Rolle sagt | Zeile mit `DENY` |

Die vollständige Entscheidung (`berechtigt()`, die **einzige** Stelle im Programm, an der
über Rechte entschieden wird). Die erste zutreffende Regel gewinnt:

```
 0. Recht unbekannt oder Person deaktiviert        → NEIN
 1. Plattform-Recht                                → nur Plattform-Admin
 2. Person ist Plattform-Admin                     → JA
 3. Geschäftsrecht außerhalb der Hauptfirma        → NEIN   (Mandantengrenze)
 4. Einzelrecht DENY                               → NEIN
 5. Ressourcen-DENY (Projekt / Team / Abteilung)   → NEIN
 6. Einzelrecht ALLOW                              → JA
 7. Ressourcen-ALLOW                               → JA
 8. Eine aktive Rolle der eigenen Firma enthält es → JA
 9. sonst                                          → NEIN
```

**DENY schlägt alles** — auch ein persönliches ALLOW und auch eine Rolle. Ein
Ressourcen-DENY auf ein Projekt sperrt dieses Projekt sogar für jemanden mit persönlichem
ALLOW auf `projects.read`. Das ist die strengste und am leichtesten vorhersagbare
Variante („deny overrides").

Einzelrechte wirken **sofort**, ohne neuen Login: Rechte werden bei jeder Anfrage neu
berechnet, nicht in der Sitzung gespeichert.

### Ressourcen-Rechte

Tabelle `resource_grants`: *Subjekt* (Person, Rolle, Team, Abteilung) bekommt für eine
*Ressource* (Projekt, Team, Abteilung) ein Recht mit ALLOW oder DENY.

Ein Projekt erbt Freigaben von seinem Team (`projekte.team_id`) und seiner Abteilung
(`projekte.department_id`). Umgesetzt und getestet sind:

- Projektzugriff pro Person in der Oberfläche (Lesen / Lesen + Bearbeiten / Verbieten)
- Projektliste und Projektseite werten Ressourcen-Rechte aus
- Freigaben über Rolle, Team und Abteilung werden in der Entscheidung berücksichtigt

Für Teams und Abteilungen gibt es Tabellen und die Auswertung, aber **noch keine
Oberfläche** zum Anlegen. Das ist mit „vorbereiten" gemeint.

---

## 5. Mandantengrenzen

**Ehrliche Ausgangslage:** IC·HQ war eine Installation für eine Firma. Kunden, Finanzen,
Dateien, Chat usw. haben **keine** Firmenspalte. M4 führt Firmen ein, macht aber nicht
das ganze Programm mandantenfähig — das wäre ein eigener Meilenstein.

Daraus folgt eine harte Regel, die in `berechtigt()` selbst steckt (nicht in einzelnen
Seiten):

- **Firma 1 (Hauptfirma)** besitzt alle Geschäftsdaten.
- **Jede weitere Firma** hat eigene Benutzer und eigene Rollen und kann diese voll
  verwalten — aber **jedes Geschäftsrecht ist dort gesperrt**, auch für den eigenen
  Company Admin, auch mit ALLOW. Nur Rechte mit „mandantenfähig" (Benutzer, Rollen)
  wirken dort.

Weitere Grenzen:

- Benutzer und Rollen anderer Firmen existieren für Firmen-Admins nicht (404, nicht 403 —
  man erfährt nicht einmal, dass es sie gibt).
- Eine Rolle aus Firma A kann keiner Person aus Firma B zugewiesen werden. Selbst wenn
  eine solche Zeile in der Datenbank stünde, zählt sie nicht: Rollen wirken nur, wenn
  sie zur Firma der Person gehören.
- `?firma=` in der Adresse wird nur bei Plattform-Admins ausgewertet.
- Formularfelder wie `company_id` oder `platform_admin` werden nie gelesen.

Damit eine Nebenfirma überhaupt einen zweiten Admin ernennen kann, gilt beim
**Weitergeben** von Rechten die Mandantensperre nicht (`delegierbar()`). Das ist
gefahrlos: Die gesperrten Rechte bleiben für jeden in dieser Firma wirkungslos.

### Plattform-Admin

- Wird **nur** über die Kommandozeile gesetzt:
  `python ic_hq.py --platform-admin BENUTZERNAME`
  (entfernen: `--platform-admin-entfernen`). Wer am Rechner sitzt, hat ohnehin Zugriff
  auf die Datenbankdatei — mehr Macht entsteht dadurch nicht.
- Es gibt **keine Route**, die das Flag setzt. Ein Test sucht im Quelltext danach.
- Plattform-Rechte (`platform.*`) können in keiner Rolle stehen und nicht als
  Einzelrecht vergeben werden. Versuche werden mit 400 abgelehnt und als
  `eskalationsversuch` protokolliert.
- Plattform-Admins können nur von Plattform-Admins verwaltet werden.
- Ein Plattform-Admin zählt **nicht** als Admin einer Firma (siehe Abschnitt 6).

**Ein Company Admin kann sich auf keinem Weg zum Plattform-Admin machen.** Getestet
über: Formularfeld, Einzelrecht, Rolle bearbeiten, eigene Admin-Rolle, andere Person,
Plattform-Seite direkt aufrufen.

---

## 6. Schutzregeln gegen Rechteausweitung

1. **Obergrenze:** Niemand kann ein Recht vergeben, entziehen (per Einzelrecht) oder in
   eine Rolle schreiben, das er selbst nicht hat.
2. **Keine Lücken-Löschung:** Bearbeitet jemand eine Rolle, bleiben Rechte, die er selbst
   nicht hat, unverändert — er kann sie weder hinzufügen noch entfernen.
3. **Kopieren:** Duplizieren oder „Rechte übernehmen von" übernimmt nur die eigenen Rechte.
4. **Kein Selbstbedienen:** Eigene Rollen, eigene Einzelrechte und der eigene
   Aktiv-Status sind für jeden gesperrt.
5. **Rang:** siehe Abschnitt 3.
6. **Letzter Admin:** Als „Admin" gilt, wer effektiv `users.update`, `roles.update` und
   `roles.assign` hat (ohne Plattform-Flag). Jede Rechteänderung läuft in einer
   Transaktion; fiele die Zahl der Admins einer Firma dadurch auf null, wird
   zurückgerollt. Das gilt für: Rolle entziehen, Rolle bearbeiten, Rolle archivieren,
   Einzelrecht DENY, Person deaktivieren — auch für Plattform-Admins.

---

## 7. Geschützte Endpunkte

Durchsetzung: Ein zentraler `before_request`-Hook (`_rbac_durchsetzen`) prüft **jede**
Anfrage serverseitig, bevor die Seite läuft. Grundlage ist die Tabelle `ENDPUNKT_RECHTE`.

- **Fail closed:** Eine Route, die nicht in der Tabelle steht, wird mit 403 verweigert —
  auch für Admins. Beim Start meldet `rbac_selbsttest()` jede solche Lücke in der
  Konsole. Prüfen ohne Start: `python ic_hq.py --rbac-pruefen`
- **Unteraktionen:** Formulare mit `aktion=…` (z. B. Kunde löschen vs. bearbeiten) werden
  einzeln geprüft.
- **Ausblenden ist keine Sicherung:** Die Navigation blendet Module ohne Leserecht aus,
  aber jeder Direktaufruf wird trotzdem serverseitig geprüft.
- **Querschnittsfunktionen filtern selbst:** Suche, Verweis-Picker, Badge-Zähler,
  Dashboard und Chat-Verweise zeigen nur Inhalte, für die Leserecht besteht — bei
  Projekten pro Projekt, also inklusive Projektfreigaben und Projektsperren. Ein
  Verweis `rechnung:12` bleibt ohne `invoices.read` reiner Text — ohne Link und ohne
  Rechnungsnummer.

| Pfad | Methode | Erforderliches Recht |
|---|---|---|
| `/` | GET | `dashboard.read` |
| `/admin` | GET | `users.read` |
| `/admin/<int:uid>/aktiv` | POST | `users.deactivate` |
| `/admin/<int:uid>/reset` | POST | `users.update` |
| `/admin/audit` | GET | `audit.read` |
| `/admin/backup.db` | GET | `system.backup` |
| `/admin/matrix` | GET | `roles.read` |
| `/admin/neu` | POST | `users.create` |
| `/admin/nutzer/<int:uid>` | GET | `users.read` |
| `/admin/nutzer/<int:uid>/projekte` | POST | `projects.assign` |
| `/admin/nutzer/<int:uid>/rechte` | POST | `users.override` |
| `/admin/nutzer/<int:uid>/rollen` | POST | `roles.assign` |
| `/admin/rollen` | GET,POST | GET: `roles.read`<br>POST: `roles.create` |
| `/admin/rollen/<int:rid>` | GET,POST | GET: `roles.read`<br>POST: `roles.update` |
| `/admin/rollen/<int:rid>/archivieren` | POST | `roles.delete` |
| `/admin/rollen/<int:rid>/duplizieren` | POST | `roles.create` |
| `/admin/rollen/<int:rid>/loeschen` | POST | `roles.delete` |
| `/anfragen` | GET | `inquiries.read` |
| `/anfragen/<int:aid>` | GET,POST | GET: `inquiries.read`<br>POST: aktion=loeschen: `inquiries.delete`; aktion=kunde: `inquiries.update` **und** `customers.create`; aktion=projekt: `inquiries.update` **und** `projects.create`; `inquiries.update` |
| `/anfragen/neu` | GET,POST | `inquiries.create` |
| `/api/chat/<int:cid>/messages` | GET | `chat.read` |
| `/api/finanzen` | GET | `finance.read` |
| `/api/unread` | GET | jeder Angemeldete (filtert selbst) |
| `/api/verweise` | GET | jeder Angemeldete (filtert selbst) |
| `/app.js` | GET | öffentlich |
| `/chat` | GET | `chat.read` |
| `/chat/<int:cid>` | GET | `chat.read` |
| `/chat/<int:cid>/senden` | POST | `chat.create` |
| `/chat/dm` | POST | `chat.create` |
| `/chat/neu` | POST | `chat.moderate` |
| `/dateien` | GET | `files.read` |
| `/dateien/d/<int:did>` | GET | `files.read` |
| `/dateien/d/<int:did>/loeschen` | POST | `files.delete` |
| `/dateien/o/<int:oid>` | GET | `files.read` |
| `/dateien/o/<int:oid>/loeschen` | POST | `files.delete` |
| `/dateien/ordner-neu` | POST | `files.update` |
| `/dateien/upload` | POST | `files.upload` |
| `/einstellungen` | GET,POST | GET: jeder Angemeldete (filtert selbst)<br>POST: aktion=mail: `settings.update`; aktion=mailtest: `settings.update`; jeder Angemeldete (filtert selbst) |
| `/finanzen` | GET | `finance.read` |
| `/finanzen/a/<int:aid>` | GET | `finance.read` |
| `/finanzen/a/<int:aid>/loeschen` | POST | `finance.delete` |
| `/finanzen/a/neu` | GET,POST | `finance.create` |
| `/finanzen/ausgaben` | GET | `finance.read` |
| `/finanzen/auswertung` | GET | `finance.read` |
| `/finanzen/dauerkosten` | GET,POST | GET: `finance.read`<br>POST: `finance.create` |
| `/finanzen/dauerkosten/<int:did>/aus` | POST | `finance.update` |
| `/finanzen/einstellungen` | GET,POST | `finance.configure` |
| `/finanzen/entnahmen` | GET,POST | GET: `finance.read`<br>POST: `finance.create` |
| `/finanzen/export.csv` | GET | `finance.export` |
| `/finanzen/r/<int:rid>` | GET | `invoices.read` |
| `/finanzen/r/<int:rid>/bezahlt` | POST | `invoices.update` |
| `/finanzen/r/<int:rid>/festschreiben` | POST | `invoices.approve` |
| `/finanzen/r/<int:rid>/loeschen` | POST | `invoices.delete` |
| `/finanzen/r/<int:rid>/mahnung` | POST | `invoices.update` |
| `/finanzen/r/<int:rid>/mailen` | POST | `invoices.update` **und** `mail.send` |
| `/finanzen/r/<int:rid>/pdf` | GET | `invoices.read` |
| `/finanzen/r/<int:rid>/storno` | POST | `invoices.approve` |
| `/finanzen/r/<int:rid>/xrechnung.xml` | GET | `invoices.export` |
| `/finanzen/r/<int:rid>/zu_rechnung` | POST | `invoices.create` |
| `/finanzen/r/neu` | GET,POST | `invoices.create` |
| `/finanzen/rechnungen` | GET | `invoices.read` |
| `/fonts/<path:name>` | GET | öffentlich |
| `/kunden` | GET | `customers.read` |
| `/kunden/<int:kid>` | GET,POST | GET: `customers.read`<br>POST: aktion=loeschen: `customers.delete`; `customers.update` |
| `/kunden/export.csv` | GET | `customers.export` |
| `/kunden/neu` | GET,POST | `customers.create` |
| `/login` | GET,POST | öffentlich |
| `/login/2fa` | GET,POST | öffentlich |
| `/logout` | GET | öffentlich |
| `/notizen` | GET | `notes.read` |
| `/notizen/<int:nid>` | GET | `notes.read` |
| `/notizen/<int:nid>/bearbeiten` | GET,POST | `notes.update` |
| `/notizen/<int:nid>/loeschen` | POST | `notes.delete` |
| `/notizen/<int:nid>/pin` | POST | `notes.update` |
| `/notizen/neu` | GET,POST | `notes.create` |
| `/passwort` | GET,POST | jeder Angemeldete (filtert selbst) |
| `/plattform` | GET,POST | GET: `platform.companies.read`<br>POST: `platform.companies.manage` |
| `/postfach` | GET | `mail.read` |
| `/postfach/aktualisieren` | POST | `mail.read` |
| `/postfach/mail/<uid>` | GET | `mail.read` |
| `/postfach/mail/<uid>/anhang/<int:idx>` | GET | `mail.read` |
| `/postfach/mail/<uid>/antworten` | POST | `mail.send` |
| `/postfach/mail/<uid>/lead` | POST | `mail.read` **und** `customers.create` |
| `/postfach/mail/<uid>/loeschen` | POST | `mail.delete` |
| `/postfach/verfassen` | GET,POST | `mail.send` |
| `/projekte` | GET | `projects.read` · Liste gefiltert |
| `/projekte/<int:pid>` | GET,POST | GET: `projects.read`<br>POST: aktion=loeschen: `projects.delete`; `projects.update` · Ressource project |
| `/projekte/<int:pid>/status` | POST | `projects.update` · Ressource project |
| `/projekte/neu` | GET,POST | `projects.create` |
| `/static.css` | GET | öffentlich |
| `/static/<path:filename>` | GET | öffentlich |
| `/suche` | GET | jeder Angemeldete (filtert selbst) |
| `/termine` | GET | `calendar.read` |
| `/termine/<int:tid>` | GET,POST | GET: `calendar.read`<br>POST: aktion=loeschen: `calendar.delete`; `calendar.update` |
| `/termine/neu` | GET,POST | `calendar.create` |
| `/todos` | GET | `tasks.read` |
| `/todos/<int:tid>/loeschen` | POST | `tasks.delete` |
| `/todos/<int:tid>/toggle` | POST | `tasks.update` |
| `/todos/neu` | POST | `tasks.create` |
| `/webseite` | GET | `website.read` |
| `/webseite/export.csv` | GET | `website.export` |
| `/webseite/loeschen` | GET,POST | `website.delete` |

Der öffentliche Website-Server (zweiter Port) ist eine eigene Flask-Anwendung ohne
Zugang zu diesen Routen. Getestet: `/admin`, `/admin/rollen`, `/plattform`, `/login`
liefern dort 404.

---

## 8. Oberfläche

**Benutzer & Rechte** (Seitenleiste) mit Reitern:

- **Benutzer** — Liste mit Rollen; Anlegen mit Rollenwahl (nur vergebbare Rollen)
- **Person** — Rollen (Checkboxen), *Was diese Person darf* (Live-Vorschau mit Quelle je
  Recht), Einzelrechte (Geerbt/Erlauben/Verbieten je Recht), Projektzugriff
- **Rollen** — Liste, anlegen, duplizieren, archivieren
- **Rolle** — Editor als Matrix: Modul links, Aktionen als ✓/✗-Schalter. Gelb =
  kritisch, gestrichelt = vorbereitet, grau = du hast das Recht selbst nicht.
  Darunter die Vorschau „Wer nur diese Rolle hat, darf …"
- **Rechte-Matrix** — alle Rollen × alle Rechte auf einer Seite
- **Plattform** — nur für Plattform-Admins: Firmen anlegen

---

## 9. Bekannte Grenzen (nicht gelöst in M4)

- **Geschäftsdaten sind nicht mandantenfähig** (Abschnitt 5). Nebenfirmen können nur
  Benutzer und Rollen verwalten.
- **Team/Abteilung ohne Oberfläche.** Datenmodell und Auswertung stehen, Anlegen geht
  nur per Datenbank.
- **Ressourcen-Rechte nur für Projekte.** Kunden, Dateien usw. kennen nur globale Rechte.
- **Der Aktivitätsverlauf** (`dashboard.feed`) ist Freitext aus allen Modulen und kann
  Rechnungsnummern und Beträge nennen. Deshalb ist er ein eigenes Recht.
- **Audit-Log ist nicht mandantenfähig** — `audit.read` wirkt nur in der Hauptfirma.
- `files.share`, `finance.approve` sind vorbereitet, ohne Funktion dahinter.
- Plattform-Admin-Setzen braucht Konsolenzugriff am Rechner. Auf einem gemeinsam
  genutzten Rechner ist das kein Schutz.

---

## 10. Tests

| Datei | Art | Ergebnis |
|---|---|---|
| `tests/test_m4.py` | gegen den laufenden Server, frische Datenbank | 181 / 181 |
| `tests/test_m4_intern.py` | im Prozess: Upgrade, jede Route, fail closed, Entscheidungsreihenfolge | 26 / 26 |
| Regression Geschäftsmodule + Website | gegen den laufenden Server | 36 / 36 |

Der Routen-Vollabdeckungstest wurde per **Mutationstest** geprüft: Mit absichtlich
geöffneter Kundenliste schlägt er an (`GET /kunden → 200`), ebenso die
Reihenfolge-Tests bei ausgeschaltetem Ressourcen-DENY. Dabei fiel auf, dass der Test
anfangs seine Erwartung aus der zu prüfenden Tabelle selbst las und den Fehler deshalb
**nicht** fand — das ist korrigiert.

Ausführen:
```
# Server starten (eigener Ordner für Testdaten!)
HOME=/tmp/rbactest ICHQ_PORT=8100 ICHQ_NO_BROWSER=1 python ic_hq.py
# zweites Fenster
python tests/test_m4.py 8100 /tmp/rbactest .
python tests/test_m4_intern.py ic_hq.py <Pfad zur Vorversion>/ic_hq.py
```
