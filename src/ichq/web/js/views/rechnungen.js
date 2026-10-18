// Rechnungen: Liste (offen, überfällig, Entwürfe), Entwurf mit Positionen, Ausstellen, Versandvermerk, Zahlungen mit
// Rücknahme, Mahn-/Kontakthistorie, Storno, Druckansicht. HQ verschickt nichts selbst — Versand wird nur vermerkt.
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { del, get, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf, state } from "../state.js";
import { alsBetrag, archivKnopf, auswahl, cent, eingabe, Eingabefehler, feld, fehlertext, filterleiste, geld, leerZuNull,
  mitglieder, personen, seitenkopf, speichern, tabelle, text, weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";

export const STATUS = { draft: "Entwurf", issued: "Ausgestellt", sent: "Versendet", partially_paid: "Teilweise bezahlt",
  paid: "Bezahlt", cancelled: "Storniert" };
const ANSICHT = { open: "Offene Forderungen", overdue: "Überfällig", draft: "Entwürfe", followup: "Wiedervorlage fällig", all: "Alle" };
const KANAL = { phone: "Telefon", email: "E-Mail", letter: "Brief", in_person: "Persönlich", other: "Sonstiges" };
const ART = { contact_attempt: "Kontaktversuch", reminder_noted: "Erinnerung (vermerkt)", dunning_level: "Mahnstufe", note: "Notiz" };
const METHODE = { bank_transfer: "Überweisung", cash: "Bar", card: "Karte", direct_debit: "Lastschrift", other: "Sonstiges" };
const heute = () => new Date().toISOString().slice(0, 10);
const plusTage = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

export function statusTag(r) {
  if (r.overdue) return h("span", { class: "tag tag--danger" }, `Überfällig (${r.days_overdue} T.)`);
  const art = r.status === "paid" ? "" : r.status === "cancelled" ? " tag--muted" : r.status === "draft" ? " tag--muted" : " tag--warn";
  return h("span", { class: `tag${art}` }, r.kind === "cancellation" ? "Storno" : STATUS[r.status] || r.status);
}

const PARAMS = { open: { open: true, sort: "due_date", order: "asc" }, overdue: { overdue: true, sort: "due_date", order: "asc" },
  draft: { status: "draft" }, followup: { follow_up_due: true, sort: "due_date", order: "asc" }, all: {} };

export async function liste(el, _p, q) {
  const ansicht = q.get("ansicht") || "open";
  const filter = { ansicht, q: q.get("q") || "", responsible: q.get("responsible") || "", customer: q.get("customer") || "",
    project: q.get("project") || "" };
  const daten = await get(`/invoices${query({ q: filter.q, responsible: filter.responsible, customer: filter.customer,
    project: filter.project, ...(PARAMS[ansicht] || {}), limit: 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/rechnungen", [auswahl("ansicht", ANSICHT, ansicht, undefined, { "aria-label": "Ansicht" }),
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Nummer oder Titel", "aria-label": "Rechnungen suchen", maxlength: 100 }),
    auswahl("responsible", { me: "Ich bin zuständig" }, filter.responsible, "Alle Zuständigen", { "aria-label": "Zuständig" })],
  { customer: filter.customer, project: filter.project });
  const zeilen = daten.items.map((r) => h("tr", {},
    zelle(h("a", { href: `#/rechnungen/${r.id}` }, r.number || r.title)), zelle(r.customer ? r.customer.title : "—", true),
    zelle(geld(r.gross_minor, r.currency)), zelle(r.status === "draft" ? "—" : geld(r.open_minor, r.currency), true),
    zelle(datum(r.due_date), true), zelle(statusTag(r))));
  const neu = darf("invoices.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Neue Rechnung") : null;
  ersetze(el, seitenkopf("Rechnungen", null, neu), leiste, h("br"),
    tabelle([{ text: "Nummer" }, { text: "Kunde", opt: true }, { text: "Brutto" }, { text: "Offen", opt: true }, { text: "Fällig", opt: true }, { text: "Status" }],
      zeilen, ansicht === "overdue" ? "Keine überfälligen Rechnungen." : "Keine Rechnungen für diese Ansicht. Lege eine neue Rechnung an."),
    weiterLink("/rechnungen", filter, daten.next_cursor));
}

async function auswahlListen() {
  const [k, p] = await Promise.all([darf("customers.read") ? get("/customers?limit=100") : { items: [] },
    darf("projects.read") ? get("/projects?limit=100") : { items: [] }]);
  return { kunden: k.items, projekte: p.items };
}

function bezugFelder(r, l) {
  return [l.kunden.length ? feld("Kunde", h("select", { name: "customer", class: "input" }, h("option", { value: "" }, "— wählen —"),
    l.kunden.map((k) => h("option", { value: k.id, selected: r.customer && r.customer.id === k.id }, k.name)))) : null,
  l.projekte.length ? feld("Projekt", h("select", { name: "project", class: "input" }, h("option", { value: "" }, "— ohne —"),
    l.projekte.map((p) => h("option", { value: p.id, selected: r.project && r.project.id === p.id }, p.name)))) : null];
}

async function anlegen() {
  const l = await auswahlListen();
  const d = await dialog("Neue Rechnung", [feld("Titel", eingabe("title", "", { maxlength: 300, placeholder: "z. B. Dachsanierung Oktober" })),
    ...bezugFelder({}, l)], "Entwurf anlegen");
  if (!d) return;
  leerZuNull(d, "title", "customer", "project");
  for (const k of Object.keys(d)) if (d[k] === null) delete d[k];
  try { const r = await post("/invoices", d); toast("Entwurf angelegt."); gehe(`/rechnungen/${r.id}`); } catch (e) { toast(meldung(e), "error"); }
}

// Menge „1,5“ → 1500 (Tausendstel); Prozent „19“ / „7,5“ → Basispunkte
function milli(s) { const m = /^(-?)(\d+)(?:[,.](\d{1,3}))?$/.exec(String(s).trim()); if (!m) return null; return (m[1] ? -1 : 1) * (Number(m[2]) * 1000 + Number((m[3] || "0").padEnd(3, "0"))); }
function bp(s) { const m = /^(\d{1,3})(?:[,.](\d{1,2}))?$/.exec(String(s).trim()); if (!m) return null; const v = Number(m[1]) * 100 + Number((m[2] || "0").padEnd(2, "0")); return v <= 10000 ? v : null; }
const zahl = (milliwert) => (milliwert / 1000).toLocaleString("de-DE", { maximumFractionDigits: 3 });
const prozent = (b) => `${(b / 100).toLocaleString("de-DE", { maximumFractionDigits: 2 })} %`;

function positionFelder(z = {}) {
  return [feld("Beschreibung", eingabe("description", z.description, { required: true, maxlength: 1000 })),
    h("div", { class: "grid2" }, feld("Menge", eingabe("menge", z.quantity_milli ? zahl(z.quantity_milli) : "1", { required: true, inputmode: "decimal" })),
      feld("Einheit", eingabe("unit", z.unit, { maxlength: 20, placeholder: "Std, Stk …" }))),
    h("div", { class: "grid2" }, feld("Einzelpreis netto (€)", eingabe("preis", alsBetrag(z.unit_price_minor), { required: true, inputmode: "decimal" })),
      feld("Steuersatz (%)", eingabe("satz", z.tax_rate_bp !== undefined ? String(z.tax_rate_bp / 100).replace(".", ",") : "", { required: true, inputmode: "decimal" }),
        "Von dir erfasst — HQ gibt keinen Steuersatz vor und prüft ihn nicht."))];
}

function positionBody(d) {
  const b = { description: d.description, unit: d.unit || null, quantity_milli: milli(d.menge), unit_price_minor: cent(d.preis), tax_rate_bp: bp(d.satz) };
  if (!b.quantity_milli) throw new Eingabefehler("Menge ungültig (z. B. 1,5)");
  if (b.unit_price_minor === null) throw new Eingabefehler("Einzelpreis ungültig (z. B. 120,00)");
  if (b.tax_rate_bp === null) throw new Eingabefehler("Steuersatz ungültig (0–100, z. B. 19 oder 7)");
  return b;
}

export async function detail(el, { ref }) {
  const r = await get(`/invoices/${ref}`);
  const neu = () => detail(el, { ref });
  const entwurf = r.status === "draft";
  const aktionen = [statusTag(r)];
  if (entwurf && darf("invoices.approve")) aktionen.push(h("button", { class: "btn", type: "button", on: { click: einmal(() => ausstellen(r, neu)) } }, "Ausstellen"));
  if (!entwurf) aktionen.push(h("a", { class: "btn btn--ghost btn--sm", href: `#/rechnungen/${ref}/druck` }, "Druckansicht"));
  if (["issued", "sent", "partially_paid"].includes(r.status) && r.kind === "invoice" && darf("invoices.approve")) {
    aktionen.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
      if (!await dialog("Rechnung stornieren?", h("p", {}, `Für ${r.number} wird eine Stornorechnung mit eigener Nummer erzeugt. Das Original bleibt unverändert sichtbar.`), "Stornieren", true)) return;
      try { const s = await post(`/invoices/${ref}/cancel`); toast("Storniert."); gehe(`/rechnungen/${s.id}`); } catch (e) { toast(meldung(e), "error"); }
    }) } }, "Stornieren"));
  }
  if (entwurf && darf("invoices.update")) aktionen.push(archivKnopf(r, () => gehe("/rechnungen?ansicht=draft")));
  const kom = h("section", { class: "card" });
  ersetze(el, seitenkopf(r.number ? `${r.kind === "cancellation" ? "Storno" : "Rechnung"} ${r.number}` : r.title, { href: "#/rechnungen", text: "Rechnungen" }, aktionen),
    r.cancels ? alertBox(`Storno zu „${r.cancels.title}“.`, "info") : null,
    r.cancelled_by ? alertBox(`Storniert durch „${r.cancelled_by.title}“.`, "info") : null,
    h("div", { class: "metrics" }, [["Brutto", geld(r.gross_minor, r.currency)], ["Bezahlt", geld(r.paid_minor, r.currency)],
      ["Offen", geld(r.open_minor, r.currency)], ["Fällig", datum(r.due_date)]].map(([a, b]) => h("div", { class: `metric${a === "Offen" && r.overdue ? " metric--danger" : ""}` },
      h("span", { class: "metric-value" }, b), h("span", { class: "metric-label" }, a)))), h("br"),
    entwurf ? entwurfKarte(r, neu) : kopfKarte(r), positionen(r, neu), zahlungen(r, neu), bearbeitung(r, neu), kom);
  await kommentare(kom, ref);
}

function kopfKarte(r) {
  const k = r.customer_snapshot || {};
  return h("section", { class: "card" }, h("h2", {}, "Rechnung"), h("p", {}, [k.name, k.legal_name, k.street, [k.postal_code, k.city].filter(Boolean).join(" "), k.country].filter(Boolean).join(" · ")),
    h("p", { class: "muted small" }, `Ausgestellt ${datum(r.issue_date)}${r.service_date ? ` · Leistung ${datum(r.service_date)}` : ""}${r.sent_at ? ` · versendet ${zeit(r.sent_at)}` : ""}${r.project ? ` · Projekt: ${r.project.title}` : ""}`),
    r.notes ? h("p", { class: "body" }, r.notes) : null);
}

function entwurfKarte(r, neu) {
  const box = h("section", { class: "card" }, h("h2", {}, "Entwurf"), h("p", { class: "muted" }, "Lädt …"));
  if (!darf("invoices.update")) { ersetze(box, h("h2", {}, "Entwurf"), h("p", { class: "muted" }, "Nur lesbar.")); return box; }
  auswahlListen().then((l) => {
    const fehler = h("div");
    ersetze(box, h("h2", {}, "Entwurf"), speichern(h("form", { class: "stack" }, fehler,
      feld("Titel", eingabe("title", r.title, { required: true, maxlength: 300 })), h("div", { class: "grid2" }, bezugFelder(r, l)),
      h("div", { class: "grid2" }, feld("Leistungsdatum", eingabe("service_date", r.service_date, { type: "date" })),
        feld("Fällig am", eingabe("due_date", r.due_date, { type: "date" }))),
      feld("Hinweis auf der Rechnung", text("notes", r.notes, { rows: 2, maxlength: 5000 })),
      h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
      leerZuNull(d, "customer", "project", "service_date", "due_date");
      if (!l.kunden.length) delete d.customer;
      if (!l.projekte.length) delete d.project;
      await patch(`/invoices/${r.id}`, d); toast("Gespeichert."); neu();
    }));
  });
  return box;
}

function positionen(r, neu) {
  const entwurf = r.status === "draft" && darf("invoices.update");
  const bearbeiten = (z) => einmal(async () => {
    const d = await dialog(z ? "Position bearbeiten" : "Neue Position", positionFelder(z || {}), "Speichern");
    if (!d) return;
    try {
      const b = positionBody(d);
      if (z) await patch(`/invoices/${r.id}/lines/${z.id}`, b); else await post(`/invoices/${r.id}/lines`, b);
      toast("Gespeichert."); neu();
    } catch (e) { toast(fehlertext(e), "error"); }
  });
  const kopf = [{ text: "Pos." }, { text: "Beschreibung" }, { text: "Menge", opt: true }, { text: "Einzelpreis", opt: true }, { text: "USt", opt: true }, { text: "Netto" }];
  if (entwurf) kopf.push({ text: "" });
  return h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Positionen"),
    entwurf ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: bearbeiten(null) } }, "Position hinzufügen") : null),
  tabelle(kopf, r.lines.map((z) => h("tr", {}, zelle(String(z.position)), zelle(z.description), zelle(`${zahl(z.quantity_milli)} ${z.unit || ""}`, true),
    zelle(geld(z.unit_price_minor, r.currency), true), zelle(prozent(z.tax_rate_bp), true), zelle(geld(z.net_minor, r.currency)),
    entwurf ? zelle(h("span", { class: "row" }, h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: bearbeiten(z) } }, "Ändern"),
      h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
        try { await del(`/invoices/${r.id}/lines/${z.id}`); toast("Entfernt."); neu(); } catch (e) { toast(meldung(e), "error"); }
      }) } }, "Entfernen"))) : null)), "Noch keine Positionen."),
  h("div", { class: "stack small" }, r.tax_by_rate.map((t) => h("div", { class: "row row--between" }, h("span", {}, `USt ${prozent(t.tax_rate_bp)} auf ${geld(t.net_minor, r.currency)}`), h("span", {}, geld(t.tax_minor, r.currency)))),
    h("div", { class: "row row--between" }, h("strong", {}, "Summe brutto"), h("strong", {}, geld(r.gross_minor, r.currency)))),
  h("p", { class: "muted small" }, "Steuersätze sind Nutzereingaben; Rundung kaufmännisch je Position. Keine Prüfung auf steuerliche Richtigkeit."));
}

async function ausstellen(r, neu) {
  const d = await dialog("Rechnung ausstellen", [h("p", {}, "Danach sind Kunde, Positionen und Beträge unveränderlich. Korrekturen nur per Storno."),
    feld("Fällig am", eingabe("due_date", r.due_date || plusTage(14), { type: "date", required: true, min: heute() }),
      "Zahlungsziel legst du fest — HQ gibt keine Frist vor.")], "Ausstellen");
  if (!d) return;
  try { await post(`/invoices/${r.id}/issue`, { due_date: d.due_date }); toast("Ausgestellt."); neu(); } catch (e) { toast(meldung(e), "error"); }
}

function zahlungen(r, neu) {
  if (r.status === "draft" || r.kind !== "invoice") return null;
  const offen = ["issued", "sent", "partially_paid"].includes(r.status);
  const erfassen = offen && darf("finance.create") ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Zahlung erfassen", [h("div", { class: "grid2" }, feld("Betrag (€)", eingabe("betrag", alsBetrag(r.open_minor), { required: true, inputmode: "decimal" })),
      feld("Eingang am", eingabe("paid_on", heute(), { type: "date", required: true, max: heute() }))),
    h("div", { class: "grid2" }, feld("Art", auswahl("method", METHODE, "bank_transfer")), feld("Referenz", eingabe("reference", "", { maxlength: 200 })))], "Erfassen");
    if (!d) return;
    const betrag = cent(d.betrag);
    if (!betrag || betrag <= 0) { toast("Betrag ungültig.", "error"); return; }
    try { await post(`/invoices/${r.id}/payments`, { amount_minor: betrag, paid_on: d.paid_on, method: d.method, reference: d.reference || null }); toast("Zahlung erfasst."); neu(); }
    catch (e) { toast(meldung(e), "error"); }
  }) } }, "Zahlung erfassen") : null;
  if (!r.payments) return h("section", { class: "card" }, h("h2", {}, "Zahlungen"), h("p", { class: "muted" }, `Bezahlt: ${geld(r.paid_minor, r.currency)} (Einzelheiten nur mit Finanzrecht).`));
  return h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Zahlungen"), erfassen),
    tabelle([{ text: "Datum" }, { text: "Betrag" }, { text: "Art", opt: true }, { text: "Referenz", opt: true }, { text: "" }],
      r.payments.map((z, i) => h("tr", {}, zelle(datum(z.paid_on)), zelle(geld(z.amount_minor, r.currency)), zelle(METHODE[z.method] || z.method, true), zelle(z.reference || "—", true),
        zelle(!z.reversal && darf("finance.update") && !r.payments.slice(i + 1).some((x) => x.reversal && x.amount_minor === -z.amount_minor)
          ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
            if (!await dialog("Zahlung zurücknehmen?", h("p", {}, "Es entsteht eine Gegenbuchung; beide bleiben sichtbar."), "Zurücknehmen", true)) return;
            try { await post(`/invoices/${r.id}/payments/${z.id}/reverse`); toast("Zurückgenommen."); neu(); } catch (e) { toast(meldung(e), "error"); }
          }) } }, "Zurücknehmen") : (z.reversal ? h("span", { class: "tag tag--muted" }, "Rücknahme") : "")))), "Noch keine Zahlungen."));
}

function bearbeitung(r, neu) {
  if (r.status === "draft") return null;
  const offen = r.kind === "invoice" && ["issued", "sent", "partially_paid"].includes(r.status) && darf("invoices.update");
  const vermerken = offen ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Bearbeitung dokumentieren", [h("p", { class: "muted small" }, "HQ versendet keine Mahnung — hier wird nur festgehalten, was du getan hast."),
      h("div", { class: "grid2" }, feld("Art", auswahl("kind", ART, "contact_attempt")), feld("Kanal", auswahl("channel", KANAL, "", "—"))),
      h("div", { class: "grid2" }, feld("Mahnstufe", eingabe("dunning_level", "", { type: "number", min: 0, max: 9 })), feld("Wiedervorlage am", eingabe("next_follow_up", "", { type: "date" }))),
      feld("Notiz", text("note", "", { rows: 2, maxlength: 5000 }))], "Speichern");
    if (!d) return;
    const b = { kind: d.kind, note: d.note };
    if (d.channel) b.channel = d.channel;
    if (d.dunning_level !== "") b.dunning_level = Number(d.dunning_level);
    if (d.next_follow_up) b.next_follow_up = d.next_follow_up;
    try { await post(`/invoices/${r.id}/followups`, b); toast("Gespeichert."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Bearbeitung dokumentieren") : null;
  const versand = darf("invoices.update") && r.status !== "cancelled" ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Versand vermerken", [feld("Kanal", auswahl("channel", KANAL, "email")), feld("Notiz", eingabe("note", "", { maxlength: 500 }))], "Vermerken");
    if (!d) return;
    try { await post(`/invoices/${r.id}/dispatches`, { action: "sent", channel: d.channel, note: d.note }); toast("Vermerkt."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Versand vermerken") : null;
  const verlauf = [...r.followups.map((f) => ({ t: f.created_at, text: `${ART[f.kind]}${f.channel ? ` (${KANAL[f.channel]})` : ""}${f.dunning_level !== null ? ` · Stufe ${f.dunning_level}` : ""}${f.next_follow_up ? ` · Wiedervorlage ${datum(f.next_follow_up)}` : ""}`, note: f.note, by: f.by })),
    ...r.dispatches.map((d) => ({ t: d.created_at, text: `${d.action === "sent" ? "Versand vermerkt" : "Gedruckt"}${d.channel ? ` (${KANAL[d.channel]})` : ""}`, note: d.note, by: d.by }))]
    .sort((a, b) => (a.t < b.t ? -1 : 1));
  return h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Versand & Bearbeitung"), h("span", { class: "row" }, versand, vermerken)),
    r.responsible ? h("p", { class: "muted small" }, `Zuständig: ${r.responsible.display_name} · Mahnstufe ${r.dunning_level}`) : null,
    verlauf.length ? h("div", { class: "list" }, verlauf.map((v) => h("div", { class: "item" }, h("div", {}, h("strong", {}, v.text), v.note ? h("div", { class: "small" }, v.note) : null),
      h("span", { class: "muted small" }, `${zeit(v.t)}${v.by ? ` · ${v.by.display_name}` : ""}`)))) : h("p", { class: "muted" }, "Noch nichts vermerkt."));
}

export async function druck(el, { ref }) {
  const [r, firma] = await Promise.all([get(`/invoices/${ref}`), darf("company.read") ? get("/company") : null]);
  const k = r.customer_snapshot || {};
  ersetze(el, h("div", { class: "row row--between no-print" }, h("a", { href: `#/rechnungen/${ref}`, class: "small" }, "← zurück"),
    h("button", { class: "btn", type: "button", on: { click: einmal(async () => {
      try { await post(`/invoices/${ref}/dispatches`, { action: "printed" }); } catch { /* Vermerk optional */ }
      window.print();
    }) } }, "Drucken / als PDF speichern")),
  h("article", { class: "card druck" }, h("p", { class: "small muted" }, firma ? (firma.legal_name || firma.name) : state.firma || ""),
    h("p", {}, [k.name, k.legal_name, k.street, [k.postal_code, k.city].filter(Boolean).join(" "), k.country].filter(Boolean).map((x) => h("div", {}, x))),
    h("h1", {}, `${r.kind === "cancellation" ? "Stornorechnung" : "Rechnung"} ${r.number || "(Entwurf)"}`),
    h("p", {}, `Datum: ${datum(r.issue_date)}${r.service_date ? ` · Leistung: ${datum(r.service_date)}` : ""} · Fällig: ${datum(r.due_date)}`),
    r.cancels ? h("p", {}, `Storno zu ${r.cancels.title}`) : null,
    tabelle([{ text: "Pos." }, { text: "Beschreibung" }, { text: "Menge" }, { text: "Einzelpreis" }, { text: "USt" }, { text: "Netto" }],
      r.lines.map((z) => h("tr", {}, zelle(String(z.position)), zelle(z.description), zelle(`${zahl(z.quantity_milli)} ${z.unit || ""}`),
        zelle(geld(z.unit_price_minor, r.currency)), zelle(prozent(z.tax_rate_bp)), zelle(geld(z.net_minor, r.currency))))),
    h("div", { class: "stack" }, h("div", { class: "row row--between" }, h("span", {}, "Netto"), h("span", {}, geld(r.net_minor, r.currency))),
      r.tax_by_rate.map((t) => h("div", { class: "row row--between" }, h("span", {}, `USt ${prozent(t.tax_rate_bp)}`), h("span", {}, geld(t.tax_minor, r.currency)))),
      h("div", { class: "row row--between" }, h("strong", {}, "Gesamt"), h("strong", {}, geld(r.gross_minor, r.currency)))),
    r.notes ? h("p", { class: "body" }, r.notes) : null,
    h("p", { class: "small muted no-print" }, "Druckansicht aus HQ. Pflichtangaben einer Rechnung (z. B. § 14 UStG) sind nicht geprüft — vor dem Versand selbst kontrollieren.")));
}
