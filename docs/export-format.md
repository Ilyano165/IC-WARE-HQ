# Exportformat `ichq-buchungen-v1`

Internes, dokumentiertes CSV-Format für die Übergabe an den Steuerberater (ADR-020 Nr. 11).

> **Kein DATEV-Format.** Dieses Format ist **nicht** DATEV-kompatibel, und wir behaupten das auch nicht. Es ist mit
> keinem Importprogramm getestet. Ein DATEV-Export ist nicht gebaut. Dafür bräuchte es die DATEV-Formatbeschreibung,
> Kontenrahmen und Buchungsschlüssel der Firma und einen echten Importtest.

## Datei

* Kodierung UTF-8 mit BOM (Excel erkennt Umlaute), Zeilenende `CRLF`, Trennzeichen `;`, Anführungszeichen nur bei Bedarf.
* Erste Zeile: Spaltennamen.
* Beträge sind **ganze Zahlen in Cent**, ohne Tausender- oder Dezimaltrennzeichen. Negative Beträge stehen bei
  Stornorechnungen und Rücknahmen von Zahlungen.
* Datum im Format `YYYY-MM-DD`.
* **Schutz vor CSV-Injection:** Textzellen, die mit `=`, `+`, `-`, `@`, Tab oder CR beginnen, bekommen ein `'`
  vorangestellt. Tabellenprogramme führen sie dann nicht als Formel aus.

## Spalten

| Spalte | Inhalt |
| --- | --- |
| `satzart` | `invoice`, `cancellation` (Stornorechnung), `payment` (Zahlungseingang/Rücknahme), `receipt` (Ausgabe) |
| `id` | öffentliche ID in HQ |
| `nummer` | Rechnungsnummer (nur Rechnungen) |
| `datum` | Rechnungsdatum, Zahlungsdatum bzw. Ausgabedatum |
| `partner` | Kunde laut Stand beim Ausstellen bzw. Lieferant |
| `bezeichnung` | Titel bzw. Verwendungszweck |
| `steuersatz_bp` | Steuersatz in Basispunkten (1900 = 19 %). Wie vom Nutzer erfasst, von HQ nicht geprüft. Bei Ausgaben optional |
| `netto_cent`, `steuer_cent` | nur bei Rechnungen (je Steuersatz eine Zeile). Bei Ausgaben leer, weil HQ aus dem Brutto keine Steuer herausrechnet |
| `brutto_cent` | Bruttobetrag |
| `waehrung` | ISO-Code |
| `status` | Rechnung: Status in HQ. Zahlung: Zahlungsart. Ausgabe: `offen`, `bezahlt` oder `storniert` |
| `beleg` | Ausgabe: `missing`, `unchecked`, `rejected` oder `complete` (siehe Belegprinzip) |
| `bezug` | Storno: Nummer der Originalrechnung. Zahlung: Rechnungsnummer. Ausgabe: ID des Belegdokuments |
| `periode_abgeschlossen` | `ja`, wenn der Monat des Datums abgeschlossen ist |

Stornierte Ausgaben werden mit exportiert (`status = storniert`), damit der Export vollständig ist. Rechnungsentwürfe
werden nicht exportiert.

## Prüfbericht, Historie, Wiederholung

Jeder Export speichert Inhalt, SHA-256-Prüfsumme, Zeilenzahl und Prüfbericht. Der Bericht enthält:

* Ausgaben ohne geprüften Beleg,
* Ausgaben ohne Steuersatz,
* nicht abgeschlossene Monate im Zeitraum.

Exporte sind Historie, die Datenbank verbietet Ändern und Löschen. „Wiederholen“ erzeugt einen neuen Export für
denselben Zeitraum. `changed_since_original` sagt, ob sich die Daten seitdem geändert haben (andere Prüfsumme). Jeder
Download wird im Audit protokolliert (`export.downloaded`).
