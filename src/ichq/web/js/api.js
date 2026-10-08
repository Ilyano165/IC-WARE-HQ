// Einziger Zugang zum Server: /api/v1, gleiche Herkunft, Sitzungs-Cookie (HttpOnly) — das Skript sieht kein Token.
// Fehler kommen als RFC-9457-Problem und werden als ApiError mit `code` weitergegeben.

export class ApiError extends Error {
  constructor(status, problem) {
    super((problem && (problem.detail || problem.title)) || `Fehler ${status}`);
    this.status = status;
    this.code = (problem && problem.code) || "error";
    this.problem = problem || {};
  }
}

async function antwort(r) {
  if (r.status === 204) return null;
  const typ = r.headers.get("content-type") || "";
  const daten = typ.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const fehler = new ApiError(r.status, typeof daten === "object" ? daten : null);
    if (r.status === 401) window.dispatchEvent(new CustomEvent("ichq:abgemeldet"));
    throw fehler;
  }
  return daten;
}

export async function api(methode, pfad, body) {
  const init = { method: methode, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  return antwort(await fetch(`/api/v1${pfad}`, init));
}

export const get = (p) => api("GET", p);
export const post = (p, b) => api("POST", p, b === undefined ? {} : b);
export const patch = (p, b) => api("PATCH", p, b);
export const put = (p, b) => api("PUT", p, b);
export const del = (p, b) => api("DELETE", p, b);

export async function hochladen(datei) {
  const r = await fetch(`/api/v1/documents?filename=${encodeURIComponent(datei.name)}`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": datei.type || "application/octet-stream", Accept: "application/json" }, body: datei,
  });
  return antwort(r);
}

export function query(params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    for (const w of Array.isArray(v) ? v : [v]) q.append(k, w);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

// Lesbare Meldung für Menschen — ohne interne Details
export function meldung(e) {
  if (!(e instanceof ApiError)) return "Verbindung fehlgeschlagen. Bitte erneut versuchen.";
  const texte = {
    permission_denied: "Dafür fehlt die Berechtigung.",
    tenant_paused: "Die Firma ist pausiert — nur Lesen ist möglich.",
    feature_disabled: "Dieses Modul ist für die Firma nicht freigeschaltet.",
    not_found: "Nicht gefunden.",
    last_admin: "Danach gäbe es niemanden mehr mit Verwaltungsrechten.",
  };
  if (e.code === "validation_failed" && e.problem.errors) {
    return e.problem.errors.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join(" · ");
  }
  return e.problem.detail || texte[e.code] || e.message;
}
