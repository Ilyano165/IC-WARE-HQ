# Datenschutzkonzept IC WARE HQ

> **Status: ENTWURF — von Claude erstellt, keine Rechtsberatung, nicht von einer Datenschutzberatung geprüft.**
> Erstellt am 08.10.2026 als Voraussetzung für das CRM (Export und Löschung „nach dem bestehenden
> Datenschutzkonzept" — ein solches existierte nicht). Kennzeichnung: **[RECHT]** = Normtext/Behördenquelle (Quellen
> unten; Volltexte teils nur über Suchtreffer geprüft) · **[VORSCHLAG]** = technische/organisatorische Umsetzung in HQ ·
> **[OFFEN]** = muss von einer fachkundigen Person entschieden werden. Vor dem ersten Kunden (Tor 3) durch eine
> Datenschutzberatung prüfen lassen.

## 1. Rollen

| Wer | Rolle nach DSGVO | Folge für HQ |
| --- | --- | --- |
| Kundenfirma (Mandant) | **Verantwortlicher** für die Daten, die sie in HQ pflegt (eigene Kunden, Kontakte, Mitarbeiter) | entscheidet über Zweck, Speicherdauer, Auskunft, Löschung |
| IC Ware GbR als Betreiber | **Auftragsverarbeiter** (Art. 28 DSGVO) für diese Daten — auch ohne inhaltlichen Zugriff [RECHT, DSK-Kurzpapier 13: Cloud-Betrieb ist typischer Fall] | AVV vor dem ersten Kunden (M0), Unterauftragnehmer (Hoster, Mail, Backup-Ziel) nur mit Genehmigung |
| IC Ware GbR | Verantwortlicher für eigene Daten: Konten der Nutzer (Login), Plattform-Audit, Abrechnung | eigene Datenschutzerklärung, eigene Löschfristen |

HQ muss den Verantwortlichen **befähigen**, seine Pflichten zu erfüllen (Auskunft, Export, Löschung, Einschränkung) — HQ
entscheidet nicht für ihn. Daraus folgt: Funktionen, keine automatischen Rechtsentscheidungen. [VORSCHLAG]

## 2. Grundsätze für jedes Modul [VORSCHLAG, abgeleitet aus Art. 5 DSGVO]

1. **Datenminimierung:** Jedes personenbezogene Feld braucht einen Zweck, der im Modul-Dokument steht. Keine
   Freitext-Pflichtfelder für Personen. Keine Felder „auf Vorrat" (z. B. Geburtsdatum, Privatadresse im CRM nur, wenn
   der Zweck es verlangt).
2. **Zweckbindung je Datenkategorie** (Tabelle 3). Neue Kategorie ⇒ Konzept ergänzen, bevor Code entsteht.
3. **Speicherbegrenzung:** jede Kategorie hat eine Löschregel mit Startzeitpunkt (Tabelle 3).
4. **Nachweisbarkeit (Art. 5 Abs. 2):** Löschungen, Exporte, Einschränkungen werden protokolliert — **ohne** die
   gelöschten Inhalte (Protokoll enthält nur öffentliche IDs, Zeitpunkt, Akteur, Kategorie, Anzahl).
5. **Mandantentrennung** ist Teil des Datenschutzes: kein Zugriff einer Firma auf Personen einer anderen (RLS,
   zusammengesetzte Fremdschlüssel, IDOR-Generator — `docs/m3-mandanten.md`).
6. **Kein Support-Generalschlüssel** (M0): Zugriff des Betreibers nur befristet, sichtbar, protokolliert.

## 3. Datenkategorien und Löschregeln

| Kategorie | Beispiele in HQ | Zweck / Rechtsgrundlage (Einschätzung) | Löschregel [VORSCHLAG] | Konflikt mit Aufbewahrung? |
| --- | --- | --- | --- | --- |
| Nutzerkonto | E-Mail, Name, Passwort-Hash, 2FA | Vertragserfüllung (Art. 6 Abs. 1 b) | bei Kontolöschung; Auth-Ereignisse begrenzt (Frist **[OFFEN]**) | nein |
| Mitgliedschaft | Rolle, Status, Titel | Vertrag mit der Kundenfirma | Status `left` sofort; Daten bleiben, solange Audit/Belege darauf verweisen ⇒ Pseudonymisierung (s. 5) | ja (Audit, Belege) |
| CRM-Kontakt | Name, Funktion, dienstliche E-Mail/Telefon | Vertragsanbahnung/-erfüllung (b), berechtigtes Interesse (f) | auf Antrag oder wenn Kunde inaktiv + Frist **[OFFEN]** abgelaufen | ja, wenn Teil von Handelsbriefen/Rechnungen |
| CRM-Kunde (Firma) | Firmenname, Adresse, USt-IdNr. | Vertrag; Rechnungsstellung | bei Personenfirmen (Einzelunternehmer) wie Kontakt behandeln | ja (Rechnungen 8/10 Jahre) |
| Kommunikation | Telefonnotiz, E-Mail, Website-Anfrage | Vertragsanbahnung | Website-Anfrage ohne Folgegeschäft: Frist **[OFFEN]**; geschäftliche Korrespondenz: Handelsbrief? (s. 4) | möglich |
| Kommentare + Historie | `comments`, `comment_revisions` | Zusammenarbeit | wie das Objekt, an dem sie hängen | möglich — `core-activity-model.md` |
| Belege, Rechnungen | Dokumente, später S1/S5 | gesetzliche Pflicht (c) | **nicht** vor Fristablauf; danach löschen | ja — das ist die Pflicht selbst |
| Audit (Mandant) | Aktionen, Akteur, öffentliche IDs | Nachweis/Sicherheit (f, c) | Frist **[OFFEN]**; enthält bewusst keine Inhalte | — |
| Auth-Ereignisse | Login, IP | Sicherheit (f) | **[OFFEN]** (Vorschlag: 90 Tage für IP, Ereignis länger ohne IP) | nein |
| Backups | alles | Verfügbarkeit (Art. 32) | Rotation; gelöschte Daten verschwinden mit Ablauf der Backup-Aufbewahrung **[OFFEN: Dauer]** | — |

## 4. Aufbewahrungspflicht vs. Löschanspruch [RECHT, ohne Gewähr]

- Löschpflicht entfällt, soweit die Verarbeitung zur Erfüllung einer **rechtlichen Verpflichtung** erforderlich ist
  (Art. 17 Abs. 3 lit. b DSGVO). Dazu zählen gesetzliche Aufbewahrungspflichten aus HGB/AO.
- Fristen: § 257 Abs. 4 HGB / § 147 Abs. 3 AO — Bücher, Abschlüsse **10 Jahre**, Buchungsbelege **8 Jahre**
  (aktueller Text laut amtlichem Suchtreffer; Stichtag der Änderung nicht selbst gelesen — `docs/steuerwerte-pruefung.md`),
  empfangene/abgesandte **Handelsbriefe 6 Jahre**. Fristbeginn: Ende des Kalenderjahres der Entstehung/des Empfangs.
- Wo Löschung (noch) nicht zulässig ist: **Einschränkung der Verarbeitung** (Art. 18 DSGVO) — Daten bleiben gespeichert,
  werden aber nicht mehr anderweitig verarbeitet. § 35 BDSG regelt Fälle, in denen Einschränkung an die Stelle der
  Löschung tritt (u. a. satzungsgemäße/vertragliche Fristen, Abs. 3); die BfDI hat Bedenken zur Unionsrechtskonformität
  von § 35 BDSG geäußert. **[OFFEN: Für HQ nicht abschließend bewertet.]**
- **Ob Kommentare, Telefonnotizen oder interne CRM-Notizen „Handelsbriefe" oder „sonstige steuerlich bedeutsame
  Unterlagen" sind, hängt vom Inhalt ab und ist nicht allgemein entscheidbar. [OFFEN]** Konsequenz für HQ: Die
  Entscheidung trifft der Verantwortliche je Löschantrag (Abschnitt 6), HQ zeigt nur an, was an Aufbewahrungspflichtiges
  angebunden ist.

## 5. Technische Umsetzung in HQ [VORSCHLAG]

### 5.1 Löschen heißt in HQ eines von drei Dingen
| Verfahren | Wann | Wie |
| --- | --- | --- |
| **Löschen** | keine Aufbewahrungspflicht, keine Verweise aus Aufbewahrungspflichtigem | Datensatz und abhängige Daten entfernen; Dateien im Speicher löschen; Suchtext leeren |
| **Pseudonymisieren** | Person wird gelöscht, aber Audit/Belege verweisen auf sie | personenbezogene Felder ersetzen (`„gelöschte Person #<kurz-id>"`), Kontaktwege leeren; Verweise (FK) bleiben gültig |
| **Einschränken** (Art. 18) | Aufbewahrungsfrist läuft noch | Datensatz als `restricted` markieren: aus Listen, Suche, Benachrichtigungen, Export an Dritte ausgeblendet; lesbar nur mit Sonderrecht; nach Fristablauf automatisch Löschen/Pseudonymisieren |

Physisches Löschen trifft in HQ auf **nur anhängende Tabellen** (`audit_events`, `activities`, `comment_revisions`).
Die enthalten deshalb von Anfang an möglichst wenig Personenbezug (öffentliche IDs statt Namen, keine Inhalte —
bereits so umgesetzt bis auf `comment_revisions.body`). **[OFFEN]** Für `comment_revisions` braucht es einen
kontrollierten, protokollierten Löschpfad nach Fristablauf (heute verhindert der Trigger jede Löschung).

### 5.2 Auskunft und Export (Art. 15, Art. 20)
- Frist **ein Monat** ab Eingang, Verlängerung um zwei Monate nur mit Begründung innerhalb des ersten Monats
  (Art. 12 Abs. 3). [RECHT]
- HQ liefert dem Verantwortlichen je Person einen **maschinenlesbaren Export (JSON)** aller Datensätze, in denen die
  Person vorkommt (Kontakt, Kommunikation, Kommentare, Erwähnungen, Aktivitäten, Dokument-Metadaten), mit Angabe der
  Kategorie und der Löschregel. JSON erfüllt auch Art. 20 („strukturiert, gängig, maschinenlesbar"). [VORSCHLAG]
- Der Export selbst ist ein Audit-Ereignis (ohne Inhalt) und braucht ein eigenes Recht.
- **[OFFEN]** Dateiinhalte (PDF-Belege) mit exportieren oder nur auflisten?

### 5.3 Ablauf eines Löschantrags [VORSCHLAG]
1. Antrag wird im Mandanten als Vorgang erfasst (wer, wann, welche Person, Frist = +1 Monat) — Aufgabe mit Fälligkeit.
2. HQ ermittelt automatisch alle Fundstellen der Person und klassifiziert sie: frei löschbar / verweist auf
   Aufbewahrungspflichtiges / selbst aufbewahrungspflichtig.
3. Eine berechtigte Person entscheidet (Vier-Augen-Prinzip **[OFFEN]**), HQ führt aus: löschen, pseudonymisieren,
   einschränken.
4. Protokoll ohne Inhalte; Bestätigung an die betroffene Person erzeugt der Verantwortliche.
5. Backups: Hinweis an den Verantwortlichen, dass Daten mit Ablauf der Backup-Rotation verschwinden; bei einem Restore
   werden protokollierte Löschungen erneut angewendet (**Löschprotokoll muss Restore überleben** — Pflicht für M22).

### 5.4 Rechte (Vorschlag für die Registry)
Neues Recht **`privacy.manage`** (Auskunft/Export je Person, Löschanträge ausführen) — getrennt von `customers.*` und
`users.*`, damit Vertrieb/Buchhaltung Kontakte pflegen können, ohne Personen löschen oder vollständig exportieren zu
dürfen. Löschung ist zusätzlich an `customers.delete` bzw. `users.deactivate` gebunden. **[OFFEN: Bestätigung]**

### 5.5 Was für das CRM daraus folgt
- Kontakte nur mit dienstlichen Kontaktwegen; private Daten nicht als Felder vorsehen.
- Kunde ↔ Steuer-/Rechnungsdaten getrennt speichern, damit sie getrennt berechtigt (Finanzrecht) **und** getrennt
  behandelt werden können (Rechnungsdaten unterliegen Aufbewahrung, Kontaktdaten oft nicht).
- Website-Anfragen ohne Folgegeschäft: eigene, kurze Löschregel (**[OFFEN: Frist]**).
- Jede CRM-Tabelle mit Personenbezug muss in den Export (5.2) und den Löschablauf (5.3) eingehängt werden — als Test,
  der rot wird, wenn eine neue Tabelle mit Personenbezug nicht registriert ist (analog zur IDOR-Zuordnung).

## 6. Was HQ heute schon erfüllt und was fehlt

| Punkt | Stand |
| --- | --- |
| Mandantentrennung | umgesetzt (RLS, FK, IDOR-Generator; Tor 1 lokal belegt) |
| Minimierung in Audit/Aktivität | umgesetzt (keine Inhalte, öffentliche IDs) |
| Verschlüsselung von Geheimnissen, Passwörter Argon2id | umgesetzt (M2) |
| Firma löschen (M0-Ablauf) | **nicht umgesetzt** (Control Plane, M17) |
| Personenbezogener Export / Löschung / Einschränkung | **nicht umgesetzt** — Vorschlag oben |
| Löschfristen je Kategorie | **nicht festgelegt** [OFFEN] |
| AVV, Verzeichnis der Verarbeitungstätigkeiten (Art. 30), TOMs (Art. 32) | **nicht vorhanden** — vor Tor 3 |
| Meldung von Datenpannen (Art. 33, 72 h) | kein Prozess |

## 7. Offene Entscheidungen (für Datenschutzberatung / Geschäftsführung)
- [ ] Bestätigung der Rollen (Auftragsverarbeitung) und Erstellung des AVV-Musters.
- [ ] Löschfristen je Kategorie (Tabelle 3), Frist für Website-Anfragen, Auth-Ereignisse, Audit, Backups.
- [ ] Sind Kommentare/Notizen/Telefonnotizen im CRM Handelsbriefe bzw. steuerlich bedeutsam? Wer entscheidet im Einzelfall?
- [ ] Löschpfad für nur anhängende Tabellen (`comment_revisions`) nach Fristablauf — technisch und organisatorisch.
- [ ] Vier-Augen-Prinzip für Löschanträge ja/nein.
- [ ] Recht `privacy.manage` einführen.
- [ ] Umfang Export: Dateiinhalte ja/nein.

## Quellen (amtlich bzw. Aufsichtsbehörden; über Suche gefunden, Volltexte teils nicht selbst gelesen)
- DSGVO, Art. 5, 12, 15, 17, 18, 20, 28 — EUR-Lex CELEX:32016R0679
- § 35 BDSG — gesetze-im-internet.de/bdsg_2018/__35.html
- BfDI: Recht auf Löschung (Art. 17), Recht auf Einschränkung (Art. 18)
- DSK Kurzpapier Nr. 11 (Löschung), Nr. 6 (Auskunft), Nr. 13 (Auftragsverarbeitung; laut DSK in Überarbeitung)
- § 257 HGB — gesetze-im-internet.de/hgb/__257.html; § 147 AO — gesetze-im-internet.de/ao_1977/__147.html
- BfDI: Löschkonzept (Beispiel, 2021); BayLDA-Prüfbögen (Löschkonzept nach DIN 66398 inkl. Backups)
