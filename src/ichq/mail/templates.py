"""Mailvorlagen (Text + HTML). Alle eingesetzten Werte werden für HTML maskiert; Links nur aus ``public_origin``.

Keine Vorlagen-Engine: wenige, feste Texte — so bleibt prüfbar, dass nichts ungeprüft in HTML landet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape

MARKE = "IC WARE HQ"


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def _html(titel: str, absaetze: list[str], link: tuple[str, str] | None = None, hinweis: str = "") -> str:
    teile = "".join(f'<p style="margin:0 0 14px">{escape(a)}</p>' for a in absaetze)
    knopf = ""
    if link:
        url, beschriftung = link
        knopf = (f'<p style="margin:22px 0"><a href="{escape(url, quote=True)}" style="background:#19E56E;'
                 f'color:#060708;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">'
                 f'{escape(beschriftung)}</a></p><p style="margin:0 0 14px;font-size:13px;color:#5b6168">'
                 f'Falls der Knopf nicht funktioniert: {escape(url)}</p>')
    fuss = f'<p style="margin:22px 0 0;font-size:13px;color:#5b6168">{escape(hinweis)}</p>' if hinweis else ""
    return (f'<!doctype html><html lang="de"><body style="margin:0;background:#f4f5f6;font-family:Inter,Arial,'
            f'sans-serif;color:#111417"><div style="max-width:560px;margin:0 auto;padding:28px 20px">'
            f'<div style="font-weight:700;letter-spacing:.04em;margin-bottom:18px">{MARKE}</div>'
            f'<div style="background:#fff;border-radius:12px;padding:26px 24px">'
            f'<h1 style="font-size:20px;margin:0 0 16px">{escape(titel)}</h1>{teile}{knopf}{fuss}</div>'
            f'</div></body></html>')


def _text(titel: str, absaetze: list[str], link: tuple[str, str] | None = None, hinweis: str = "") -> str:
    zeilen = [titel, "", *[a + "\n" for a in absaetze]]
    if link:
        zeilen += [link[0], ""]
    if hinweis:
        zeilen += [hinweis, ""]
    return "\n".join(zeilen) + f"\n— {MARKE}\n"


def _mail(subject: str, titel: str, absaetze: list[str], link: tuple[str, str] | None = None,
          hinweis: str = "") -> Rendered:
    return Rendered(f"{MARKE}: {subject}", _text(titel, absaetze, link, hinweis),
                    _html(titel, absaetze, link, hinweis))


def password_reset(basis: str, token: str, minuten: int) -> Rendered:
    # Token im Fragment (#): erreicht nie ein Server- oder Proxy-Log
    return _mail("Passwort zurücksetzen", "Neues Passwort festlegen",
                 [f"Für dein Konto wurde ein neues Passwort angefordert. Der Link ist {minuten} Minuten gültig "
                  "und nur einmal verwendbar."],
                 (f"{basis}/reset#token={token}", "Passwort festlegen"),
                 "Wenn du das nicht warst, ignoriere diese Mail — dein Passwort bleibt unverändert.")


def invitation(basis: str, token: str, tage: int) -> Rendered:
    # Ohne Firmennamen: eine vertippte Adresse soll nicht erfahren, wer mit wem arbeitet (M3-Entscheidung).
    # Die Firma sieht man nach dem Öffnen des Links.
    return _mail("Einladung", "Einladung zu IC WARE HQ",
                 [f"Du wurdest zu {MARKE} eingeladen. Der Link ist {tage} Tage gültig und nur einmal "
                  "verwendbar."],
                 (f"{basis}/invite#token={token}", "Einladung annehmen"),
                 "Wenn du nichts damit anfangen kannst, ignoriere diese Mail.")


SICHERHEIT: dict[str, tuple[str, str]] = {
    "password_changed": ("Passwort geändert", "Das Passwort deines Kontos wurde geändert. Andere Sitzungen "
                         "wurden abgemeldet."),
    "password_reset_completed": ("Passwort zurückgesetzt", "Das Passwort deines Kontos wurde über einen "
                                 "Rücksetz-Link neu gesetzt. Alle Sitzungen wurden abgemeldet."),
    "totp_enabled": ("Zwei-Faktor-Anmeldung eingeschaltet", "Für dein Konto ist jetzt die Zwei-Faktor-Anmeldung "
                     "aktiv."),
    "totp_disabled": ("Zwei-Faktor-Anmeldung ausgeschaltet", "Für dein Konto wurde die Zwei-Faktor-Anmeldung "
                      "abgeschaltet."),
    "recovery_codes_regenerated": ("Neue Wiederherstellungscodes", "Für dein Konto wurden neue "
                                   "Wiederherstellungscodes erzeugt; die alten gelten nicht mehr."),
    "account_locked": ("Konto vorübergehend gesperrt", "Nach mehreren fehlgeschlagenen Anmeldeversuchen wurde "
                       "dein Konto vorübergehend gesperrt."),
}


def security_notice(event: str, zeitpunkt: datetime | None = None) -> Rendered:
    titel, satz = SICHERHEIT[event]
    wann = (zeitpunkt or datetime.now(UTC)).strftime("%d.%m.%Y %H:%M UTC")
    return _mail(titel, titel, [satz, f"Zeitpunkt: {wann}"],
                 hinweis="Warst du das nicht? Setze sofort über die Anmeldeseite ein neues Passwort und "
                         "informiere den Administrator deiner Firma.")


def alert(betreff: str, nachricht: str, server: str) -> Rendered:
    kopf = betreff if betreff.startswith("Entwarnung") else f"WARNUNG — {betreff}"
    return _mail(kopf, betreff, [nachricht, f"Server: {server}"],
                 hinweis="Automatische Betreiberwarnung (deploy/hq check). Details: deploy/hq status und "
                         "deploy/hq logs.")
