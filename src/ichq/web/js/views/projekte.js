// Projekte: Liste oder Kanban nach Status, Anlegen, Detail mit Stammdaten, Team, Projektzeiten, Aufgaben, Dokumenten.
import { datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { del, get, meldung, patch, post, put, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { alsBetrag, archivKnopf, auswahl, cent, eingabe, Eingabefehler, feld, fehlertext, filterleiste, geld, leerZuNull,
  mitglieder, personen, seitenkopf, speichern, tabelle, text, weiterLink, zelle } from "./bausteine.js";
import { kommentare } from "./kommentare.js";
import { status as aufgabenStatus } from "./aufgaben.js";

export const STATUS = { planned: "Geplant", active: "Aktiv", on_hold: "Pausiert", completed: "Abgeschlossen", cancelled: "Abgebrochen" };
const OFFEN = ["planned", "active", "on_hold"];
const PRIO = { low: "Niedrig", normal: "Normal", high: "Hoch", urgent: "Dringend" };
const statusTag = (s) => h("span", { class: `tag${s === "active" ? "" : s === "cancelled" ? " tag--danger" : " tag--muted"}` }, STATUS[s] || s);
const stunden = (min) => `${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")} h`;

export async function liste(el, _p, q) {
  const filter = { q: q.get("q") || "", status: q.get("status") || "", member: q.get("member") || "",
    customer: q.get("customer") || "", ansicht: q.get("ansicht") || "liste", sort: q.get("sort") || "name" };
  const daten = await get(`/projects${query({ q: filter.q, status: filter.status || OFFEN, member: filter.member, customer: filter.customer,
    sort: filter.sort, order: filter.sort === "created_at" ? "desc" : "asc", limit: filter.ansicht === "kanban" ? 100 : 25, cursor: q.get("cursor") })}`);
  const leiste = filterleiste("/projekte", [
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Projekt suchen", "aria-label": "Projekte suchen", maxlength: 100 }),
    auswahl("status", STATUS, filter.status, "Alle offenen", { "aria-label": "Status" }),
    auswahl("member", { me: "Meine Projekte" }, filter.member, "Alle Projekte", { "aria-label": "Team" }),
    auswahl("sort", { name: "Name", end_date: "Ende", start_date: "Beginn", priority: "Priorität", created_at: "Neueste" }, filter.sort, undefined, { "aria-label": "Sortierung" }),
    auswahl("ansicht", { liste: "Liste", kanban: "Kanban" }, filter.ansicht, undefined, { "aria-label": "Ansicht" })], { customer: filter.customer });
  const neu = darf("projects.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Neues Projekt") : null;
  const inhalt = filter.ansicht === "kanban" ? kanban(daten.items, filter.status ? [filter.status] : OFFEN)
    : tabelle([{ text: "Projekt" }, { text: "Status" }, { text: "Kunde", opt: true }, { text: "Leitung", opt: true }, { text: "Ende", opt: true }],
      daten.items.map((p) => h("tr", {}, zelle(h("a", { href: `#/projekte/${p.id}` }, p.name)), zelle(statusTag(p.status)),
        zelle(p.customer ? p.customer.title : "—", true), zelle(p.owner ? p.owner.display_name : "—", true), zelle(datum(p.end_date), true))),
      filter.q || filter.status || filter.member ? "Keine Projekte für diesen Filter." : "Noch keine Projekte vorhanden. Lege dein erstes Projekt an.");
  ersetze(el, seitenkopf("Projekte", null, neu), leiste, h("br"), inhalt,
    filter.ansicht === "kanban" ? null : weiterLink("/projekte", filter, daten.next_cursor));
}

function kanban(items, spalten) {
  return h("div", { class: "grid2 kanban" }, spalten.map((s) => {
    const karten = items.filter((p) => p.status === s);
    return h("section", { class: "card", "aria-label": STATUS[s] }, h("h2", {}, `${STATUS[s]} (${karten.length})`),
      karten.length ? h("div", { class: "list" }, karten.map((p) => h("div", { class: "item" },
        h("a", { href: `#/projekte/${p.id}` }, p.name), h("span", { class: "muted small" }, p.end_date ? `bis ${datum(p.end_date)}` : "")))) : h("p", { class: "muted" }, "Leer."));
  }));
}

async function kunden() { return darf("customers.read") ? (await get("/customers?limit=100")).items : []; }

function felder(p, leute, kl) {
  return [feld("Name", eingabe("name", p.name, { required: true, maxlength: 300 })),
    feld("Beschreibung", text("description", p.description, { rows: 3 })),
    h("div", { class: "grid2" }, feld("Status", auswahl("status", STATUS, p.status || "planned")), feld("Priorität", auswahl("priority", PRIO, p.priority || "normal"))),
    h("div", { class: "grid2" }, kl.length ? feld("Kunde", h("select", { name: "customer", class: "input" }, h("option", { value: "" }, "— ohne —"),
      kl.map((k) => h("option", { value: k.id, selected: p.customer && p.customer.id === k.id }, k.name)))) : null,
    leute.length ? feld("Projektleitung", personen("owner", leute, p.owner ? p.owner.id : "", "— offen —")) : null),
    h("div", { class: "grid2" }, feld("Beginn", eingabe("start_date", p.start_date, { type: "date" })), feld("Ende", eingabe("end_date", p.end_date, { type: "date" }))),
    feld("Budget (€)", eingabe("budget", alsBetrag(p.budget_minor), { inputmode: "decimal", placeholder: "z. B. 15.000,00" }), "Leer lassen, wenn es kein Budget gibt.")];
}

function body(d, leute, kl) {
  leerZuNull(d, "customer", "owner", "start_date", "end_date");
  if (!leute.length) delete d.owner;
  if (!kl.length) delete d.customer;
  const betrag = d.budget;
  delete d.budget;
  d.budget_minor = betrag ? cent(betrag) : null;
  if (betrag && d.budget_minor === null) throw new Eingabefehler("Budget: ungültiger Betrag (z. B. 15.000,00)");
  return d;
}

async function anlegen() {
  const [leute, kl] = await Promise.all([mitglieder(), kunden()]);
  const d = await dialog("Neues Projekt", felder({}, leute, kl), "Anlegen");
  if (!d) return;
  try { const p = await post("/projects", body(d, leute, kl)); toast("Projekt angelegt."); gehe(`/projekte/${p.id}`); }
  catch (e) { toast(fehlertext(e), "error"); }
}

export async function detail(el, { ref }) {
  const [p, leute, kl] = await Promise.all([get(`/projects/${ref}`), mitglieder(), kunden()]);
  const neu = () => detail(el, { ref });
  const fehler = h("div");
  const stamm = darf("projects.update") ? speichern(h("form", { class: "stack" }, fehler, felder(p, leute, kl),
    h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
    await patch(`/projects/${ref}`, body(d, leute, kl)); toast("Gespeichert."); neu();
  }) : h("p", { class: "body" }, p.description || h("span", { class: "muted" }, "Keine Beschreibung."));
  const s = p.summary;
  const kennzahlen = h("div", { class: "metrics" },
    h("div", { class: "metric" }, h("span", { class: "metric-value" }, String(s.open_tasks)), h("span", { class: "metric-label" }, "offene Aufgaben")),
    h("div", { class: "metric" }, h("span", { class: "metric-value" }, stunden(s.minutes_total)), h("span", { class: "metric-label" }, "Projektzeit")),
    h("div", { class: "metric" }, h("span", { class: "metric-value" }, stunden(s.minutes_billable)), h("span", { class: "metric-label" }, "abrechenbar")),
    h("div", { class: "metric" }, h("span", { class: "metric-value" }, p.budget_minor === null ? "—" : geld(p.budget_minor, p.currency)), h("span", { class: "metric-label" }, "Budget")));
  const teamEl = h("section", { class: "card" });
  const zeitEl = h("section", { class: "card" });
  const aufgabenEl = h("section", { class: "card" });
  const kom = h("section", { class: "card" });
  const profitEl = darf("finance.read") ? h("section", { class: "card" }) : null;
  ersetze(el, seitenkopf(p.name, { href: "#/projekte", text: "Projekte" }, statusTag(p.status),
    p.archived ? h("span", { class: "tag tag--muted" }, "archiviert") : null, darf("projects.update") ? archivKnopf(p, neu) : null),
  h("p", { class: "muted small" }, [p.customer ? `Kunde: ${p.customer.title}` : null, p.start_date || p.end_date ? `${datum(p.start_date)} – ${datum(p.end_date)}` : null,
    `angelegt ${zeit(p.created_at)}`].filter(Boolean).join(" · ")),
  p.customer ? h("p", {}, h("a", { href: `#/kunden/${p.customer.id}` }, "Zum Kunden")) : null,
  kennzahlen, h("br"), profitEl, h("section", { class: "card" }, h("h2", {}, "Stammdaten"), stamm), teamEl, aufgabenEl, zeitEl, kom);
  teamZeigen(teamEl, p, leute, neu);
  await Promise.all([zeitenZeigen(zeitEl, p, leute, neu), aufgabenZeigen(aufgabenEl, p), kommentare(kom, ref),
    profitEl ? profitZeigen(profitEl, ref) : null]);
}

// Profitabilität: Rechenhilfe aus erfassten Daten; was fehlt, steht ausdrücklich da (nie still als 0 €)
async function profitZeigen(el, ref) {
  const r = await get(`/projects/${ref}/profitability`);
  const zeile = (text, wert) => h("li", {}, `${text}: ${geld(wert, r.currency)}`);
  ersetze(el, h("h2", {}, "Profitabilität"),
    h("div", { class: "metrics" }, h("div", { class: `metric${r.margin_minor < 0 ? " metric--danger" : ""}` },
      h("span", { class: "metric-value" }, geld(r.margin_minor, r.currency)), h("span", { class: "metric-label" }, r.complete ? "Marge" : "Marge (unvollständig)"))),
    h("ul", { class: "list" }, zeile("Erlös netto (ausgestellte Rechnungen und Stornos)", r.revenue_net_minor),
      zeile("Ausgaben", r.receipts_net_minor), zeile("Personalkosten (Projektzeit × Stundensatz)", r.labour_cost_minor)),
    r.gaps.length ? h("ul", { class: "list" }, r.gaps.map((g) => h("li", { class: "small" }, h("span", { class: "tag tag--warn" }, String(g.count)), ` ${g.text}`))) : null,
    h("p", { class: "muted small" }, r.note));
}

function teamZeigen(el, p, leute, neu) {
  const kosten = darf("finance.read");
  const aufnehmen = darf("projects.assign") && leute.length ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Ins Team aufnehmen", [feld("Person", personen("member", leute, "", "— wählen —")),
      feld("Rolle im Projekt", eingabe("role", "", { maxlength: 100 })),
      kosten ? feld("Kostensatz je Stunde (€)", eingabe("kosten", "", { inputmode: "decimal" }), "Kalkulatorisch, nur für Finanzrechte sichtbar.") : null], "Aufnehmen");
    if (!d || !d.member) return;
    const b = { role: d.role || null };
    if (kosten && d.kosten) { b.hourly_cost_minor = cent(d.kosten); if (b.hourly_cost_minor === null) { toast("Kostensatz ungültig.", "error"); return; } }
    try { await put(`/projects/${p.id}/members/${d.member}`, b); toast("Aufgenommen."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Person aufnehmen") : null;
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Team"), aufnehmen),
    p.team.length ? h("div", { class: "list" }, p.team.map((t) => h("div", { class: "item" },
      h("div", {}, h("strong", {}, t.member ? t.member.display_name : "—"), h("div", { class: "muted small" },
        [t.role, kosten && t.hourly_cost_minor !== null && t.hourly_cost_minor !== undefined ? `${geld(t.hourly_cost_minor, p.currency)}/h` : null].filter(Boolean).join(" · "))),
      darf("projects.assign") && t.member && (!p.owner || p.owner.id !== t.member.id) ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
        if (!await dialog("Aus dem Team entfernen?", h("p", {}, `${t.member.display_name} verliert den Zugriff über das Team.`), "Entfernen", true)) return;
        try { await del(`/projects/${p.id}/members/${t.member.id}`); toast("Entfernt."); neu(); } catch (e) { toast(meldung(e), "error"); }
      }) } }, "Entfernen") : null))) : h("p", { class: "muted" }, "Noch niemand im Team."));
}

async function zeitenZeigen(el, p, leute, neu) {
  const daten = await get(`/projects/${p.id}/time-entries`);
  const erfassen = h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Projektzeit erfassen", [h("p", { class: "muted small" }, "Aufwand je Projekt — keine Arbeitszeiterfassung."),
      h("div", { class: "grid2" }, feld("Datum", eingabe("work_date", new Date().toISOString().slice(0, 10), { type: "date", required: true })),
        feld("Minuten", eingabe("minutes", "", { type: "number", min: 1, max: 1440, required: true }))),
      feld("Tätigkeit", eingabe("description", "", { maxlength: 500 })),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "billable", value: "1", checked: true }), " abrechenbar")], "Erfassen");
    if (!d) return;
    try { await post(`/projects/${p.id}/time-entries`, { work_date: d.work_date, minutes: Number(d.minutes), description: d.description, billable: d.billable === "1" }); toast("Erfasst."); neu(); }
    catch (e) { toast(meldung(e), "error"); }
  }) } }, "Zeit erfassen");
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Projektzeiten"), erfassen),
    tabelle([{ text: "Datum" }, { text: "Person" }, { text: "Dauer" }, { text: "Tätigkeit", opt: true }, { text: "" }],
      daten.items.map((e) => h("tr", {}, zelle(datum(e.work_date)), zelle(e.member ? e.member.display_name : "—"),
        zelle(`${stunden(e.minutes)}${e.billable ? "" : " (intern)"}`), zelle(e.description || "—", true),
        zelle(h("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Eintrag löschen", on: { click: einmal(async () => {
          try { await del(`/projects/${p.id}/time-entries/${e.id}`); toast("Gelöscht."); neu(); } catch (err) { toast(meldung(err), "error"); }
        }) } }, "Löschen")))), "Noch keine Zeiten erfasst."));
}

async function aufgabenZeigen(el, p) {
  if (!darf("tasks.read")) { ersetze(el); return; }
  const daten = await get(`/tasks?subject=${p.id}&status=open&status=in_progress&status=blocked&status=done&limit=50`);
  const neu = darf("tasks.create") ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Aufgabe zum Projekt", [feld("Titel", eingabe("title", "", { required: true, maxlength: 300 })),
      feld("Fällig am", eingabe("due_date", "", { type: "date" }))], "Anlegen");
    if (!d) return;
    try { const t = await post(`/objects/${p.id}/tasks`, { title: d.title, due_date: d.due_date || null }); toast("Aufgabe angelegt."); gehe(`/aufgaben/${t.id}`); }
    catch (e) { toast(meldung(e), "error"); }
  }) } }, "Aufgabe anlegen") : null;
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Aufgaben"), neu),
    daten.items.length ? h("div", { class: "list" }, daten.items.map((t) => h("div", { class: "item" },
      h("a", { href: `#/aufgaben/${t.id}` }, t.title), aufgabenStatus(t.status)))) : h("p", { class: "muted" }, "Keine Aufgaben."));
}
