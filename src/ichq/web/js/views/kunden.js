// Kunden (CRM): Liste mit Suche/Filter/Sortierung, Anlegen mit Dublettenprüfung, Detail mit Kontaktpersonen,
// Anfragen, Zusammenführen, Archivieren und Kommentaren.
import { alertBox, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { del, get, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { archivKnopf, auswahl, eingabe, feld, filterleiste, leerZuNull, mitglieder, personen, seitenkopf, speichern,
  tabelle, text, weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

export const STATUS = { lead: "Interessent", active: "Aktiv", inactive: "Inaktiv" };
const ART = { company: "Firma", person: "Person" };
const statusTag = (s) => h("span", { class: `tag${s === "active" ? "" : " tag--muted"}` }, STATUS[s] || s);

export async function liste(el, _p, q) {
  const filter = { q: q.get("q") || "", status: q.get("status") || "", owner: q.get("owner") || "",
    archived: q.get("archived") || "", sort: q.get("sort") || "name" };
  const daten = await get(`/customers${query({ ...filter, order: filter.sort === "name" ? "asc" : "desc", limit: 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/kunden", [
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Name, E-Mail, Ort", "aria-label": "Kunden suchen", maxlength: 100 }),
    auswahl("status", STATUS, filter.status, "Alle Status", { "aria-label": "Status" }),
    auswahl("owner", { me: "Ich bin zuständig" }, filter.owner, "Alle Zuständigen", { "aria-label": "Zuständig" }),
    auswahl("archived", { true: "Archiv" }, filter.archived, "Aktuelle", { "aria-label": "Archiv" }),
    auswahl("sort", { name: "Name", created_at: "Neueste" }, filter.sort, undefined, { "aria-label": "Sortierung" })]);
  const zeilen = daten.items.map((k) => h("tr", {},
    zelle(h("a", { href: `#/kunden/${k.id}` }, k.name)), zelle(statusTag(k.status)),
    zelle(k.email || "—", true), zelle(k.city || "—", true), zelle(k.owner ? k.owner.display_name : "—", true)));
  const neu = darf("customers.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Neuer Kunde") : null;
  ersetze(el, seitenkopf("Kunden", null, darf("customers.read") ? h("a", { class: "btn btn--ghost", href: "#/anfragen" }, "Anfragen") : null, neu),
    leiste, h("br"),
    tabelle([{ text: "Name" }, { text: "Status" }, { text: "E-Mail", opt: true }, { text: "Ort", opt: true }, { text: "Zuständig", opt: true }],
      zeilen, filter.q || filter.status || filter.owner ? "Keine Kunden für diesen Filter." : "Noch keine Kunden vorhanden. Lege deinen ersten Kunden an."),
    weiterLink("/kunden", filter, daten.next_cursor));
}

function stammfelder(k = {}, leute = []) {
  return [
    h("div", { class: "grid2" }, feld("Name", eingabe("name", k.name, { required: true, maxlength: 300 })),
      feld("Art", auswahl("kind", ART, k.kind || "company"))),
    h("div", { class: "grid2" }, feld("Status", auswahl("status", STATUS, k.status || "active")),
      leute.length ? feld("Zuständig", personen("owner", leute, k.owner ? k.owner.id : "")) : null),
    h("div", { class: "grid2" }, feld("E-Mail", eingabe("email", k.email, { type: "email", maxlength: 254 })),
      feld("Telefon", eingabe("phone", k.phone, { maxlength: 50 }))),
    h("div", { class: "grid2" }, feld("Rechtlicher Name", eingabe("legal_name", k.legal_name, { maxlength: 300 })),
      feld("Website", eingabe("website", k.website, { maxlength: 300 }))),
    feld("Straße", eingabe("street", k.street, { maxlength: 200 })),
    h("div", { class: "grid2" }, feld("PLZ", eingabe("postal_code", k.postal_code, { maxlength: 20 })),
      feld("Ort", eingabe("city", k.city, { maxlength: 100 }))),
    h("div", { class: "grid2" }, feld("Land (z. B. DE)", eingabe("country", k.country, { maxlength: 2, pattern: "[A-Z]{2}" })),
      feld("USt-IdNr.", eingabe("vat_id", k.vat_id, { maxlength: 30 }), "Wird nicht geprüft.")),
  ];
}

const OPTIONAL = ["email", "phone", "legal_name", "website", "street", "postal_code", "city", "country", "vat_id", "owner"];

async function anlegen() {
  const leute = await mitglieder();
  const d = await dialog("Neuer Kunde", stammfelder({}, leute), "Weiter");
  if (!d) return;
  leerZuNull(d, ...OPTIONAL);
  const doppelt = (await get(`/customers/duplicates${query({ name: d.name, email: d.email })}`)).items;
  if (doppelt.length) {
    const ok = await dialog("Möglicher Doppeleintrag", [h("p", {}, "Diese Kunden sehen gleich aus:"),
      h("ul", {}, doppelt.map((x) => h("li", {}, h("a", { href: `#/kunden/${x.id}` }, x.name), x.email ? ` · ${x.email}` : ""))),
      h("p", { class: "muted" }, "Trotzdem einen neuen Kunden anlegen?")], "Trotzdem anlegen");
    if (!ok) return;
    d.allow_duplicate = true;
  }
  try { const k = await post("/customers", d); toast("Kunde angelegt."); gehe(`/kunden/${k.id}`); }
  catch (e) { toast(meldung(e), "error"); }
}

export async function detail(el, { ref }) {
  const [k, leute] = await Promise.all([get(`/customers/${ref}`), mitglieder()]);
  const neu = () => detail(el, { ref });
  const fehler = h("div");
  let stamm;
  if (darf("customers.update")) {
    stamm = speichern(h("form", { class: "stack" }, fehler, stammfelder(k, leute),
      feld("Notizen", text("notes", k.notes, { rows: 3 })),
      h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
      leerZuNull(d, ...OPTIONAL);
      if (!leute.length) delete d.owner;
      await patch(`/customers/${ref}`, d); toast("Gespeichert."); neu();
    });
  } else {
    stamm = h("dl", { class: "stack" }, [["E-Mail", k.email], ["Telefon", k.phone], ["Ort", [k.postal_code, k.city].filter(Boolean).join(" ")],
      ["Zuständig", k.owner && k.owner.display_name], ["Notizen", k.notes]].map(([a, b]) => [h("dt", { class: "muted small" }, a), h("dd", {}, b || "—")]));
  }
  const zusammen = darf("customers.delete") && !k.archived ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(() => zusammenfuehren(k)) } }, "Mit anderem Kunden zusammenführen") : null;
  const kontakte = h("section", { class: "card" });
  const anfragen = h("section", { class: "card" });
  const projekteEl = h("section", { class: "card" });
  const kom = h("section", { class: "card" });
  ersetze(el, seitenkopf(k.name, { href: "#/kunden", text: "Kunden" }, statusTag(k.status),
    k.archived ? h("span", { class: "tag tag--muted" }, "archiviert") : null, darf("customers.update") ? archivKnopf(k, neu) : null),
  k.merged_into ? alertBox(`Zusammengeführt in „${k.merged_into.title}“.`, "info") : null,
  h("p", { class: "muted small" }, `angelegt ${zeit(k.created_at)}${k.created_by ? ` von ${k.created_by.display_name}` : ""}`),
  h("section", { class: "card" }, h("h2", {}, "Stammdaten"), stamm), kontakte, anfragen, projekteEl, h("div", { class: "row" }, zusammen), kom);
  kontakteZeigen(kontakte, k, neu);
  await Promise.all([anfragenZeigen(anfragen, k), projekteZeigen(projekteEl, k), kommentare(kom, ref)]);
}

function kontaktFelder(x = {}) {
  return [feld("Name", eingabe("name", x.name, { required: true, maxlength: 200 })),
    h("div", { class: "grid2" }, feld("Rolle", eingabe("role", x.role, { maxlength: 100 })),
      feld("Telefon", eingabe("phone", x.phone, { maxlength: 50 }))),
    feld("E-Mail", eingabe("email", x.email, { type: "email", maxlength: 254 })),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "is_primary", value: "1", checked: x.is_primary }), " Hauptkontakt")];
}

function kontakteZeigen(el, k, neu) {
  const darfAendern = darf("customers.update");
  const bearbeiten = (x) => einmal(async () => {
    const d = await dialog(x ? "Kontaktperson bearbeiten" : "Neue Kontaktperson", kontaktFelder(x || {}), "Speichern");
    if (!d) return;
    d.is_primary = d.is_primary === "1";
    leerZuNull(d, "role", "phone", "email");
    try {
      if (x) await patch(`/customers/${k.id}/contacts/${x.id}`, d); else await post(`/customers/${k.id}/contacts`, d);
      toast("Gespeichert."); neu();
    } catch (e) { toast(meldung(e), "error"); }
  });
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Kontaktpersonen"),
    darfAendern ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: bearbeiten(null) } }, "Kontakt hinzufügen") : null),
  k.contacts.length ? h("div", { class: "list" }, k.contacts.map((x) => h("div", { class: "item" },
    h("div", {}, h("strong", {}, x.name), x.is_primary ? h("span", { class: "tag" }, " Hauptkontakt") : null,
      h("div", { class: "muted small" }, [x.role, x.email, x.phone].filter(Boolean).join(" · "))),
    darfAendern ? h("span", { class: "row" },
      h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: bearbeiten(x) } }, "Bearbeiten"),
      h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
        if (!await dialog("Kontaktperson löschen?", h("p", {}, `„${x.name}“ wird entfernt.`), "Löschen", true)) return;
        try { await del(`/customers/${k.id}/contacts/${x.id}`); toast("Gelöscht."); neu(); } catch (e) { toast(meldung(e), "error"); }
      }) } }, "Löschen")) : null))) : h("p", { class: "muted" }, "Keine Kontaktpersonen."));
}

async function anfragenZeigen(el, k) {
  const daten = await get(`/inquiries?customer=${k.id}&limit=20`);
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Anfragen"),
    darf("customers.create") ? h("a", { class: "btn btn--ghost btn--sm", href: `#/anfragen?neu=${k.id}` }, "Anfrage erfassen") : null),
  daten.items.length ? h("div", { class: "list" }, daten.items.map((a) => h("div", { class: "item" },
    h("a", { href: `#/anfragen/${a.id}` }, a.title), h("span", { class: "muted small" }, a.status)))) : h("p", { class: "muted" }, "Keine Anfragen."));
}

async function zusammenfuehren(k) {
  const kandidaten = (await get(`/customers${query({ limit: 100 })}`)).items.filter((x) => x.id !== k.id);
  if (!kandidaten.length) { toast("Kein anderer Kunde vorhanden.", "error"); return; }
  const d = await dialog("Zusammenführen", [h("p", {}, `„${k.name}“ wird in den gewählten Kunden übernommen: Kontakte, Anfragen und weitere Verweise wandern mit, „${k.name}“ wird archiviert.`),
    feld("Kunde, der bleibt", h("select", { name: "into", required: true, class: "input" }, kandidaten.map((x) => h("option", { value: x.id }, x.name))))],
  "Zusammenführen", true);
  if (!d) return;
  try { const z = await post(`/customers/${k.id}/merge`, d); toast("Zusammengeführt."); gehe(`/kunden/${z.id}`); }
  catch (e) { toast(meldung(e), "error"); }
}

async function projekteZeigen(el, k) {
  if (!darf("projects.read")) { ersetze(el); return; }
  const daten = await get(`/projects?customer=${k.id}&status=planned&status=active&status=on_hold&status=completed&status=cancelled&limit=20`);
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Projekte"),
    h("a", { class: "btn btn--ghost btn--sm", href: `#/projekte?customer=${k.id}` }, "Alle")),
  daten.items.length ? h("div", { class: "list" }, daten.items.map((p) => h("div", { class: "item" },
    h("a", { href: `#/projekte/${p.id}` }, p.name), h("span", { class: "muted small" }, p.status)))) : h("p", { class: "muted" }, "Keine Projekte."));
}
