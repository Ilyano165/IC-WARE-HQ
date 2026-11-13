// Kommentare an einem Objekt (C0): lesen, schreiben (Notiz/Rückfrage), eigene bearbeiten, löschen mit Grund.
import { alertBox, dialog, einmal, ersetze, feld, h, toast, zeit } from "../dom.js";
import { del, get, meldung, patch, post } from "../api.js";
import { darf } from "../state.js";

const ART = { note: "Notiz", question: "Rückfrage" };

export async function kommentare(el, ref) {
  if (!darf("comments.read")) { ersetze(el); return; }
  const daten = await get(`/objects/${ref}/comments?limit=100`);
  const liste = h("div", { class: "stack" }, daten.items.length ? daten.items.map((k) => eintrag(k, () => kommentare(el, ref)))
    : h("p", { class: "muted" }, "Noch keine Kommentare."));
  const fehler = h("div");
  let form = null;
  if (darf("comments.create")) {
    const text = h("textarea", { name: "body", required: true, maxlength: 10000, placeholder: "Kommentar schreiben …" });
    const art = h("select", { name: "kind" }, h("option", { value: "note" }, "Notiz"), h("option", { value: "question" }, "Rückfrage"));
    form = h("form", { class: "stack" }, fehler, feld("Kommentar", text), h("div", { class: "row row--between" }, art,
      h("button", { class: "btn btn--sm", type: "submit" }, "Senden")));
    form.addEventListener("submit", einmal(async () => {
      try {
        await post(`/objects/${ref}/comments`, { body: text.value, kind: art.value });
        kommentare(el, ref);
      } catch (err) { ersetze(fehler, alertBox(meldung(err))); }
    }));
  }
  ersetze(el, h("h2", {}, "Kommentare"), liste, form);
}

function eintrag(k, neu) {
  const knoepfe = [];
  if (!k.deleted && k.own) {   // bearbeiten nur eigene (der Server prüft das ohnehin)
    knoepfe.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
      const d = await dialog("Kommentar bearbeiten", feld("Text", h("textarea", { name: "body", required: true, maxlength: 10000, value: k.body })));
      if (!d) return;
      try { await patch(`/comments/${k.id}`, { body: d.body }); neu(); } catch (e) { toast(meldung(e), "error"); }
    } } }, "Bearbeiten"));
  }
  if (!k.deleted && (k.own || darf("comments.moderate"))) {   // löschen: eigene oder als Moderator
    knoepfe.push(h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
      const d = await dialog("Kommentar löschen", [h("p", { class: "muted" }, "Der Text bleibt in der Historie; sichtbar bleibt ein Vermerk mit Grund."),
        feld("Grund", h("input", { name: "reason", required: true, minlength: 3, maxlength: 500 }))], "Löschen", true);
      if (!d) return;
      try { await del(`/comments/${k.id}`, { reason: d.reason }); neu(); } catch (e) { toast(meldung(e), "error"); }
    } } }, "Löschen"));
  }
  return h("div", { class: `comment${k.deleted ? " deleted" : ""}` },
    h("div", { class: "row row--between" }, h("span", { class: "who" }, k.author ? k.author.display_name : "—",
      " ", h("span", { class: "muted small" }, zeit(k.created_at), k.edited_at ? " · bearbeitet" : "")),
    h("span", { class: `tag${k.kind === "question" ? " tag--warn" : " tag--muted"}` }, ART[k.kind] || k.kind)),
    h("div", { class: "body" }, k.deleted ? `Gelöscht${k.delete_reason ? ` — Grund: ${k.delete_reason}` : ""}` : k.body),
    knoepfe.length ? h("div", { class: "row" }, knoepfe) : null);
}
