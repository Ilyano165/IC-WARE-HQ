// DOM-Bausteine. REGEL (ADR-013): Serverdaten nur als Text — dieser Baustein setzt Kinder als Textknoten.
// Verboten im gesamten App-Code: innerHTML, outerHTML, insertAdjacentHTML, document.write, eval, new Function.

const SVG = "http://www.w3.org/2000/svg";

export function h(tag, props, ...kinder) {
  const el = document.createElement(tag);
  setze(el, props || {});
  haenge(el, kinder);
  return el;
}

function setze(el, props) {
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = Boolean(v);
    else if (k === "text") el.textContent = String(v);
    else if (/^on/i.test(k) || /html/i.test(k)) throw new Error(`Eigenschaft ${k} ist nicht erlaubt`);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}

function haenge(el, kinder) {
  for (const k of kinder.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

export const $ = (sel, root = document) => root.querySelector(sel);

export function ersetze(el, ...kinder) {
  el.replaceChildren();
  haenge(el, kinder);
  return el;
}

// IC-Logo (wie auf der Website): weißer Balken + grünes C
export function logo() {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 32 32");
  svg.setAttribute("aria-hidden", "true");
  const balken = document.createElementNS(SVG, "rect");
  for (const [k, v] of Object.entries({ x: 4, y: 5, width: 6, height: 22, rx: 1, fill: "#F4F6F5" })) balken.setAttribute(k, v);
  const c = document.createElementNS(SVG, "path");
  c.setAttribute("d", "M28 5 H14 V27 H28 V21 H20 V11 H28 Z");
  c.setAttribute("fill", "#19E56E");
  svg.append(balken, c);
  return svg;
}

export function marke(zusatz) {
  return h("div", { class: "brand" }, logo(), h("span", {}, "IC Ware ", h("span", { class: "sub" }, zusatz || "HQ")));
}

// ---------- Meldungen ----------
export function toast(text, art) {
  let box = $(".toasts");
  if (!box) {
    box = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(box);
  }
  const t = h("div", { class: `toast${art === "error" ? " toast--error" : ""}` }, text);
  box.append(t);
  setTimeout(() => t.remove(), art === "error" ? 7000 : 3500);
}

export function alertBox(text, art = "error") {
  return h("div", { class: `alert alert--${art}`, role: art === "error" ? "alert" : "status" }, text);
}

// ---------- Dialog: gibt die Formulardaten zurück oder null (Abbrechen) ----------
export function dialog(titel, felder, knopf = "Speichern", gefaehrlich = false) {
  return new Promise((fertig) => {
    const form = h("form", { method: "dialog" }, h("h2", {}, titel), felder,
      h("div", { class: "row row--end" },
        h("button", { class: "btn btn--ghost", value: "abbrechen", type: "button", on: { click: () => d.close() } },
          "Abbrechen"),
        h("button", { class: `btn${gefaehrlich ? " btn--danger" : ""}`, value: "ok", type: "submit" }, knopf)));
    const d = h("dialog", {}, form);
    let ergebnis = null;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      ergebnis = Object.fromEntries(new FormData(form).entries());
      d.close();
    });
    d.addEventListener("close", () => { d.remove(); fertig(ergebnis); });
    document.body.append(d);
    d.showModal();
  });
}

export function feld(label, input, hinweis) {
  const id = input.id || `f-${Math.random().toString(36).slice(2, 9)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hinweis ? h("div", { class: "hint" }, hinweis) : null);
}

// ---------- Formatierung ----------
const DATUM = new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" });
const ZEIT = new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" });
export const datum = (iso) => (iso ? DATUM.format(new Date(iso)) : "—");
export const zeit = (iso) => (iso ? ZEIT.format(new Date(iso)) : "—");
export function groesse(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// Doppelklick-Schutz: solange die Aktion läuft, sind die Knöpfe gesperrt und weitere Auslöser werden ignoriert
export function einmal(fn) {
  let laeuft = false;
  return async (e) => {
    if (e && e.type === "submit") e.preventDefault();
    if (laeuft) return;
    laeuft = true;
    const ziel = e && (e.currentTarget || e.target);
    const knoepfe = ziel && ziel.tagName === "FORM" ? [...ziel.querySelectorAll("button[type=submit]")]
      : ziel && ziel.tagName === "BUTTON" ? [ziel] : [];
    for (const k of knoepfe) k.disabled = true;
    try { await fn(e); } finally { laeuft = false; for (const k of knoepfe) k.disabled = false; }
  };
}
