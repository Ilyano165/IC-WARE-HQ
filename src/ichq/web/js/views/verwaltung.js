// Firmenprofil (M3), Aktivitätsverlauf und Audit (C0) — lesen; Audit-Export als CSV mit audit.export.
import { alertBox, ersetze, feld, h, toast, zeit } from "../dom.js";
import { get, meldung, patch, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";

export async function firma(el) {
  const f = await get("/company");
  const kann = darf("company.update") && f.status === "active";
  const fehler = h("div");
  const eingabe = (name, extra = {}) => h("input", { name, value: f[name] || "", disabled: !kann, ...extra });
  const form = h("form", { class: "stack" }, fehler,
    h("div", { class: "grid2" }, feld("Name", eingabe("name", { required: true, maxlength: 120 })),
      feld("Rechtlicher Name", eingabe("legal_name", { maxlength: 200 })),
      feld("Zeitzone", eingabe("timezone", { required: true, maxlength: 64 })),
      feld("Sprache", eingabe("language", { required: true, maxlength: 8 })),
      feld("Währung", eingabe("currency", { required: true, minlength: 3, maxlength: 3 }))),
    kann ? h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern")) : null);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(form).entries());
    d.legal_name = d.legal_name || null;
    try { await patch("/company", d); toast("Firmenprofil gespeichert."); firma(el); } catch (err) { ersetze(fehler, alertBox(meldung(err))); }
  });
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Firma"), h("p", {}, `${f.slug} · Status ${f.status}`))),
    f.status === "paused" ? alertBox("Die Firma ist pausiert — nur Lesen ist möglich.", "info") : null, h("section", { class: "card" }, form));
}

function tabelle(kopf, zeilen, leer) {
  return zeilen.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, kopf.map(([t, opt]) => h("th", { class: opt ? "opt" : null }, t)))),
    h("tbody", {}, zeilen))) : h("p", { class: "empty" }, leer);
}

const weiter = (pfad, cursor, extra = {}) => (cursor ? h("div", { class: "row row--end" },
  h("a", { class: "btn btn--ghost btn--sm", href: `#${pfad}${query({ ...extra, cursor })}` }, "Ältere")) : null);

export async function aktivitaet(el, _p, q) {
  const d = await get(`/activities${query({ limit: 50, cursor: q.get("cursor") })}`);
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Aktivität"), h("p", {}, "Was in der Firma passiert ist — nur Sichtbares."))),
    tabelle([["Wann"], ["Was"], ["Objekt"], ["Wer", true]], d.items.map((a) => h("tr", {}, h("td", {}, zeit(a.occurred_at)), h("td", {}, a.label),
      h("td", {}, a.object.title), h("td", { class: "opt" }, a.actor ? a.actor.display_name : "System"))), "Noch keine Aktivität."),
    weiter("/aktivitaet", d.next_cursor));
}

export async function audit(el, _p, q) {
  const aktion = q.get("action") || "";
  const d = await get(`/audit${query({ action: aktion, limit: 50, cursor: q.get("cursor") })}`);
  const filter = h("form", { class: "row", on: { submit: (e) => { e.preventDefault(); gehe(`/audit${query({ action: e.target.elements.action.value.trim() })}`); } } },
    h("input", { class: "input", name: "action", value: aktion, placeholder: "Aktion, z. B. role.updated", maxlength: 64, "aria-label": "Aktion filtern" }),
    h("button", { class: "btn btn--ghost btn--sm", type: "submit" }, "Filtern"));
  const exportLink = darf("audit.export") ? h("a", { class: "btn btn--ghost btn--sm", href: `/api/v1/audit/export${query({ action: aktion })}`,
    download: "audit.csv" }, "CSV exportieren") : null;
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Audit"), h("p", {}, "Nur anhängend — Einträge lassen sich nicht ändern.")), exportLink),
    filter, h("br"),
    tabelle([["Wann"], ["Aktion"], ["Ziel", true], ["Wer", true]], d.items.map((a) => h("tr", {}, h("td", {}, zeit(a.occurred_at)),
      h("td", {}, h("span", { class: "code" }, a.action)), h("td", { class: "opt" }, a.target_type ? `${a.target_type} ${a.target_id || ""}` : "—"),
      h("td", { class: "opt" }, a.actor ? a.actor.display_name : "System"))), "Keine Einträge."),
    weiter("/audit", d.next_cursor, { action: aktion }));
}
