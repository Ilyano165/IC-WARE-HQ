"""Konfiguration ausschließlich über Umgebungsvariablen und Secret-Dateien.

Jede Variable ``ICHQ_<NAME>`` kann alternativ als ``ICHQ_<NAME>_FILE`` angegeben
werden; dann wird der Wert aus dieser Datei gelesen (Docker-/Kubernetes-Secrets).
Für kein Geheimnis gibt es einen Standardwert.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PREFIX = "ICHQ_"
MIN_SECRET_LEN = 32
_PLATZHALTER = {"change-me", "changeme", "secret", "geheim", "test", "development", "password"}


class ConfigError(RuntimeError):
    """Konfiguration unvollständig oder unsicher. Die Meldung nennt nie einen geheimen Wert."""


def _datei_werte(environ: dict[str, str]) -> dict[str, str]:
    """Liest ``ICHQ_X_FILE``-Variablen und gibt ``{x: inhalt}`` zurück."""
    werte: dict[str, str] = {}
    for key, pfad in environ.items():
        if not (key.startswith(PREFIX) and key.endswith("_FILE")) or not pfad.strip():
            continue   # leere Variable = nicht gesetzt
        feld = key[len(PREFIX):-len("_FILE")].lower()
        if f"{PREFIX}{feld.upper()}" in environ:
            raise ConfigError(f"{PREFIX}{feld.upper()} und {key} sind beide gesetzt — nur eines ist erlaubt.")
        try:
            werte[feld] = Path(pfad).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ConfigError(f"Secret-Datei für {key} ist nicht lesbar ({e.__class__.__name__}).") from None
    return werte


def read_secret_env(name: str, environ: dict[str, str] | None = None) -> str | None:
    """Ein einzelnes Geheimnis lesen — für Werkzeuge wie Alembic, die keine vollständigen Settings brauchen."""
    env = dict(os.environ if environ is None else environ)
    if f"{PREFIX}{name}" in env:
        return env[f"{PREFIX}{name}"]
    datei = env.get(f"{PREFIX}{name}_FILE")
    return Path(datei).read_text(encoding="utf-8").strip() if datei else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=PREFIX, extra="ignore", frozen=True)

    env: Literal["development", "test", "production"] = "development"

    # Datenbank: je Aufgabe eine eigene Rolle (docs/architecture.md, Abschnitt Datenbankrollen)
    database_url: SecretStr                          # ichq_app — Mandantenebene, RLS erzwungen
    platform_database_url: SecretStr                 # ichq_platform — Firmen, Konten, Plattform-Audit
    worker_database_url: SecretStr                   # ichq_worker — Outbox über alle Firmen
    auth_database_url: SecretStr                     # ichq_auth — Anmeldung, Sitzungen, Passwort-Hashes
    migration_database_url: SecretStr | None = None  # ichq_owner — nur für Migrationen
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)

    secret_key: SecretStr        # Anwendungsgeheimnis (Signaturen ab M2)
    session_secret: SecretStr    # Sitzungen (ab M2) — bewusst getrennt vom secret_key

    storage_backend: Literal["local", "s3"] = "local"
    storage_path: Path | None = None
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "eu-central-1"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    # Virenprüfung (ClamAV/clamd über TCP) — nur der Dienst `ichq documents-scan` braucht sie
    clamd_host: str | None = None
    clamd_port: int = Field(default=3310, ge=1, le=65535)

    # E-Mail (ichq.mail): Versand über den Worker aus der Tabelle mail_outbox
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False                    # implizites TLS (Port 465); hat Vorrang vor STARTTLS
    mail_per_recipient_hour: int = Field(default=10, ge=1, le=1000)   # danach zurückgestellt, nicht verworfen
    alert_email: str | None = None            # Betreiber-Adresse für Systemwarnungen (ichq alert, Monitoring)

    # Anmeldung (M2)
    public_origin: str | None = None          # z. B. https://app.ic-ware.eu — Pflicht in Produktion
    cookie_secure: bool | None = None         # Standard: an in Produktion
    trusted_proxies: str = "127.0.0.1"        # IPs, deren X-Forwarded-For vertraut wird
    session_idle_minutes: int = Field(default=30, ge=5, le=1440)
    session_absolute_hours: int = Field(default=12, ge=1, le=720)
    mfa_challenge_minutes: int = Field(default=5, ge=1, le=30)
    login_max_failures: int = Field(default=5, ge=3, le=20)      # je Konto, dann Sperre
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    throttle_window_minutes: int = Field(default=15, ge=1, le=1440)
    ip_max_failures: int = Field(default=30, ge=5, le=1000)      # je IP im Fenster
    identifier_max_failures: int = Field(default=10, ge=3, le=100)  # je Login-Name (auch unbekannte)
    password_reset_minutes: int = Field(default=30, ge=5, le=1440)
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_kib: int = Field(default=65536, ge=8192, le=1048576)
    argon2_parallelism: int = Field(default=4, ge=1, le=16)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    expose_docs: bool = False

    @field_validator("secret_key", "session_secret")
    @classmethod
    def _secret_stark(cls, v: SecretStr) -> SecretStr:
        roh = v.get_secret_value()
        if roh.strip().lower() in _PLATZHALTER:
            raise ValueError("ist ein Platzhalter und darf nicht verwendet werden")
        if len(roh) < MIN_SECRET_LEN:
            raise ValueError(f"muss mindestens {MIN_SECRET_LEN} Zeichen lang sein")
        return v

    @model_validator(mode="after")
    def _gesamtpruefung(self) -> Settings:
        if self.secret_key.get_secret_value() == self.session_secret.get_secret_value():
            raise ValueError("secret_key und session_secret müssen verschieden sein")
        urls = {
            "database_url": self.database_url.get_secret_value(),
            "platform_database_url": self.platform_database_url.get_secret_value(),
            "worker_database_url": self.worker_database_url.get_secret_value(),
            "auth_database_url": self.auth_database_url.get_secret_value(),
        }
        for name, url in urls.items():
            if not url.startswith("postgresql"):
                raise ValueError(f"{name} muss eine PostgreSQL-URL sein")
        if len(set(urls.values())) < len(urls):
            raise ValueError("App, Plattform, Worker und Auth brauchen getrennte Datenbankrollen")
        if self.public_origin is not None and not self.public_origin.startswith(("https://", "http://")):
            raise ValueError("public_origin muss mit http:// oder https:// beginnen")
        if self.storage_backend == "local" and self.storage_path is None:
            raise ValueError("storage_path ist bei storage_backend=local Pflicht")
        if self.storage_backend == "s3" and not (self.s3_bucket and self.s3_access_key and self.s3_secret_key):
            raise ValueError("s3_bucket, s3_access_key und s3_secret_key sind bei storage_backend=s3 Pflicht")
        if self.smtp_host and self.smtp_user and not (self.smtp_starttls or self.smtp_ssl):
            raise ValueError("SMTP-Anmeldung nur verschlüsselt: smtp_starttls oder smtp_ssl einschalten")
        if self.env == "production":
            if self.expose_docs:
                raise ValueError("expose_docs darf in Produktion nicht aktiv sein")
            if self.log_format != "json":
                raise ValueError("Produktion verlangt log_format=json")
            if not (self.public_origin or "").startswith("https://"):
                raise ValueError("Produktion verlangt public_origin mit https://")
            if self.cookie_secure is False:
                raise ValueError("cookie_secure darf in Produktion nicht aus sein")
            if self.argon2_memory_kib < 65536:
                raise ValueError("argon2_memory_kib muss in Produktion mindestens 65536 sein")
            for name, url in urls.items():
                if "://postgres:" in url or "://postgres@" in url:
                    raise ValueError(f"{name} nutzt den Superuser postgres — in Produktion verboten")
        return self


def secure_cookies(settings: Settings) -> bool:
    return settings.cookie_secure if settings.cookie_secure is not None else settings.env == "production"


def load_settings(environ: dict[str, str] | None = None) -> Settings:
    """Settings aus Umgebung und Secret-Dateien laden. Fehlermeldungen enthalten nie Werte."""
    env = dict(os.environ if environ is None else environ)
    kwargs: dict[str, Any] = _datei_werte(env)
    try:
        if environ is None:
            return Settings(**kwargs)
        for key, wert in env.items():
            if key.startswith(PREFIX) and not key.endswith("_FILE"):
                kwargs.setdefault(key[len(PREFIX):].lower(), wert)
        return Settings.model_validate(kwargs)
    except ValidationError as e:
        zeilen = []
        for f in e.errors(include_input=False, include_url=False):
            ort = ".".join(str(x) for x in f.get("loc", ())).upper()
            zeilen.append(f"{PREFIX}{ort}: {f.get('msg')}" if ort else f"(gesamt): {f.get('msg')}")
        raise ConfigError("Konfiguration ungültig:\n  " + "\n  ".join(zeilen)) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
