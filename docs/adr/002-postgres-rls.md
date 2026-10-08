# ADR-002: PostgreSQL, ein Schema, Row-Level Security

**Status:** angenommen (M1) · **Grundlage:** M0, Abschnitt 16

## Entscheidung
Eine Datenbank, ein gemeinsames Schema. Jede Mandantentabelle trägt `tenant_id`. Isolation dreifach:
Service-Kontext, Row-Level Security mit `FORCE`, zusammengesetzte Fremdschlüssel. Vier Datenbankrollen,
keine davon Superuser oder `BYPASSRLS`. Mandantenkontext per `SET LOCAL` je Transaktion.

## Verworfen
- Schema pro Firma / Datenbank pro Firma: stärker isoliert, vervielfacht aber Migrationen und Betrieb.
  Bleibt als Enterprise-Option.
- Isolation nur im Code (`WHERE tenant_id = …`): ein vergessener Filter wäre ein Datenleck.

## Folgen
- Jede neue Tabelle braucht die Checkliste aus `docs/migrations.md`.
- Connection-Pooler nur im Transaction-Modus (`SET LOCAL`), nie im Statement-Modus.
