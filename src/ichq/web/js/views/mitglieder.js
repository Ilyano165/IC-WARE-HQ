// Mitglieder (M3) und Rechte einer Person (M4): Rollen, Einzelrechte, Vorschau „was darf diese Person" mit Quelle.
// Alle Regeln (Obergrenze, Rang, kein Selbstbedienen, letzter Admin) prüft der Server — hier nur Anzeige + Fehlermeldung.
import { alertBox, datum, dialog, ersetze, feld, h, toast } from "../dom.js";
import { del, get, meldung, post, put } from "../api.js";
import { darf, state } from "../state.js";

const STATUS = { active: "aktiv", suspended: "deaktiviert", left: "ausgetreten", invited: "eingeladen" };
const QUELLE = { role: "Rolle", allow: "Einzelrecht: erlaubt", deny: "Einzelrecht: verboten", feature_disabled: "Modul abgeschaltet", none: "—" };

export async function liste(el, _p, q) {
  const status = q && STATUS[q.get("status")] ? q.get("status") : null;
  const [m, e] = await Promise.all([get(`/members?limit=100${status ? `&status=${status}` : ""}`),
    darf("users.read") ? get("/invitations?limit=50") : null]);
  const einladen = darf("users.create") ? h("button", { class: "btn", type: "button", on: { click: async () => {
    const d = await dialog("Person einladen", [feld("E-Mail", h("input", { name: "email", type: "email", required: true, maxlength: 254 })),
      feld("Funktion (optional)", h("input", { name: "title", maxlength: 120 })),
      h("p", { class: "muted small" }, "Der Link ist 7 Tage gültig. Eine Einladung gibt noch keine Rechte — Rollen danach vergeben.")], "Einladen");
    if (!d) return;
    try { await post("/invitations", { email: d.email, title: d.title || null }); toast("Einladung versendet."); liste(el); } catch (x) { toast(meldung(x), "error"); }
  } } }, "Person einladen") : null;
  const zeilen = m.items.map((p) => h("tr", {}, h("td", {}, h("a", { href: `#/mitglieder/${p.id}` }, p.display_name),
    h("div", { class: "muted small" }, p.email)), h("td", { class: "opt" }, p.title || "—"),
  h("td", {}, h("span", { class: `tag${p.status === "active" ? "" : " tag--muted"}` }, STATUS[p.status] || p.status))));
  const offen = e ? e.items.filter((i) => !i.accepted && !i.revoked) : [];
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Mitglieder"), h("p", {}, `${m.items.length} Personen${status ? ` · nur ${STATUS[status]}` : ""}`)), einladen),
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Person"), h("th", { class: "opt" }, "Funktion"),
      h("th", {}, "Status"))), h("tbody", {}, zeilen))),
    offen.length ? h("section", { class: "card" }, h("h2", {}, "Offene Einladungen"), h("div", { class: "list" }, offen.map((i) =>
      h("div", { class: "item" }, h("span", {}, i.email, h("div", { class: "meta" }, i.expired ? "abgelaufen" : `gültig bis ${datum(i.expires_at)}`)),
        darf("users.create") ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
          try { await del(`/invitations/${i.id}`); toast("Einladung widerrufen."); liste(el); } catch (x) { toast(meldung(x), "error"); }
        } } }, "Widerrufen") : null)))) : null);
}

async function aktion(fn, neu) {
  try { await fn(); toast("Gespeichert."); neu(); } catch (e) { toast(meldung(e), "error"); }
}

export async function person(el, { ref }) {
  const neu = () => person(el, { ref });
  const [mitglieder, rechte, rollen] = await Promise.all([get("/members?limit=100"), darf("roles.read") ? get(`/members/${ref}/permissions`) : null,
    darf("roles.read") ? get("/roles") : null]);
  const p = mitglieder.items.find((x) => x.id === ref);
  if (!p) { ersetze(el, alertBox("Mitglied nicht gefunden.")); return; }
  const selbst = p.email === state.sitzung.user.email;
  const kopf = h("div", { class: "pagehead" }, h("div", {}, h("a", { href: "#/mitglieder", class: "small" }, "← Mitglieder"),
    h("h1", {}, p.display_name), h("p", {}, `${p.email} · ${STATUS[p.status] || p.status}${rechte ? ` · Rang ${rechte.rank}` : ""}`)),
  darf("users.deactivate") && !selbst && p.status === "active" ? h("button", { class: "btn btn--danger", type: "button", on: { click: async () => {
    const d = await dialog("Mitglied deaktivieren", h("p", {}, `${p.display_name} verliert sofort den Zugang zur Firma.`), "Deaktivieren", true);
    if (d) aktion(() => post(`/members/${ref}/deactivate`), neu);
  } } }, "Deaktivieren") : null);
  if (!rechte) { ersetze(el, kopf); return; }
  const hinweis = selbst ? alertBox("Das ist dein eigenes Konto — eigene Rollen und Einzelrechte kann niemand selbst ändern.", "info") : null;
  const gehalten = new Set(rechte.roles.map((r) => r.id));
  const rollenKarte = h("section", { class: "card" }, h("h2", {}, "Rollen"), h("div", { class: "list" },
    rechte.roles.map((r) => h("div", { class: "item" }, h("span", {}, h("b", {}, r.name), h("div", { class: "meta" }, `Rang ${r.rank}${r.archived ? " · archiviert (wirkt nicht)" : ""}`)),
      darf("roles.assign") && !selbst ? h("button", { class: "btn btn--ghost btn--sm", type: "button",
        on: { click: () => aktion(() => del(`/members/${ref}/roles/${r.id}`), neu) } }, "Entziehen") : null)),
    rechte.roles.length ? null : h("p", { class: "muted" }, "Keine Rollen.")),
  darf("roles.assign") && !selbst ? h("form", { class: "row", on: { submit: (e) => {
    e.preventDefault();
    const wahl = e.target.elements.rolle.value;
    if (wahl) aktion(() => put(`/members/${ref}/roles/${wahl}`), neu);
  } } }, h("select", { class: "input", name: "rolle", "aria-label": "Rolle vergeben" }, h("option", { value: "" }, "Rolle vergeben …"),
    rollen.items.filter((r) => !gehalten.has(r.id)).map((r) => h("option", { value: r.id }, `${r.name} (Rang ${r.rank})`))),
  h("button", { class: "btn btn--sm", type: "submit" }, "Vergeben")) : null);
  const tabelle = h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Recht"), h("th", {}, "Ergebnis"),
    h("th", { class: "opt" }, "Quelle"), darf("users.override") && !selbst ? h("th", {}, "Einzelrecht") : null)),
  h("tbody", {}, rechte.permissions.map((r) => h("tr", {},
    h("td", {}, h("span", { class: "code" }, r.permission)),
    h("td", {}, h("span", { class: `tag${r.granted ? "" : " tag--muted"}` }, r.granted ? "darf" : "darf nicht")),
    h("td", { class: "opt" }, QUELLE[r.decided_by] || r.decided_by, r.roles.length ? h("div", { class: "src" }, r.roles.map((x) => x.name).join(", ")) : null),
    darf("users.override") && !selbst ? h("td", {}, einzelrecht(ref, r.permission, rechte.overrides[r.permission], neu)) : null)))));
  ersetze(el, kopf, hinweis, rollenKarte, h("section", { class: "card" }, h("h2", {}, "Was diese Person darf"),
    h("p", { class: "muted small" }, "Berechnet wie bei jeder Anfrage: Modul-Schalter → Einzelverbot → Einzelerlaubnis → Rolle."), tabelle));
}

function einzelrecht(ref, recht, wert, neu) {
  const s = h("select", { class: "input", "aria-label": `Einzelrecht ${recht}` },
    [["", "geerbt"], ["allow", "erlauben"], ["deny", "verbieten"]].map(([k, v]) => h("option", { value: k, selected: (wert || "") === k }, v)));
  s.addEventListener("change", () => aktion(() => (s.value ? put(`/members/${ref}/overrides/${recht}`, { effect: s.value })
    : del(`/members/${ref}/overrides/${recht}`)), neu));
  return s;
}
