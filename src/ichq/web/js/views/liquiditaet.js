// Liquidität: keine Bankanbindung — Stände sind manuell erfasst (Stichtag, wer), alles Weitere ist als Schätzung
// gekennzeichnet und mit Herkunft verlinkt. Die Rechnung macht der Server; hier wird nur angezeigt.
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, patch, post, query } from "../api.js";
import { darf } from "../state.js";
import { auswahl, cent, eingabe, Eingabefehler, feld, fehlertext, geld, seitenkopf, tabelle, zelle } from "./bausteine.js";

const ZIEL = { invoice: "#/rechnungen/", receipt: "#/belege/", payment: null, forecast: null };
const HERKUNFT = { invoice: "Rechnung", receipt: "Ausgabe", payment: "Zahlungseingang", forecast: "Planposten" };
const heute = () => new Date().toISOString().slice(0, 10);

function kennzahl(wert, text, art) {
  return h("div", { class: `metric${art ? ` metric--${art}` : ""}` }, h("span", { class: "metric-value" }, wert), h("span", { class: "metric-label" }, text));
}

function posten(liste, w, leer) {
  const zeilen = liste.items.map((x) => h("tr", {},
    zelle(ZIEL[x.type] ? h("a", { href: `${ZIEL[x.type]}${x.id}` }, x.title) : x.title),
    zelle(HERKUNFT[x.type], true),
    zelle([datum(x.due_date || x.date), x.overdue ? h("span", { class: "tag tag--danger" }, " überfällig") : null]),
    zelle(geld(x.amount_minor, w))));
  const mehr = liste.count > liste.items.length ? h("p", { class: "muted small" }, `… und ${liste.count - liste.items.length} weitere`) : null;
  return [tabelle([{ text: "Posten" }, { text: "Herkunft", opt: true }, { text: "Fällig" }, { text: "Betrag" }], zeilen, leer), mehr];
}

export async function seite(el, _p, q) {
  const bucket = q.get("bucket") === "month" ? "month" : "week";
  const horizont = q.get("horizon") || "90";
  const [u, konten, plan] = await Promise.all([get(`/liquidity${query({ horizon_days: horizont, bucket })}`),
    get("/liquidity/accounts"), get("/liquidity/forecasts")]);
  const neu = () => seite(el, _p, q);
  const w = u.currency;
  const m = u.manual;
  const hinweise = [alertBox("Keine Bankanbindung: Kontostände sind manuell erfasst. „Geschätzt heute“ = letzte erfasste Stände + seither in HQ erfasste Ein- und Auszahlungen.", "info")];
  if (!m.accounts.length) hinweise.push(alertBox("Noch kein Kontostand erfasst — ohne Stand gibt es keine Schätzung, nur erwartete Bewegungen.", "info"));
  if (m.dates_differ) hinweise.push(alertBox(`Die Stände haben unterschiedliche Stichtage (ältester ${datum(m.oldest_as_of)}). Bewegungen werden ab dem ältesten gezählt — die Schätzung ist unscharf.`, "error"));
  if (m.accounts_without_balance.length) hinweise.push(alertBox(`Ohne Stand: ${m.accounts_without_balance.map((a) => a.name).join(", ")}.`, "info"));
  if (u.hidden_items) hinweise.push(alertBox(`${u.hidden_items} Posten sind für dich nicht sichtbar und fehlen in dieser Übersicht.`, "error"));
  if (u.other_currencies.length) hinweise.push(alertBox(`Nicht umgerechnet (kein Kurs): ${u.other_currencies.map((x) => `${x.open_items} × ${x.currency}`).join(", ")}.`, "info"));
  const e = u.expected;
  const ende = u.timeline.length ? u.timeline[u.timeline.length - 1].balance_minor : u.estimated_today_minor;
  const leiste = h("form", { class: "row", "aria-label": "Zeitraum" },
    auswahl("bucket", { week: "je Woche", month: "je Monat" }, bucket, undefined, { "aria-label": "Einteilung" }),
    auswahl("horizon", { 30: "30 Tage", 90: "90 Tage", 180: "180 Tage", 365: "365 Tage" }, horizont, undefined, { "aria-label": "Horizont" }));
  leiste.addEventListener("change", () => { const d = new FormData(leiste); location.hash = `#/liquiditaet${query({ bucket: d.get("bucket"), horizon: d.get("horizon") })}`; });
  ersetze(el, seitenkopf("Liquidität"), ...hinweise,
    h("section", { class: "card" }, h("div", { class: "metrics" },
      kennzahl(geld(m.total_minor, w), m.accounts.length ? `manuelle Stände (ab ${datum(m.oldest_as_of)})` : "kein Stand erfasst"),
      kennzahl(geld(u.recorded.inflows.total_minor, w), "seither eingegangen (erfasst)"),
      kennzahl(geld(u.recorded.outflows.total_minor, w), "seither bezahlt (erfasst)"),
      kennzahl(geld(u.estimated_today_minor, w), "geschätzt heute", u.estimated_today_minor < 0 ? "danger" : null),
      kennzahl(geld(ende, w), `geschätzt am ${datum(u.horizon_end)}`, ende < 0 ? "danger" : null))),
    h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Verlauf (geschätzt)"), leiste),
      tabelle([{ text: "Zeitraum" }, { text: "Ein", opt: true }, { text: "Aus", opt: true }, { text: "Stand" }],
        u.timeline.map((z) => h("tr", { class: z.balance_minor < 0 ? "witem--danger" : null }, zelle(`${datum(z.from)} – ${datum(z.to)}`),
          zelle(geld(z.inflow_minor, w), true), zelle(geld(z.outflow_minor, w), true), zelle(geld(z.balance_minor, w)))))),
    h("section", { class: "card" }, h("h2", {}, `Offene Forderungen · ${geld(e.receivables.total_minor, w)}`), posten(e.receivables, w, "Keine offenen Forderungen im Zeitraum.")),
    h("section", { class: "card" }, h("h2", {}, `Unbezahlte Ausgaben · ${geld(e.payables.total_minor, w)}`), posten(e.payables, w, "Keine unbezahlten Ausgaben im Zeitraum.")),
    kontenKarte(konten.items, neu), planKarte(plan.items, neu));
}

function kontenKarte(konten, neu) {
  const schreiben = darf("finance.update");
  const anlegen = schreiben ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Konto anlegen", [feld("Name", eingabe("name", "", { required: true, maxlength: 100, placeholder: "z. B. Geschäftskonto Sparkasse" })),
      feld("Art", auswahl("kind", { bank: "Bankkonto", cash: "Kasse", other: "Sonstiges" }, "bank"))], "Anlegen");
    if (!d) return;
    try { await post("/liquidity/accounts", d); toast("Konto angelegt."); neu(); } catch (e) { toast(meldung(e), "error"); }
  }) } }, "Konto anlegen") : null;
  const zeilen = konten.map((k) => {
    const b = k.latest_balance;
    const stand = schreiben ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(() => standErfassen(k, neu)) } }, "Stand erfassen") : null;
    return h("tr", {}, zelle(k.name), zelle(b ? geld(b.balance_minor, k.currency) : "kein Stand"),
      zelle(b ? `${datum(b.as_of)} · ${b.recorded_by ? b.recorded_by.display_name : "—"}` : "—", true), zelle(stand));
  });
  return h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Konten (manuelle Stände)"), anlegen),
    tabelle([{ text: "Konto" }, { text: "Stand" }, { text: "Stichtag · erfasst von", opt: true }, { text: "" }], zeilen, "Noch kein Konto angelegt."));
}

async function standErfassen(k, neu) {
  const d = await dialog(`Kontostand ${k.name}`, [h("p", { class: "small" }, "Stand laut Kontoauszug. Ein erfasster Stand wird nie geändert — bei einem Fehler einfach einen neuen erfassen."),
    feld("Stichtag", eingabe("as_of", heute(), { type: "date", required: true, max: heute() })),
    feld("Kontostand (€, negativ = Soll)", eingabe("betrag", "", { required: true, inputmode: "decimal" })),
    feld("Notiz", eingabe("note", "", { maxlength: 300, placeholder: "z. B. Auszug Nr. 42" }))], "Erfassen");
  if (!d) return;
  try {
    const betrag = cent(d.betrag);
    if (betrag === null) throw new Eingabefehler("Betrag ungültig (z. B. 1.250,00 oder -80,00)");
    await post(`/liquidity/accounts/${k.id}/balances`, { as_of: d.as_of, balance_minor: betrag, note: d.note || "" });
    toast("Stand erfasst."); neu();
  } catch (e) { toast(fehlertext(e), "error"); }
}

function planKarte(plan, neu) {
  const schreiben = darf("finance.update");
  const anlegen = schreiben ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
    const d = await dialog("Planposten anlegen", [h("p", { class: "small" }, "Für erwartete Zahlungen, die noch nicht als Rechnung oder Ausgabe erfasst sind (z. B. Steuervorauszahlung, Förderung)."),
      feld("Bezeichnung", eingabe("label", "", { required: true, maxlength: 200 })),
      feld("Erwartet am", eingabe("expected_on", "", { type: "date", required: true })),
      feld("Betrag (€, + Einzahlung / − Auszahlung)", eingabe("betrag", "", { required: true, inputmode: "decimal" })),
      feld("Kategorie", eingabe("category", "", { maxlength: 60 }))], "Anlegen");
    if (!d) return;
    try {
      const betrag = cent(d.betrag);
      if (!betrag) throw new Eingabefehler("Betrag ungültig oder 0");
      await post("/liquidity/forecasts", { label: d.label, expected_on: d.expected_on, amount_minor: betrag, category: d.category || null });
      toast("Planposten angelegt."); neu();
    } catch (e) { toast(fehlertext(e), "error"); }
  }) } }, "Planposten anlegen") : null;
  const setze = (f, status) => einmal(async () => {
    try { await patch(`/liquidity/forecasts/${f.id}`, { status }); toast(status === "done" ? "Als erledigt markiert." : "Abgesagt."); neu(); } catch (e) { toast(meldung(e), "error"); }
  });
  const zeilen = plan.map((f) => h("tr", {}, zelle(f.label), zelle(datum(f.expected_on)), zelle(geld(f.amount_minor, f.currency)),
    zelle(schreiben ? h("span", { class: "row" }, h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: setze(f, "done") } }, "erledigt"),
      h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: setze(f, "cancelled") } }, "absagen")) : null)));
  return h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Planposten (Prognose)"), anlegen),
    tabelle([{ text: "Bezeichnung" }, { text: "Erwartet" }, { text: "Betrag" }, { text: "" }], zeilen, "Keine offenen Planposten."),
    h("p", { class: "muted small" }, `Stand der Übersicht: ${zeit(new Date().toISOString())}`));
}
