// Dokumente (C0): Liste, Hochladen (Quarantäne bis Virenprüfung), Detail mit Download und Prüfung, Kommentare.
import { alertBox, datum, ersetze, h, groesse, toast, zeit } from "../dom.js";
import { get, hochladen, meldung, post, query } from "../api.js";
import { gehe } from "../router.js";
import { darf } from "../state.js";
import { kommentare } from "./kommentare.js";

const PRUEFUNG = { pending: "zu prüfen", approved: "freigegeben", rejected: "abgelehnt" };
const SCAN = { pending: "Virenprüfung läuft", clean: "geprüft", infected: "gesperrt", error: "Prüfung fehlgeschlagen" };
const TYPEN = ".pdf,.png,.jpg,.jpeg,.xml,.txt,.csv";

const pruefTag = (s) => h("span", { class: `tag${s === "approved" ? "" : s === "rejected" ? " tag--danger" : " tag--muted"}` }, PRUEFUNG[s] || s);

export async function liste(el, _p, q) {
  const daten = await get(`/documents${query({ review_status: q.get("review_status"), limit: 25, cursor: q.get("cursor") })}`);
  let upload = null;
  if (darf("files.upload")) {
    const datei = h("input", { type: "file", accept: TYPEN, class: "sr-only", id: "upload" });
    datei.addEventListener("change", async () => {
      const f = datei.files[0];
      if (!f) return;
      try {
        const d = await hochladen(f);
        toast(`„${f.name}“ hochgeladen.`);
        gehe(`/dokumente/${d.id}`);
      } catch (e) { toast(meldung(e), "error"); }
    });
    upload = h("label", { class: "btn", for: "upload" }, "Hochladen", datei);
  }
  const filter = h("select", { class: "input", "aria-label": "Prüfstatus" }, h("option", { value: "" }, "Alle"),
    Object.entries(PRUEFUNG).map(([k, v]) => h("option", { value: k, selected: q.get("review_status") === k }, v)));
  filter.addEventListener("change", () => gehe(`/dokumente${query({ review_status: filter.value })}`));
  const zeilen = daten.items.map((d) => h("tr", {}, h("td", {}, h("a", { href: `#/dokumente/${d.id}` }, d.title)),
    h("td", {}, pruefTag(d.review_status)), h("td", { class: "opt" }, groesse(d.size_bytes)), h("td", { class: "opt" }, datum(d.created_at))));
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Dokumente"),
    h("p", {}, "Neue Dateien sind bis zur Virenprüfung gesperrt.")), upload),
  h("div", { class: "row" }, filter), h("br"),
  zeilen.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Datei"), h("th", {}, "Prüfung"),
    h("th", { class: "opt" }, "Größe"), h("th", { class: "opt" }, "Hochgeladen"))), h("tbody", {}, zeilen))) : h("p", { class: "empty" }, "Keine Dokumente."),
  daten.next_cursor ? h("div", { class: "row row--end" }, h("a", { class: "btn btn--ghost btn--sm",
    href: `#/dokumente${query({ review_status: q.get("review_status"), cursor: daten.next_cursor })}` }, "Weitere")) : null);
}

export async function detail(el, { ref }) {
  const d = await get(`/documents/${ref}`);
  const kom = h("section", { class: "card" });
  const aktionen = [];
  if (d.scan_status === "clean") {
    aktionen.push(h("a", { class: "btn btn--ghost", href: `/api/v1/documents/${ref}/content`, download: d.filename }, "Herunterladen"));
  }
  if (darf("files.update") && d.review_status === "pending") {
    for (const [entscheidung, text] of [["approved", "Freigeben"], ["rejected", "Ablehnen"]]) {
      aktionen.push(h("button", { class: `btn${entscheidung === "rejected" ? " btn--danger" : ""}`, type: "button", on: { click: async () => {
        try { await post(`/documents/${ref}/review`, { decision: entscheidung }); toast("Gespeichert."); detail(el, { ref }); } catch (e) { toast(meldung(e), "error"); }
      } } }, text));
    }
  }
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("a", { href: "#/dokumente", class: "small" }, "← Dokumente"), h("h1", {}, d.title)),
    h("div", { class: "row" }, aktionen)),
  d.scan_status !== "clean" ? alertBox(`${SCAN[d.scan_status] || d.scan_status} — Download erst nach erfolgreicher Prüfung.`, "info") : null,
  h("section", { class: "card" }, h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {},
    [["Dateiname", d.filename], ["Typ", d.content_type], ["Größe", groesse(d.size_bytes)], ["Virenprüfung", SCAN[d.scan_status] || d.scan_status],
      ["Prüfung", PRUEFUNG[d.review_status] || d.review_status],
      ["Geprüft", d.reviewed_at ? `${zeit(d.reviewed_at)}${d.reviewed_by ? ` · ${d.reviewed_by.display_name}` : ""}` : "—"],
      ["SHA-256", h("span", { class: "code" }, d.sha256)], ["Hochgeladen", zeit(d.created_at)]]
      .map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, v))))))), kom);
  await kommentare(kom, ref);
}
