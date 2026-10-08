"""Virenprüfung: Ergebnis schreibt nur die Worker-Rolle — und nur als Übergang aus der Quarantäne.

Revision: 0007_documents_scan
Vorgänger: 0006_m4_rbac

* Die Web-App (``ichq_app``) bekommt **kein** Schreibrecht auf ``documents.scan_status`` (C0-Regel bleibt:
  ``tests/test_core_objects.py``). Der Dienst ``ichq documents-scan`` arbeitet als ``ichq_worker`` im
  Mandantenkontext (``app.tenant_id``) — eigene Zugangsdaten, kein Web-Request erreicht diese Verbindung.
* ``ichq_worker`` sieht von ``documents`` und ``objects`` nur, was er braucht, nur in der gesetzten Firma (RLS mit
  ``FORCE`` gilt seit 0001/0003), darf nur ``scan_status`` ändern und Audit-Einträge der Firma anhängen.
* Ein Trigger erlaubt NUR ``quarantined → clean`` und ``quarantined → infected`` — für jede Rolle. Ein infiziertes
  Dokument kann nie wieder freigegeben, ein geprüftes nie „zurückgedreht" werden — auch nicht durch einen Fehler im Code.
"""
from alembic import op

revision = "0007_documents_scan"
down_revision = "0006_m4_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    GRANT SELECT ON documents TO ichq_worker;
    GRANT UPDATE (scan_status) ON documents TO ichq_worker;
    GRANT SELECT (id, tenant_id, public_id, created_at) ON objects TO ichq_worker;
    GRANT SELECT, INSERT ON audit_events TO ichq_worker;
    CREATE POLICY p_documents_scan_worker ON documents FOR SELECT TO ichq_worker
      USING (tenant_id = ichq_current_tenant());
    CREATE POLICY p_documents_scan_worker_update ON documents FOR UPDATE TO ichq_worker
      USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
    CREATE POLICY p_objects_scan_worker ON objects FOR SELECT TO ichq_worker
      USING (tenant_id = ichq_current_tenant());
    CREATE POLICY p_audit_events_worker_read ON audit_events FOR SELECT TO ichq_worker
      USING (tenant_id = ichq_current_tenant());
    CREATE POLICY p_audit_events_worker_insert ON audit_events FOR INSERT TO ichq_worker
      WITH CHECK (tenant_id = ichq_current_tenant());
    CREATE FUNCTION ichq_document_scan_status() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.scan_status IS DISTINCT FROM OLD.scan_status
         AND NOT (OLD.scan_status = 'quarantined' AND NEW.scan_status IN ('clean', 'infected')) THEN
        RAISE EXCEPTION 'scan_status: % -> % ist nicht erlaubt', OLD.scan_status, NEW.scan_status;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tr_documents_scan_status BEFORE UPDATE OF scan_status ON documents
      FOR EACH ROW EXECUTE FUNCTION ichq_document_scan_status();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER tr_documents_scan_status ON documents;
    DROP FUNCTION ichq_document_scan_status();
    DROP POLICY p_audit_events_worker_insert ON audit_events;
    DROP POLICY p_audit_events_worker_read ON audit_events;
    DROP POLICY p_objects_scan_worker ON objects;
    DROP POLICY p_documents_scan_worker_update ON documents;
    DROP POLICY p_documents_scan_worker ON documents;
    REVOKE SELECT, INSERT ON audit_events FROM ichq_worker;
    REVOKE SELECT (id, tenant_id, public_id, created_at) ON objects FROM ichq_worker;
    REVOKE UPDATE (scan_status) ON documents FROM ichq_worker;
    REVOKE SELECT ON documents FROM ichq_worker;
    """)
