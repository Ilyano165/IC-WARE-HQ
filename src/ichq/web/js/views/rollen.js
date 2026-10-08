// Rollen (M4): Liste, anlegen, Editor als Matrix (Modul × Aktion), duplizieren, archivieren, wiederherstellen, löschen.
// Gelb = kritisch, ausgegraut = man hat das Recht selbst nicht (der Server lehnt es ohnehin ab).
import { alertBox, dialog, ersetze, feld, h, toast } from "../dom.js";
import { del, get, meldung, patch, post } from "../api.js";
import { gehe } from "../router.js";
import { darf, state } from "../state.js";

export async function liste(el, _p, q) {
  const archiv = q.get("archiv") === "1";
  const daten = await get(`/roles${archiv ? "?archived=true" : ""}`);
  const neu = darf("roles.create") ? h("button", { class: "btn", type: "button", on: { click: anlegen } }, "Neue Rolle") : null;
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Rollen & Rechte"),
    h("p", {}, "Rollen sind Bündel von Rechten. Mehrere Rollen addieren sich; verbieten kann nur ein Einzelrecht.")),
  h("div", { class: "row" }, h("a", { class: "btn btn--ghost btn--sm", href: archiv ? "#/rollen" : "#/rollen?archiv=1" },
    archiv ? "Nur aktive" : "Mit archivierten"), neu)),
  h("div", { class: "list" }, daten.items.map((r) => h("a", { class: "item", href: `#/rollen/${r.id}` },
    h("span", {}, h("b", {}, r.name), h("div", { class: "meta" }, `Rang ${r.rank} · ${r.permissions.length} Rechte · ${r.members} Personen`)),
    h("span", { class: "row" }, r.locked ? h("span", { class: "tag" }, "gesperrt") : null,
      r.archived ? h("span", { class: "tag tag--muted" }, "archiviert") : null)))));
}

async function anlegen() {
  const d = await dialog("Neue Rolle", [feld("Name", h("input", { name: "name", required: true, maxlength: 60 })),
    feld("Beschreibung", h("input", { name: "description", maxlength: 200 })),
    feld("Rang", h("input", { name: "rank", type: "number", min: 1, max: 999, value: 10, required: true }),
      "Nur unter dem eigenen Rang. Rechte danach im Editor setzen.")], "Anlegen");
  if (!d) return;
  try {
    const r = await post("/roles", { name: d.name, description: d.description || "", rank: Number(d.rank), permissions: [] });
    gehe(`/rollen/${r.id}`);
  } catch (e) { toast(meldung(e), "error"); }
}

function matrix(registry, aktiv, gesperrt) {
  const module = new Map();
  for (const p of registry) {
    if (!module.has(p.module)) module.set(p.module, []);
    module.get(p.module).push(p);
  }
  return h("div", { class: "matrix" }, [...module.entries()].map(([mod, rechte]) => h("fieldset", {}, h("legend", {}, mod),
    h("div", { class: "perms" }, rechte.map((p) => h("label", { class: `check${p.critical ? " perm-critical" : ""}`,
      title: state.rechte.has(p.permission) ? p.permission : `${p.permission} — hast du selbst nicht` },
    h("input", { type: "checkbox", name: "perm", value: p.permission, checked: aktiv.has(p.permission),
      disabled: gesperrt || !state.rechte.has(p.permission) }),
    p.permission.split(".").slice(1).join("."), p.disabled ? " (Modul aus)" : ""))))));
}

export async function editor(el, { ref }) {
  const [r, registry] = await Promise.all([get(`/roles/${ref}`), get("/permissions")]);
  const neu = () => editor(el, { ref });
  const kannBearbeiten = darf("roles.update") && !r.locked && !r.archived;
  const fehler = h("div");
  const form = h("form", { class: "stack" }, fehler,
    h("div", { class: "grid2" }, feld("Name", h("input", { name: "name", required: true, maxlength: 60, value: r.name, disabled: !kannBearbeiten })),
      feld("Rang", h("input", { name: "rank", type: "number", min: 1, max: 999, value: r.rank, disabled: !kannBearbeiten }))),
    feld("Beschreibung", h("input", { name: "description", maxlength: 200, value: r.description, disabled: !kannBearbeiten })),
    r.locked ? alertBox("„Company Admin“ ist gesperrt und hält immer alle Rechte — auch künftige.", "info") : null,
    matrix(registry.items, new Set(r.permissions), !kannBearbeiten),
    kannBearbeiten ? h("div", { class: "row row--end" }, h("button", { class: "btn", type: "submit" }, "Speichern")) : null);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    try {
      await patch(`/roles/${ref}`, { name: fd.get("name"), description: fd.get("description") || "", rank: Number(fd.get("rank")),
        permissions: fd.getAll("perm") });
      toast("Rolle gespeichert. Rechte, die du selbst nicht hast, bleiben unverändert.");
      neu();
    } catch (err) { ersetze(fehler, alertBox(meldung(err))); }
  });
  const knopf = (text, fn, art = "btn--ghost") => h("button", { class: `btn ${art} btn--sm`, type: "button", on: { click: fn } }, text);
  const aktionen = [];
  if (darf("roles.create")) aktionen.push(knopf("Duplizieren", async () => {
    const d = await dialog("Rolle duplizieren", feld("Name der Kopie", h("input", { name: "name", required: true, maxlength: 60, value: `${r.name} (Kopie)` })), "Duplizieren");
    if (!d) return;
    try { const k = await post(`/roles/${ref}/duplicate`, { name: d.name }); gehe(`/rollen/${k.id}`); } catch (x) { toast(meldung(x), "error"); }
  }));
  if (darf("roles.delete") && !r.locked) {
    if (!r.archived) aktionen.push(knopf("Archivieren", async () => {
      try { await post(`/roles/${ref}/archive`); toast("Archiviert — die Rechte wirken für niemanden mehr."); neu(); } catch (x) { toast(meldung(x), "error"); }
    }));
    else {
      aktionen.push(knopf("Wiederherstellen", async () => { try { await post(`/roles/${ref}/restore`); neu(); } catch (x) { toast(meldung(x), "error"); } }));
      aktionen.push(knopf("Endgültig löschen", async () => {
        if (!(await dialog("Rolle löschen", h("p", {}, "Nur möglich, wenn niemand die Rolle mehr hat."), "Löschen", true))) return;
        try { await del(`/roles/${ref}`); toast("Rolle gelöscht."); gehe("/rollen"); } catch (x) { toast(meldung(x), "error"); }
      }, "btn--danger"));
    }
  }
  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("a", { href: "#/rollen", class: "small" }, "← Rollen"), h("h1", {}, r.name),
    h("p", {}, `${r.members} Personen · ${r.permissions.length} Rechte${r.archived ? " · archiviert" : ""}`)), h("div", { class: "row" }, aktionen)),
  h("section", { class: "card" }, form));
}
