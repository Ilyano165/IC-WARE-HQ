// Benachrichtigungen und globale Suche (C0). Beides liefert der Server bereits rechtegefiltert.
import { ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, post, query } from "../api.js";

const ZIEL = { task: "aufgaben", document: "dokumente" };
const link = (o) => (o && ZIEL[o.type] ? `#/${ZIEL[o.type]}/${o.id}` : null);
const GRUPPEN = { tasks: "Aufgaben", documents: "Dokumente", persons: "Personen", companies: "Firmen", projects: "Projekte",
  receipts: "Belege", invoices: "Rechnungen" };

export async function benachrichtigungen(el, _p, q) {
  const nurNeu = q.get("alle") !== "1";
  const daten = await get(`/notifications${query({ unread: nurNeu ? "true" : null, limit: 50 })}`);
  const neu = () => { window.dispatchEvent(new Event("ichq:ungelesen")); benachrichtigungen(el, _p, q); };
  const alle = h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
    try { await post("/notifications/read-all"); neu(); } catch (e) { toast(meldung(e), "error"); }
  } } }, "Alle als gelesen markieren");
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Benachrichtigungen"),
    h("p", {}, `${daten.unread_count} ungelesen`)), h("div", { class: "row" },
    h("a", { class: "btn btn--ghost btn--sm", href: nurNeu ? "#/benachrichtigungen?alle=1" : "#/benachrichtigungen" },
      nurNeu ? "Auch gelesene zeigen" : "Nur ungelesene"), daten.unread_count ? alle : null)),
  daten.items.length ? h("div", { class: "list" }, daten.items.map((n) => h("div", { class: "item" },
    h("span", {}, link(n.object) ? h("a", { href: link(n.object) }, n.title) : n.title,
      h("div", { class: "meta" }, zeit(n.created_at), n.object ? ` · ${n.object.title}` : "")),
    n.read ? h("span", { class: "tag tag--muted" }, "gelesen")
      : h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
        try { await post(`/notifications/${n.id}/read`); neu(); } catch (e) { toast(meldung(e), "error"); }
      } } }, "Gelesen")))) : h("p", { class: "empty" }, nurNeu ? "Keine ungelesenen Benachrichtigungen." : "Keine Benachrichtigungen."));
}

export async function suche(el, _p, q) {
  const begriff = (q.get("q") || "").trim();
  const kopf = h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Suche"), h("p", {}, begriff ? `„${begriff}“` : "")));
  if (begriff.length < 2) { ersetze(el, kopf, h("p", { class: "empty" }, "Mindestens zwei Zeichen eingeben.")); return; }
  const daten = await get(`/search${query({ q: begriff, per_group: 10 })}`);
  const gruppen = Object.entries(daten.groups).filter(([, g]) => g.items.length);
  ersetze(el, kopf, gruppen.length ? gruppen.map(([name, g]) => h("section", { class: "card" }, h("h2", {}, GRUPPEN[name] || name),
    h("div", { class: "list" }, g.items.map((t) => h("div", { class: "item" },
      link(t) ? h("a", { href: link(t) }, t.title) : h("span", {}, t.title), h("span", { class: "tag tag--muted" }, t.type)))),
    g.has_more ? h("p", { class: "muted small" }, "Weitere Treffer — Suche verfeinern.") : null))
    : h("p", { class: "empty" }, "Keine Treffer."));
}
