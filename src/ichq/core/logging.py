"""Strukturiertes Logging mit Korrelations-ID und Schwärzung sensibler Werte.

Regel: Was hier durchläuft, darf keine Passwörter, Sitzungs-, Zugangs- oder
Onboarding-Tokens und keine Dateiinhalte enthalten. Der Filter schwärzt
bekannte Muster als zweite Verteidigungslinie — die erste ist, so etwas gar
nicht erst zu loggen.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)

GESCHWAERZT = "[REDACTED]"
_SENSIBLE_SCHLUESSEL = re.compile(
    r"(pass(word|wort)?|pwd|secret|token|authorization|cookie|session|api[_-]?key|credential|private)",
    re.IGNORECASE,
)
_MUSTER = [
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer " + GESCHWAERZT),
    (re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]+:)[^@\s]+@"), r"\1" + GESCHWAERZT + "@"),
    (re.compile(r"(?i)\b(password|passwort|token|secret|api_key|apikey|session)=([^&\s]+)"),
     r"\1=" + GESCHWAERZT),
    (re.compile(r"(/onboard/)[A-Za-z0-9_-]{16,}"), r"\1" + GESCHWAERZT),
]
_STANDARD_FELDER = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}


def redact_text(text: str) -> str:
    for muster, ersatz in _MUSTER:
        text = muster.sub(ersatz, text)
    return text


def redact_value(key: str, value: Any) -> Any:
    if _SENSIBLE_SCHLUESSEL.search(key):
        return GESCHWAERZT
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        daten: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
        }
        rid, tid = request_id_var.get(), tenant_id_var.get()
        if rid:
            daten["request_id"] = rid
        if tid:
            daten["tenant_id"] = tid
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FELDER and not key.startswith("_"):
                daten[key] = redact_value(key, value)
        if record.exc_info and record.exc_info[0] is not None:
            daten["exc_type"] = record.exc_info[0].__name__
            daten["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(daten, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        teil = f" [{rid[:8]}]" if rid else ""
        text = f"{record.levelname:<7}{teil} {record.name}: {redact_text(record.getMessage())}"
        if record.exc_info and record.exc_info[0] is not None:
            text += "\n" + redact_text(self.formatException(record.exc_info))
        return text


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn-Zugriffslog enthält rohe Pfade (z. B. Onboarding-Tokens) — wir loggen selbst, mit Routen-Vorlage
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
