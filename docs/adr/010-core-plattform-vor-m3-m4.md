# ADR-010: Core-Plattform (C0) vor M3/M4 gebaut

**Status:** angenommen (C0) · **Abweichung von:** Roadmap in `docs/m0-zielarchitektur.md`

## Kontext
Die Roadmap sieht M3 (Mandanten), M4 (Rollen & Rechte), M5 (UI-Shell) vor M7 (Aufgaben), M9 (Kommunikation),
M10 (Dateien) und M14 (Suche). Der Auftrag C0 verlangt jetzt eine gemeinsame Plattformschicht für genau diese
Querschnittsthemen, damit spätere Module nicht isoliert entstehen.

## Entscheidung
C0 baut **die Querschnitts-Bausteine** (Objektmodell, Verknüpfungen, Freigaben, Aktivität, Aufgaben,
Kommentare, Dokument-Metadaten, Benachrichtigungen, Suche, Audit-Lesen/Export) — **nicht** die Fachmodule.
Aus M3 übernommen: zentraler Schreibschutz für pausierte Firmen (nur für die Core-Routen, Code `tenant_paused`),
Muster „Laden per ID im Kontext → 404, Cursor-Paginierung, Anlegen mit Audit + Outbox".

## Nicht in C0 (bleibt im jeweiligen Meilenstein)
Rollenverwaltung, Einzelrechte, Ressourcen-DENY (M4) · Einladungen, Mitgliederverwaltung (M3) · Oberfläche (M5) ·
Virenscanner und signierte Download-Links (M10) · E-Mail/Push-Kanäle (M9/M15) · Fachmodule (CRM, Rechnungen …).

## Folgen
- **Tor 1 ist nicht erreicht**: Der IDOR-Generator deckt alle Core-Routen ab, aber nicht die Firmenprofil-
  und Mitglieder-Routen aus M3, die es noch nicht gibt.
- Die Rechte gelten heute nur über Rollen, die per SQL/Tests angelegt werden — eine Verwaltungsoberfläche
  oder -API gibt es erst mit M4.
- Der Schreibschutz für pausierte Firmen gilt nur für Routen, die `writing()` nutzen; M3 muss ihn für alle
  Routen zentral machen.
