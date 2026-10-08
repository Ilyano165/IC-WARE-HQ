# IC WARE HQ — Produktvision v2

> **Status: ENTWURF — von Claude erstellt, nicht vom Produktverantwortlichen bestätigt.**
> Erstellt am 08.10.2026 auf ausdrückliche Bitte („die Produktvision gibt es nicht, also erfinde sie"),
> weil keine Vorlage existierte. Grundlage: M0-Kurzfassung (`docs/m0-zielarchitektur.md`), die bisherigen
> Aufträge im Projekt (C0 Core, D0 Dashboard, Steuerberater-Szenario, Fahrtenbuch-Grundsatz, Reihenfolge
> Tor 1 → C0 → U1 → D0 → S1 …) und eine Recherche der Steuerwerte (Abschnitt 3).
>
> Kennzeichnung im Text: **[VORGABE]** = so vom Auftraggeber gesagt · **[ANNAHME]** = von Claude
> vorgeschlagen, muss bestätigt werden · **[OFFEN]** = bewusst nicht entschieden.
> Bis zur Bestätigung gilt: Wo diese Vision etwas *verschärft* (Sicherheit, Nachvollziehbarkeit), wird sie
> befolgt. Wo sie Umfang, Preis oder Zielgruppe festlegt, ist sie nur ein Vorschlag.

---

## 1. Worum es geht

### 1.1 Ein Satz
IC WARE HQ ist das **Back-Office für kleine Firmen in Deutschland**: Belege, Fahrten, Reisen, Bewirtungen,
Rechnungen, Aufgaben und die Zusammenarbeit mit dem Steuerberater an einem Ort — so geführt, dass am
Monatsende nichts fehlt und nichts nachträglich unbemerkt verändert werden kann. **[ANNAHME, Kern aus ADR-007-Auftrag]**

### 1.2 Warum dieser Fokus (und nicht „digitales Betriebssystem für alles")
M0 nennt als großes Risiko den **Wettbewerb gegen Generalisten** und fordert „Nische schärfen". Zwei Personen
können kein besseres CRM als HubSpot, kein besseres Projekttool als Asana und keine bessere Buchhaltung als
DATEV bauen. Was es für kleine deutsche Firmen kaum gut gibt: **die Strecke zwischen Alltag und Steuerberater**
— Beleg fotografiert, Fahrt erfasst, Bewirtung begründet, Rückfrage des Steuerberaters beantwortet,
Monat abgeschlossen. Dort ist der Schmerz konkret (Zettelwirtschaft, verworfene Fahrtenbücher, fehlende
Bewirtungsangaben, Rückfragen per E-Mail) und der Nutzen messbar. **[ANNAHME]**

### 1.3 Für wen
| Zielgruppe | Merkmal | Warum passend |
| --- | --- | --- |
| Inhabergeführte Firmen, 1–20 Personen | Handwerk, Agenturen, Beratung, Dienstleister | haben Steuerberater, aber keine eigene Buchhaltungsabteilung |
| mit Firmenfahrzeugen oder Außendienst | Fahrtenbuch, Reisen | höchstes Risiko bei Betriebsprüfungen (1-%-Regel statt Fahrtenbuch) |
| mit Kundenbewirtung / Reisen | Bewirtungsbelege, Reisekosten | formale Nachweispflichten, oft unvollständig |

**Nicht** Zielgruppe in v2: Konzerne, Firmen mit eigener Finanzabteilung und ERP, reine B2C-Shops,
Firmen außerhalb Deutschlands. **[ANNAHME]**

### 1.4 Rollen [VORGABE aus D0-Auftrag, Rechte-Umsetzung ANNAHME]
| Rolle | will wissen / tun | sieht nicht |
| --- | --- | --- |
| **Geschäftsführung** | Was muss ich heute wissen oder erledigen? Liquidität, offene/überfällige Rechnungen, Projekte, Steuertermine, fehlende Belege, Fristen, Aufgaben, Warnungen | — |
| **Mitarbeiter** | eigene Aufgaben, Fahrten, Reisekosten, Zeiten, zugewiesene Projekte | Daten anderer, Firmenfinanzen |
| **Steuerberater** (extern) | offene Rückfragen, nicht abgeschlossene Monate, fehlende Belege, Exportstatus, Kommentare | HR-Daten, alles nicht Freigegebene |

Rollen sind **Bündel von Rechten**, keine Sonderfälle im Code (CLAUDE.md Regel 5). Der Steuerberater bekommt
seinen eingeschränkten Sichtbereich über fehlendes `objects.read_all` + Freigaben (ADR-009).

### 1.5 Was HQ ausdrücklich NICHT ist
- **keine Buchhaltung und kein Ersatz für DATEV/Steuerberater** — HQ bereitet vor und exportiert, der
  Steuerberater bucht. **[ANNAHME]**
- **keine Steuerberatung** — Hinweise mit Quelle, Entscheidungen trifft der Mensch (Abschnitt 2, Regel 3).
- kein allgemeines Statistik-Dashboard (D0-Auftrag), kein CRM-Konkurrent, kein Chat-Tool.
- **keine Rechtssicherheits-Versprechen** (GoBD, XRechnung) ohne externe Prüfung (M0-Risiko „Rechtsversprechen").

---

## 2. Steuerfunktionen — fünf Regeln (nicht verhandelbar)

Diese Regeln gelten für jedes Modul, das steuerlich relevante Daten erfasst (S1–S8). **[ANNAHME für die
Formulierung; Regel 2 enthält die VORGABE zum Fahrtenbuch]**

1. **Kein Steuerwert ohne amtliche Quelle.** Jeder Betrag, Satz oder jede Grenze (Pauschalen, Prozentsätze,
   Fristen) steht als **Daten** in einer versionierten Wertetabelle mit Gültigkeit *von–bis*, Fundstelle
   (Gesetz, BMF-Schreiben) und Prüfdatum — nie als Konstante im Code. Ein Wert ohne bestätigte Fundstelle
   wird nicht verwendet, sondern als „nicht amtlich bestätigt" angezeigt.

2. **Unveränderbarkeit mit sichtbarer Historie.** Steuerlich relevante Aufzeichnungen werden nie
   überschrieben oder gelöscht. Eine Korrektur ist eine neue, sichtbare Version **im Datensatz selbst**
   (wer, wann, was vorher, warum). Nach Abschluss eines Zeitraums (Festschreibung) sind nur noch
   Korrekturbuchungen möglich. Grundlage: GoBD Rz. 58 (ursprünglicher Inhalt muss feststellbar bleiben).
   **Fahrtenbuch-Grundsatz [VORGABE]:** Korrekturen müssen **in der Fahrt selbst** sichtbar sein — kein
   separates Änderungsprotokoll, das man erst suchen muss. Das FG Düsseldorf (Urteil vom 24.11.2023,
   3 K 1887/22 H(L)) hat ein elektronisches Fahrtenbuch verworfen, weil nachträgliche Änderungen nicht
   ausgeschlossen bzw. nicht offengelegt waren und Fahrten nur alle drei bis sechs Wochen nachgetragen
   wurden. Daraus folgt außerdem: **zeitnahe Erfassung** wird erzwungen bzw. sichtbar gemacht
   (Erfassungszeitpunkt ≠ Fahrtzeitpunkt wird angezeigt).

3. **Vorschlag, nicht Entscheidung.** HQ rechnet vor, erinnert und warnt — mit Quelle. Ob etwas steuerlich
   abziehbar ist, entscheidet der Mensch bzw. der Steuerberater. Keine Formulierung wie „steuerlich
   korrekt" oder „GoBD-konform" ohne externe Prüfung.

4. **Belegprinzip.** Kein steuerlich relevanter Eintrag ohne Nachweis (Beleg, Fahrtangaben, Teilnehmer und
   Anlass bei Bewirtung). Fehlende Nachweise sind ein **sichtbarer Zustand** („fehlender Beleg"), kein
   stiller Mangel.

5. **Export statt Insel.** Alles, was der Steuerberater braucht, ist vollständig und nachvollziehbar
   exportierbar (Ziel: DATEV-Format) — mit Exportprotokoll (was, wann, von wem, welcher Zeitraum). Ein
   Datenzugriff der Finanzverwaltung (GoBD-Datenzugriff) muss ohne Sonderentwicklung möglich sein.

---

## 3. Wertetabelle (Stand 08.10.2026)

Prüfmethode: Die amtlichen Seiten (gesetze-im-internet.de, bundesfinanzministerium.de) sind aus der
Entwicklungsumgebung **nicht direkt abrufbar** (Netzwerkrichtlinie, HTTP 403). Geprüft wurde über eine
Websuche, die auf amtliche Domains beschränkt war; die Fundstellen unten sind die Treffer dieser Suche.
**Prüfstatus „Suchtreffer amtlich"** heißt: Wert und Fundstelle stammen aus einem amtlichen Treffer, der
Volltext wurde aber nicht selbst gelesen. Vor Verwendung in S2–S8 (Tor S) ist jeder Wert im Volltext zu prüfen.
Details: `docs/steuerwerte-pruefung.md`.

| Wert | Betrag | gilt ab | Rechtsgrundlage | Fundstelle (amtlich) | Prüfstatus |
| --- | --- | --- | --- | --- | --- |
| Entfernungspauschale | 0,38 €/km ab 1. km, max. 4.500 €/Jahr (Grenze gilt nicht für Pkw-Nutzung, Details prüfen) | 01.01.2026 | § 9 Abs. 1 S. 3 Nr. 4 EStG (StÄndG 2025) | LStH 2026 Anhang 14; BMF-Pressemitteilung 10.09.2025 | Suchtreffer amtlich |
| Kilometersatz Dienstreise Pkw | 0,30 €/km | — | § 9 Abs. 1 S. 3 Nr. 4a EStG i. V. m. BRKG | LStH 2026, Tabelle „Reisekosten bei Auswärtstätigkeiten" | Suchtreffer amtlich |
| Kilometersatz andere motorbetriebene Fahrzeuge | 0,20 €/km | — | wie oben | wie oben | Suchtreffer amtlich |
| Verpflegung Inland, 24 h | 28 € | — | § 9 Abs. 4a EStG | LStH 2026, Tabelle Reisekosten | Suchtreffer amtlich |
| Verpflegung Inland, An-/Abreisetag bzw. > 8 h | 14 € | — | § 9 Abs. 4a EStG | wie oben | Suchtreffer amtlich |
| Übernachtungspauschale Inland (nur Arbeitgebererstattung) | 20 € | — | R 9.7 LStR | wie oben | Suchtreffer amtlich |
| Auslandspauschalen | länderweise | 01.01.2026 | § 9 Abs. 4a EStG | BMF-Schreiben vom 05.12.2025 | Suchtreffer amtlich, Einzelwerte nicht erfasst |
| Bewirtung, abziehbarer Anteil | 70 % | — | § 4 Abs. 5 S. 1 Nr. 2 EStG | gesetze-im-internet.de/estg/__4.html; EStH 2024 | Suchtreffer amtlich |
| Geschenke an Geschäftsfreunde, Freigrenze | 50 € netto je Empfänger/Jahr | (seit 2024) | § 4 Abs. 5 S. 1 Nr. 1 EStG | gesetze-im-internet.de/estg/__4.html | Suchtreffer amtlich; Geltungsbeginn 2024 **nicht amtlich bestätigt** |
| GWG-Sofortabschreibung | 800 € netto | — | § 6 Abs. 2 EStG | EStH 2024 Tabelle; Anlage EÜR 2025 (BMF 29.08.2025) | Suchtreffer amtlich; Fortgeltung 2026 nicht ausdrücklich bestätigt |
| GWG-Verzeichnis ab | > 250 € netto | — | § 6 Abs. 2 EStG | wie oben | Suchtreffer amtlich |
| Sammelposten | > 250 € bis 1.000 €, 5 Jahre | — | § 6 Abs. 2a EStG | wie oben | Suchtreffer amtlich |
| Privatnutzung Kfz pauschal | 1 % des Bruttolistenpreises/Monat (bei > 50 % betrieblicher Nutzung) | — | § 6 Abs. 1 Nr. 4 S. 2 EStG | EStH 2024/2025 Anhang 16 III | Suchtreffer amtlich |
| Privatnutzung E-Fahrzeug | ¼ der Bemessungsgrundlage (BLP ≤ 100.000 €, Anschaffung 2019–2030) | — | § 6 Abs. 1 Nr. 4 S. 2 EStG | EStH 2024/2025 Anhang 16 III | Suchtreffer amtlich |
| Kleinunternehmer | Vorjahr ≤ 25.000 €, lfd. Jahr ≤ 100.000 € | 01.01.2025 | § 19 Abs. 1 UStG (JStG 2024) | BMF-Schreiben 18.03.2025 | Suchtreffer amtlich |
| Aufbewahrung Bücher, Abschlüsse | 10 Jahre | — | § 147 Abs. 3 AO | gesetze-im-internet.de/ao_1977/__147.html | Suchtreffer amtlich |
| Aufbewahrung Buchungsbelege | 8 Jahre | (BEG IV) | § 147 Abs. 3 AO | wie oben | Suchtreffer amtlich; **Stichtag nicht amtlich bestätigt**; Sonderregel Banken/Versicherungen geplant |
| Aufbewahrung sonstige Unterlagen (z. B. Handelsbriefe) | 6 Jahre | — | § 147 Abs. 3 AO | wie oben | Suchtreffer amtlich |
| E-Rechnung empfangen können | Pflicht für alle inländischen Unternehmer | 01.01.2025 | § 14 UStG | BMF-FAQ E-Rechnung; BMF-Schreiben 15.10.2025 | Suchtreffer amtlich |
| E-Rechnung ausstellen, Übergang | sonstige Rechnung bis 31.12.2026; bei Vorjahresumsatz ≤ 800.000 € bis 31.12.2027 | — | § 27 Abs. 38 UStG | BMF-FAQ E-Rechnung | Suchtreffer amtlich; Normtext nicht gelesen |
| GoBD | Fassung vom 14.07.2025 (2. Änderung), Grundfassung 28.11.2019 | 14.07.2025 | BMF-Schreiben | bundesfinanzministerium.de, 2025-07-14-GoBD-2-aenderung | Suchtreffer amtlich; Rz. 58 nur in Fassung 2019 gelesen |

---

## 4. Produktumfang

### 4.1 Bausteine, die schon stehen
M1 Fundament (Mandanten, RLS, Rollen-Schema, Outbox), M2 Anmeldung, C0 Core-Plattform (Objektmodell,
Aufgaben, Kommentare, Dokumente, Aktivität, Benachrichtigungen, Suche, Audit). Siehe `CLAUDE.md`.

### 4.2 Fachmodule (S-Reihe) [ANNAHME für Zuschnitt und Reihenfolge]
| Modul | Kern | Rechte (Registry) | Steuerregeln besonders betroffen |
| --- | --- | --- | --- |
| **S1 Belegeingang** | Upload/Foto, Zuordnung, Prüfstatus, „fehlender Beleg", Steuerberater-Rückfragen | `finance.*`, `files.*` | 4, 2 |
| **S2 Fahrtenbuch & Fahrzeuge** | Fahrten zeitnah erfassen, Korrektur sichtbar in der Fahrt, Festschreibung, 1-%-Vergleich nur als Hinweis | `vehicles.*` | 2 (Fahrtenbuch-Grundsatz), 1 |
| **S3 Reisen & Reisekosten** | Reise, Abwesenheitszeiten, Pauschalen aus Wertetabelle, Belege | `travel.*` | 1, 4 |
| **S4 Bewirtung** | Anlass, Teilnehmer, Ort, Beleg, 70-%-Hinweis | `hospitality.*` | 4, 1 |
| **S5 Rechnungen & E-Rechnung** | Ausgangsrechnungen, XRechnung/ZUGFeRD erzeugen und empfangen | `invoices.*`, `customers.*` | 2, 5 |
| **S6 Zahlungen & Liquidität** | Zahlungseingang, Abgleich, offene Posten, Liquiditätsblick | `finance.*` | 3 |
| **S7 Steuerberater-Arbeitsplatz & Export** | Monate abschließen, Exportstatus, DATEV-Export mit Protokoll | `finance.export` | 5, 2 |
| **S8 Steuertermine & Fristen** | Termine (USt-VA u. a.) als Erinnerung, Quelle je Termin | `finance.read` | 1, 3 |

Lieferanten (`suppliers.*`) und Verträge (`contracts.*`) sind Querschnittsobjekte für S1/S5/S6.

### 4.3 Dashboard (D0) [VORGABE aus D0-Auftrag]
Beantwortet „Was muss ich heute in meiner Firma wissen oder erledigen?" — je Rolle, jeder Wert
nachvollziehbar bis zum Einzelobjekt (Wert → Liste → Objekt → Kunde → Projekt), keine erfundenen Zahlen,
fehlende Daten als „keine Daten vorhanden". Widgets einzeln, rechtegeprüft, tenant-safe. Kommt **nach U1**.

---

## 5. Roadmap und Tore

Reihenfolge **[VORGABE]**: **Tor 1 / M3 → C0 → U1 → D0 → S1 …** — D0 erst nach C0 und U1; keine S-Module vor
Tor 1. Die M0-Meilensteine bleiben gültig; diese Tabelle ordnet sie neu, wo die Vision es verlangt.

| Phase | Inhalt | Stand |
| --- | --- | --- |
| Fundament | M0 ✅ · M1 ✅ · M2 (Kern ✅, Abschluss offen) · **M3 Mandanten** | in Arbeit |
| **Tor 1** | Isolation bewiesen: Fremd-ID-Tests je Endpunkt grün, RLS greift (M0) | offen |
| C0 Core | Querschnitts-Bausteine (vor Tor 1 gebaut, ADR-010; nach Tor 1 abnehmen) | gebaut |
| M4 Rollen & Rechte | Rollenverwaltung, Einzelrechte, Ressourcen-DENY, Vorlagen „Geschäftsführung / Mitarbeiter / Steuerberater" | offen **[ANNAHME: vor U1]** |
| **U1 UI-Shell** | = M5; vorher ADR-004 (HTMX oder React) entscheiden; mobil nutzbar | offen |
| **D0 Dashboard** | siehe 4.3 | offen |
| **S1–S8** | Fachmodule nach 4.2 | offen |
| **Tor S** (Steuerfunktionen) | siehe unten | offen |
| Tor 2 Eigenbetrieb | IC Ware nutzt HQ selbst (M0) | offen |
| Tor 3 Erster zahlender Kunde | AVV, Pentest (M0) — **und Tor S für jedes verkaufte S-Modul** | offen |
| Tor 4 Release | M0 | offen |

### Tor S — Steuerfunktionen dürfen genutzt/verkauft werden, wenn [ANNAHME]
1. Jeder verwendete Wert der Wertetabelle ist im **Volltext** der amtlichen Quelle geprüft (Prüfdatum, Prüfer).
2. Regel 2 ist technisch bewiesen: Tests + Mutationen zeigen, dass Änderungen nur als sichtbare Version
   möglich sind und Festschreibung wirkt — auch gegen direkten Datenbankzugriff der App-Rolle.
3. Eine **Verfahrensdokumentation** (GoBD) liegt im Entwurf vor.
4. Ein **Steuerberater** hat die Abläufe S1–S4/S7 fachlich durchgesehen (schriftliche Rückmeldung).
5. Export (S7) wurde mit einem echten Steuerberater-Import erprobt.
6. Keine Marketing- oder UI-Aussage verspricht Rechtssicherheit.

---

## 6. Prinzipien für Produktentscheidungen [ANNAHME]
- **Weniger, aber prüfbar:** lieber ein Modul, das eine Betriebsprüfung übersteht, als fünf halbe.
- **Nachvollziehbar statt clever:** jede Zahl erklärt ihre Herkunft (D0), jede Warnung ihre Quelle.
- **Steuerberater als Partner, nicht als Gegner:** Zugang eingeschränkt, aber bequem; Rückfragen im Objekt.
- **Sicherheit vor Funktion:** Mandantenisolation ist existenzbedrohend (M0) — Tor 1 vor allem anderen.

## 7. Offene Fragen
- [ ] **Bestätigung dieser Vision insgesamt** (Zielgruppe, Nicht-Ziele, S-Zuschnitt, Tor S).
- [ ] Preis- und Lizenzmodell (M0: Einmallizenz → Abo); lokale Edition ja/nein (M0).
- [ ] DATEV-Export: Format/Schnittstelle und ob eine DATEV-Partnerschaft nötig ist.
- [ ] Zeiterfassung (D0 nennt „eigene Zeiterfassung"): Teil von HQ oder Integration? Arbeitszeiterfassung hat
      eigene arbeitsrechtliche Anforderungen — **nicht geprüft**.
- [ ] Sind Kommentare/Rückfragen GoBD-relevant (Handels-/Geschäftsbriefe, § 147 Abs. 1 AO)? Siehe
      `docs/core-activity-model.md` — fachlich ungeklärt.
- [ ] Bankanbindung für S6 (FinTS/PSD2-Anbieter) und deren AVV.
- [ ] Wer ist „Steuerberater" technisch: Mitglied der Mandantenfirma oder eigener Kanzlei-Mandant mit Zugriff
      auf mehrere Firmen? (Heute: Mitglied je Firma.)
