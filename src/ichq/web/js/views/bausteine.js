// Gemeinsame Bausteine der Fachmodule (Listen, Filter, Formulare, Geld, Archivieren). Nur Anzeige — der Server prüft.
import { alertBox, dialog, einmal, ersetze, feld, h, toast } from "../dom.js";
import { get, meldung, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";

export const auswahl = (name, werte, wert, leer, extra = {}) => h("select", { name, class: "input", ...extra },
  leer !== undefined ? h("option", { value: "" }, leer) : null,
  Object.entries(werte).map(([k, v]) => h("option", { value: k, selected: k === wert }, v)));

export const eingabe = (name, wert, extra = {}) => h("input", { name, value: wert ?? "", ...extra });
export const text = (name, wert, extra = {}) => h("textarea", { name, maxlength: 20000, value: wert ?? "", ...extra });

export function seitenkopf(titel, unter, ...aktionen) {
  return h("div", { class: "pagehead" }, h("div", {}, unter ? h("a", { href: unter.href, class: "small" }, `← ${unter.text}`) : null,
    h("h1", {}, titel)), h("span", { class: "row" }, aktionen));
}

export function tabelle(kopf, zeilen, leer) {
  if (!zeilen.length) return h("p", { class: "empty" }, leer || "Noch keine Daten vorhanden.");
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, kopf.map((k) => h("th", { class: k.opt ? "opt" : null, scope: "col" }, k.text)))),
    h("tbody", {}, zeilen)));
}

export const zelle = (inhalt, opt) => h("td", { class: opt ? "opt" : null }, inhalt);

// Filterleiste: jede Änderung lädt die Liste mit den Werten als Query (Links bleiben teilbar)
export function filterleiste(pfad, felder, fest = {}) {
  const form = h("form", { class: "row", role: "search", "aria-label": "Filter" }, felder);
  const los = () => gehe(`${pfad}${query({ ...fest, ...Object.fromEntries(new FormData(form).entries()) })}`);
  form.addEventListener("change", los);
  form.addEventListener("submit", (e) => { e.preventDefault(); los(); });
  return form;
}

export function weiterLink(pfad, filter, cursor) {
  return cursor ? h("div", { class: "row row--end" }, h("a", { class: "btn btn--ghost btn--sm", href: `#${pfad}${query({ ...filter, cursor })}` }, "Weitere")) : null;
}

let mitgliederCache = null;
export async function mitglieder() {
  if (!darf("users.read")) return [];
  if (!mitgliederCache) mitgliederCache = (await get("/members?status=active&limit=100")).items;
  return mitgliederCache;
}
window.addEventListener("hashchange", () => { mitgliederCache = null; });

export const personen = (name, liste, wert, leer = "Niemand") => h("select", { name, class: "input" },
  h("option", { value: "" }, leer), liste.map((m) => h("option", { value: m.id, selected: m.id === wert }, m.display_name)));

// ---------- Geld (Cent, nie Gleitkomma für Summen) ----------
const FORMAT = {};
export function geld(minor, waehrung = "EUR") {
  if (minor === null || minor === undefined) return "—";
  if (!FORMAT[waehrung]) FORMAT[waehrung] = new Intl.NumberFormat("de-DE", { style: "currency", currency: waehrung });
  const vz = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  // Ganze Euro und Cent getrennt formatieren — kein Rundungsfehler durch Division
  const teile = FORMAT[waehrung].formatToParts(Math.trunc(abs / 100) + (abs % 100) / 100);
  return vz + teile.map((t) => t.value).join("");
}

// „1.234,56“ / „1234.56“ / „12“ → Cent (Ganzzahl) oder null, wenn ungültig
export function cent(eingabe) {
  const s = String(eingabe ?? "").trim().replace(/\s|€/g, "");
  if (!s) return null;
  const m = /^(-?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?$/.exec(s) || /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(s);
  if (!m) return null;
  const ganz = Number(m[2].replace(/\./g, ""));
  const nach = Number((m[3] || "0").padEnd(2, "0"));
  if (!Number.isSafeInteger(ganz * 100 + nach)) return null;
  return (m[1] ? -1 : 1) * (ganz * 100 + nach);
}
export const alsBetrag = (minor) => (minor === null || minor === undefined ? "" : `${minor < 0 ? "-" : ""}${Math.trunc(Math.abs(minor) / 100)},${String(Math.abs(minor) % 100).padStart(2, "0")}`);

// ---------- Archivieren ----------
export function archivKnopf(obj, nachher) {
  if (!obj) return null;
  const archiviert = obj.archived;
  return h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    if (!archiviert) {
      const ok = await dialog("Archivieren?", h("p", {}, `„${obj.title}“ verschwindet aus den Listen. Nichts wird gelöscht; du kannst es im Archiv wiederherstellen.`), "Archivieren", true);
      if (!ok) return;
    }
    try { await post(`/objects/${obj.id}/${archiviert ? "restore" : "archive"}`); toast(archiviert ? "Wiederhergestellt." : "Archiviert."); nachher(); }
    catch (e) { toast(meldung(e), "error"); }
  }) } }, archiviert ? "Wiederherstellen" : "Archivieren");
}

// Formular speichern mit Fehleranzeige im Formular
export function speichern(form, fehler, aktion) {
  form.addEventListener("submit", einmal(async () => {
    const d = Object.fromEntries(new FormData(form).entries());
    try { await aktion(d); } catch (e) { ersetze(fehler, alertBox(meldung(e))); }
  }));
  return form;
}

export const leerZuNull = (d, ...felder) => { for (const f of felder) if (d[f] === "") d[f] = null; return d; };
export { feld };
