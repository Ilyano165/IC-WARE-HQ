// Dienstreisen: Antrag stellen, einreichen, genehmigen/ablehnen (nie die eigene — das prüft der Server), stornieren.
// Pauschalen werden nicht berechnet (keine amtlichen Werte hinterlegt).
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { alsBetrag, auswahl, cent, eingabe, feld, filterleiste, geld, seitenkopf, speichern, tabelle, text, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

const STATUS = { draft: "Entwurf", submitted: "eingereicht", approved: "genehmigt", rejected: "abgelehnt", cancelled: "storniert" };
const tag = (s) => h("span", { class: `tag${s === "approved" ? "" : s === "rejected" ? " tag--danger" : s === "submitted" ? " tag--warn" : " tag--muted"}` }, STATUS[s]);

export async function liste(el, _p, q) {
  const filter = { status: q.get("status") || "", traveller: q.get("traveller") || "" };
  const daten = await get(`/travels${query(filter)}`);
  const leiste = filterleiste("/reisen", [auswahl("status", STATUS, filter.status, "Alle", { "aria-label": "Status" }),
    auswahl("traveller", { me: "Meine Reisen" }, filter.traveller, "Alle Reisenden", { "aria-label": "Reisende" })]);
  const zeilen = daten.items.map((r) => h("tr", {}, zelle(h("a", { href: `#/reisen/${r.id}` }, r.title)), zelle(r.destination, true),
    zelle(`${datum(r.start_date)} – ${datum(r.end_date)}`), zelle(r.traveller ? r.traveller.display_name : "—", true), zelle(tag(r.status))));
  const neu = darf("travel.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Reise beantragen") : null;
  ersetze(el, seitenkopf("Dienstreisen", null, neu), leiste, h("br"),
    tabelle([{ text: "Reise" }, { text: "Ziel", opt: true }, { text: "Zeitraum" }, { text: "Reisende", opt: true }, { text: "Status" }], zeilen, "Keine Reisen für diesen Filter."));
}

function felder(r) {
  return [feld("Titel", eingabe("title", r.title, { required: true, maxlength: 300 })),
    feld("Reiseziel", eingabe("destination", r.destination, { required: true, maxlength: 300 })),
    h("div", { class: "grid2" }, feld("Von", eingabe("start_date", r.start_date, { type: "date", required: true })),
      feld("Bis", eingabe("end_date", r.end_date, { type: "date", required: true }))),
    feld("Geschätzte Kosten (€)", eingabe("kosten", alsBetrag(r.estimated_cost_minor), { inputmode: "decimal" })),
    feld("Zweck", text("purpose", r.purpose, { rows: 3, maxlength: 5000 }))];
}

function body(d) {
  const b = { ...d, estimated_cost_minor: d.kosten ? cent(d.kosten) : null };
  delete b.kosten;
  return b;
}

async function anlegen() {
  const d = await dialog("Reise beantragen", felder({}), "Anlegen");
  if (!d) return;
  try { const r = await post("/travels", body(d)); toast("Als Entwurf angelegt."); gehe(`/reisen/${r.id}`); } catch (e) { toast(meldung(e), "error"); }
}

export async function detail(el, { ref }) {
  const r = await get(`/travels/${ref}`);
  const neu = () => detail(el, { ref });
  const aktion = (pfad, text_, body_) => einmal(async () => {
    try { await post(`/travels/${ref}/${pfad}`, body_ ? await body_() : undefined); toast(text_); neu(); } catch (e) { if (e) toast(meldung(e), "error"); }
  });
  const eigene = r.own;
  const knoepfe = [];
  if (["draft", "rejected"].includes(r.status) && darf("travel.update")) knoepfe.push(h("button", { class: "btn btn--sm", type: "button", on: { click: aktion("submit", "Eingereicht.") } }, "Einreichen"));
  if (r.status === "submitted" && darf("travel.approve") && !eigene) {
    knoepfe.push(h("button", { class: "btn btn--sm", type: "button", on: { click: aktion("decision", "Genehmigt.", async () => ({ approve: true, note: "" })) } }, "Genehmigen"));
    knoepfe.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
      const d = await dialog("Reise ablehnen", [feld("Begründung", eingabe("note", "", { required: true, minlength: 3, maxlength: 500 }))], "Ablehnen", true);
      if (!d) return;
      try { await post(`/travels/${ref}/decision`, { approve: false, note: d.note }); toast("Abgelehnt."); neu(); } catch (e) { toast(meldung(e), "error"); }
    }) } }, "Ablehnen"));
  }
  if (r.status !== "cancelled" && darf("travel.update")) knoepfe.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: aktion("cancel", "Storniert.") } }, "Stornieren"));
  const fehler = h("div");
  const stamm = ["draft", "rejected"].includes(r.status) && darf("travel.update") ? speichern(h("form", { class: "stack" }, fehler, felder(r),
    h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
    await patch(`/travels/${ref}`, body(d)); toast("Gespeichert."); neu();
  }) : h("p", {}, `${r.destination} · ${datum(r.start_date)} – ${datum(r.end_date)} · ${r.estimated_cost_minor !== null ? geld(r.estimated_cost_minor, r.currency) : "Kosten offen"}`);
  const kom = h("section", { class: "card" });
  ersetze(el, seitenkopf(r.title, { href: "#/reisen", text: "Dienstreisen" }, tag(r.status), ...knoepfe),
    r.decided_at ? alertBox(`Entschieden ${zeit(r.decided_at)} von ${r.decided_by ? r.decided_by.display_name : "—"}${r.decision_note ? `: ${r.decision_note}` : ""}`, "info") : null,
    eigene && r.status === "submitted" ? h("p", { class: "small muted" }, "Eigene Reisen genehmigt jemand anderes.") : null,
    h("section", { class: "card" }, h("h2", {}, "Reise"), stamm, h("p", { class: "small muted" }, `Pauschalen: ${r.allowances}`)),
    h("section", { class: "card" }, h("h2", {}, "Belege"), r.evidence.length
      ? h("ul", { class: "list" }, r.evidence.map((b) => h("li", {}, h("a", { href: `#/belege/${b.id}` }, b.title))))
      : h("p", { class: "empty" }, "Keine Belege verknüpft. Verknüpfen: in der Ausgabe als „Nachweis für“ diese Reise wählen.")), kom);
  await kommentare(kom, ref);
}
