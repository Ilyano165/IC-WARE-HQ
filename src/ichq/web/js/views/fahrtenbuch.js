// Fahrtenbuch: Fahrten erfassen, korrigieren (neue Version mit Grund — die alte bleibt sichtbar), stornieren.
// Erfassungszeitpunkt steht neben dem Fahrtdatum. HQ sagt nichts darüber, ob das Fahrtenbuch ordnungsgemäß ist.
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { auswahl, eingabe, feld, filterleiste, seitenkopf, tabelle, zelle } from "./bausteine.js";

const ZWECK = { business: "Dienstfahrt", private: "Privat", commute: "Arbeitsweg" };
const heute = () => new Date().toISOString().slice(0, 10);

function luecke(f) {
  if (!f.km_gap) return null;
  return h("span", { class: "tag tag--warn" }, f.km_gap > 0 ? `Lücke ${f.km_gap} km` : `Überschneidung ${-f.km_gap} km`);
}

export async function liste(el, _p, q) {
  const filter = { vehicle: q.get("vehicle") || "", purpose: q.get("purpose") || "", voided: q.get("voided") || "", date_from: q.get("date_from") || "" };
  const [fahrzeuge, daten] = await Promise.all([get("/vehicles"), get(`/trips${query(filter)}`)]);
  const autos = Object.fromEntries(fahrzeuge.items.map((v) => [v.id, `${v.name} (${v.license_plate})`]));
  const leiste = filterleiste("/fahrtenbuch", [auswahl("vehicle", autos, filter.vehicle, "Alle Fahrzeuge", { "aria-label": "Fahrzeug" }),
    auswahl("purpose", ZWECK, filter.purpose, "Alle Fahrten", { "aria-label": "Zweck" }),
    auswahl("voided", { true: "Stornierte" }, filter.voided, "Gültige", { "aria-label": "Storno" }),
    eingabe("date_from", filter.date_from, { class: "input", type: "date", "aria-label": "Ab Datum" })]);
  const zeilen = daten.items.map((f) => h("tr", {}, zelle(h("a", { href: `#/fahrtenbuch/${f.id}` }, datum(f.current.trip_date))),
    zelle(f.vehicle.license_plate, true), zelle(`${f.current.start_km} – ${f.current.end_km} (${f.current.distance_km} km)`),
    zelle(ZWECK[f.current.purpose], true), zelle([f.current.destination || "—", " ", luecke(f), f.corrected ? h("span", { class: "tag tag--muted" }, ` korrigiert (${f.version_count})`) : null])));
  const knoepfe = [darf("vehicles.update") && fahrzeuge.items.length ? h("button", { class: "btn", type: "button", on: { click: () => anlegen(fahrzeuge.items) } }, "Fahrt erfassen") : null,
    darf("vehicles.create") ? h("button", { class: "btn btn--ghost", type: "button", on: { click: fahrzeug } }, "Fahrzeug anlegen") : null];
  ersetze(el, seitenkopf("Fahrtenbuch", null, ...knoepfe), alertBox(daten.note, "info"), leiste, h("br"),
    tabelle([{ text: "Datum" }, { text: "Fahrzeug", opt: true }, { text: "Kilometer" }, { text: "Zweck", opt: true }, { text: "Ziel" }], zeilen,
      fahrzeuge.items.length ? "Keine Fahrten für diesen Filter." : "Noch kein Fahrzeug angelegt."));
}

async function fahrzeug() {
  const d = await dialog("Fahrzeug anlegen", [feld("Bezeichnung", eingabe("name", "", { required: true, maxlength: 100 })),
    feld("Kennzeichen", eingabe("license_plate", "", { required: true, maxlength: 20 })),
    feld("Nutzung", auswahl("usage", { mixed: "auch privat", company: "nur betrieblich" }, "mixed"))], "Anlegen");
  if (!d) return;
  try { await post("/vehicles", d); toast("Fahrzeug angelegt."); gehe("/fahrtenbuch"); } catch (e) { toast(meldung(e), "error"); }
}

function felder(v) {
  return [h("div", { class: "grid2" }, feld("Datum", eingabe("trip_date", v.trip_date || heute(), { type: "date", required: true, max: heute() })),
    feld("Zweck", auswahl("purpose", ZWECK, v.purpose || "business"))),
  h("div", { class: "grid2" }, feld("km Beginn", eingabe("start_km", v.start_km ?? "", { type: "number", min: 0, required: true })),
    feld("km Ende", eingabe("end_km", v.end_km ?? "", { type: "number", min: 0, required: true }))),
  h("div", { class: "grid2" }, feld("Start", eingabe("start_place", v.start_place, { maxlength: 200 })),
    feld("Reiseziel", eingabe("destination", v.destination, { maxlength: 300 }))),
  h("div", { class: "grid2" }, feld("Reisezweck", eingabe("reason", v.reason, { maxlength: 500 })),
    feld("Geschäftspartner", eingabe("business_partner", v.business_partner, { maxlength: 300 })))];
}

const zahlen = (d) => ({ ...d, start_km: Number(d.start_km), end_km: Number(d.end_km) });

async function anlegen(autos) {
  const d = await dialog("Fahrt erfassen", [feld("Fahrzeug", auswahl("vehicle", Object.fromEntries(autos.map((v) => [v.id, `${v.name} (${v.license_plate})`])), autos[0].id)), ...felder({})], "Erfassen");
  if (!d) return;
  try { const f = await post("/trips", zahlen(d)); toast("Fahrt erfasst."); gehe(`/fahrtenbuch/${f.id}`); } catch (e) { toast(meldung(e), "error"); }
}

export async function detail(el, { ref }) {
  const f = await get(`/trips/${ref}`);
  const neu = () => detail(el, { ref });
  const c = f.current;
  const aktiv = !c.voided && darf("vehicles.update");
  const korrigieren = aktiv ? h("button", { class: "btn btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Fahrt korrigieren", [h("p", { class: "small" }, "Die Korrektur wird als neue Version gespeichert. Die bisherige Fassung bleibt in der Fahrt sichtbar."),
      ...felder(c), feld("Grund der Korrektur", eingabe("change_reason", "", { required: true, minlength: 5, maxlength: 500 }))], "Korrigieren");
    if (!d) return;
    try { await post(`/trips/${ref}/corrections`, zahlen(d)); toast("Neue Version gespeichert."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Korrigieren") : null;
  const storno = aktiv ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Fahrt stornieren?", [feld("Grund", eingabe("reason", "", { required: true, minlength: 5, maxlength: 500 }))], "Stornieren", true);
    if (!d) return;
    try { await post(`/trips/${ref}/void`, d); toast("Storniert (als neue Version)."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Stornieren") : null;
  const versionen = f.versions.map((v) => h("tr", {}, zelle(`V${v.version}${v.voided ? " · storniert" : ""}`),
    zelle(`${datum(v.trip_date)} · ${v.start_km}–${v.end_km} km · ${ZWECK[v.purpose]}${v.destination ? ` · ${v.destination}` : ""}`),
    zelle(`erfasst ${zeit(v.recorded_at)} von ${v.recorded_by ? v.recorded_by.display_name : "—"}${v.days_recorded_after_trip > 0 ? ` (${v.days_recorded_after_trip} Tage nach der Fahrt)` : ""}`, true),
    zelle(v.change_reason || "—")));
  ersetze(el, seitenkopf(`Fahrt ${datum(c.trip_date)}`, { href: "#/fahrtenbuch", text: "Fahrtenbuch" }, luecke(f), korrigieren, storno),
    c.voided ? alertBox(`Storniert: ${c.change_reason}`, "info") : null,
    h("section", { class: "card" }, h("h2", {}, `${f.vehicle.name} (${f.vehicle.license_plate})`),
      h("p", {}, `${c.start_km} – ${c.end_km} km (${c.distance_km} km) · ${ZWECK[c.purpose]} · Fahrer: ${f.driver ? f.driver.display_name : "—"}`),
      c.purpose === "business" ? h("p", {}, `Ziel: ${c.destination} · Zweck: ${c.reason}${c.business_partner ? ` · Partner: ${c.business_partner}` : ""}`) : null,
      h("p", { class: "small muted" }, f.note)),
    h("section", { class: "card" }, h("h2", {}, "Versionen (Korrekturhistorie)"),
      tabelle([{ text: "Version" }, { text: "Inhalt" }, { text: "Erfasst", opt: true }, { text: "Grund" }], versionen)));
}
