// D0 Dashboard (ADR-014): EIN Aufruf GET /dashboard; der Server entscheidet, welche Widgets der Mensch sehen darf
// (effektive Rechte). Die Oberfläche zeigt nur an, was kommt — jede Zahl ist ein Link auf die Liste, aus der sie
// gezählt wurde (Wert → Liste → Objekt). Geplante Module erscheinen ohne Werte.
import { datum, ersetze, h, zeit } from "../dom.js";
import { get, query } from "../api.js";
import { state } from "../state.js";

const LISTE = { tasks: "/aufgaben", documents: "/dokumente", questions: "/rueckfragen", members: "/mitglieder",
  notifications: "/benachrichtigungen", activities: "/aktivitaet" };
const OBJEKT = { task: "/aufgaben", document: "/dokumente" };

function listenLink(liste, filter) {
  const basis = LISTE[liste];
  if (!basis) return null;
  return `#${basis}${query(filter || {})}`;
}

function kennzahl(w, m) {
  const ziel = m.linked === false ? null : listenLink(w.list, m.filter);
  const inhalt = [h("span", { class: "metric-value" }, String(m.value)), h("span", { class: "metric-label" }, m.label)];
  const art = `metric metric--${m.tone}`;
  return ziel ? h("a", { class: art, href: ziel, "aria-label": `${m.label}: ${m.value}` }, inhalt) : h("div", { class: art }, inhalt);
}

function eintrag(w, it) {
  const ziel = it.id && OBJEKT[it.type] ? `#${OBJEKT[it.type]}/${it.id}` : (it.list ? listenLink(it.list, it.filter) : null);
  const titel = ziel ? h("a", { href: ziel }, it.title) : h("span", {}, it.title);
  const wann = it.date ? (it.date.length === 10 ? `fällig ${datum(it.date)}` : zeit(it.date)) : "";
  return h("li", { class: `witem witem--${it.tone}` }, titel,
    it.detail || wann ? h("div", { class: "meta" }, [it.detail, wann].filter(Boolean).join(" · ")) : null);
}

function widget(w) {
  const kopf = h("div", { class: "widget-head" }, h("h2", {}, w.title),
    w.list && LISTE[w.list] ? h("a", { class: "small", href: `#${LISTE[w.list]}` }, "Alle") : null);
  if (w.error) {
    return h("section", { class: `card widget widget--${w.size}`, dataset: { widget: w.key } }, kopf,
      h("p", { class: "empty" }, "Dieses Widget ist gerade nicht verfügbar."));
  }
  return h("section", { class: `card widget widget--${w.size}`, dataset: { widget: w.key }, "aria-label": w.title }, kopf,
    w.metrics.length ? h("div", { class: "metrics" }, w.metrics.map((m) => kennzahl(w, m))) : null,
    w.items.length ? h("ul", { class: "witems" }, w.items.map((it) => eintrag(w, it)))
      : (w.empty ? h("p", { class: "empty" }, w.empty) : null));
}

function geplant(liste) {
  if (!liste.length) return null;
  return h("section", { class: "planned", "aria-label": "Geplante Module" }, h("h2", { class: "small muted" }, "In Vorbereitung"),
    h("p", { class: "muted small" }, "Diese Bereiche erscheinen, sobald ihr Fachmodul gebaut ist — bis dahin ohne Zahlen."),
    h("div", { class: "row" }, liste.map((p) => h("span", { class: "tag tag--muted", title: p.module }, p.title))));
}

export async function ansicht(el) {
  const kopf = h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, `Hallo ${state.sitzung.user.display_name}`),
    h("p", {}, state.firma || "")));
  // Gerüst in Endgröße, damit beim Laden nichts springt
  ersetze(el, kopf, h("div", { class: "dash" }, [1, 2, 3, 4].map(() => h("section", { class: "card widget skeleton", "aria-hidden": "true" }))));
  if (!state.rechte.has("dashboard.read")) {
    ersetze(el, kopf, h("p", { class: "empty" }, "Für das Dashboard fehlt das Recht dashboard.read."));
    return;
  }
  const d = await get("/dashboard");
  ersetze(el, kopf, h("p", { class: "muted small" }, `Stand ${zeit(new Date().toISOString())}`),
    h("div", { class: "dash" }, d.widgets.filter((w) => w.key !== "warnings" || w.items.length).map(widget)),
    geplant(d.planned));
}
