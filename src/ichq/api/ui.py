"""Auslieferung der Oberfläche (U1, ADR-013): statische Dateien aus ``ichq/web`` unter ``/app/``.

Die App ist reines Frontend ohne eigene Daten — sie spricht nur mit ``/api/v1``. Deshalb Marke ``public``.
Schutz hier: nur Dateien INNERHALB von ``ichq/web`` (kein ``..``, keine Symlinks hinaus), nur bekannte Dateitypen,
strenge Sicherheits-Header (CSP ohne Inline-Skripte, kein Einbetten in fremde Seiten).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse, Response

from ichq.api.security import public
from ichq.core.errors import NotFound

router = APIRouter(include_in_schema=False)

WEB = (Path(__file__).resolve().parent.parent / "web").resolve()
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
         ".webmanifest": "application/manifest+json"}
_PFAD = re.compile(r"^[A-Za-z0-9_./-]{0,200}$")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def resolve(pfad: str) -> Path:
    """Datei unter ``WEB`` oder ``NotFound`` — die eine Prüfung gegen Pfad-Ausbruch."""
    if not _PFAD.match(pfad) or any(teil in ("", ".", "..") for teil in pfad.split("/")[:-1]) or ".." in pfad:
        raise NotFound()
    datei = (WEB / (pfad or "index.html")).resolve()
    if not datei.is_relative_to(WEB) or not datei.is_file() or datei.suffix not in TYPES:
        raise NotFound()
    return datei


@router.api_route("/", methods=["GET", "HEAD"])
def root(_: None = Depends(public("Weiterleitung zur Oberfläche"))) -> Response:
    return RedirectResponse("/app/", status_code=307)


@router.api_route("/app", methods=["GET", "HEAD"])
def app_ohne_slash(_: None = Depends(public("Weiterleitung zur Oberfläche"))) -> Response:
    return RedirectResponse("/app/", status_code=307)


# Links aus E-Mails (M2/M3): …/invite#token=… und …/reset#token=… — der Browser übernimmt das Fragment in die
# Weiterleitung (RFC 9110, 10.2.2), der Token erreicht den Server also nie.
@router.get("/invite")
def invite(_: None = Depends(public("Einladungslink → Oberfläche"))) -> Response:
    return RedirectResponse("/app/?v=einladung", status_code=307)


@router.get("/reset")
def reset(_: None = Depends(public("Passwort-Link → Oberfläche"))) -> Response:
    return RedirectResponse("/app/?v=passwort-neu", status_code=307)


@router.api_route("/app/{pfad:path}", methods=["GET", "HEAD"])   # HEAD: Uptime-Monitore
def static(pfad: str, _: None = Depends(public("Oberfläche: statische Dateien, keine Daten"))) -> Response:
    datei = resolve(pfad)
    resp = FileResponse(datei, media_type=TYPES[datei.suffix])
    resp.headers.update(HEADERS)
    # index.html nie cachen (neue Version sofort); Rest: immer nachfragen (ETag), kein veraltetes Skript
    resp.headers["Cache-Control"] = "no-store" if datei.name == "index.html" else "no-cache"
    return resp
