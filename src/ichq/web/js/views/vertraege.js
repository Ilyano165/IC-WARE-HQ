// Verträge: Verwaltungsakte mit Laufzeit und Kündigungsfrist. Termine rechnet der Server aus den Angaben —
// keine Rechtsprüfung; hochgeladene Dokumente werden nicht ausgewertet.
import { alertBox, datum, dialog, einmal, ersetze, h, toast } from "../dom.js";
import { get, hochladen, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { alsBetrag, auswahl, cent, eingabe, Eingabefehler, feld, fehlertext, filterleiste, geld, leerZuNull, mitglieder,
  personen, seitenkopf, speichern, tabelle, text, weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

const ZUSTAND = { draft: "Entwurf", active: "läuft", terminated: "gekündigt", ended: "beendet" };
const EINHEIT = { days: "Tage", weeks: "Wochen", months: "Monate" };
const ZAHLUNG = { none: "—", once: "einmalig", monthly: "monatlich", quarterly: "vierteljährlich", yearly: "jährlich" };
const ANSICHT = { alle: "Alle", kuendigung: "Kündigung in 60 Tagen", aktiv: "Laufend", gekuendigt: "Gekündigt" };
const heute = () => new Date().toISOString().slice(0, 10);

function termin(v) {
  if (v.state !== "active" || !v.notice_deadline) return h("span", { class: "tag tag--muted" }, ZUSTAND[v.state]);
  return h("span", { class: v.days_to_notice <= 60 ? "tag tag--warn" : "tag" }, `kündbar bis ${datum(v.notice_deadline)}`);
}

export async function liste(el, _p, q) {
  const ansicht = q.get("ansicht") || "alle";
  const filter = { ansicht, q: q.get("q") || "" };
  const daten = ansicht === "kuendigung" ? await get("/contracts/notice-due?days=60")
    : await get(`/contracts${query({ q: filter.q, status: ansicht === "aktiv" ? ["active"] : ansicht === "gekuendigt" ? ["terminated"] : undefined, limit: 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/vertraege", [auswahl("ansicht", ANSICHT, ansicht, undefined, { "aria-label": "Ansicht" }),
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Titel, Partei, Nummer", "aria-label": "Verträge suchen", maxlength: 100 })]);
  const zeilen = daten.items.map((v) => h("tr", {}, zelle(h("a", { href: `#/vertraege/${v.id}` }, v.title)),
    zelle(v.customer ? v.customer.title : v.counterparty_name || "—", true), zelle(v.term_end ? datum(v.term_end) : "unbefristet", true),
    zelle(v.amount_minor !== null ? `${geld(v.amount_minor, v.currency)} ${ZAHLUNG[v.billing]}` : "—", true), zelle(termin(v))));
  const neu = darf("contracts.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Vertrag anlegen") : null;
  ersetze(el, seitenkopf("Verträge", null, neu), leiste, h("br"),
    tabelle([{ text: "Vertrag" }, { text: "Partei", opt: true }, { text: "Laufzeit bis", opt: true }, { text: "Kosten", opt: true }, { text: "Stand" }],
      zeilen, "Keine Verträge für diese Ansicht."),
    daten.truncated ? alertBox("Mehr als 1000 laufende Verträge — die Liste ist unvollständig.", "error") : weiterLink("/vertraege", filter, daten.next_cursor));
}

async function kunden() { return darf("customers.read") ? (await get("/customers?limit=100")).items : []; }

function felder(v, leute, kl) {
  return [feld("Titel", eingabe("title", v.title, { required: true, maxlength: 300 })),
    h("div", { class: "grid2" }, kl.length ? feld("Kunde", h("select", { name: "customer", class: "input" }, h("option", { value: "" }, "— kein Kunde —"),
      kl.map((k) => h("option", { value: k.id, selected: v.customer && v.customer.id === k.id }, k.name)))) : null,
    feld("Vertragspartner (Freitext)", eingabe("counterparty_name", v.counterparty_name, { maxlength: 200 }))),
    h("div", { class: "grid2" }, feld("Art", eingabe("contract_type", v.contract_type, { maxlength: 60, placeholder: "z. B. Miete" })),
      feld("Vertragsnummer", eingabe("reference", v.reference, { maxlength: 100 }))),
    h("div", { class: "grid2" }, feld("Beginn", eingabe("start_date", v.start_date, { type: "date" })),
      feld("Laufzeit bis", eingabe("end_date", v.end_date, { type: "date" }), "Leer = unbefristet")),
    h("div", { class: "grid2" }, feld("Kündigungsfrist", eingabe("notice_value", v.notice_value ?? "", { type: "number", min: 0, max: 3650 })),
      feld("Einheit", auswahl("notice_unit", EINHEIT, v.notice_unit || "months"))),
    h("div", { class: "grid2" }, feld("Verlängert sich automatisch", auswahl("auto_renew", { false: "nein", true: "ja" }, String(!!v.auto_renew))),
      feld("um Monate", eingabe("renewal_months", v.renewal_months ?? "", { type: "number", min: 1, max: 120 }))),
    h("div", { class: "grid2" }, feld("Kosten (€)", eingabe("betrag", alsBetrag(v.amount_minor), { inputmode: "decimal" })),
      feld("Zahlweise", auswahl("billing", ZAHLUNG, v.billing || "none"))),
    leute.length ? feld("Zuständig", personen("responsible", leute, v.responsible ? v.responsible.id : "")) : null,
    feld("Notizen", text("notes", v.notes, { rows: 3, maxlength: 20000 }))];
}

function body(d, kl, leute) {
  const b = { ...d, auto_renew: d.auto_renew === "true", amount_minor: d.betrag ? cent(d.betrag) : null,
    notice_value: d.notice_value === "" ? null : Number(d.notice_value), renewal_months: d.renewal_months === "" ? null : Number(d.renewal_months) };
  delete b.betrag;
  if (d.betrag && (b.amount_minor === null || b.amount_minor < 0)) throw new Eingabefehler("Kosten ungültig (z. B. 1.200,00)");
  if (b.notice_value === null) b.notice_unit = null;
  leerZuNull(b, "customer", "counterparty_name", "contract_type", "reference", "start_date", "end_date", "responsible");
  if (!kl.length) delete b.customer;
  if (!leute.length) delete b.responsible;
  return b;
}

async function anlegen() {
  const [leute, kl] = await Promise.all([mitglieder(), kunden()]);
  const d = await dialog("Vertrag anlegen", felder({}, leute, kl), "Anlegen");
  if (!d) return;
  try { const v = await post("/contracts", body(d, kl, leute)); toast("Vertrag angelegt."); gehe(`/vertraege/${v.id}`); } catch (e) { toast(fehlertext(e), "error"); }
}

export async function detail(el, { ref }) {
  const [v, leute, kl, links] = await Promise.all([get(`/contracts/${ref}`), mitglieder(), kunden(), get(`/objects/${ref}/links`)]);
  const neu = () => detail(el, { ref });
  const aenderbar = v.status !== "terminated" && darf("contracts.update");
  const fehler = h("div");
  const stamm = aenderbar ? speichern(h("form", { class: "stack" }, fehler, felder(v, leute, kl),
    h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
    await patch(`/contracts/${ref}`, body(d, kl, leute)); toast("Gespeichert."); neu();
  }) : h("p", {}, `${v.customer ? v.customer.title : v.counterparty_name || "—"} · ${v.contract_type || ""}`);
  const kuendigen = aenderbar ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Kündigung erfassen", [h("p", { class: "small" }, "HQ verschickt nichts und prüft die Wirksamkeit nicht — hier wird nur festgehalten, was passiert ist."),
      feld("Kündigung zugegangen am", eingabe("terminated_on", heute(), { type: "date", required: true, max: heute() })),
      feld("Wirksam zum", eingabe("effective_on", v.term_end || heute(), { type: "date", required: true })),
      feld("Vermerk", eingabe("note", "", { maxlength: 500 }))], "Erfassen", true);
    if (!d) return;
    try { await post(`/contracts/${ref}/terminate`, d); toast("Kündigung erfasst."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Kündigung erfassen") : null;
  const termine = h("section", { class: "card" }, h("h2", {}, "Termine"),
    h("p", { class: "small muted" }, "Berechnet aus den Angaben im Vertrag — keine rechtliche Prüfung."),
    h("p", {}, `Laufzeit bis: ${v.term_end ? datum(v.term_end) : "unbefristet"}${v.renewals ? ` (${v.renewals}× automatisch verlängert)` : ""}`),
    v.notice_deadline ? h("p", {}, `Kündigung muss zugehen bis: ${datum(v.notice_deadline)} (in ${v.days_to_notice} Tagen)`) : null,
    v.status === "terminated" ? alertBox(`Gekündigt am ${datum(v.terminated_on)}, wirksam zum ${datum(v.termination_effective_on)}${v.termination_note ? ` — ${v.termination_note}` : ""}`, "info") : null);
  const kom = h("section", { class: "card" });
  ersetze(el, seitenkopf(v.title, { href: "#/vertraege", text: "Verträge" }, termin(v), kuendigen), termine,
    dokumente(v, links.items, neu), h("section", { class: "card" }, h("h2", {}, "Vertrag"), stamm), kom);
  await kommentare(kom, ref);
}

function dokumente(v, links, neu) {
  const docs = links.filter((l) => l.link_type === "attachment" && l.direction === "outgoing");
  const datei = h("input", { type: "file", accept: "application/pdf,image/*", "aria-label": "Vertragsdokument hochladen" });
  const hoch = darf("contracts.update") && darf("files.upload") ? h("div", { class: "row" }, datei, h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    if (!datei.files || !datei.files[0]) { toast("Bitte zuerst eine Datei wählen.", "error"); return; }
    try { const doc = await hochladen(datei.files[0]); await post(`/objects/${v.id}/links`, { target: doc.id, link_type: "attachment" }); toast("Dokument angehängt."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Hochladen & anhängen")) : null;
  return h("section", { class: "card" }, h("h2", {}, "Dokumente"),
    h("p", { class: "small muted" }, "Ein hochgeladenes Dokument wird nicht ausgewertet — ein Upload ist keine rechtliche Prüfung."),
    docs.length ? h("ul", { class: "list" }, docs.map((l) => h("li", {}, h("a", { href: `#/dokumente/${l.object.id}` }, l.object.title)))) : h("p", { class: "empty" }, "Noch kein Dokument angehängt."),
    hoch);
}
