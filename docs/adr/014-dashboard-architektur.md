# ADR-014: Dashboard (D0) — Widget-Registry im Server, ein Aufruf, Zahl = Liste

**Status:** angenommen (D0) · **Grundlage:** Produktvision 4.3, D0-Auftrag (08.10.2026), ADR-009/011/013

## Kontext
Die Vision verlangt: „Was muss ich heute wissen oder erledigen?" — je Person nach Rechten, jeder Wert bis zum
Einzelobjekt nachvollziehbar, keine erfundenen Zahlen, fehlende Daten als „keine Daten vorhanden". Die meisten
Fachmodule (Belege, Rechnungen, Liquidität …) existieren noch nicht. Sicherheit darf nicht in der Oberfläche liegen.

## Entscheidung
1. **Registry im Server** (`ichq.dashboard.registry`): Ein Widget = Schlüssel, Titel, **benötigte Rechte**, Loader.
   Der Server liefert nur Widgets, deren Rechte der Principal **effektiv** hat (`decide` — also inklusive
   Feature-Flags, Einzelrechte-DENY, archivierter Rollen). Kein Rollenname, keine Prüfung im Browser.
2. **Ein Aufruf** `GET /api/v1/dashboard` (Recht `dashboard.read`) liefert alle erlaubten Widgets; `?widget=…`
   lädt eines neu. Jedes Widget läuft in einem eigenen **Savepoint**: scheitert eines, kommt `error: unavailable`,
   die anderen bleiben (die Transaktion bleibt gültig).
3. **Zahl = Liste:** Jede Kennzahl trägt den Namen der Liste und deren **Filter** (dieselben Parameter wie die
   Listen-API). Gezählt wird mit **denselben Filterbedingungen** wie die Liste (`tasks.service.filter_clauses`,
   `documents.service.filter_clauses`, `comments.questions`) — ein Test vergleicht jede Zahl mit der Länge der
   verlinkten Liste. Dafür wurden die Listen erweitert (Aufgaben `assignee=none`, Dokumente `scan_status`, `since`,
   `unlinked`) und `GET /api/v1/questions` neu angelegt.
4. **Sichtbarkeit unverändert** über `visible_clause` (ADR-009): Ohne `objects.read_all` zählt ein Mitarbeiter nur
   Eigenes, Zugewiesenes und Freigegebenes. Das Widget „Aufgaben der Firma" verlangt deshalb ausdrücklich
   `objects.read_all` — sonst wäre „Firma" irreführend.
5. **„Heute" in der Zeitzone der Firma** (`tenants.timezone`), nicht UTC — Fälligkeit ist ein Kalendertag der Firma.
6. **Offene Rückfrage** (abgeleitet, keine neue Spalte): Kommentar `kind = question`, nicht gelöscht, und danach kein
   nicht gelöschter Kommentar einer **anderen** Person am selben Objekt. Begründung: ohne Migration, aus vorhandenen
   Daten eindeutig ableitbar und nachvollziehbar; eine explizite „erledigt"-Markierung kann später ergänzt werden.
7. **Geplante Module** (`PLANNED`) haben keinen Loader und liefern **nie Werte** — nur Titel und Modul, nur bei
   passenden Rechten; die Oberfläche zeigt sie gesammelt unter „In Vorbereitung". Ein Fachmodul ersetzt seinen
   Planeintrag durch ein registriertes Widget.
8. **Hinweise** nur aus vorhandenen Daten (Firma pausiert, eigene Aufgaben überfällig, Dokumente mit Schadsoftware,
   nur eine Person mit Verwaltungsrechten) — jeweils mit Liste + Filter dahinter.

## Verworfen
- **Ein Endpunkt je Widget vom Browser aus:** 8+ Anfragen je Aufruf, Rechte doppelt; bleibt über `?widget=` möglich.
- **Widgets im Frontend nach Rollen ein-/ausblenden:** Sicherheit im Browser, Rollen statt Rechte (Regel 5).
- **Kennzahlen materialisieren (Tabelle/Cache):** Firmen 1–20 Personen, Aggregat-Abfragen mit Index reichen;
  Zwischenspeicher wäre eine zweite Wahrheit. Bei Bedarf messen (M24).
- **Platzhalter-Werte für fehlende Module:** verstößt gegen „keine erfundenen Zahlen".

## Folgen
- Neue Widgets: Loader in `ichq.dashboard.loaders` (oder dem Fachmodul) mit `@register(key, titel, rechte)`, Platz in
  `REIHENFOLGE`, Renderer ist generisch (Kennzahlen + Einträge) — kein Frontend-Code nötig, solange das Format passt.
- Jede neue Kennzahl braucht einen Listenfilter mit derselben Bedingung und einen Eintrag im Gleichheitstest.
