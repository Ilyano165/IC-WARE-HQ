# ADR-001: Neubau statt Umbau von IC·HQ 2.x

**Status:** angenommen (M1) · **Grundlage:** M0-Bericht, Abschnitte 11–14 und 34

## Kontext
IC·HQ 2.x ist eine Datei mit 7.141 Zeilen, SQLite, 33 Tabellen ohne Fremdschlüssel, davon 27 ohne
Firmenbezug, Geld als Gleitkommazahl. Mandantenfähigkeit lässt sich darin nicht prüfbar herstellen.

## Entscheidung
Neue Codebasis. IC·HQ 2.x bleibt Arbeitswerkzeug von IC Ware und wird nur noch gewartet. Übernommen
werden Konzepte und Fachregeln (Rechte-Registry, Entscheidungsreihenfolge, Rechnungslogik), nicht Code.

## Verworfen
Schrittweiser Umbau: Jeder Zwischenstand wäre halb mandantenfähig — der Zustand, in dem Datenlecks entstehen.

## Folgen
Doppelter Pflegeaufwand bis zum Umzug. Ein Import-Werkzeug für die alte SQLite-Datei wird nötig.
