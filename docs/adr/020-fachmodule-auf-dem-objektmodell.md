# ADR-020: Fachmodule (CRM, Projekte, Finanzen, Verträge, Reisen) auf dem Objektmodell

**Status:** angenommen (12.10.2026) · baut auf ADR-008 (Objektmodell), ADR-009 (Sichtbarkeit), ADR-011 (Rechte), ADR-014 (Dashboard)

## Kontext

Auftrag „Master Prompt 1 — Enterprise Modules“: Kunden, Anfragen, Projekte, Rechnungen, Zahlungen, Belege,
Liquidität, Fristen, Monatsabschluss, Export, Verträge, Reisen und Fahrtenbuch sollen echte Daten speichern,
Rechte durchsetzen und zusammenarbeiten. Bestandsaufnahme: `docs/enterprise-bestandsaufnahme.md`. Bis heute sind
diese Objekttypen nur reserviert (`implemented=False`), und das Dashboard zeigt sie als `PLANNED` ohne Werte.

Es gelten unverändert die Regeln aus CLAUDE.md: dreifache Mandantentrennung, Objekte nur über `objects`,
Sichtbarkeit nur über `ichq.objects.visibility`, Rechte nur über `ichq.authz.effective`, und die
**Steuerfunktionen-Regeln**: kein Steuerwert im Code, Unveränderbarkeit mit sichtbarer Historie, Vorschlag statt
Entscheidung, Belegprinzip, Export.

## Entscheidungen

1. **Jedes Geschäftsobjekt ist ein Objekt** (Supertyp `objects`, typisierter Fremdschlüssel). Implementiert werden:
   `customer`, `project`, `invoice`, `payment`, `receipt` (Ausgabe mit Beleg), `contract`, `travel`, `trip`, außerdem
   die neuen Typen `inquiry` (Anfrage) und `deadline` (Frist). Kindzeilen ohne eigene Sichtbarkeit (Rechnungspositionen,
   Kontaktpersonen, Projektteam, Kontaktversuche, Fahrt-Versionen) hängen per `(tenant_id, parent_id)` am Objekt.
   Querverweise wie Kunde→Projekt sind echte zusammengesetzte Fremdschlüssel, keine `target_type/target_id`-Paare.
2. **Pakete und Schichten:** `ichq.crm` → `ichq.projects` → `ichq.finance | ichq.contracts | ichq.travel`
   (lint-imports). Finanzen dürfen Kunden/Projekte kennen, nicht umgekehrt.
3. **Geld:** `bigint` in der kleinsten Einheit plus `currency CHAR(3)`. Summen werden **je Währung** gebildet; die
   Liquidität rechnet nur in der Firmenwährung und nennt Posten anderer Währungen getrennt (keine Umrechnung ohne Kurs).
4. **Steuer auf Rechnungen:** Der Steuersatz je Position wird vom Nutzer eingegeben (Basispunkte, 1900 = 19 %).
   Es gibt **keinen Standardsatz im Code** (Steuerregel 1). Die Oberfläche sagt: „vom Nutzer erfasst, nicht geprüft“.
   Gesetzliche Pflichtangaben einer Rechnung werden nicht behauptet.
5. **Rechnungsnummern** erst beim Ausstellen: `INSERT … ON CONFLICT DO UPDATE … RETURNING` auf einer Zählertabelle
   je Firma und Jahr. Die Zeilensperre serialisiert parallele Ausstellungen. Ein Abbruch rollt auch den Zähler
   zurück, deshalb bleibt die Folge lückenlos. Eindeutigkeit erzwingt zusätzlich `UNIQUE (tenant_id, number)`.
6. **Unveränderbarkeit per Datenbank:** Ein Trigger verbietet nach dem Ausstellen jede Änderung an Betrag, Positionen,
   Kunde, Datum oder Nummer. Erlaubt bleiben nur Statusfelder. Korrektur = **Stornorechnung** (neue Rechnung mit
   negierten Positionen, Verweis auf das Original). Gelöscht werden dürfen nur Entwürfe.
7. **Periodensperre:** `month_closes` je Firma und Monat. Trigger auf Rechnungen, Zahlungen, Belegen, Fahrten und Reisen
   lehnen Einfügen/Ändern/Löschen mit Datum in einem abgeschlossenen Monat ab — auch bei direktem DB-Zugriff der
   App-Rolle. Wiedereröffnen braucht `finance.approve`, einen Grund und wird im Audit protokolliert.
8. **Fahrtenbuch:** Fahrtdaten liegen nur in `trip_versions` (nur `INSERT`/`SELECT` für `ichq_app`). Jede Korrektur ist
   eine neue Version mit Grund, sichtbar **in der Fahrt selbst** (Vorgabe FG Düsseldorf, CLAUDE.md). Erfassungs- und
   Fahrtzeitpunkt werden getrennt gespeichert und angezeigt. Eine Aussage zur Rechtskonformität gibt es nicht.
9. **Liquidität** täuscht keine Kontostände vor: Es gibt nur manuell gepflegte Stände (mit Datum und Erfasser),
   erfasste Zahlungen/Ausgaben (tatsächlich) und Erwartungen (offene Rechnungen, unbezahlte Ausgaben, Planposten).
   Jede Zahl liefert ihre Herkunft (Liste der Posten) mit.
10. **Fristen** werden nicht vorgegeben. Steuerfristen legt die Firma selbst an (Quelle als Freitext). Ohne Quelle
    zeigt die Oberfläche „nicht amtlich bestätigt“.
11. **Export:** dokumentiertes internes CSV-Format (`docs/export-format.md`) mit Validierung, Fehlerbericht, Historie
    und Wiederholung. **Keine DATEV-Kompatibilität behauptet** — das DATEV-Format ist nicht implementiert und nicht
    mit einem echten Import getestet.
12. **Mahnungen** werden nie automatisch verschickt. Erfasst werden Kontaktversuche, Mahnstufe und Wiedervorlage.
    Der Versand an Kunden ist nicht gebaut (Konfiguration und Freigabe fehlen).
13. **PDF:** Es gibt keine PDF-Bibliothek im Projekt. Rechnungen haben eine Druckansicht im Browser („Als PDF
    drucken“). Eine serverseitige PDF-Erzeugung ist nicht gebaut.
14. **Neue Rechte** nur mit Funktion: `contracts.create`, `travel.create`, `travel.approve`, `vehicles.create`.
    Abschluss/Wiedereröffnung nutzt `finance.approve`, Export `finance.export`, Ausstellen `invoices.approve`.
15. **Projektteam = Sichtbarkeit:** Wer ins Projektteam aufgenommen wird, erhält eine Freigabe mit der Quelle
    `project_team` (wie `task_assignment`) — nur für das Projekt, nicht für Rechnungen dazu.

## Folgen

* Viele neue Tabellen (Migration 0009 ff.), jede mit RLS FORCE, zusammengesetzten Fremdschlüsseln und Spaltenrechten.
* Rollenvorlagen erhalten die neuen Rechte nur für **neu angelegte** Firmen. Bestehende Rollen werden nie
  überschrieben (ADR-011), dort ergänzt der Admin die Rechte selbst.
* Steuerlich relevante Module bleiben bis **Tor S** intern (Produktvision Abschnitt 5). Gebaut werden darf, verkauft nicht.
