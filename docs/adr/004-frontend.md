# ADR-004: Frontend — Entscheidung vertagt auf M5

**Status:** abgelöst durch ADR-013 (U1, 08.10.2026)

## Kontext
M1 hat keine Oberfläche. Zur Wahl stehen serverseitiges Rendering mit HTMX und eine React-SPA.

## Stand
Die API ist so gebaut, dass beides möglich bleibt: alle Funktionen über `/api/v1`, Sicherheit in der
Service-Schicht, nicht in der Oberfläche. Entscheidung vor M5, abhängig von Zielgruppe (M0, offene Frage 1).
