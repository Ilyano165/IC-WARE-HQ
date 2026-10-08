# ADR-012: KI-Schicht — Vorschlag statt Aktion, keine Zahl ohne Quelle

**Status:** vorgeschlagen (Umsetzung M21; Anbieter/AVV/Region offen) · **Grundlage:** M0 „AI", Auftrag vom 08.10.2026

## Entscheidung
1. Die KI handelt ausschließlich mit den Rechten des angemeldeten Menschen; Werkzeuge sind lesende Service-Aufrufe im
   Mandantenkontext. Keine eigene DB-Rolle, kein firmenübergreifender Index.
2. **Kein KI-Werkzeug führt aus.** Die KI legt höchstens Vorschläge (`ai_proposals`) an; ausgeführt wird nur über die
   bestehenden Routen durch den Menschen (Rechte, Audit, Schreibschutz gelten unverändert). Ein Schichtvertrag verbietet
   der KI-Schicht den Import schreibender Service-Funktionen.
3. Antworten sind strukturiert; der Server prüft vor der Anzeige, dass jede Quelle aus diesem Gespräch stammt und
   sichtbar ist und jede Zahl aus einem Werkzeugergebnis kommt (Rechnen im Code, nicht im Modell). Fehlende Daten sind
   ausdrücklich Lücken.
4. Opt-in je Firma (Feature-Flag `ai`) und je Rolle (`ai.use`).

## Verworfen
- KI mit eigenem Service-Konto und eigenen Rechten: würde eine zweite Rechtequelle schaffen (CLAUDE.md Regel 5).
- Ausführende Werkzeuge mit Bestätigungsdialog im KI-Ablauf: zweite Ausführungsstrecke neben der API, doppelte Prüfungen.
- Freitext-Antworten mit Fußnoten: nicht maschinell prüfbar.

## Folgen
Details, Injection-Schutz, Abnahmekriterien und offene Datenschutzfragen: `docs/ki-schicht.md`.
