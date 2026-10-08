# ADR-007: Produktfokus — Back-Office für kleine Firmen in Deutschland

**Status:** vorgeschlagen — beruht auf `docs/produktvision-v2.md`, die selbst ein **unbestätigter Entwurf** ist.
Wird „angenommen", sobald die Vision bestätigt ist.

## Kontext
M0 beschreibt HQ als „digitales Betriebssystem eines Unternehmens" mit 26 Meilensteinen (CRM, Projekte,
Kommunikation, Termine, Finanzen …) und nennt selbst die Risiken: **Umfang vs. zwei Personen** und
**Wettbewerb gegen Generalisten** („Nische schärfen"). Ein breites Produkt konkurriert gleichzeitig mit
spezialisierten Marktführern in jeder Kategorie und wird in keiner besser.

## Entscheidung (Vorschlag)
HQ konzentriert sich auf das **Back-Office kleiner deutscher Firmen (1–20 Personen)** zwischen Alltag und
Steuerberater: Belege, Fahrten, Reisen, Bewirtungen, Rechnungen, Aufgaben, Rückfragen, Export
(Vision Abschnitt 1, Module S1–S8). Steuerfunktionen folgen fünf festen Regeln (Vision Abschnitt 2) und
gehen erst nach **Tor S** an Kunden.

## Verworfene Alternativen
- **Generalist („Betriebssystem für alles")** wie in M0: zu breit für zwei Personen, Wettbewerb mit
  HubSpot/Asana/Microsoft in jeder Kategorie.
- **Vollbuchhaltung (DATEV-/lexoffice-Konkurrent):** hohes Haftungs- und Zulassungsrisiko, Steuerberater
  arbeiten mit DATEV; Mehrwert für die Zielgruppe gering.
- **Branchenlösung (z. B. nur Handwerk):** schärfer, aber kleiner Markt und Branchen-Spezialfunktionen
  (Aufmaß, Kalkulation) außerhalb der Stärken; als spätere Ausprägung möglich.
- **Agentur-Projekttool** (Herkunft IC·HQ 2.x): starker Wettbewerb, kein besonderer Vorteil.

## Folgen für die Roadmap
- Reihenfolge **Tor 1/M3 → C0 → U1 → D0 → S1–S8 → Tor S**; M0-Meilensteine M6 (Mitarbeiter/Teams),
  M8 (CRM), M9 (Kommunikation), M11 (Termine/Ressourcen), M13 (Angebote) werden **zurückgestellt** und nur
  in dem Umfang gebaut, den S1–S8 brauchen. **[Annahme]**
- Neues Tor **Tor S** vor dem Verkauf jeder Steuerfunktion (Vision Abschnitt 5).
- Rechte-Registry bekommt fachliche Rechte für Fahrzeuge, Reisen, Bewirtung, Lieferanten (umgesetzt).
- Architekturentscheidungen aus M0/M1/M2 (Mandantenisolation, Rollen, Outbox, Betrieb) bleiben unverändert.
- Risiko: Rechtsversprechen (M0) wächst mit dem Steuerfokus → Regel 3 der Vision, externer Steuerberater vor Tor S.
