// Mehrstufiger Assistent (Ersteinrichtung, Firma anlegen). Jeder Schritt hat eigene Felder und eine optionale
// Prüfung; erst der letzte Schritt schreibt. Die Werte bleiben beim Zurückgehen erhalten. Der Server prüft alles erneut.
import { alertBox, ersetze, h } from "../dom.js";
import { ApiError, meldung } from "../api.js";

// schritte: [{ titel, felder: (daten) => Knoten[], pruefe?: async (daten) => void, knopf? }]
// abschluss: async (daten) => void — Fehler erscheinen im letzten Schritt, mit Sprung zum passenden Schritt.
export function assistent(el, schritte, abschluss, daten = {}) {
  let nr = 0;
  const zeige = () => {
    const s = schritte[nr];
    const fehler = h("div", { "aria-live": "polite" });
    const letzter = nr === schritte.length - 1;
    const weiter = h("button", { class: "btn", type: "submit" }, s.knopf || (letzter ? "Anlegen" : "Weiter"));
    const zurueck = nr > 0 ? h("button", { class: "btn btn--ghost", type: "button", on: { click: () => { merke(); nr -= 1; zeige(); } } }, "Zurück") : null;
    const form = h("form", { class: "stack", novalidate: false }, fehler, s.felder(daten),
      h("div", { class: "row row--between" }, zurueck || h("span"), weiter));
    const merke = () => {
      // Checkbox-Gruppen (name mit []) als Liste, sonst Einzelwerte; nicht angehakte Boxen = leere Liste
      for (const box of form.querySelectorAll("input[type=checkbox][name$='[]']")) daten[box.name.slice(0, -2)] = [];
      for (const [k, v] of new FormData(form).entries()) {
        if (k.endsWith("[]")) daten[k.slice(0, -2)].push(v); else daten[k] = typeof v === "string" ? v.trim() : v;
      }
    };
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      merke();
      weiter.disabled = true;
      ersetze(fehler);
      try {
        if (s.pruefe) await s.pruefe(daten);
        if (letzter) await abschluss(daten); else { nr += 1; zeige(); }
      } catch (err) {
        const ziel = err && err.schritt !== undefined ? err.schritt : null;
        const text = err instanceof SchrittFehler ? err.message : meldung(err);
        if (!(err instanceof ApiError) && !(err instanceof SchrittFehler)) console.warn(err);   // nur Diagnose
        ersetze(fehler, alertBox(text), ziel !== null && ziel !== nr
          ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: () => { nr = ziel; zeige(); } } },
            `Zu „${schritte[ziel].titel}“`) : null);
      } finally {
        weiter.disabled = false;
      }
    });
    ersetze(el, h("ol", { class: "steps", "aria-label": "Schritte" }, schritte.map((x, i) =>
      h("li", { class: i < nr ? "done" : null, "aria-current": i === nr ? "step" : null }, h("span", {}, String(i + 1)), x.titel))),
    h("h2", {}, `Schritt ${nr + 1} von ${schritte.length}: ${s.titel}`), form);
    const erstes = form.querySelector("input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select");
    if (erstes) erstes.focus();
  };
  zeige();
}

// Fehler, der den Nutzer zu einem bestimmten Schritt zurückführt
export class SchrittFehler extends Error {
  constructor(text, schritt) { super(text); this.schritt = schritt; }
}

// Kürzel aus dem Namen — dieselbe Regel wie der Server (ichq.control.onboarding.slug_vorschlag), nur als Vorschlag
export function kuerzel(name) {
  const s = (name || "").toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48)
    .replace(/-+$/g, "");
  return s.length >= 3 ? s : s ? `${s}-firma` : "firma";
}

export const ZEITZONEN = { "Europe/Berlin": "Deutschland (Europe/Berlin)", "Europe/Vienna": "Österreich (Europe/Vienna)",
  "Europe/Zurich": "Schweiz (Europe/Zurich)", "Europe/Luxembourg": "Luxemburg", "Europe/Amsterdam": "Niederlande",
  "Europe/Paris": "Frankreich", "Europe/London": "Vereinigtes Königreich", "Europe/Istanbul": "Türkei", UTC: "UTC" };
export const WAEHRUNGEN = { EUR: "Euro (EUR)", CHF: "Schweizer Franken (CHF)", GBP: "Pfund (GBP)", USD: "US-Dollar (USD)", TRY: "Lira (TRY)" };
export const SPRACHEN = { de: "Deutsch", en: "Englisch" };

export function zusammenfassung(zeilen) {
  return h("dl", { class: "summary" }, zeilen.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v || "—")]));
}
