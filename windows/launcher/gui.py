"""Dialoge des Windows-Launchers (tkinter, in Python enthalten). Logik und Prüfung: ichq_launcher.py."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import ichq_launcher as L


def _frage_adresse(vorschlag: str = "", fehler: str = "") -> str | None:
    """Eingabefenster für die Adresse; None = abgebrochen."""
    fenster = tk.Tk()
    fenster.title(f"{L.APP_NAME} — Adresse der Firma")
    fenster.resizable(False, False)
    rahmen = ttk.Frame(fenster, padding=16)
    rahmen.grid()
    ttk.Label(rahmen, text="Adresse Ihrer IC-WARE-HQ-Instanz (von Ihrer Betreuung):").grid(sticky="w")
    wert = tk.StringVar(value=vorschlag)
    feld = ttk.Entry(rahmen, textvariable=wert, width=48)
    feld.grid(sticky="we", pady=(4, 4))
    ttk.Label(rahmen, text="Beispiel: hq.ihre-firma.de", foreground="#666").grid(sticky="w")
    meldung = ttk.Label(rahmen, text=fehler, foreground="#b00020", wraplength=380)
    meldung.grid(sticky="w", pady=(6, 0))
    ergebnis: dict[str, str] = {}

    def weiter(_: object = None) -> None:
        try:
            url = L.normalisiere(wert.get())
        except L.Ungueltig as e:
            meldung.configure(text=str(e))
            return
        meldung.configure(text="Verbindung wird geprüft …")
        fenster.update_idletasks()
        erg = L.pruefe(url)
        if not erg.oeffnen:
            meldung.configure(text=erg.text)
            return
        ergebnis["url"] = url
        fenster.destroy()

    knoepfe = ttk.Frame(rahmen)
    knoepfe.grid(sticky="e", pady=(12, 0))
    ttk.Button(knoepfe, text="Abbrechen", command=fenster.destroy).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(knoepfe, text="Verbinden", command=weiter).grid(row=0, column=1)
    fenster.bind("<Return>", weiter)
    fenster.bind("<Escape>", lambda _: fenster.destroy())
    feld.focus_set()
    fenster.mainloop()
    return ergebnis.get("url")


def starte(neu_fragen: bool = False) -> int:
    url = None if neu_fragen else L.adresse()
    if url is None:
        url = _frage_adresse(L.adresse() or "")
        if url is None:
            return 1
        L.speichere(url)
    erg = L.pruefe(url)
    wurzel = tk.Tk()
    wurzel.withdraw()
    if not erg.oeffnen:
        if erg.befund in (L.Befund.FREMD, L.Befund.DNS) and messagebox.askyesno(
                L.APP_NAME, f"{erg.text}\n\nAdresse: {url}\n\nAndere Adresse eingeben?"):
            wurzel.destroy()
            return starte(neu_fragen=True)
        messagebox.showerror(L.APP_NAME, f"{erg.text}\n\nAdresse: {url}")
        wurzel.destroy()
        return 1
    if erg.befund is L.Befund.STOERUNG:
        messagebox.showwarning(L.APP_NAME, erg.text)
    elif L.neue_version(erg):
        messagebox.showinfo(L.APP_NAME, f"IC WARE HQ wurde auf Version {erg.version} aktualisiert. "
                                        "Die Neuerungen stehen sofort allen Nutzern zur Verfügung.")
    wurzel.destroy()
    L.speichere(version=erg.version)
    L.oeffne(url)
    return 0
