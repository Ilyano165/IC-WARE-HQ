"""IC WARE HQ — Windows-Launcher (ADR-017). Öffnet die ZENTRALE Instanz der Firma; er ist kein zweiter Server und
speichert keine Firmendaten — nur die Adresse der Instanz.

Ablauf beim Start:
1. Adresse aus der Benutzer-Einstellung (%APPDATA%\\IC WARE HQ\\launcher.json) oder der Vorgabe des Installers
   (server.json neben der .exe); fehlt sie, fragt der Launcher danach.
2. Prüfung, dass unter der Adresse wirklich IC WARE HQ antwortet (/health über HTTPS mit gültigem Zertifikat).
   Ein ungültiges Zertifikat ist ein harter Fehler — es gibt bewusst keinen „trotzdem öffnen"-Knopf.
3. Öffnen als eigenes Fenster (Microsoft Edge im App-Modus, sonst Chrome, sonst Standardbrowser).

Die Logik hier ist ohne Windows und ohne GUI testbar (tests/test_windows_launcher.py); die Dialoge stehen in gui.py.
"""
from __future__ import annotations

import enum
import json
import os
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

VERSION = "1.0.0rc1"
APP_NAME = "IC WARE HQ"
TIMEOUT_S = 10
_LOKAL = {"localhost", "127.0.0.1", "::1"}


class Ungueltig(ValueError):
    """Eingabe ist keine brauchbare Adresse (Meldung ist für Menschen)."""


def normalisiere(eingabe: str) -> str:
    """``hq.firma.de`` → ``https://hq.firma.de``. Nur Schema + Host (+ Port); Pfad, Query, Zugangsdaten sind Fehler.

    http:// nur für localhost (Testbetrieb) — sonst gingen Passwort und Sitzung unverschlüsselt über das Netz.
    """
    roh = eingabe.strip()
    if not roh:
        raise Ungueltig("Bitte die Adresse Ihrer IC-WARE-HQ-Instanz eingeben, z. B. hq.ihre-firma.de")
    if "://" not in roh:
        roh = "https://" + roh
    try:
        teile = urllib.parse.urlsplit(roh)
        port = teile.port
    except ValueError as e:
        raise Ungueltig("Die Adresse ist ungültig.") from e
    host = (teile.hostname or "").lower()
    if teile.scheme not in ("https", "http") or not host:
        raise Ungueltig("Die Adresse muss mit https:// beginnen.")
    if teile.username or teile.password:
        raise Ungueltig("Die Adresse darf keine Zugangsdaten enthalten.")
    if teile.query or teile.fragment or teile.path.strip("/") not in ("", "app"):
        raise Ungueltig("Nur die Adresse der Instanz angeben, ohne Pfad (z. B. https://hq.ihre-firma.de).")
    if teile.scheme == "http" and host not in _LOKAL:
        raise Ungueltig("Nur verschlüsselte Verbindungen (https://) sind erlaubt.")
    if not all(c.isalnum() or c in ".-:[]" for c in host):
        raise Ungueltig("Die Adresse enthält unerlaubte Zeichen.")
    netz = f"[{host}]" if ":" in host else host
    return f"{teile.scheme}://{netz}{f':{port}' if port else ''}"


class Befund(enum.Enum):
    OK = "ok"
    STOERUNG = "stoerung"          # IC WARE HQ antwortet, meldet aber eine Störung — trotzdem öffnen
    DNS = "dns"
    NICHT_ERREICHBAR = "nicht_erreichbar"
    ZERTIFIKAT = "zertifikat"
    FREMD = "fremd"


MELDUNG = {
    Befund.OK: "Verbunden.",
    Befund.STOERUNG: "Der Server meldet eine Störung. Einige Funktionen sind eventuell eingeschränkt — "
                     "bitte die Betreuung informieren.",
    Befund.DNS: "Die Adresse wurde nicht gefunden. Tippfehler? Besteht eine Internetverbindung?",
    Befund.NICHT_ERREICHBAR: "Der Server antwortet nicht. Internetverbindung prüfen; besteht das Problem weiter, "
                             "ist der Server vermutlich ausgefallen — bitte die Betreuung informieren.",
    Befund.ZERTIFIKAT: "Das Sicherheitszertifikat des Servers ist ungültig. Die Verbindung wurde zu Ihrem Schutz "
                       "nicht aufgebaut (mögliches Abhören). Bitte die Betreuung informieren.",
    Befund.FREMD: "Unter dieser Adresse läuft kein IC WARE HQ. Bitte die Adresse prüfen.",
}


@dataclass(frozen=True)
class Ergebnis:
    befund: Befund
    version: str | None = None
    detail: str = ""

    @property
    def oeffnen(self) -> bool:
        return self.befund in (Befund.OK, Befund.STOERUNG)

    @property
    def text(self) -> str:
        return MELDUNG[self.befund]


def pruefe(url: str, timeout: float = TIMEOUT_S, ctx: ssl.SSLContext | None = None) -> Ergebnis:
    """Antwortet unter ``url`` eine IC-WARE-HQ-Instanz? Folgt keinen Weiterleitungen auf fremde Hosts."""
    ctx = ctx or ssl.create_default_context()      # Windows: Zertifikatsspeicher des Systems
    anfrage = urllib.request.Request(f"{url}/health", headers={  # noqa: S310  (Schema geprüft: normalisiere)
        "Accept": "application/json", "User-Agent": f"ichq-launcher/{VERSION}"})
    try:
        with urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), _KeineWeiterleitung()).open(
                anfrage, timeout=timeout) as antwort:
            daten = json.loads(antwort.read(65536).decode("utf-8"))
    except urllib.error.HTTPError as e:
        return Ergebnis(Befund.FREMD, detail=f"HTTP {e.code}")
    except urllib.error.URLError as e:
        grund = e.reason
        if isinstance(grund, ssl.SSLCertVerificationError | ssl.CertificateError):
            return Ergebnis(Befund.ZERTIFIKAT, detail=str(grund))
        if isinstance(grund, socket.gaierror):
            return Ergebnis(Befund.DNS, detail=str(grund))
        if isinstance(grund, ssl.SSLError):
            return Ergebnis(Befund.FREMD, detail=str(grund))
        return Ergebnis(Befund.NICHT_ERREICHBAR, detail=str(grund))
    except (TimeoutError, ConnectionError) as e:
        return Ergebnis(Befund.NICHT_ERREICHBAR, detail=str(e))
    except (ValueError, UnicodeDecodeError) as e:              # kein JSON ⇒ irgendeine andere Webseite
        return Ergebnis(Befund.FREMD, detail=str(e))
    if not isinstance(daten, dict) or not isinstance(daten.get("version"), str) or "application" not in daten:
        return Ergebnis(Befund.FREMD, detail="keine IC-WARE-HQ-Antwort")
    befund = Befund.OK if daten.get("status") == "ok" else Befund.STOERUNG
    return Ergebnis(befund, version=daten["version"][:40])


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kw: object) -> None:
        return None                                        # /health leitet nie weiter — sonst ist es nicht HQ


# ---- Einstellungen ------------------------------------------------------------------------------------------------
def benutzer_datei() -> Path:
    basis = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(basis) / APP_NAME / "launcher.json"


def vorgabe_datei() -> Path:
    """server.json neben der .exe — schreibt der Installer (Adresse aus dem Assistenten oder /URL=…)."""
    basis = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return basis / "server.json"


def _lies(datei: Path) -> dict[str, str]:
    try:
        d = json.loads(datei.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(d, dict) else {}


def adresse(benutzer: Path | None = None, vorgabe: Path | None = None) -> str | None:
    """Benutzer-Einstellung vor Installer-Vorgabe; Ungültiges zählt als nicht gesetzt."""
    for datei in (benutzer or benutzer_datei(), vorgabe or vorgabe_datei()):
        wert = _lies(datei).get("url")
        if wert:
            try:
                return normalisiere(wert)
            except Ungueltig:
                continue
    return None


def speichere(url: str | None = None, version: str | None = None, datei: Path | None = None) -> None:
    datei = datei or benutzer_datei()
    daten = _lies(datei)
    if url is not None:
        daten["url"] = normalisiere(url)
    if version is not None:
        daten["last_server_version"] = version
    datei.parent.mkdir(parents=True, exist_ok=True)
    tmp = datei.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, indent=2), encoding="utf-8")
    tmp.replace(datei)


def vergiss(datei: Path | None = None) -> None:
    (datei or benutzer_datei()).unlink(missing_ok=True)


def neue_version(ergebnis: Ergebnis, datei: Path | None = None) -> bool:
    """True, wenn der Server seit dem letzten Start aktualisiert wurde (Hinweis einmal anzeigen)."""
    alt = _lies(datei or benutzer_datei()).get("last_server_version")
    return bool(ergebnis.version and alt and alt != ergebnis.version)


# ---- Öffnen -------------------------------------------------------------------------------------------------------
def browser_befehl(url: str, kandidaten: list[Path] | None = None) -> list[str] | None:
    """Edge/Chrome im App-Modus (eigenes Fenster ohne Adressleiste); None ⇒ Standardbrowser."""
    if kandidaten is None:
        kandidaten = []
        for basis in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                      os.environ.get("LOCALAPPDATA")):
            if basis:
                kandidaten += [Path(basis) / "Microsoft/Edge/Application/msedge.exe",
                               Path(basis) / "Google/Chrome/Application/chrome.exe"]
    for exe in kandidaten:
        if exe.is_file():
            return [str(exe), f"--app={url}/app/"]
    return None


def oeffne(url: str) -> None:
    befehl = browser_befehl(url)
    if befehl:
        subprocess.Popen(befehl, close_fds=True)  # noqa: S603  (fester Pfad, URL geprüft)
    else:
        webbrowser.open(f"{url}/app/")


# ---- Kommandozeile (auch für Tests und Administratoren) -------------------------------------------------------------
HILFE = """IC WARE HQ Launcher {v}
  (ohne Argumente)      Instanz öffnen (fragt beim ersten Start nach der Adresse)
  --adresse-aendern     Adresse neu eingeben
  --check URL           nur prüfen, Ergebnis ausgeben (Exitcode 0 = IC WARE HQ erreichbar)
  --set-url URL         Adresse für diesen Benutzer setzen (ohne Rückfrage)
  --adresse             gespeicherte Adresse ausgeben (Exitcode 1 = keine)
  --vergessen           gespeicherte Adresse löschen
  --version"""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--version"]:
        print(VERSION)
        return 0
    if args[:1] in (["-h"], ["--help"]):
        print(HILFE.format(v=VERSION))
        return 0
    if args[:1] in (["--check"], ["--set-url"]) and len(args) == 2:
        try:
            url = normalisiere(args[1])
        except Ungueltig as e:
            print(f"Fehler: {e}", file=sys.stderr)
            return 2
        if args[0] == "--set-url":
            speichere(url)
            print(f"Adresse gespeichert: {url}")
            return 0
        erg = pruefe(url)
        print(f"{erg.befund.value}: {erg.text}" + (f" (Server {erg.version})" if erg.version else "")
              + (f" [{erg.detail}]" if erg.detail else ""))
        return 0 if erg.oeffnen else 1
    if args == ["--adresse"]:
        gespeichert = adresse()
        print(gespeichert or "keine Adresse gespeichert")
        return 0 if gespeichert else 1
    if args[:1] == ["--vergessen"]:
        vergiss()
        return 0
    if args and args != ["--adresse-aendern"]:
        print(HILFE.format(v=VERSION), file=sys.stderr)
        return 2
    from gui import starte  # GUI (tkinter) erst hier — Kommandozeile ohne Fenster
    return starte(neu_fragen=bool(args))


if __name__ == "__main__":
    sys.exit(main())
