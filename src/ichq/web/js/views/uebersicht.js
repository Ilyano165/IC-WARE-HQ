// Startseite der Shell. KEIN Dashboard (D0 kommt nach U1): nur eigene offene Aufgaben und ungelesene Mitteilungen.
import { datum, ersetze, h, zeit } from "../dom.js";
import { get } from "../api.js";
import { darf, state } from "../state.js";
import { prioritaet, status } from "./aufgaben.js";

export async function ansicht(el) {
  const teile = [];
  if (darf("tasks.read")) {
    const t = await get("/tasks?assignee=me&status=open&status=in_progress&status=blocked&sort=due_date&order=asc&limit=10");
    teile.push(h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Meine offenen Aufgaben"),
      h("a", { href: "#/aufgaben" }, "Alle Aufgaben")),
    t.items.length ? h("div", { class: "list" }, t.items.map((a) => h("a", { class: "item", href: `#/aufgaben/${a.id}` },
      h("span", {}, a.title, h("div", { class: "meta" }, `fällig ${datum(a.due_date)}`)),
      h("span", { class: "row" }, prioritaet(a.priority), status(a.status)))))
      : h("p", { class: "empty" }, "Keine offenen Aufgaben.")));
  }
  const n = await get("/notifications?unread=true&limit=5");
  teile.push(h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Ungelesene Mitteilungen"),
    h("a", { href: "#/benachrichtigungen" }, "Alle")),
  n.items.length ? h("div", { class: "list" }, n.items.map((m) => h("div", { class: "item" },
    h("span", {}, m.title, h("div", { class: "meta" }, zeit(m.created_at)))))) : h("p", { class: "empty" }, "Nichts Neues.")));
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, `Hallo ${state.sitzung.user.display_name}`),
    h("p", {}, state.firma || ""))), h("div", { class: "grid2" }, teile),
  h("p", { class: "muted small" }, "Das Dashboard mit Kennzahlen folgt als eigener Meilenstein (D0)."));
}
