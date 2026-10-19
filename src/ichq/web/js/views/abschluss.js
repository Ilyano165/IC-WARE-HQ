// Monatsabschluss & Export: Prüfliste, abschließen (Warnungen bestätigen), wiedereröffnen mit Grund, Export-Historie.
// Die Sperre sitzt in der Datenbank; die Oberfläche zeigt nur an. Kein DATEV-Format — das steht auch so da.
import { alertBox, datum, dialog, einmal, ersetze, h, toast, zeit } from "../dom.js";
import { get, meldung, post, query } from "../api.js";
import { darf } from "../state.js";
import { auswahl, eingabe, feld, seitenkopf, tabelle, zelle } from "./bausteine.js";

const MONATE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const ZAHL = { receipts: "Ausgaben", receipts_missing_evidence: "davon ohne geprüften Beleg", invoices_issued: "Rechnungen ausgestellt",
  payments: "Zahlungseingänge", invoice_drafts_total: "Rechnungsentwürfe (gesamt)", documents_unchecked: "Dokumente in Prüfung (gesamt)" };

export async function seite(el, _p, q) {
  const jahr = Number(q.get("jahr")) || new Date().getFullYear();
  const vor = new Date(); vor.setDate(1); vor.setMonth(vor.getMonth() - 1);
  const monat = q.get("monat") || `${vor.getFullYear()}-${String(vor.getMonth() + 1).padStart(2, "0")}`;
  const [jahrDaten, p, exporte] = await Promise.all([get(`/periods${query({ year: jahr })}`), get(`/periods/check${query({ month: monat })}`),
    darf("finance.export") ? get("/exports") : Promise.resolve(null)]);
  const neu = () => seite(el, _p, q);
  const kacheln = h("div", { class: "metrics" }, jahrDaten.items.map((m, i) => h("a", { class: `metric${m.period === monat ? " metric--warn" : ""}`,
    href: `#/abschluss${query({ jahr, monat: m.period })}` }, h("span", { class: "metric-value" }, MONATE[i]),
    h("span", { class: "metric-label" }, m.closed ? `abgeschlossen${m.reopen_count ? ` · ${m.reopen_count}× wiedereröffnet` : ""}` : "offen"))));
  const jahrWahl = h("form", { class: "row", "aria-label": "Jahr" }, auswahl("jahr", Object.fromEntries([jahr - 1, jahr, jahr + 1].map((j) => [j, String(j)])), String(jahr), undefined, { "aria-label": "Jahr" }));
  jahrWahl.addEventListener("change", () => { location.hash = `#/abschluss${query({ jahr: new FormData(jahrWahl).get("jahr") })}`; });
  ersetze(el, seitenkopf("Abschluss & Export"),
    h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, "Monate"), jahrWahl), kacheln),
    monatKarte(p, neu), exporte ? exportKarte(exporte.items, neu) : null);
}

function monatKarte(p, neu) {
  const zahlen = h("ul", { class: "list" }, Object.entries(ZAHL).map(([k, t]) => h("li", {}, `${t}: ${p.counts[k]}`)));
  const warn = p.warnings.length ? alertBox(`Offene Punkte: ${p.warnings.map((w) => `${w.count} ${w.text}`).join(" · ")}`, "error") : alertBox("Keine offenen Punkte gefunden.", "ok");
  const darfAbschluss = darf("finance.approve");
  const knopf = !darfAbschluss ? null : p.closed
    ? h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
      const d = await dialog(`${p.period} wiedereröffnen?`, [h("p", { class: "small" }, "Danach sind Änderungen in diesem Monat wieder möglich. Der Grund wird protokolliert."),
        feld("Grund", eingabe("reason", "", { required: true, minlength: 10, maxlength: 500 }))], "Wiedereröffnen", true);
      if (!d) return;
      try { await post("/periods/reopen", { month: p.period, reason: d.reason }); toast("Monat wiedereröffnet."); neu(); } catch (e) { toast(meldung(e), "error"); }
    }) } }, "Wiedereröffnen")
    : h("button", { class: "btn btn--sm", type: "button", on: { click: einmal(async () => {
      const d = await dialog(`${p.period} abschließen?`, [h("p", { class: "small" }, "Danach sind Rechnungsdaten, Zahlungen und Ausgaben dieses Monats gesperrt — auch in der Datenbank. Belege nachreichen bleibt möglich."),
        p.warnings.length ? h("label", { class: "check" }, h("input", { type: "checkbox", name: "confirm_warnings", value: "true", required: true }), " Offene Punkte gesehen — trotzdem abschließen") : null,
        feld("Notiz", eingabe("note", "", { maxlength: 500 }))], "Abschließen");
      if (!d) return;
      try { await post("/periods/close", { month: p.period, note: d.note || "", confirm_warnings: d.confirm_warnings === "true" }); toast("Monat abgeschlossen."); neu(); } catch (e) { toast(meldung(e), "error"); }
    }) } }, "Monat abschließen");
  const historie = p.history.map((m) => h("li", { class: "small" }, `Abgeschlossen ${zeit(m.closed_at)} von ${m.closed_by ? m.closed_by.display_name : "—"}`,
    m.reopened_at ? ` · wiedereröffnet ${zeit(m.reopened_at)} von ${m.reopened_by ? m.reopened_by.display_name : "—"}: ${m.reopen_reason}` : ""));
  return h("section", { class: "card" }, h("div", { class: "row row--between" }, h("h2", {}, `Monat ${p.period}`),
    h("span", { class: p.closed ? "tag" : "tag tag--muted" }, p.closed ? "abgeschlossen" : "offen"), knopf),
    warn, zahlen, historie.length ? h("ul", { class: "list" }, historie) : null);
}

function exportKarte(liste, neu) {
  const heute = new Date().toISOString().slice(0, 10);
  const form = h("form", { class: "row" }, feld("Von", eingabe("period_from", `${heute.slice(0, 8)}01`, { type: "date", required: true })),
    feld("Bis", eingabe("period_to", heute, { type: "date", required: true })), h("button", { class: "btn btn--sm", type: "submit" }, "Export erstellen"));
  form.addEventListener("submit", einmal(async () => {
    const d = Object.fromEntries(new FormData(form).entries());
    try { const e = await post("/exports", d); toast(`Export mit ${e.row_count} Zeilen erstellt.`); neu(); } catch (e) { toast(meldung(e), "error"); }
  }));
  const zeilen = liste.map((e) => h("tr", {}, zelle(`${datum(e.period_from)} – ${datum(e.period_to)}`), zelle(zeit(e.created_at), true),
    zelle(String(e.row_count)), zelle(e.report.findings.length ? h("span", { class: "tag tag--warn" }, `${e.report.findings.length} Hinweise`) : h("span", { class: "tag" }, "ohne Hinweise")),
    zelle(h("span", { class: "row" }, h("a", { class: "btn btn--ghost btn--sm", href: `/api/v1/exports/${e.id}/download`, download: "" }, "CSV"),
      h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: einmal(async () => {
        try { const r = await post(`/exports/${e.id}/repeat`); toast(r.report.changed_since_original ? "Neu exportiert — die Daten haben sich seitdem geändert." : "Neu exportiert — unverändert."); neu(); } catch (x) { toast(meldung(x), "error"); }
      }) } }, "Wiederholen")))));
  return h("section", { class: "card" }, h("h2", {}, "Export für den Steuerberater"),
    alertBox("Internes CSV-Format (ichq-buchungen-v1, siehe Doku) — kein DATEV-Format und mit keinem Importprogramm getestet.", "info"),
    form, tabelle([{ text: "Zeitraum" }, { text: "Erstellt", opt: true }, { text: "Zeilen" }, { text: "Prüfung" }, { text: "" }], zeilen, "Noch kein Export erstellt."));
}
