# IC WARE HQ — Sicherungs-Werkzeug (ADR-016): pg_dump/pg_restore (PostgreSQL 16 wie der Server) + restic.
# restic verschlüsselt authentifiziert (AES-256 + Poly1305), dedupliziert, spricht S3 — keine eigene Kryptografie.
# Bauen: deploy/hq build (Image ic-ware-hq-backup:local). restic kommt aus dem offiziellen, fest versionierten Image.
ARG RESTIC_IMAGE=restic/restic:0.18.1
FROM ${RESTIC_IMAGE} AS restic

FROM postgres:16-alpine
COPY --from=restic /usr/bin/restic /usr/local/bin/restic
RUN restic version
ENTRYPOINT []
