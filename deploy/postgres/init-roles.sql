-- Einmalig als PostgreSQL-Administrator ausführen, BEVOR die erste Migration läuft.
-- Passwörter kommen als psql-Variablen, nie aus dem Repository:
--
--   psql "$ADMIN_URL" -v owner_pw="..." -v app_pw="..." -v platform_pw="..." -v worker_pw="..." -v auth_pw="..." \
--        -v dbname=ichq -f deploy/postgres/init-roles.sql
--
-- Keine dieser Rollen ist Superuser oder darf RLS umgehen. Die Migration prüft das.

SELECT format('CREATE ROLE ichq_owner LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD %L', :'owner_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_owner') \gexec
SELECT format('CREATE ROLE ichq_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD %L', :'app_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_app') \gexec
SELECT format('CREATE ROLE ichq_platform LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD %L', :'platform_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_platform') \gexec
SELECT format('CREATE ROLE ichq_worker LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD %L', :'worker_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_worker') \gexec

SELECT format('CREATE ROLE ichq_auth LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD %L', :'auth_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_auth') \gexec

-- Passwörter bei jedem Lauf an die Secret-Dateien angleichen (Wiederherstellung, Rotation): die Dateien sind die
-- einzige Quelle. Nur Rollen, die es gibt — CREATE oben hat fehlende gerade angelegt.
SELECT format('ALTER ROLE ichq_owner PASSWORD %L', :'owner_pw') \gexec
SELECT format('ALTER ROLE ichq_app PASSWORD %L', :'app_pw') \gexec
SELECT format('ALTER ROLE ichq_platform PASSWORD %L', :'platform_pw') \gexec
SELECT format('ALTER ROLE ichq_worker PASSWORD %L', :'worker_pw') \gexec
SELECT format('ALTER ROLE ichq_auth PASSWORD %L', :'auth_pw') \gexec

SELECT format('CREATE DATABASE %I OWNER ichq_owner', :'dbname')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'dbname') \gexec

ALTER ROLE ichq_app      SET statement_timeout = '15s';
ALTER ROLE ichq_platform SET statement_timeout = '15s';
ALTER ROLE ichq_worker   SET statement_timeout = '60s';
ALTER ROLE ichq_auth     SET statement_timeout = '15s';

\connect :dbname
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CREATE, USAGE ON SCHEMA public TO ichq_owner;
