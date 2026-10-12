// Aufgaben (C0): Liste mit Filtern und Seiten, anlegen, Detail mit Bearbeiten, Status, Zuweisung, Kommentaren.
import { alertBox, datum, dialog, einmal, ersetze, feld, h, toast, zeit } from "../dom.js";
import { del, get, meldung, patch, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { kommentare } from "./kommentare.js";

const STATUS = { open: "Offen", in_progress: "In Arbeit", blocked: "Blockiert", done: "Erledigt", cancelled: "Abgebrochen" };
const PRIO = { low: "Niedrig", normal: "Normal", high: "Hoch", urgent: "Dringend" };

export const status = (s) => h("span", { class: `tag${s === "done" ? "" : s === "blocked" ? " tag--danger" : " tag--muted"}` }, STATUS[s] || s);
export const prioritaet = (p) => (p === "high" || p === "urgent" ? h("span", { class: "tag tag--warn" }, PRIO[p]) : null);

const auswahl = (name, werte, wert, leer) => h("select", { name },
  leer ? h("option", { value: "" }, leer) : null,
  Object.entries(werte).map(([k, v]) => h("option", { value: k, selected: k === wert }, v)));

async function mitglieder() {
  if (!darf("users.read")) return [];
  return (await get("/members?status=active&limit=100")).items;
}

const OFFEN = ["open", "in_progress", "blocked"];

function chip(text, ohne) {
  return h("a", { class: "tag tag--muted", href: `#/aufgaben${query(ohne)}`, title: "Filter entfernen" }, `${text} ×`);
}

export async function liste(el, _params, q) {
  const st = q.getAll("status");
  const alleOffen = st.length === 0 || (st.length === OFFEN.length && OFFEN.every((s) => st.includes(s)));
  // Filter aus Links (z. B. Dashboard) bleiben erhalten — dieselben Parameter wie die API (Wert → Liste)
  const filter = { status: alleOffen ? "" : st, assignee: q.get("assignee") || "", priority: q.getAll("priority"),
    due_before: q.get("due_before") || "", sort: q.get("sort") || "created_at" };
  const params = { ...filter, status: alleOffen ? OFFEN : st,
    order: filter.sort === "due_date" || filter.sort === "title" ? "asc" : "desc", limit: 25, cursor: q.get("cursor") };
  const daten = await get(`/tasks${query(params)}`);
  const leiste = h("form", { class: "row" },
    auswahl("status", STATUS, st.length === 1 ? st[0] : "", "Alle offenen"),
    h("select", { name: "assignee" }, h("option", { value: "" }, "Alle"),
      h("option", { value: "me", selected: filter.assignee === "me" }, "Mir zugewiesen"),
      h("option", { value: "none", selected: filter.assignee === "none" }, "Ohne Zuständige")),
    auswahl("sort", { created_at: "Neueste", due_date: "Fälligkeit", priority: "Priorität", title: "Titel" }, filter.sort));
  for (const s of leiste.querySelectorAll("select")) s.classList.add("input");
  leiste.addEventListener("change", () => gehe(`/aufgaben${query({ ...Object.fromEntries(new FormData(leiste).entries()),
    priority: filter.priority, due_before: filter.due_before })}`));
  const chips = [];
  if (filter.due_before) chips.push(chip(`Fällig vor ${datum(filter.due_before)}`, { ...filter, due_before: "" }));
  if (filter.priority.length) {
    chips.push(chip(`Priorität: ${filter.priority.map((p) => PRIO[p] || p).join(", ")}`, { ...filter, priority: [] }));
  }
  const neu = darf("tasks.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Neue Aufgabe") : null;
  const zeilen = daten.items.map((a) => h("tr", {},
    h("td", {}, h("a", { href: `#/aufgaben/${a.id}` }, a.title)),
    h("td", {}, status(a.status), " ", prioritaet(a.priority)),
    h("td", { class: "opt" }, a.assignee ? a.assignee.display_name : "—"),
    h("td", { class: "opt" }, datum(a.due_date))));
  const weiter = daten.next_cursor ? h("a", { class: "btn btn--ghost btn--sm",
    href: `#/aufgaben${query({ ...filter, cursor: daten.next_cursor })}` }, "Weitere") : null;
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Aufgaben")), neu), leiste,
    chips.length ? h("div", { class: "row chips" }, chips) : null, h("br"),
    zeilen.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Titel"), h("th", {}, "Status"),
      h("th", { class: "opt" }, "Zuständig"), h("th", { class: "opt" }, "Fällig"))), h("tbody", {}, zeilen)))
      : h("p", { class: "empty" }, "Keine Aufgaben für diesen Filter."), h("div", { class: "row row--end" }, weiter));
}

function personenAuswahl(personen, wert) {
  return h("select", { name: "assignee" }, h("option", { value: "" }, "Niemand"),
    personen.map((m) => h("option", { value: m.id, selected: m.id === wert }, m.display_name)));
}

async function anlegen() {
  const personen = await mitglieder();
  const d = await dialog("Neue Aufgabe", [
    feld("Titel", h("input", { name: "title", required: true, maxlength: 200 })),
    feld("Beschreibung", h("textarea", { name: "description", maxlength: 10000 })),
    h("div", { class: "grid2" }, feld("Fällig am", h("input", { name: "due_date", type: "date" })),
      feld("Priorität", auswahl("priority", PRIO, "normal"))),
    personen.length ? feld("Zuständig", personenAuswahl(personen, "")) : null], "Anlegen");
  if (!d) return;
  const body = { title: d.title, description: d.description || null, priority: d.priority, due_date: d.due_date || null };
  if (d.assignee) body.assignee = d.assignee;
  try {
    const t = await post("/tasks", body);
    toast("Aufgabe angelegt.");
    gehe(`/aufgaben/${t.id}`);
  } catch (e) { toast(meldung(e), "error"); }
}

export async function detail(el, { ref }) {
  const [a, personen] = await Promise.all([get(`/tasks/${ref}`), mitglieder()]);
  const kom = h("section", { class: "card" });
  const fehler = h("div");
  let form = h("div", { class: "stack" }, h("p", { class: "body" }, a.description || h("span", { class: "muted" }, "Keine Beschreibung.")));
  if (darf("tasks.update")) {
    form = h("form", { class: "stack" }, fehler,
      feld("Titel", h("input", { name: "title", required: true, maxlength: 200, value: a.title })),
      feld("Beschreibung", h("textarea", { name: "description", maxlength: 10000, value: a.description || "" })),
      h("div", { class: "grid2" }, feld("Status", auswahl("status", STATUS, a.status)), feld("Priorität", auswahl("priority", PRIO, a.priority)),
        feld("Fällig am", h("input", { name: "due_date", type: "date", value: a.due_date || "" })),
        personen.length ? feld("Zuständig", personenAuswahl(personen, a.assignee ? a.assignee.id : "")) : null),
      h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern")));
    form.addEventListener("submit", einmal(async () => {
      const d = Object.fromEntries(new FormData(form).entries());
      const aenderung = { title: d.title, description: d.description, status: d.status, priority: d.priority,
        due_date: d.due_date || null };
      if (personen.length) aenderung.assignee = d.assignee || null;
      try { await patch(`/tasks/${ref}`, aenderung); toast("Gespeichert."); detail(el, { ref }); } catch (err) { ersetze(fehler, alertBox(meldung(err))); }
    }));
  }
  const anhaenge = h("section", { class: "card" });
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("a", { href: "#/aufgaben", class: "small" }, "← Aufgaben"), h("h1", {}, a.title),
    h("p", {}, `angelegt ${zeit(a.created_at)}${a.created_by ? ` von ${a.created_by.display_name}` : ""}`)),
  h("span", { class: "row" }, prioritaet(a.priority), status(a.status))),
  h("section", { class: "card" }, form), anhaenge, kom);
  await Promise.all([anhaengeZeigen(anhaenge, ref), kommentare(kom, ref)]);
}

// Anhänge = verknüpfte Dokumente (nur sichtbare Gegenseiten liefert der Server)
async function anhaengeZeigen(el, ref) {
  if (!darf("files.read")) { ersetze(el); return; }
  const docs = (await get(`/objects/${ref}/links`)).items.filter((l) => l.object.type === "document");
  const neu = () => anhaengeZeigen(el, ref);
  const knopf = darf("tasks.update") ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const auswahl = (await get("/documents?limit=100")).items.filter((d) => !docs.some((l) => l.object.id === d.id));
    if (!auswahl.length) { toast("Keine weiteren Dokumente vorhanden — zuerst unter „Dokumente“ hochladen.", "error"); return; }
    const d = await dialog("Dokument anhängen", feld("Dokument", h("select", { name: "document", required: true },
      auswahl.map((x) => h("option", { value: x.id }, x.title)))), "Anhängen");
    if (!d) return;
    try { await post(`/tasks/${ref}/attachments`, { document: d.document }); toast("Angehängt."); neu(); }
    catch (e) { toast(meldung(e), "error"); }
  }) } }, "Dokument anhängen") : null;
  ersetze(el, h("div", { class: "row row--between" }, h("h2", {}, "Anhänge"), knopf),
    docs.length ? h("div", { class: "list" }, docs.map((l) => h("div", { class: "item" },
      h("a", { href: `#/dokumente/${l.object.id}` }, l.object.title),
      darf("tasks.update") ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
        try { await del(`/links/${l.id}`); toast("Anhang entfernt."); neu(); } catch (e) { toast(meldung(e), "error"); }
      }) } }, "Entfernen") : null))) : h("p", { class: "muted" }, "Keine Anhänge."));
}
