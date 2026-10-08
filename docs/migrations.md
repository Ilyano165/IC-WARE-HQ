# Migrationen

Alembic, Dateien in `src/ichq/migrations/versions/`. Migrationen laufen **nur** mit der Rolle
`ichq_owner` über `ICHQ_MIGRATION_DATABASE_URL`.

```bash
ichq migrate              # auf den neuesten Stand
ichq migrate 0001_foundation
ichq downgrade base       # alles zurück (nur Entwicklung!)
```

Vor jeder Migration in Produktion: Sicherung. Ein automatisches Backup gibt es erst ab M22.

## Neue Migration

```bash
alembic -c src/ichq/migrations/alembic.ini revision -m "kurze beschreibung"
```

Migrationen werden **von Hand** geschrieben. Autogenerate erkennt weder Row-Level Security noch
Policies, Trigger oder Rechte.

## Checkliste für jede neue Mandantentabelle

- [ ] Modell erbt `TenantScoped` → `tenant_id NOT NULL`, Fremdschlüssel, Index
- [ ] Verweise auf andere Mandantentabellen als zusammengesetzter Fremdschlüssel `(tenant_id, x_id)`
- [ ] Zieltabelle hat `UNIQUE (tenant_id, id)`
- [ ] `ENABLE` **und** `FORCE ROW LEVEL SECURITY`
- [ ] Policy für `ichq_app` mit `USING` **und** `WITH CHECK` auf `ichq_current_tenant()`
- [ ] Nur die nötigen `GRANT`s — erst `REVOKE ALL`, dann gezielt
- [ ] Modul in `ichq/models.py` registriert
- [ ] `downgrade()` räumt alles weg, auch Policies, die an fremden Tabellen hängen

Die Tests prüfen automatisch: Modelle und Datenbank stimmen überein (`compare_metadata`), jede Tabelle
mit `tenant_id` hat erzwungene RLS, hoch → runter → hoch funktioniert.

## Regeln für Produktionsmigrationen (Expand/Contract)

1. Nur erweitern: neue Spalten nullable oder mit Standardwert, neue Tabellen.
2. Code ausrollen, der alt und neu versteht.
3. Daten nachziehen.
4. Erst in der **nächsten** Version alte Spalten entfernen.

So kann jederzeit das vorherige Image wieder gestartet werden.
