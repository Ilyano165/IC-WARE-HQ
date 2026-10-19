// Ausgaben & Belege: fehlende Belege zuerst, erfassen mit Beleg-Upload, Beleg anhängen/lösen, bezahlt, stornieren.
// Ein Beleg zählt erst nach bestandener Virenprüfung — das entscheidet der Server, nicht die Oberfläche.
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { get, hochladen, meldung, patch, post, put, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { alsBetrag, auswahl, cent, eingabe, Eingabefehler, feld, fehlertext, filterleiste, geld, leerZuNull,
  mitglieder, personen, seitenkopf, speichern, tabelle, text, weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

const BELEG = { missing: "Beleg fehlt", unchecked: "Beleg wird geprüft", rejected: "Beleg abgelehnt", complete: "Beleg vorhanden" };
const ANSICHT = { fehlend: "Fehlende Belege", wiedervorlage: "Wiedervorlage fällig", alle: "Alle Ausgaben", unbezahlt: "Unbezahlt", storniert: "Storniert" };
const PARAMS = { fehlend: { evidence: ["missing", "unchecked", "rejected"] }, wiedervorlage: { follow_up_due: true }, alle: {}, unbezahlt: { payment_status: "unpaid" }, storniert: { voided: true } };
const heute = () => new Date().toISOString().slice(0, 10);

export const belegTag = (b) => h("span", { class: `tag${b === "complete" ? "" : b === "unchecked" ? " tag--warn" : " tag--danger"}` }, BELEG[b] || b);

export async function liste(el, _p, q) {
  const ansicht = q.get("ansicht") || "fehlend";
  const filter = { ansicht, q: q.get("q") || "", date_from: q.get("date_from") || "", date_to: q.get("date_to") || "",
    responsible: q.get("responsible") || "", project: q.get("project") || "" };
  const daten = await get(`/receipts${query({ ...PARAMS[ansicht] || {}, q: filter.q, date_from: filter.date_from, date_to: filter.date_to,
    responsible: filter.responsible, project: filter.project, limit: 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/belege", [auswahl("ansicht", ANSICHT, ansicht, undefined, { "aria-label": "Ansicht" }),
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Titel, Lieferant, Kategorie", "aria-label": "Ausgaben suchen", maxlength: 100 }),
    eingabe("date_from", filter.date_from, { class: "input", type: "date", "aria-label": "Von" }),
    eingabe("date_to", filter.date_to, { class: "input", type: "date", "aria-label": "Bis" }),
    auswahl("responsible", { me: "Ich bin zuständig" }, filter.responsible, "Alle Zuständigen", { "aria-label": "Zuständig" })], { project: filter.project });
  const zeilen = daten.items.map((r) => h("tr", {}, zelle(h("a", { href: `#/belege/${r.id}` }, r.title)), zelle(datum(r.expense_date), true),
    zelle(r.supplier_name || "—", true), zelle(geld(r.amount_minor, r.currency)), zelle(r.voided_at ? h("span", { class: "tag tag--muted" }, "storniert") : belegTag(r.evidence))));
  const neu = darf("finance.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Ausgabe erfassen") : null;
  ersetze(el, seitenkopf("Ausgaben & Belege", null, neu), leiste, h("br"),
    tabelle([{ text: "Ausgabe" }, { text: "Datum", opt: true }, { text: "Lieferant", opt: true }, { text: "Betrag" }, { text: "Beleg" }], zeilen,
      ansicht === "fehlend" ? "Keine fehlenden Belege — alles vollständig." : "Noch keine Ausgaben erfasst."),
    weiterLink("/belege", filter, daten.next_cursor));
}

async function projekte() { return darf("projects.read") ? (await get("/projects?limit=100")).items : []; }

function felder(r, leute, pl) {
  return [feld("Titel", eingabe("title", r.title, { required: true, maxlength: 300 })),
    h("div", { class: "grid2" }, feld("Datum", eingabe("expense_date", r.expense_date || heute(), { type: "date", required: true, max: heute() })),
      feld("Betrag brutto (€)", eingabe("betrag", alsBetrag(r.amount_minor), { required: true, inputmode: "decimal" }))),
    h("div", { class: "grid2" }, feld("Lieferant", eingabe("supplier_name", r.supplier_name, { maxlength: 200 })),
      feld("Kategorie", eingabe("category", r.category, { maxlength: 60, placeholder: "z. B. Material" }))),
    h("div", { class: "grid2" }, pl.length ? feld("Projekt", h("select", { name: "project", class: "input" }, h("option", { value: "" }, "— ohne —"),
      pl.map((p) => h("option", { value: p.id, selected: r.project && r.project.id === p.id }, p.name)))) : null,
    leute.length ? feld("Zuständig", personen("responsible", leute, r.responsible ? r.responsible.id : "")) : null),
    h("div", { class: "grid2" }, feld("Zahlung", auswahl("payment_status", { unpaid: "offen", paid: "bezahlt" }, r.payment_status || "unpaid")),
      feld("Fällig am", eingabe("due_date", r.due_date, { type: "date" }))),
    feld("Beschreibung", text("description", r.description, { rows: 2, maxlength: 5000 }))];
}

function body(d, leute, pl) {
  const b = { ...d, amount_minor: cent(d.betrag) };
  delete b.betrag;
  if (!b.amount_minor || b.amount_minor <= 0) throw new Eingabefehler("Betrag ungültig (z. B. 49,99)");
  leerZuNull(b, "project", "responsible", "due_date", "supplier_name", "category");
  if (!pl.length) delete b.project;
  if (!leute.length) delete b.responsible;
  return b;
}

async function anlegen() {
  const [leute, pl] = await Promise.all([mitglieder(), projekte()]);
  const datei = h("input", { type: "file", name: "datei", accept: "application/pdf,image/*" });
  const d = await dialog("Ausgabe erfassen", [...felder({}, leute, pl), darf("files.upload") ? feld("Beleg (PDF/Bild)", datei, "Wird auf Viren geprüft — bis dahin „Beleg wird geprüft“.") : null], "Erfassen");
  if (!d) return;
  try {
    const b = body(d, leute, pl);
    delete b.datei;
    if (datei.files && datei.files[0]) b.document = (await hochladen(datei.files[0])).id;
    const r = await post("/receipts", b);
    toast("Ausgabe erfasst."); gehe(`/belege/${r.id}`);
  } catch (e) { toast(fehlertext(e), "error"); }
}

export async function detail(el, { ref }) {
  const [r, leute, pl] = await Promise.all([get(`/receipts/${ref}`), mitglieder(), projekte()]);
  const neu = () => detail(el, { ref });
  const aenderbar = !r.voided_at && darf("finance.update");
  const fehler = h("div");
  const stamm = aenderbar ? speichern(h("form", { class: "stack" }, fehler, felder(r, leute, pl),
    h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
    await patch(`/receipts/${ref}`, body(d, leute, pl)); toast("Gespeichert."); neu();
  }) : h("p", {}, `${datum(r.expense_date)} · ${r.supplier_name || "—"} · ${geld(r.amount_minor, r.currency)}`);
  const kom = h("section", { class: "card" });
  const storno = aenderbar ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Ausgabe stornieren?", [h("p", {}, "Für Fehlerfassungen. Die Ausgabe bleibt sichtbar, zählt aber nicht mehr mit und ist danach unveränderlich."),
      feld("Grund", eingabe("reason", "", { required: true, minlength: 3, maxlength: 500 }))], "Stornieren", true);
    if (!d) return;
    try { await post(`/receipts/${ref}/void`, d); toast("Storniert."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Stornieren") : null;
  ersetze(el, seitenkopf(r.title, { href: "#/belege", text: "Ausgaben & Belege" }, r.voided_at ? h("span", { class: "tag tag--muted" }, "storniert") : belegTag(r.evidence), storno),
    r.voided_at ? alertBox(`Storniert ${zeit(r.voided_at)}: ${r.void_reason}`, "info") : null,
    belegKarte(r, neu), h("section", { class: "card" }, h("h2", {}, "Ausgabe"), stamm), kom);
  await kommentare(kom, ref);
}

function belegKarte(r, neu) {
  const aenderbar = !r.voided_at && darf("finance.update");
  const datei = h("input", { type: "file", accept: "application/pdf,image/*", "aria-label": "Beleg hochladen" });
  const setzen = async (doc) => { try { await put(`/receipts/${r.id}/document`, { document: doc }); toast(doc ? "Beleg verknüpft." : "Beleg gelöst."); neu(); } catch (e) { toast(meldung(e), "error"); } };
  const grund = aenderbar && r.evidence !== "complete" ? speichern(h("form", { class: "row" },
    feld("Warum fehlt der Beleg?", eingabe("missing_reason", r.missing_reason, { maxlength: 500 })),
    feld("Wiedervorlage", eingabe("follow_up_on", r.follow_up_on, { type: "date" })),
    h("button", { class: "btn btn--ghost btn--sm", type: "submit" }, "Vermerken")), h("div"), async (d) => {
    await patch(`/receipts/${r.id}`, leerZuNull(d, "missing_reason", "follow_up_on")); toast("Vermerkt."); neu();
  }) : null;
  return h("section", { class: "card" }, h("h2", {}, "Beleg"),
    h("p", {}, belegTag(r.evidence), " ", r.document ? h("a", { href: `#/dokumente/${r.document.id}` }, r.document.title) : (r.has_document ? "(Dokument nicht sichtbar)" : "")),
    r.evidence === "unchecked" ? h("p", { class: "muted small" }, "Das Dokument liegt in Quarantäne, bis die Virenprüfung abgeschlossen ist.") : null,
    r.missing_reason ? h("p", { class: "small" }, `Vermerk: ${r.missing_reason}`) : null,
    aenderbar && darf("files.upload") ? h("div", { class: "row" }, datei, h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
      if (!datei.files || !datei.files[0]) { toast("Bitte zuerst eine Datei wählen.", "error"); return; }
      try { const doc = await hochladen(datei.files[0]); await setzen(doc.id); } catch (e) { toast(meldung(e), "error"); }
    }) } }, "Hochladen & verknüpfen")) : null,
    aenderbar && r.has_document ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(() => setzen(null)) } }, "Beleg lösen") : null,
    grund);
}
