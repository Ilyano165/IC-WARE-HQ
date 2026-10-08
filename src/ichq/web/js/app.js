// Start: Sitzung prüfen → Anmeldung / Firmenwahl / App-Shell. Navigation nach Rechten (nur Anzeige — der Server prüft).
import { $, alertBox, ersetze, h, marke, toast } from "./dom.js";
import { ApiError, get, meldung, post } from "./api.js";
import { aktuell, finde, gehe, route } from "./router.js";
import { darf, setzeMe, state } from "./state.js";
import * as anmeldung from "./views/anmeldung.js";
import * as uebersicht from "./views/uebersicht.js";
import * as aufgaben from "./views/aufgaben.js";
import * as dokumente from "./views/dokumente.js";
import * as inbox from "./views/inbox.js";
import * as mitglieder from "./views/mitglieder.js";
import * as rollen from "./views/rollen.js";
import * as verwaltung from "./views/verwaltung.js";
import * as konto from "./views/konto.js";

const app = $("#app");

route("/", uebersicht.ansicht);
route("/aufgaben", aufgaben.liste, "tasks.read");
route("/aufgaben/:ref", aufgaben.detail, "tasks.read");
route("/dokumente", dokumente.liste, "files.read");
route("/dokumente/:ref", dokumente.detail, "files.read");
route("/benachrichtigungen", inbox.benachrichtigungen);
route("/suche", inbox.suche);
route("/mitglieder", mitglieder.liste, "users.read");
route("/mitglieder/:ref", mitglieder.person, "users.read");
route("/rollen", rollen.liste, "roles.read");
route("/rollen/:ref", rollen.editor, "roles.read");
route("/firma", verwaltung.firma, "company.read");
route("/aktivitaet", verwaltung.aktivitaet, "activity.read");
route("/audit", verwaltung.audit, "audit.read");
route("/konto", konto.ansicht);

const NAV = [
  { pfad: "/", text: "Übersicht" },
  { pfad: "/aufgaben", text: "Aufgaben", recht: "tasks.read" },
  { pfad: "/dokumente", text: "Dokumente", recht: "files.read" },
  { pfad: "/benachrichtigungen", text: "Benachrichtigungen" },
  { gruppe: "Verwaltung" },
  { pfad: "/mitglieder", text: "Mitglieder", recht: "users.read" },
  { pfad: "/rollen", text: "Rollen & Rechte", recht: "roles.read" },
  { pfad: "/firma", text: "Firma", recht: "company.read" },
  { pfad: "/aktivitaet", text: "Aktivität", recht: "activity.read" },
  { pfad: "/audit", text: "Audit", recht: "audit.read" },
  { gruppe: "Persönlich" },
  { pfad: "/konto", text: "Konto & Sicherheit" },
];

function navigation() {
  const eintraege = NAV.filter((n) => !n.recht || darf(n.recht));
  // Gruppenüberschriften nur, wenn danach noch Einträge folgen
  const sichtbar = eintraege.filter((n, i) => !n.gruppe || (eintraege[i + 1] && !eintraege[i + 1].gruppe));
  return h("nav", { class: "nav", "aria-label": "Hauptnavigation" },
    sichtbar.map((n) => (n.gruppe ? h("div", { class: "group" }, n.gruppe)
      : h("a", { href: `#${n.pfad}`, dataset: { pfad: n.pfad } }, n.text))));
}

async function abmelden() {
  try { await post("/auth/logout"); } catch { /* Sitzung war schon weg */ }
  setzeMe(null);
  location.hash = "#/";
  start();
}

function shell() {
  const suche = h("input", { class: "input", type: "search", name: "q", placeholder: "Suchen …",
    "aria-label": "Suchen", minlength: 2, maxlength: 100 });
  const glocke = h("a", { class: "btn btn--ghost btn--sm bell", href: "#/benachrichtigungen", "aria-label": "Benachrichtigungen" },
    "Mitteilungen", h("span", { class: "badge", id: "ungelesen", hidden: true }, "0"));
  const name = state.sitzung.user.display_name;
  const huelle = h("div", { class: "shell" },
    h("aside", { class: "side", id: "seite" }, marke("HQ"), navigation(),
      h("div", { class: "tenant" }, h("div", { class: "muted small" }, "Firma"), h("div", {}, state.firma || "—"),
        state.sitzung.memberships.length > 1
          ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: () => anmeldung.firmenwahl(app, state.sitzung, start, true) } }, "Firma wechseln")
          : null)),
    h("div", { class: "main" },
      h("header", { class: "top" },
        h("button", { class: "btn btn--ghost btn--sm menu-btn", type: "button", "aria-controls": "seite",
          on: { click: () => huelle.classList.toggle("nav-open") } }, "Menü"),
        h("form", { class: "search", role: "search", on: { submit: (e) => { e.preventDefault(); gehe(`/suche?q=${encodeURIComponent(suche.value.trim())}`); } } }, suche),
        glocke,
        h("span", { class: "who-name muted small" }, name),
        h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: abmelden } }, "Abmelden")),
      h("div", { class: "content", id: "inhalt" })));
  huelle.addEventListener("click", (e) => { if (e.target.closest(".nav a")) huelle.classList.remove("nav-open"); });
  ersetze(app, huelle);
}

async function ungelesen() {
  const b = $("#ungelesen");
  if (!b) return;
  try {
    const n = (await get("/notifications?unread=true&limit=1")).unread_count;
    b.textContent = String(n);
    b.hidden = n === 0;
  } catch { b.hidden = true; }
}

async function zeige() {
  const inhalt = $("#inhalt");
  if (!inhalt) return;
  const { pfad, query } = aktuell();
  for (const a of document.querySelectorAll(".nav a")) {
    const p = a.dataset.pfad;
    if (p === pfad || (p !== "/" && pfad.startsWith(`${p}/`))) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  const r = finde(pfad);
  if (!r) { ersetze(inhalt, h("div", { class: "view" }, h("h1", {}, "Nicht gefunden"), h("p", { class: "muted" }, "Diese Seite gibt es nicht."))); return; }
  if (r.recht && !darf(r.recht)) {
    ersetze(inhalt, h("div", { class: "view" }, h("h1", {}, "Keine Berechtigung"), h("p", { class: "muted" }, `Dafür fehlt das Recht ${r.recht}.`)));
    return;
  }
  // Jeder Seitenwechsel rendert in einen EIGENEN Container. Kommt eine langsame, ältere Ansicht erst nach einem
  // neueren Wechsel zurück, schreibt sie in ihren abgehängten Container und überschreibt die neue Seite nicht.
  const ziel = h("div", { class: "view" }, h("p", { class: "muted" }, "Lädt …"));
  ersetze(inhalt, ziel);
  try {
    await r.ansicht(ziel, r.params, query);
  } catch (e) {
    ersetze(ziel, alertBox(meldung(e)));
  }
  if (ziel.isConnected) ungelesen();
}

export async function start() {
  const art = new URLSearchParams(location.search).get("v");
  const token = (/token=([A-Za-z0-9_-]+)/.exec(location.hash) || [])[1];
  if ((art === "einladung" || art === "passwort-neu") && token) {
    anmeldung.oeffentlich(app, art, token, () => { history.replaceState(null, "", "/app/#/"); start(); });
    return;
  }
  try {
    state.sitzung = await get("/auth/session");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { anmeldung.login(app, start); return; }
    ersetze(app, h("div", { class: "gate" }, alertBox(meldung(e))));
    return;
  }
  if (!state.sitzung.session.active_tenant_id) { anmeldung.firmenwahl(app, state.sitzung, start); return; }
  try {
    setzeMe(await get("/me"));
  } catch (e) {
    if (e instanceof ApiError && e.code === "tenant_required") { anmeldung.firmenwahl(app, state.sitzung, start); return; }
    throw e;
  }
  const aktiv = state.sitzung.memberships.find((m) => m.tenant_id === state.sitzung.session.active_tenant_id);
  state.firma = aktiv ? aktiv.name : null;
  shell();
  await zeige();
}

window.addEventListener("hashchange", zeige);
window.addEventListener("ichq:ungelesen", ungelesen);
window.addEventListener("ichq:abgemeldet", () => { if ($("#inhalt")) { toast("Sitzung beendet — bitte neu anmelden.", "error"); start(); } });
start().catch((e) => ersetze(app, h("div", { class: "gate" }, alertBox(meldung(e)))));
