# Prüfung der Steuerwerte (Produktvision v2, Abschnitt 3)

Stand: 08.10.2026 · Prüfer: Claude (keine Steuerberatung, keine Gewähr) · Gegenstand: Wertetabelle in
`docs/produktvision-v2.md`, Abschnitt 3.

## Methode und Grenzen
- **Direktabruf amtlicher Seiten nicht möglich:** `www.gesetze-im-internet.de` und `www.bundesfinanzministerium.de`
  liefern in der Entwicklungsumgebung „CONNECT tunnel failed, response 403" (Netzwerkrichtlinie). Ein Volltext
  der Normen und BMF-Schreiben wurde daher **nicht selbst gelesen**.
- Stattdessen: Websuche, beschränkt auf die Domains `gesetze-im-internet.de`, `bundesfinanzministerium.de`
  (inkl. amtliche Handbücher `esth./lsth./ao.bundesfinanzministerium.de`) und `bundesregierung.de`. Gewertet
  wurde nur, was ein Treffer **dieser** Domains belegt.
- Ergebnisklassen: **bestätigt (Suchtreffer amtlich)** · **teilweise** (Wert bestätigt, Zusatzangabe nicht) ·
  **nicht amtlich bestätigt**.
- Vor Tor S muss jeder verwendete Wert im Volltext geprüft werden (Vision, Tor S Nr. 1).

## Ergebnis je Wert

| Wert | Ergebnis | Amtliche Fundstelle | Anmerkung |
| --- | --- | --- | --- |
| Entfernungspauschale 0,38 €/km ab 1. km ab 2026 | bestätigt | LStH 2026 Anhang 14; BMF-Pressemitteilung 10.09.2025 (StÄndG 2025); bundesregierung.de | Absatz-/Satzangabe in § 9 EStG laut Treffer „nicht eindeutig lesbar" → Zitat im Volltext prüfen |
| Höchstbetrag 4.500 € | teilweise | Gesetzestext-Auszug im Treffer | Ausnahme für eigenen/überlassenen Pkw nicht geprüft |
| Dienstreise Pkw 0,30 €/km, andere Kfz 0,20 €/km | bestätigt | LStH 2026, „Reisekosten bei Auswärtstätigkeiten" | — |
| Verpflegung 28 € / 14 € | bestätigt | LStH 2026, Tabelle Reisekosten; BMF-Glossar | BMF-Monatsbericht 06/2025 enthält Reformvorschlag — **kein geltendes Recht** |
| Übernachtungspauschale 20 € | bestätigt | LStH 2026, Tabelle Reisekosten | nur bei Arbeitgebererstattung |
| Auslandspauschalen 2026 | bestätigt (Existenz), Einzelwerte nicht erfasst | BMF-Schreiben 05.12.2025 | Werte je Land müssen aus dem Schreiben übernommen werden |
| Bewirtung 70 % | bestätigt | § 4 Abs. 5 S. 1 Nr. 2 EStG (gesetze-im-internet.de); EStH 2024 | — |
| Geschenke 50 € | bestätigt | § 4 Abs. 5 S. 1 Nr. 1 EStG | Wert ja; **Geltungsbeginn nicht amtlich bestätigt** (Treffer nannten nur, dass 35 € überholt ist) |
| GWG 800 € / Verzeichnis > 250 € | bestätigt | EStH 2024 tabellarische Übersicht; Anlage EÜR 2025 (BMF 29.08.2025) | Fortgeltung für 2026 nicht ausdrücklich gelesen |
| Sammelposten 250–1.000 €, 5 Jahre | bestätigt | § 6 Abs. 2a EStG; Anlage EÜR 2025 | — |
| 1-%-Regel, Fahrtenbuchmethode | bestätigt | EStH 2024/2025 Anhang 16 III | — |
| E-Fahrzeug ¼ (BLP ≤ 100.000 €) | bestätigt | EStH Anhang 16 III | Batterieabschlag-Beispiel nicht übernommen |
| Kleinunternehmer 25.000 € / 100.000 € ab 2025 | bestätigt | BMF-Schreiben 18.03.2025; § 19 UStG | Neugründung: lfd. Jahr 25.000 € |
| Aufbewahrung 10 / 6 Jahre | bestätigt | § 147 Abs. 3 AO | — |
| Aufbewahrung Buchungsbelege 8 Jahre | teilweise | § 147 Abs. 3 AO (aktueller Text laut Treffer) | Stichtag/Übergang (BEG IV) **nicht amtlich bestätigt**; Kabinettsentwurf 08/2025: 10 Jahre für Banken/Versicherungen — Stand des Verfahrens unbekannt |
| E-Rechnung Empfang ab 2025 | bestätigt | BMF-FAQ E-Rechnung | — |
| E-Rechnung Übergang 2026 / 2027 (≤ 800.000 €) | bestätigt | BMF-FAQ E-Rechnung | Normtext § 27 Abs. 38 UStG nicht gelesen |
| GoBD Fassung 14.07.2025 | bestätigt | BMF-Schreiben „2025-07-14-GoBD-2-aenderung" | Rz. 58 nur aus Fassung 2019 (AO-Handbuch 2022) |
| FG Düsseldorf 24.11.2023, 3 K 1887/22 H(L) | nicht amtlich bestätigt | — | nur Sekundärquellen (Fachverlage, Steuerberater); NRWE-Volltext nicht abgerufen |

## Abweichungen
Keine der geprüften Zahlen weicht von einem amtlichen Treffer ab. Nicht bestätigt bzw. nur teilweise:
Geltungsbeginn der 50-€-Grenze, Stichtag der 8-Jahres-Frist, Ausnahme vom 4.500-€-Höchstbetrag,
Auslands-Einzelwerte, Volltext des FG-Urteils.
