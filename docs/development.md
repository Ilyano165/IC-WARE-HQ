# Lokale Entwicklung

## Voraussetzungen

- Python 3.12
- PostgreSQL 16 (lokal installiert oder als Container)

## 1. Abhängigkeiten

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.lock      # feste Versionen, geprüfte Hashes
pip install --no-deps -e ".[dev]"
pip install "pytest>=8" "httpx>=0.27" "moto[s3]>=5" "ruff>=0.6" "mypy>=1.11" "import-linter>=2"
```

## 2. Datenbankrollen und Datenbank

Einmalig als PostgreSQL-Administrator. Passwörter nur als Variablen, nie in Dateien im Repository:

```bash
psql "postgresql://postgres@localhost/postgres" \
  -v owner_pw="$(openssl rand -base64 24)" -v app_pw="..." -v platform_pw="..." -v worker_pw="..." \
  -v dbname=ichq -f deploy/postgres/init-roles.sql
```

## 3. Konfiguration

```bash
cp .env.example .env    # alle {PLATZHALTER} ersetzen
set -a; . ./.env; set +a
ichq check-config
```

## 4. Migrieren und starten

```bash
ichq migrate
ichq tenant-create --name "Testfirma" --slug testfirma
ichq serve --port 8000          # http://localhost:8000/health
ichq worker                      # zweites Terminal
```

Mit `ICHQ_EXPOSE_DOCS=true` gibt es unter `/docs` die OpenAPI-Oberfläche. In Produktion verweigert die
Konfiguration diese Einstellung.

## Prüfungen vor jedem Commit

```bash
ruff check src tests && mypy && lint-imports && pytest -q
```
