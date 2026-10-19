// Anfragen (CRM): Eingang, Zuständigkeit, nächste Aktion, Wiedervorlage, Abschluss.
import { datum, dialog, ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { archivKnopf, auswahl, eingabe, feld, filterleiste, leerZuNull, mitglieder, personen, seitenkopf, speichern,
  tabelle, text, weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

export const STATUS = { new: "Neu", in_progress: "In Bearbeitung", waiting: "Wartet", won: "Gewonnen", lost: "Verloren", closed: "Erledigt" };
const OFFEN = ["new", "in_progress", "waiting"];
const QUELLE = { email: "E-Mail", phone: "Telefon", website: "Website", referral: "Empfehlung", event: "Veranstaltung", other: "Sonstiges" };
const PRIO = { low: "Niedrig", normal: "Normal", high: "Hoch", urgent: "Dringend" };
const heute = () => new Date().toISOString().slice(0, 10);

export async function liste(el, _p, q) {
  const st = q.get("status") || "";
  const filter = { status: st, owner: q.get("owner") || "", follow_up_before: q.get("follow_up_before") || "",
    sort: q.get("sort") || "received_on" };
  const daten = await get(`/inquiries${query({ ...filter, status: st || OFFEN,
    order: filter.sort === "follow_up_on" || filter.sort === "title" ? "asc" : "desc", limit: 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/anfragen", [
    auswahl("status", STATUS, st, "Alle offenen", { "aria-label": "Status" }),
    auswahl("owner", { me: "Mir zugewiesen" }, filter.owner, "Alle", { "aria-label": "Zuständig" }),
    auswahl("follow_up_before", { [heute()]: "Wiedervorlage fällig" }, filter.follow_up_before, "Alle Wiedervorlagen", { "aria-label": "Wiedervorlage" }),
    auswahl("sort", { received_on: "Eingang", follow_up_on: "Wiedervorlage", priority: "Priorität", title: "Titel" }, filter.sort, undefined, { "aria-label": "Sortierung" })]);
  const zeilen = daten.items.map((a) => h("tr", {},
    zelle(h("a", { href: `#/anfragen/${a.id}` }, a.title)), zelle(h("span", { class: "tag tag--muted" }, STATUS[a.status])),
    zelle(a.customer ? a.customer.title : "—", true), zelle(a.owner ? a.owner.display_name : "—", true),
    zelle(a.follow_up_on ? h("span", { class: a.follow_up_on < heute() && OFFEN.includes(a.status) ? "tag tag--warn" : "" }, datum(a.follow_up_on)) : "—")));
  const neu = darf("customers.create") ? h("button", { class: "btn", type: "button", on: { click: () => anlegen() } }, "Neue Anfrage") : null;
  ersetze(el, seitenkopf("Anfragen", { href: "#/kunden", text: "Kunden" }, neu), leiste, h("br"),
    tabelle([{ text: "Titel" }, { text: "Status" }, { text: "Kunde", opt: true }, { text: "Zuständig", opt: true }, { text: "Wiedervorlage" }],
      zeilen, "Keine Anfragen für diesen Filter."), weiterLink("/anfragen", filter, daten.next_cursor));
  if (q.get("neu")) anlegen(q.get("neu"));
}

async function kunden() {
  return darf("customers.read") ? (await get("/customers?limit=100")).items : [];
}

function felder(a, leute, kundenliste) {
  return [feld("Titel", eingabe("title", a.title, { required: true, maxlength: 300 })),
    feld("Beschreibung", text("description", a.description, { rows: 3 })),
    h("div", { class: "grid2" }, feld("Quelle", auswahl("source", QUELLE, a.source || "other")),
      feld("Eingang am", eingabe("received_on", a.received_on || heute(), { type: "date", required: true }))),
    h("div", { class: "grid2" }, feld("Priorität", auswahl("priority", PRIO, a.priority || "normal")),
      leute.length ? feld("Zuständig", personen("owner", leute, a.owner ? a.owner.id : "")) : null),
    kundenliste.length ? feld("Kunde", h("select", { name: "customer", class: "input" }, h("option", { value: "" }, "— ohne —"),
      kundenliste.map((k) => h("option", { value: k.id, selected: a.customer && a.customer.id === k.id }, k.name)))) : null,
    h("div", { class: "grid2" }, feld("Nächste Aktion", eingabe("next_action", a.next_action, { maxlength: 300 })),
      feld("Wiedervorlage am", eingabe("follow_up_on", a.follow_up_on, { type: "date" })))];
}

async function anlegen(kundeRef) {
  const [leute, kl] = await Promise.all([mitglieder(), kunden()]);
  const d = await dialog("Neue Anfrage", felder({ customer: kundeRef ? { id: kundeRef } : null }, leute, kl), "Anlegen");
  if (!d) return;
  leerZuNull(d, "owner", "customer", "next_action", "follow_up_on", "description");
  try { const a = await post("/inquiries", d); toast("Anfrage erfasst."); gehe(`/anfragen/${a.id}`); }
  catch (e) { toast(meldung(e), "error"); }
}

export async function detail(el, { ref }) {
  const [a, leute, kl] = await Promise.all([get(`/inquiries/${ref}`), mitglieder(), kunden()]);
  const neu = () => detail(el, { ref });
  const fehler = h("div");
  let inhalt = h("p", { class: "body" }, a.description || h("span", { class: "muted" }, "Keine Beschreibung."));
  if (darf("customers.update")) {
    inhalt = speichern(h("form", { class: "stack" }, fehler, felder(a, leute, kl),
      feld("Status", auswahl("status", STATUS, a.status)),
      h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
      leerZuNull(d, "owner", "customer", "next_action", "follow_up_on");
      if (!leute.length) delete d.owner;
      if (!kl.length) delete d.customer;
      await patch(`/inquiries/${ref}`, d); toast("Gespeichert."); neu();
    });
  }
  const kom = h("section", { class: "card" });
  ersetze(el, seitenkopf(a.title, { href: "#/anfragen", text: "Anfragen" }, h("span", { class: "tag" }, STATUS[a.status]),
    darf("customers.update") ? archivKnopf(a, neu) : null),
  h("p", { class: "muted small" }, `Eingang ${datum(a.received_on)} · ${QUELLE[a.source]}${a.customer ? ` · Kunde: ${a.customer.title}` : ""}${a.closed_at ? ` · abgeschlossen ${zeit(a.closed_at)}` : ""}`),
  a.customer ? h("p", {}, h("a", { href: `#/kunden/${a.customer.id}` }, `Zum Kunden „${a.customer.title}“`)) : null,
  h("section", { class: "card" }, inhalt), kom);
  await kommentare(kom, ref);
}
