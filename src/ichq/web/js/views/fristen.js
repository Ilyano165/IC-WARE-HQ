// Fristen: selbst angelegt — HQ gibt keine Fristen vor. Ohne Quelle steht „nicht amtlich bestätigt“ daneben.
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { auswahl, eingabe, feld, filterleiste, leerZuNull, mitglieder, personen, seitenkopf, speichern, tabelle, text,
  weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

export const KATEGORIE = { tax: "Steuer", contract: "Vertrag", payroll: "Lohn", insurance: "Versicherung", authority: "Behörde", other: "Sonstiges" };
const WDH = { none: "einmalig", monthly: "monatlich", quarterly: "vierteljährlich", yearly: "jährlich" };
const ANSICHT = { offen: "Offen", erinnerung: "Erinnerung fällig", ueberfaellig: "Überfällig", erledigt: "Erledigt/abgesagt" };
const PARAMS = { offen: {}, erinnerung: { reminder_due: true }, ueberfaellig: { overdue: true }, erledigt: { status: ["done", "cancelled"] } };

export function quelle(f) {
  return f.source_status === "user_reference" ? h("span", { class: "small muted" }, `Quelle: ${f.source_reference} (nicht von HQ geprüft)`)
    : h("span", { class: "tag tag--warn" }, "nicht amtlich bestätigt");
}

function faellig(f) {
  if (f.status !== "open") return h("span", { class: "tag tag--muted" }, f.status === "done" ? "erledigt" : "abgesagt");
  if (f.overdue) return h("span", { class: "tag tag--danger" }, `überfällig seit ${datum(f.due_on)}`);
  return h("span", { class: f.days_left <= f.remind_days_before ? "tag tag--warn" : "tag" }, f.days_left === 0 ? "heute" : `in ${f.days_left} Tagen`);
}

export async function liste(el, _p, q) {
  const ansicht = q.get("ansicht") || "offen";
  const filter = { ansicht, category: q.get("category") || "", responsible: q.get("responsible") || "", q: q.get("q") || "" };
  const daten = await get(`/deadlines${query({ ...PARAMS[ansicht] || {}, category: filter.category, responsible: filter.responsible,
    q: filter.q, order: ansicht === "erledigt" ? "desc" : "asc", limit: 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/fristen", [auswahl("ansicht", ANSICHT, ansicht, undefined, { "aria-label": "Ansicht" }),
    auswahl("category", KATEGORIE, filter.category, "Alle Arten", { "aria-label": "Art" }),
    auswahl("responsible", { me: "Ich bin zuständig" }, filter.responsible, "Alle Zuständigen", { "aria-label": "Zuständig" }),
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Titel, Quelle", "aria-label": "Fristen suchen", maxlength: 100 })]);
  const zeilen = daten.items.map((f) => h("tr", {}, zelle(h("a", { href: `#/fristen/${f.id}` }, f.title)), zelle(datum(f.due_on)),
    zelle(KATEGORIE[f.category], true), zelle(f.responsible ? f.responsible.display_name : "—", true), zelle(faellig(f))));
  const neu = darf("finance.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Frist anlegen") : null;
  ersetze(el, seitenkopf("Fristen", null, neu),
    alertBox("HQ gibt keine Fristen vor und prüft keine. Datum, Wiederholung und Quelle stammen von euch.", "info"), leiste, h("br"),
    tabelle([{ text: "Frist" }, { text: "Fällig" }, { text: "Art", opt: true }, { text: "Zuständig", opt: true }, { text: "Stand" }], zeilen,
      "Keine Fristen für diese Ansicht."), weiterLink("/fristen", filter, daten.next_cursor));
}

function felder(f, leute) {
  return [feld("Titel", eingabe("title", f.title, { required: true, maxlength: 300 })),
    h("div", { class: "grid2" }, feld("Fällig am", eingabe("due_on", f.due_on, { type: "date", required: true })),
      feld("Art", auswahl("category", KATEGORIE, f.category || "other"))),
    h("div", { class: "grid2" }, feld("Wiederholung", auswahl("recurrence", WDH, f.recurrence || "none")),
      feld("Erinnern (Tage vorher)", eingabe("remind_days_before", String(f.remind_days_before ?? 7), { type: "number", min: 0, max: 365, required: true }))),
    leute.length ? feld("Zuständig", personen("responsible", leute, f.responsible ? f.responsible.id : "")) : null,
    feld("Quelle / Fundstelle", eingabe("source_reference", f.source_reference, { maxlength: 500, placeholder: "z. B. Hinweis Steuerberater vom …" }),
      "Freitext. Ohne Quelle wird die Frist als „nicht amtlich bestätigt“ angezeigt."),
    feld("Beschreibung", text("description", f.description, { rows: 2, maxlength: 5000 }))];
}

function body(d) {
  const b = { ...d, remind_days_before: Number(d.remind_days_before) };
  return leerZuNull(b, "responsible", "source_reference", "description");
}

async function anlegen() {
  const leute = await mitglieder();
  const d = await dialog("Frist anlegen", felder({}, leute), "Anlegen");
  if (!d) return;
  try { const f = await post("/deadlines", body(d)); toast("Frist angelegt."); gehe(`/fristen/${f.id}`); } catch (e) { toast(meldung(e), "error"); }
}

export async function detail(el, { ref }) {
  const [f, leute] = await Promise.all([get(`/deadlines/${ref}`), mitglieder()]);
  const neu = () => detail(el, { ref });
  const offen = f.status === "open" && darf("finance.update");
  const fehler = h("div");
  const stamm = offen ? speichern(h("form", { class: "stack" }, fehler, felder(f, leute),
    h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
    await patch(`/deadlines/${ref}`, body(d)); toast("Gespeichert."); neu();
  }) : h("p", {}, `${datum(f.due_on)} · ${KATEGORIE[f.category]} · ${WDH[f.recurrence]}`);
  const abschluss = (pfad, titel, knopf, pflicht) => einmal(async () => {
    const d = await dialog(titel, [feld("Vermerk", eingabe("note", "", { maxlength: 500, required: pflicht, minlength: pflicht ? 3 : 0 }))], knopf);
    if (!d) return;
    try {
      const r = await post(`/deadlines/${ref}/${pfad}`, d);
      toast(r.next ? `Erledigt — nächste Frist am ${datum(r.next.due_on)} angelegt.` : "Gespeichert.");
      if (r.next) gehe(`/fristen/${r.next.id}`); else neu();
    } catch (e) { toast(meldung(e), "error"); }
  });
  const knoepfe = offen ? [h("button", { class: "btn btn--sm", type: "button", on: { click: abschluss("complete", "Frist erledigt?", "Erledigt", false) } }, "Erledigt"),
    h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: abschluss("cancel", "Frist absagen?", "Absagen", true) } }, "Absagen")] : [];
  const kom = h("section", { class: "card" });
  ersetze(el, seitenkopf(f.title, { href: "#/fristen", text: "Fristen" }, faellig(f), ...knoepfe),
    f.status !== "open" ? alertBox(`${f.status === "done" ? "Erledigt" : "Abgesagt"} ${zeit(f.done_at)} von ${f.done_by ? f.done_by.display_name : "—"}${f.done_note ? `: ${f.done_note}` : ""}`, "info") : null,
    h("section", { class: "card" }, h("h2", {}, "Frist"), h("p", {}, quelle(f)),
      h("p", { class: "small muted" }, `Erinnerung ab ${datum(f.reminder_on)}${f.next_due_on ? ` · nächste Frist nach Erledigung: ${datum(f.next_due_on)}` : ""}`), stamm), kom);
  await kommentare(kom, ref);
}
