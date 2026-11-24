// Unternehmensverwaltung (ADR-021) — nur für Betreiber der Installation. Der Server prüft jede Anfrage (Marke
// `operator`); die Oberfläche blendet nur aus. Betreiber haben in einer Firma KEINE Rechte, solange sie dort nicht
// Mitglied sind — deshalb gibt es hier nur Verwaltungsdaten (Status, Module, Administratoren), keine Firmendaten.
import { alertBox, dialog, einmal, ersetze, feld, h, toast, zeit } from "../dom.js";
import { ApiError, get, meldung, patch, post, put, query } from "../api.js";
import { gehe } from "../router.js";
import { auswahl, eingabe, filterleiste, seitenkopf, speichern, tabelle, zelle } from "./bausteine.js";
import { assistent, SchrittFehler, SPRACHEN, WAEHRUNGEN, ZEITZONEN, zusammenfassung } from "./assistent.js";

const STATUS = { active: "aktiv", paused: "pausiert", suspended: "gesperrt", pending: "angelegt", deactivated: "deaktiviert" };
const AKTION = { active: "Aktivieren", paused: "Pausieren", suspended: "Sperren", deactivated: "Deaktivieren" };
const WIRKUNG = { active: "Mitglieder können wieder normal arbeiten.", paused: "Nur noch Lesen — niemand kann etwas ändern.",
  suspended: "Niemand kann sich in dieser Firma anmelden. Die Daten bleiben erhalten.",
  deactivated: "Endgültig: die Firma lässt sich danach NICHT wieder aktivieren. Die Daten bleiben erhalten (Aufbewahrungspflichten)." };
export const MODULE = { customers: "Kunden & Anfragen", projects: "Projekte & Zeiten", invoices: "Rechnungen", finance: "Belege, Liquidität, Fristen, Abschluss",
  contracts: "Verträge", travel: "Dienstreisen", vehicles: "Fahrtenbuch", tasks: "Aufgaben", files: "Dokumente", comments: "Kommentare",
  dashboard: "Übersicht", activity: "Aktivität", objects: "Verknüpfungen & Freigaben",
  calendar: "Kalender (noch nicht gebaut)", chat: "Chat (noch nicht gebaut)", hospitality: "Gastronomie (noch nicht gebaut)", suppliers: "Lieferanten (noch nicht gebaut)" };
const GEPLANT = new Set(["calendar", "chat", "hospitality", "suppliers"]);
const tag = (s) => h("span", { class: `tag${s === "active" ? "" : s === "paused" || s === "pending" ? " tag--warn" : s === "suspended" ? " tag--danger" : " tag--muted"}` }, STATUS[s] || s);

export async function liste(el, _p, q) {
  const filter = { status: q.get("status") || "", q: q.get("q") || "" };
  const offset = Number(q.get("offset") || 0);
  const d = await get(`/platform/companies${query({ ...filter, offset: offset || undefined, limit: 50 })}`);
  const zaehler = Object.fromEntries(Object.entries(STATUS).map(([k, v]) => [k, `${v} (${d.counts[k] || 0})`]));
  const leiste = filterleiste("/plattform/firmen", [auswahl("status", zaehler, filter.status, "Alle Zustände", { "aria-label": "Zustand" }),
    eingabe("q", filter.q, { class: "input", type: "search", placeholder: "Name oder Kürzel", "aria-label": "Firmen suchen", maxlength: 100 })]);
  const zeilen = d.items.map((f) => h("tr", {}, zelle(h("a", { href: `#/plattform/firmen/${encodeURIComponent(f.slug)}` }, f.name)),
    zelle(f.slug, true), zelle(f.legal_name || "—", true), zelle(zeit(f.created_at), true), zelle(tag(f.status))));
  ersetze(el, seitenkopf("Firmen verwalten", null, h("a", { class: "btn", href: "#/plattform/neue-firma" }, "Firma anlegen")),
    h("p", { class: "muted small" }, "Firmen dieser Installation. Als Betreiber sehen Sie Verwaltungsdaten — Inhalte einer Firma nur als deren Mitglied."),
    leiste, h("br"),
    tabelle([{ text: "Firma" }, { text: "Kürzel", opt: true }, { text: "Rechtlicher Name", opt: true }, { text: "Angelegt", opt: true }, { text: "Zustand" }],
      zeilen, filter.q || filter.status ? "Keine Firma passt zum Filter." : "Noch keine Firma."),
    d.next_offset ? h("div", { class: "row row--end" }, h("a", { class: "btn btn--ghost btn--sm", href: `#/plattform/firmen${query({ ...filter, offset: d.next_offset })}` }, "Weitere")) : null);
}

function modulFelder(aus) {
  return h("fieldset", { class: "stack" }, h("legend", {}, "Module"), h("p", { class: "small muted" }, "Abgewählte Module sind für die Firma gesperrt — der Server lehnt ihre Anfragen ab. Kernmodule (Mitglieder, Rollen, Firma, Audit) sind immer an."),
    h("div", { class: "grid2" }, Object.entries(MODULE).map(([k, v]) => h("label", { class: "check" },
      h("input", { type: "checkbox", name: "an[]", value: k, checked: !aus.includes(k) }), v))));
}

export function neu(el) {
  const box = h("div", { class: "card" });
  ersetze(el, seitenkopf("Firma anlegen", { href: "#/plattform/firmen", text: "Firmen verwalten" }), box);
  const d = { timezone: "Europe/Berlin", currency: "EUR", language: "de", mode: "self", an: Object.keys(MODULE).filter((k) => !GEPLANT.has(k)) };
  assistent(box, [
    { titel: "Firma", felder: (x) => {
      const slug = eingabe("slug", x.slug, { class: "input", required: true, minlength: 3, maxlength: 48, pattern: "[a-z0-9][a-z0-9\\-]{1,46}[a-z0-9]" });
      const name = eingabe("name", x.name, { class: "input", required: true, maxlength: 120, autocomplete: "off" });
      let timer;
      name.addEventListener("input", () => { if (slug.dataset.selbst) return; clearTimeout(timer); timer = setTimeout(async () => {
        if (name.value.trim()) try { slug.value = (await get(`/platform/slug-suggestion${query({ name: name.value.trim() })}`)).slug; } catch { /* Vorschlag ist nur Hilfe */ }
      }, 250); });
      slug.addEventListener("input", () => { slug.dataset.selbst = "1"; });
      if (x.slug) slug.dataset.selbst = "1";
      return [feld("Name der Firma", name), feld("Rechtlicher Name (optional)", eingabe("legal_name", x.legal_name, { class: "input", maxlength: 200 })),
        feld("Kürzel", slug, "Vorschlag aus dem Namen, schon auf Eindeutigkeit geprüft. Später nicht änderbar.")];
    } },
    { titel: "Einstellungen", felder: (x) => [h("div", { class: "grid2" }, feld("Zeitzone", auswahl("timezone", ZEITZONEN, x.timezone)),
      feld("Währung", auswahl("currency", WAEHRUNGEN, x.currency)), feld("Sprache", auswahl("language", SPRACHEN, x.language))),
    modulFelder(Object.keys(MODULE).filter((k) => !x.an.includes(k)))] },
    { titel: "Administrator", felder: (x) => {
      const art = (wert, text_, hinweis) => h("label", { class: "check" }, h("input", { type: "radio", name: "mode", value: wert, checked: x.mode === wert,
        on: { change: () => zeigeFelder(wert) } }), h("span", {}, h("b", {}, text_), h("div", { class: "small muted" }, hinweis)));
      const mail = feld("E-Mail", eingabe("email", x.email, { class: "input", type: "email", maxlength: 254, autocomplete: "off" }));
      const neuKonto = h("div", {}, feld("Name", eingabe("admin_name", x.admin_name, { class: "input", maxlength: 120 })),
        feld("Startpasswort", eingabe("password", "", { class: "input", type: "password", minlength: 12, maxlength: 512, autocomplete: "new-password" }),
          "Mindestens 12 Zeichen. Sicher weitergeben; die Person sollte es nach der ersten Anmeldung ändern und 2FA einschalten."));
      const zeigeFelder = (m) => {
        mail.hidden = m === "self"; neuKonto.hidden = m !== "new";
        mail.querySelector("input").required = m !== "self";
        for (const i of neuKonto.querySelectorAll("input")) i.required = m === "new";
      };
      queueMicrotask(() => zeigeFelder(x.mode));
      return [h("div", { class: "stack", role: "radiogroup", "aria-label": "Administrator" },
        art("self", "Ich selbst", "Ihr Konto wird Company Admin dieser Firma."),
        art("existing", "Bestehendes Konto", "Eine Person, die schon ein HQ-Konto hat (z. B. aus einer anderen Firma)."),
        art("new", "Neues Konto", "Konto mit Startpasswort anlegen.")), mail, neuKonto];
    },
    pruefe: async (x) => {
      if (x.mode === "existing") {
        const k = await get(`/platform/accounts${query({ email: x.email })}`);
        if (!k.exists || !k.active) throw new SchrittFehler("Für diese E-Mail gibt es kein aktives Konto — „Neues Konto“ wählen.", 2);
        x.konto = k.display_name;
      }
      if (x.mode === "new") {
        const k = await get(`/platform/accounts${query({ email: x.email })}`);
        if (k.exists) throw new SchrittFehler("Für diese E-Mail gibt es bereits ein Konto — „Bestehendes Konto“ wählen.", 2);
      }
    } },
    { titel: "Prüfen", knopf: "Firma anlegen", felder: (x) => [zusammenfassung([["Firma", x.name], ["Rechtlicher Name", x.legal_name], ["Kürzel", x.slug],
      ["Zeitzone", ZEITZONEN[x.timezone]], ["Währung", WAEHRUNGEN[x.currency]], ["Sprache", SPRACHEN[x.language]],
      ["Module aus", Object.keys(MODULE).filter((k) => !x.an.includes(k)).map((k) => MODULE[k]).join(", ") || "keine"],
      ["Administrator", x.mode === "self" ? "ich selbst" : x.mode === "existing" ? `${x.konto || ""} <${x.email}>` : `${x.admin_name} <${x.email}> (neues Konto)`]]),
    h("p", { class: "small muted" }, "Die Firma ist sofort aktiv; Rollenvorlagen (Geschäftsführung, Mitarbeiter, Steuerberater …) werden angelegt.")] },
  ], async (x) => {
    const admin = x.mode === "self" ? { mode: "self" } : x.mode === "existing" ? { mode: "existing", email: x.email }
      : { mode: "new", email: x.email, name: x.admin_name, password: x.password };
    try {
      const f = await post("/platform/companies", { company: { name: x.name, slug: x.slug, legal_name: x.legal_name || null, timezone: x.timezone,
        currency: x.currency, language: x.language, modules_off: Object.keys(MODULE).filter((k) => !x.an.includes(k)) }, admin });
      toast(`Firma „${f.name}“ angelegt.`);
      gehe(`/plattform/firmen/${encodeURIComponent(f.slug)}`);
    } catch (e) {
      if (e instanceof ApiError && /Kürzel|slug/i.test(e.message)) throw new SchrittFehler(e.message.replace(/^slug/, "Kürzel"), 0);
      if (e instanceof ApiError && /Passwort|Konto/.test(e.message)) throw new SchrittFehler(e.message, 2);
      throw e;
    }
  }, d);
}

export async function detail(el, { slug }) {
  const f = await get(`/platform/companies/${encodeURIComponent(slug)}`);
  const neuLaden = () => detail(el, { slug });
  const basis = `/platform/companies/${encodeURIComponent(slug)}`;
  const aktiv = f.status !== "deactivated";
  const fehler = h("div");
  const stamm = aktiv ? speichern(h("form", { class: "stack" }, fehler,
    feld("Name", eingabe("name", f.name, { class: "input", required: true, maxlength: 120 })),
    feld("Rechtlicher Name", eingabe("legal_name", f.legal_name, { class: "input", maxlength: 200 })),
    h("div", { class: "grid2" }, feld("Zeitzone", auswahl("timezone", { ...ZEITZONEN, [f.timezone]: ZEITZONEN[f.timezone] || f.timezone }, f.timezone)),
      feld("Währung", auswahl("currency", { ...WAEHRUNGEN, [f.currency]: WAEHRUNGEN[f.currency] || f.currency }, f.currency)),
      feld("Sprache", auswahl("language", SPRACHEN, f.language))),
    h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern"))), fehler, async (d) => {
    await patch(basis, { ...d, legal_name: d.legal_name || null }); toast("Gespeichert."); neuLaden();
  }) : h("p", { class: "muted" }, "Deaktiviert — Stammdaten sind nicht mehr änderbar.");
  const status = f.next_status.map((s) => h("button", { class: `btn btn--sm${s === "deactivated" ? " btn--danger" : s === "active" ? "" : " btn--ghost"}`, type: "button",
    on: { click: einmal(async () => {
      const d = await dialog(`${AKTION[s]}: ${f.name}`, [alertBox(WIRKUNG[s], s === "deactivated" ? "error" : "info"),
        feld("Begründung (steht im Plattform-Audit)", eingabe("reason", "", { class: "input", required: true, minlength: 3, maxlength: 500 })),
        s === "deactivated" ? feld(`Zur Bestätigung das Kürzel „${f.slug}“ eingeben`, eingabe("bestaetigung", "", { class: "input", required: true, pattern: f.slug, autocomplete: "off" })) : null],
      AKTION[s], s === "deactivated");
      if (!d) return;
      try { await post(`${basis}/status`, { status: s, reason: d.reason }); toast(`${STATUS[s]}.`); neuLaden(); } catch (e) { toast(meldung(e), "error"); }
    }) } }, AKTION[s]));
  const module = h("div", { class: "grid2" }, f.modules.map((m) => h("label", { class: "check" },
    h("input", { type: "checkbox", checked: m.enabled, disabled: !aktiv, on: { change: async (e) => {
      const an = e.target.checked;
      const d = await dialog(`${MODULE[m.module] || m.module} ${an ? "einschalten" : "ausschalten"}`,
        [feld("Begründung", eingabe("reason", "", { class: "input", required: true, minlength: 3, maxlength: 500 }))], an ? "Einschalten" : "Ausschalten", !an);
      if (!d) { e.target.checked = !an; return; }
      try { await put(`${basis}/modules/${m.module}`, { enabled: an, reason: d.reason }); toast("Gespeichert."); } catch (err) { e.target.checked = !an; toast(meldung(err), "error"); }
    } } }), MODULE[m.module] || m.module)));
  const zuweisen = ["active", "paused"].includes(f.status) ? h("form", { class: "row", on: { submit: einmal(async (e) => {
    const email = new FormData(e.target).get("email");
    try { const r = await post(`${basis}/admins`, { email }); toast(r.assigned ? `${r.email} ist jetzt Administrator.` : `${r.email} war schon Administrator.`); neuLaden(); } catch (err) { toast(meldung(err), "error"); }
  }) } }, eingabe("email", "", { class: "input", type: "email", required: true, maxlength: 254, placeholder: "E-Mail eines bestehenden Kontos", "aria-label": "E-Mail des neuen Administrators" }),
  h("button", { class: "btn btn--sm", type: "submit" }, "Als Administrator zuweisen")) : null;
  ersetze(el, seitenkopf(f.name, { href: "#/plattform/firmen", text: "Firmen verwalten" }, tag(f.status)),
    f.admins.length ? null : alertBox("Diese Firma hat keinen Administrator. Bitte einen zuweisen.", "error"),
    h("section", { class: "card" }, h("h2", {}, "Zustand"), h("p", {}, `${f.status_text} · Kürzel ${f.slug} · angelegt ${zeit(f.created_at)} · ${f.members} aktive Mitglieder`),
      h("div", { class: "row" }, status.length ? status : h("span", { class: "muted small" }, "Keine weiteren Übergänge."))),
    h("section", { class: "card" }, h("h2", {}, "Administratoren"),
      f.admins.length ? h("ul", { class: "list" }, f.admins.map((a) => h("li", {}, `${a.display_name} <${a.email}>`))) : h("p", { class: "empty" }, "Keiner."),
      h("p", { class: "small muted" }, "Zuweisen macht ein bestehendes Konto zum Company Admin — auch Ihr eigenes. Jede Zuweisung steht im Plattform-Audit."), zuweisen),
    h("section", { class: "card" }, h("h2", {}, "Stammdaten"), stamm),
    h("section", { class: "card" }, h("h2", {}, "Module"), module),
    h("section", { class: "card" }, h("h2", {}, "Verlauf"), f.history.length ? h("ul", { class: "list" }, f.history.map((v) =>
      h("li", { class: "small" }, `${zeit(v.occurred_at)} · ${v.action} · ${v.actor}${v.reason ? ` · „${v.reason}“` : ""}`))) : h("p", { class: "empty" }, "Kein Eintrag.")));
}

export async function betreiber(el) {
  const d = await get("/platform/operators");
  const neuLaden = () => betreiber(el);
  const zeilen = d.items.map((o) => h("tr", {}, zelle(`${o.display_name}${o.me ? " (Sie)" : ""}`), zelle(o.email, true), zelle(zeit(o.since), true),
    zelle(h("button", { class: "btn btn--ghost btn--sm", type: "button", disabled: d.items.length === 1, title: d.items.length === 1 ? "Der letzte Betreiber kann nicht entfernt werden" : null,
      on: { click: einmal(async () => {
        if (!await dialog("Betreiber entfernen", [h("p", {}, `${o.email} kann danach keine Firmen mehr verwalten.${o.me ? " Das betrifft Sie selbst — die Verwaltung schließt sich sofort." : ""}`)], "Entfernen", true)) return;
        try { await post("/platform/operators/remove", { email: o.email }); toast("Entfernt."); if (o.me) location.reload(); else neuLaden(); } catch (e) { toast(meldung(e), "error"); }
      }) } }, "Entfernen"))));
  const form = h("form", { class: "row", on: { submit: einmal(async (e) => {
    try { const r = await post("/platform/operators", { email: new FormData(e.target).get("email") }); toast(r.added ? `${r.email} ist jetzt Betreiber.` : `${r.email} war schon Betreiber.`); neuLaden(); } catch (err) { toast(meldung(err), "error"); }
  }) } }, eingabe("email", "", { class: "input", type: "email", required: true, maxlength: 254, placeholder: "E-Mail eines bestehenden Kontos", "aria-label": "E-Mail des neuen Betreibers" }),
  h("button", { class: "btn btn--sm", type: "submit" }, "Hinzufügen"));
  ersetze(el, seitenkopf("Betreiber", { href: "#/plattform/firmen", text: "Firmen verwalten" }),
    alertBox("Betreiber legen Firmen an und verwalten sie. Sie sehen keine Inhalte einer Firma, können sich aber selbst als Administrator zuweisen — nur vertrauenswürdige Personen, mit 2FA.", "info"),
    h("section", { class: "card" }, tabelle([{ text: "Name" }, { text: "E-Mail", opt: true }, { text: "Seit", opt: true }, { text: "" }], zeilen), h("br"), form));
}
